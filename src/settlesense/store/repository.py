"""Persistence. Thin and explicit — no ORM; the query set is small and worth
reading (ADR-003).

Results are never edited in place — a rerun writes a fresh set rather than
patching the previous one, which is what makes two runs comparable. The `runs`
row itself is replaced on a rerun of the same batch, because run_id is derived
from batch content and re-ingesting the same four files must not create a
second run.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from settlesense.contracts.models import ReconciliationResult
from settlesense.evaluate.metrics import RunMetrics
from settlesense.ledger.crosscheck import LedgerFinding
from settlesense.recon.engine import RunOutput

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


class Repository:
    def __init__(self, db_path: str | Path = "settlesense.db") -> None:
        self.db_path = str(db_path)
        # check_same_thread=False is required, not a shortcut: FastAPI runs sync
        # endpoints in a threadpool, and the request-scoped dependency that
        # opens this connection may run in a different thread from the endpoint
        # body that uses it. Safe here because each request gets its own
        # Repository (see api/deps.get_repository) — the connection is never
        # shared between concurrent requests.
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Repository":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- reads ---------------------------------------------------------------

    def find_run_by_batch(self, batch_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT run_id FROM runs WHERE batch_id = ? AND status = 'complete'",
            (batch_id,),
        ).fetchone()
        return row["run_id"] if row else None

    def results_for(self, run_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM reconciliation_results WHERE run_id = ? ORDER BY payment_id",
            (run_id,),
        ).fetchall()

    def metrics_for(self, run_id: str) -> dict[str, float]:
        rows = self._conn.execute(
            "SELECT name, value FROM metrics WHERE run_id = ?", (run_id,)
        ).fetchall()
        return {r["name"]: r["value"] for r in rows}

    def save_proof(self, run_id: str, proof) -> None:
        """The control-total decomposition, stored as metrics so it travels
        with the run and can be checked later."""
        for name, value in (
            ("proof_gross", proof.gross),
            ("proof_settled", proof.settled),
            ("proof_fees", proof.fees),
            ("proof_tax", proof.tax),
            ("proof_refunds", proof.refunds),
            ("proof_unexplained", proof.unexplained),
            ("proof_difference", proof.difference),
        ):
            self.save_metric(run_id, name, int(value))

    def get_run(self, run_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()

    def list_runs(self, limit: int = 50) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()

    def summary_for(self, run_id: str) -> dict:
        """Batch-level control totals — the first screen a controller checks."""
        row = self._conn.execute(
            """SELECT
                 COUNT(*)                                          AS records,
                 SUM(status = 'matched')                           AS matched,
                 SUM(status = 'review')                            AS review,
                 SUM(status = 'unresolved')                        AS unresolved,
                 COALESCE(SUM(settled_amount), 0)                  AS settled_net,
                 COALESCE(SUM(CASE WHEN status != 'matched'
                      THEN ABS(difference_amount) + pending_amount
                      ELSE 0 END), 0)                              AS unexplained
               FROM reconciliation_results WHERE run_id = ?""",
            (run_id,),
        ).fetchone()

        gross = self._conn.execute(
            """SELECT COALESCE(SUM(json_extract(raw_json, '$.amount')), 0) AS gross
               FROM source_rows WHERE run_id = ? AND table_name = 'payments'""",
            (run_id,),
        ).fetchone()["gross"]

        errors = self._conn.execute(
            "SELECT COUNT(*) AS n FROM validation_errors WHERE run_id = ?", (run_id,)
        ).fetchone()["n"]

        return {
            "records_processed": row["records"] or 0,
            "matched": row["matched"] or 0,
            "needs_review": row["review"] or 0,
            "unresolved": row["unresolved"] or 0,
            "gross_payments_paise": int(gross or 0),
            "settled_net_paise": int(row["settled_net"] or 0),
            "unexplained_paise": int(row["unexplained"] or 0),
            "validation_errors": errors,
        }

    def query_results(
        self,
        run_id: str,
        status: str | None = None,
        match_type: str | None = None,
        reason_code: str | None = None,
        min_difference: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[sqlite3.Row], int]:
        clauses = ["r.run_id = ?"]
        params: list = [run_id]
        if status:
            clauses.append("r.status = ?")
            params.append(status)
        if match_type:
            clauses.append("r.match_type = ?")
            params.append(match_type)
        if reason_code:
            clauses.append("r.reason_code = ?")
            params.append(reason_code)
        if min_difference is not None:
            clauses.append("ABS(r.difference_amount) >= ?")
            params.append(min_difference)
        where = " AND ".join(clauses)

        total = self._conn.execute(
            f"SELECT COUNT(*) AS n FROM reconciliation_results r WHERE {where}",
            params,
        ).fetchone()["n"]

        # Two things the table needs that don't live on the result row: how far
        # a reviewer has got with this case, and when the payment was captured
        # (so the UI can age an exception). Both are read here rather than by a
        # request per row.
        rows = self._conn.execute(
            f"""SELECT r.*,
                       (SELECT COUNT(*) FROM review_actions a
                         WHERE a.reconciliation_id = r.reconciliation_id)
                           AS review_count,
                       (SELECT a.action FROM review_actions a
                         WHERE a.reconciliation_id = r.reconciliation_id
                         ORDER BY a.created_at DESC, a.id DESC LIMIT 1)
                           AS last_action,
                       (SELECT json_extract(s.raw_json, '$.captured_at')
                          FROM source_rows s
                         WHERE s.run_id = r.run_id
                           AND s.table_name = 'payments'
                           AND s.natural_id = r.payment_id)
                           AS captured_at
                  FROM reconciliation_results r
                 WHERE {where}
                 ORDER BY r.payment_id LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        ).fetchall()
        return rows, total

    def result_detail(self, reconciliation_id: str) -> dict | None:
        """The evidence drawer: the result, its arithmetic, and every source
        row it cites — resolved to the actual stored row, not just an id."""
        # captured_at travels with the row so the drawer can age the case and
        # put a date in a copied note; without it "Copy as note" silently omits
        # the capture date.
        result = self._conn.execute(
            """SELECT r.*,
                      (SELECT COUNT(*) FROM review_actions a
                        WHERE a.reconciliation_id = r.reconciliation_id)
                          AS review_count,
                      (SELECT json_extract(s.raw_json, '$.captured_at')
                         FROM source_rows s
                        WHERE s.run_id = r.run_id
                          AND s.table_name = 'payments'
                          AND s.natural_id = r.payment_id)
                          AS captured_at
                 FROM reconciliation_results r
                WHERE r.reconciliation_id = ?""",
            (reconciliation_id,),
        ).fetchone()
        if result is None:
            return None

        steps = self._conn.execute(
            """SELECT seq, label, expression, inputs_json, result_paise
               FROM calc_steps WHERE reconciliation_id = ? ORDER BY seq""",
            (reconciliation_id,),
        ).fetchall()
        refs = self._conn.execute(
            """SELECT table_name, natural_id, row_hash, role
               FROM evidence_refs WHERE reconciliation_id = ?""",
            (reconciliation_id,),
        ).fetchall()
        claims = self._conn.execute(
            """SELECT settlement_id, claimed_paise
               FROM result_settlements WHERE reconciliation_id = ?""",
            (reconciliation_id,),
        ).fetchall()
        actions = self._conn.execute(
            """SELECT actor, action, note, created_at
               FROM review_actions WHERE reconciliation_id = ? ORDER BY created_at""",
            (reconciliation_id,),
        ).fetchall()

        evidence = []
        for ref in refs:
            source = self._conn.execute(
                """SELECT raw_json FROM source_rows
                   WHERE run_id = ? AND table_name = ? AND row_hash = ?""",
                (result["run_id"], ref["table_name"], ref["row_hash"]),
            ).fetchone()
            evidence.append(
                {
                    "table": ref["table_name"],
                    "natural_id": ref["natural_id"],
                    "row_hash": ref["row_hash"],
                    "role": ref["role"],
                    "row": json.loads(source["raw_json"]) if source else None,
                }
            )

        return {
            "result": dict(result),
            "calc_steps": [
                {
                    "seq": s["seq"],
                    "label": s["label"],
                    "expression": s["expression"],
                    "inputs": json.loads(s["inputs_json"]),
                    "result_paise": s["result_paise"],
                }
                for s in steps
            ],
            "settlements": [dict(c) for c in claims],
            "evidence": evidence,
            "review_actions": [dict(a) for a in actions],
        }

    def exception_groups(self, run_id: str) -> list[dict]:
        rows = self._conn.execute(
            """SELECT COALESCE(reason_code, 'unclassified') AS reason,
                      status,
                      COUNT(*) AS count,
                      SUM(ABS(difference_amount) + pending_amount) AS amount
               FROM reconciliation_results
               WHERE run_id = ? AND status != 'matched'
               GROUP BY reason, status
               ORDER BY count DESC""",
            (run_id,),
        ).fetchall()
        return [
            {
                "reason_code": r["reason"],
                "status": r["status"],
                "count": r["count"],
                "unexplained_paise": int(r["amount"] or 0),
            }
            for r in rows
        ]

    def validation_errors_for(self, run_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM validation_errors WHERE run_id = ? ORDER BY source_line",
            (run_id,),
        ).fetchall()

    def ledger_findings_for(self, run_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM ledger_findings WHERE run_id = ?", (run_id,)
        ).fetchall()

    # -- AI sidecar (additive; truncating these changes no number) -----------

    def get_cached_explanation(self, cache_key: str) -> dict | None:
        row = self._conn.execute(
            "SELECT payload_json FROM explanation_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def save_cached_explanation(
        self, cache_key: str, payload: dict, model: str, prompt_version: str
    ) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO explanation_cache
               (cache_key, payload_json, model, prompt_version, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                cache_key,
                json.dumps(payload, sort_keys=True),
                model,
                prompt_version,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()

    def save_explanation(
        self,
        reconciliation_id: str,
        explanation,
        source: str,
        grounded: bool,
        model: str | None,
        prompt_version: str,
    ) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO explanations
               (reconciliation_id, source, category, summary, recommended_action,
                needs_human_review, evidence_refs_json, model, prompt_version,
                grounded, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                reconciliation_id,
                source,
                explanation.category.value,
                explanation.summary,
                explanation.recommended_action.value,
                int(explanation.needs_human_review),
                json.dumps(list(explanation.evidence_refs)),
                model,
                prompt_version,
                int(grounded),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()

    def explanation_for(self, reconciliation_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM explanations WHERE reconciliation_id = ?",
            (reconciliation_id,),
        ).fetchone()
        if row is None:
            return None
        payload = dict(row)
        payload["evidence_refs"] = json.loads(payload.pop("evidence_refs_json"))
        payload["needs_human_review"] = bool(payload["needs_human_review"])
        payload["grounded"] = bool(payload["grounded"])
        return payload

    def save_clusters(self, run_id: str, clusters: list[dict]) -> None:
        self._conn.execute(
            "DELETE FROM exception_clusters WHERE run_id = ?", (run_id,)
        )
        self._conn.executemany(
            """INSERT INTO exception_clusters
               (cluster_id, run_id, label, rationale, member_ids_json)
               VALUES (?, ?, ?, ?, ?)""",
            [
                (
                    f"{run_id}:cluster_{i}",
                    run_id,
                    c["label"],
                    c["rationale"],
                    json.dumps(list(c["member_payment_ids"])),
                )
                for i, c in enumerate(clusters)
            ],
        )
        self._conn.commit()

    def clusters_for(self, run_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM exception_clusters WHERE run_id = ?", (run_id,)
        ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["member_payment_ids"] = json.loads(item.pop("member_ids_json"))
            out.append(item)
        return out

    def save_metric(self, run_id: str, name: str, value: float) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO metrics (run_id, name, value, computed_at)
               VALUES (?, ?, ?, ?)""",
            (run_id, name, float(value), datetime.now(timezone.utc).isoformat()),
        )
        self._conn.commit()

    def save_review_actions(
        self,
        reconciliation_ids: list[str],
        actor: str,
        action: str,
        note: str | None,
    ) -> int:
        """Sign off a group in one transaction. Eighteen payments waiting on
        the same provider batch is one decision, not eighteen.

        Ids are checked against the results actually named, rather than by
        loading every id ever written — that set grows with run history and
        has nothing to do with the size of the request.
        """
        if not reconciliation_ids:
            return 0

        now = datetime.now(timezone.utc).isoformat()
        placeholders = ",".join("?" * len(reconciliation_ids))
        known = {
            row["reconciliation_id"]
            for row in self._conn.execute(
                "SELECT reconciliation_id FROM reconciliation_results "
                f"WHERE reconciliation_id IN ({placeholders})",
                reconciliation_ids,
            ).fetchall()
        }
        rows = [
            (rid, actor, action, note, now)
            for rid in reconciliation_ids
            if rid in known
        ]
        self._conn.executemany(
            """INSERT INTO review_actions
               (reconciliation_id, actor, action, note, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            rows,
        )
        self._conn.commit()
        return len(rows)

    def save_review_action(
        self, reconciliation_id: str, actor: str, action: str, note: str | None
    ) -> None:
        self._conn.execute(
            """INSERT INTO review_actions
               (reconciliation_id, actor, action, note, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                reconciliation_id,
                actor,
                action,
                note,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()

    # -- writes --------------------------------------------------------------

    def save_run(
        self,
        output: RunOutput,
        config_json: str,
        findings: list[LedgerFinding] | None = None,
        metrics: RunMetrics | None = None,
    ) -> str:
        now = datetime.now(timezone.utc).isoformat()
        cur = self._conn.cursor()

        cur.execute(
            """INSERT OR REPLACE INTO runs
               (run_id, batch_id, engine_version, rules_version, config_json,
                started_at, finished_at, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                output.run_id,
                output.batch_id,
                output.engine_version,
                output.rules_version,
                config_json,
                now,
                now,
                "complete",
            ),
        )

        self._save_source_rows(cur, output)

        cur.executemany(
            """INSERT INTO validation_errors
               (run_id, source_file, source_line, field, reason, raw_row)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (
                    output.run_id,
                    e.source_file,
                    e.source_line,
                    e.field,
                    e.reason,
                    json.dumps(e.raw_row, sort_keys=True),
                )
                for e in output.validation_errors
            ],
        )

        for result in output.results:
            self._save_result(cur, result)

        if findings:
            cur.executemany(
                """INSERT INTO ledger_findings
                   (run_id, order_id, payment_id, reason, detail, amount)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (
                        output.run_id,
                        f.order_id,
                        f.payment_id,
                        f.reason.value,
                        f.detail,
                        int(f.amount),
                    )
                    for f in findings
                ],
            )

        if metrics:
            cur.executemany(
                """INSERT OR REPLACE INTO metrics (run_id, name, value, computed_at)
                   VALUES (?, ?, ?, ?)""",
                [
                    (output.run_id, name, float(value), now)
                    for name, value in metrics.model_dump().items()
                    if isinstance(value, (int, float))
                ],
            )

        self._conn.commit()
        return output.run_id

    def _save_source_rows(self, cur: sqlite3.Cursor, output: RunOutput) -> None:
        rows: list[tuple] = []
        for table, records, id_field in (
            ("payments", output.payments, "payment_id"),
            ("settlements", output.settlements, "settlement_id"),
            ("refunds", output.refunds, "refund_id"),
            ("ledger_entries", output.ledger, "ledger_entry_id"),
        ):
            for record in records:
                rows.append(
                    (
                        record.row_hash,
                        output.run_id,
                        table,
                        getattr(record, id_field),
                        record.model_dump_json(),
                        None,
                    )
                )
        cur.executemany(
            """INSERT OR REPLACE INTO source_rows
               (row_hash, run_id, table_name, natural_id, raw_json, duplicate_of)
               VALUES (?, ?, ?, ?, ?, ?)""",
            rows,
        )

    def _save_result(self, cur: sqlite3.Cursor, r: ReconciliationResult) -> None:
        cur.execute(
            """INSERT OR REPLACE INTO reconciliation_results
               (reconciliation_id, run_id, payment_id, match_type, match_score,
                expected_net, actual_net, difference_amount, status, reason_code,
                settled_amount, pending_amount)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                r.reconciliation_id,
                r.run_id,
                r.payment_id,
                r.match_type.value,
                r.match_score,
                int(r.expected_net),
                None if r.actual_net is None else int(r.actual_net),
                int(r.difference_amount),
                r.status.value,
                r.reason_code.value if r.reason_code else None,
                int(r.settled_amount),
                int(r.pending_amount),
            ),
        )
        cur.executemany(
            """INSERT OR REPLACE INTO result_settlements
               (reconciliation_id, settlement_id, claimed_paise) VALUES (?, ?, ?)""",
            [
                (r.reconciliation_id, c.settlement_id, int(c.claimed_paise))
                for c in r.settlements
            ],
        )
        cur.executemany(
            """INSERT OR REPLACE INTO calc_steps
               (reconciliation_id, seq, label, expression, inputs_json, result_paise)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (
                    r.reconciliation_id,
                    s.seq,
                    s.label,
                    s.expression,
                    json.dumps(s.inputs, sort_keys=True),
                    int(s.result_paise),
                )
                for s in r.trace
            ],
        )
        cur.executemany(
            """INSERT OR REPLACE INTO evidence_refs
               (reconciliation_id, table_name, natural_id, row_hash, role)
               VALUES (?, ?, ?, ?, ?)""",
            [
                (r.reconciliation_id, ref.table, ref.natural_id, ref.row_hash, None)
                for ref in r.evidence
            ],
        )

"""Exception clustering — grouping cases that share a root cause.

Rides the same rails as explanation: the model sees only exception summaries and
returns labels plus member ids, and every returned id is validated against the
actual id set before anything is stored. A hallucinated member is dropped, not
displayed.

With no AI available this falls back to grouping by reason code, which is
already useful and entirely deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass

from settlesense.ai.client import AIClient
from settlesense.ai.schemas import ClusterSetOut
from settlesense.store.repository import Repository

SYSTEM_PROMPT = """\
You group settlement reconciliation exceptions that share a root cause.

Rules:
- Use only the payment ids given to you. Never invent one.
- Every case must appear in at most one group.
- Prefer few, meaningful groups over many trivial ones. A group of one is fine
  when a case is genuinely unlike the others.
- Base groups on shared cause (same settlement batch, same fee behaviour, same
  timing gap), not on superficial similarity of amounts.\
"""


@dataclass(frozen=True)
class Cluster:
    label: str
    rationale: str
    member_payment_ids: tuple[str, ...]
    source: str  # "ai" | "reason_code"


def _deterministic_clusters(rows: list) -> list[Cluster]:
    groups: dict[str, list[str]] = {}
    for row in rows:
        key = row["reason_code"] or "unclassified"
        groups.setdefault(key, []).append(row["payment_id"])
    return [
        Cluster(
            label=key.replace("_", " "),
            rationale=f"{len(members)} case(s) share the reason code {key!r}.",
            member_payment_ids=tuple(members),
            source="reason_code",
        )
        for key, members in sorted(groups.items(), key=lambda kv: -len(kv[1]))
    ]


def cluster_run(run_id: str, repo: Repository, client: AIClient) -> list[Cluster]:
    rows, _ = repo.query_results(run_id, limit=1_000_000)
    exceptions = [r for r in rows if r["status"] != "matched"]
    if not exceptions:
        return []

    if not client.available():
        return _deterministic_clusters(exceptions)

    valid_ids = {r["payment_id"] for r in exceptions}
    lines = [
        f"- {r['payment_id']}: status={r['status']} reason={r['reason_code']} "
        f"difference={r['difference_amount']} pending={r['pending_amount']}"
        for r in exceptions
    ]
    user = "Group these exceptions:\n\n" + "\n".join(lines)

    parsed = client.parse(
        system=SYSTEM_PROMPT, user=user, output_model=ClusterSetOut
    )
    if parsed is None:
        return _deterministic_clusters(exceptions)

    clusters: list[Cluster] = []
    seen: set[str] = set()
    for group in parsed.clusters:
        # Validation gate: drop invented ids and duplicate memberships.
        members = tuple(
            pid
            for pid in group.member_payment_ids
            if pid in valid_ids and pid not in seen
        )
        seen.update(members)
        if members:
            clusters.append(
                Cluster(
                    label=group.label,
                    rationale=group.rationale,
                    member_payment_ids=members,
                    source="ai",
                )
            )

    # Anything the model failed to place still has to be visible.
    unplaced = [r["payment_id"] for r in exceptions if r["payment_id"] not in seen]
    if unplaced:
        clusters.append(
            Cluster(
                label="ungrouped",
                rationale="Not placed in any group; shown so nothing is hidden.",
                member_payment_ids=tuple(unplaced),
                source="reason_code",
            )
        )

    repo.save_clusters(run_id, [c.__dict__ for c in clusters])
    return clusters

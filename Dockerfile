# One image, one service: the API serves the dashboard from the same origin,
# so there is no cross-origin request and no second deployment to keep in step.
#
# Docker rather than a host's native Python runtime because the build needs
# both Node and Python, and pinning both here means the image that runs in
# production is the one that was built and tested.

# --- build the dashboard ---------------------------------------------------
FROM node:22-slim AS web

WORKDIR /app/web
# Copy the manifests alone first so a dependency layer is only rebuilt when
# the dependencies actually change.
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build


# --- run the engine and API ------------------------------------------------
FROM python:3.13-slim

# Fail fast and log immediately rather than buffering into a void.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
COPY src/ ./src/
# Editable, deliberately: the app resolves recon.config.yaml, data/ and
# web/dist relative to its own file, so it has to stay inside the project
# tree. A normal install would move it to site-packages and those paths
# would resolve into Python's lib directory.
RUN pip install -e .

# The batches the app can reconcile, including the three built to fail.
COPY data/ ./data/
COPY demo/ ./demo/
COPY recon.config.yaml ./

COPY --from=web /app/web/dist ./web/dist

# SQLite lives on the container filesystem. On a host without a persistent
# disk this resets when the service restarts, which is survivable because the
# schema is created on first connection and the dashboard reconciles the
# benchmark on load — a cold instance repopulates itself. Sign-offs and run
# history do not survive a restart; attach a disk and point SETTLESENSE_DB at
# it if they need to.
ENV SETTLESENSE_DB=/app/settlesense.db

# The host supplies the port; default matches local development.
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn settlesense.api.main:app --host 0.0.0.0 --port ${PORT}"]

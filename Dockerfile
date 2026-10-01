# OxyPC Inventory — container image
#
# IMPORTANT: verify the Internal Server's actual Python version before building
# against this image (`ssh oxypc-internal python3 --version`) and adjust the
# base image tag below if it differs from 3.12.
#
# Two-stage build: `builder` compiles/installs Python dependencies into an
# isolated prefix; `runtime` copies only that prefix + app code, so the final
# image doesn't carry build toolchains (gcc, headers) it only needed to build
# wheels like asyncpg/bcrypt.

FROM python:3.12-slim AS builder

WORKDIR /build

# build-essential: some pinned deps (asyncpg, bcrypt) may need to compile from
# sdist if no matching manylinux wheel exists for this base image's platform.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


FROM python:3.12-slim AS runtime

# Postgres client libs needed at runtime by asyncpg's C extension.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 --shell /usr/sbin/nologin appuser

COPY --from=builder /install /usr/local

WORKDIR /app
COPY . .

# Runtime data dirs — these are bind-mounted over by docker-compose.yml in
# production so writes land on the host, not in the image layer. Creating them
# here just keeps `docker run` (without compose) from failing on a missing dir.
RUN mkdir -p uploads backups static/stress_reports \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# Health check mirrors the app's own /health route (see main.py) — lets
# `docker ps` / `docker compose ps` show unhealthy before you'd notice from
# outside the container.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health',timeout=3).status==200 else 1)"

# uvicorn directly (not `python main.py`) — skips main.py's __main__ block,
# which spawns a thread to auto-open a local browser (OXYPC_OPEN_BROWSER),
# meaningless and best avoided inside a container.
# --workers 1 is a hard requirement, not tunable here — see main.py's inline
# comment on _PERM_CACHE/_transitions_cache going stale across worker processes.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]

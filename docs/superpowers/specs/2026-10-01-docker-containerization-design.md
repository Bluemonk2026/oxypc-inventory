# Docker Containerization — Design

> Status: **IMPLEMENTED — 2026-10-01.** Cutover complete, verified, and stable in production. See §9 for the final state, deviations from this plan, and issues found + fixed along the way.
> Author: Claude Sonnet 5, for Pankaj Sehgal (Director, OxyPC Computers)
> Date: 2026-10-01

---

## 1. Business Objective

**Why:** The Internal Server (`10.199.206.109`, `/opt/oxypc`) runs OxyPC Inventory directly on bare metal — a Python venv, a systemd unit (`oxypc.service`), and a 2-minute polling auto-deploy timer (`oxypc-autodeploy.timer`). This works, but it has three structural weaknesses that get worse as the app grows:

1. **No environment reproducibility.** "Works on the server" depends on whatever happens to be installed on that one VM. A second environment (staging, DR standby, a new hire's laptop for a quick repro) means manually recreating venv + system packages + Postgres client libs by hand.
2. **No rollback primitive.** Today, rollback means `git revert` + redeploy + hope schema changes are compatible. A container image is a known-good, immutable artifact — rollback is "run the previous image," not "hope the previous commit still builds."
3. **No blast-radius isolation.** The app, its dependencies, and the host OS share one filesystem and process space. A bad `pip install` or a misbehaving library can affect the whole box, including Postgres if it's ever co-located more tightly.

**What this buys you, concretely:** faster, safer rollback; a reproducible build you can hand to anyone; and a foundation for the things the global CLAUDE.md's 16-Phase system expects at scale (blue-green/canary deploys, DR standby, multi-environment staging) — none of which are possible on the current bare-metal setup without this step first.

**What this does NOT change:** the application code, the database schema, the business logic, or the URL/access pattern for users. This is infrastructure-only.

---

## 2. Current State (as verified today)

| Item | Current value |
|---|---|
| App | FastAPI, `uvicorn.run(host=APP_HOST, port=APP_PORT)` in [main.py](../../main.py), **1 worker only** (hard constraint — in-memory `_PERM_CACHE`/`_transitions_cache` go stale across processes) |
| Python deps | [requirements.txt](../../requirements.txt) — fastapi 0.115.6, sqlalchemy[asyncio] 2.0.36, asyncpg 0.30.0, alembic 1.14.0, bcrypt 5.0.0 (pinned — see inline comment on bcrypt/passlib incompatibility), uvicorn[standard] 0.32.1 |
| Config | `.env` → `OXYPC_DATABASE_URL`, `OXYPC_SECRET_KEY`, `OXYPC_API_KEY`, `OXYPC_TOKEN_EXPIRE_MINUTES`, `OXYPC_REFRESH_DAYS`, `OXYPC_PORT`, `OXYPC_HOST` |
| Database | PostgreSQL, native install on the same box (not containerized today), reached via `OXYPC_DATABASE_URL` |
| Schema management | `db_validator.py` auto-applies `CREATE TABLE`/`ADD COLUMN` on every app startup — **not** a conventional Alembic migration gate, even though `alembic/` exists in the tree |
| Persistent data outside the DB | `uploads/`, `backups/`, `static/stress_reports/`, `static/manuals/` — all on local disk, not in git (except manuals) |
| Process management | `oxypc.service` (systemd) |
| Deploy mechanism | `oxypc-autodeploy.timer` polls `origin/main` every 2 min, auto-restarts on new commits; refuses to run if the working tree has uncommitted/untracked changes |
| Backups | `oxypc-backup.service` (nightly) → `/opt/oxypc/backups`, plus `scripts/backup_db.py` |
| Reverse proxy / TLS | **Resolved during implementation:** nginx, plain HTTP (LAN-only, no TLS) — `deploy/nginx-oxypc-internal.conf`, proxies `/` to `127.0.0.1:8000` and serves `/static/` straight off `/opt/oxypc/static/` on host disk, bypassing the app. See §9. |

---

## 3. Target Architecture

**Recommendation: containerize the app only. Leave PostgreSQL as a native install on the host.**

### Why not containerize Postgres too (yet)

Moving a live production database into a container means a data migration (dump/restore or volume takeover), and it's the one component where a mistake is genuinely hard to undo. The app gets ~90% of the reproducibility/rollback benefit from being containerized on its own, talking to Postgres over `localhost` (or a fixed host-network address) exactly as it does today. Containerizing Postgres is a reasonable **Phase 2** once the app-only setup has run clean in production for a few weeks — not part of this plan.

### Components

```
┌─────────────────────────────────────────────┐
│ Internal Server (10.199.206.109)             │
│                                               │
│  ┌─────────────────┐     ┌────────────────┐ │
│  │ Docker container │     │  PostgreSQL     │ │
│  │ oxypc-app         │────▶│  (native,       │ │
│  │ uvicorn, 1 worker │     │   unchanged)    │ │
│  │ port 8000         │     └────────────────┘ │
│  └────────┬──────────┘                        │
│           │ bind mounts                       │
│           ▼                                   │
│  /opt/oxypc/uploads    (volume)                │
│  /opt/oxypc/backups    (volume)                │
│  /opt/oxypc/.env       (bind mount, read-only) │
└─────────────────────────────────────────────┘
```

- **Image:** multi-stage build — a `builder` stage installs Python deps (including anything needing compilation, e.g. `psycopg`/`asyncpg` build deps if wheels aren't available for the base image's platform), a slim `runtime` stage copies only the installed packages + app code. Pin the Python version explicitly (the repo has no `.python-version`/`runtime.txt` today — recommend `python:3.12-slim` as the base, matching whatever the Internal Server currently runs; **confirm the server's actual Python version before pinning** — one-line check: `ssh oxypc-internal python3 --version`).
- **Non-root user inside the container.** Don't run uvicorn as root in the image even though the host process may run as root today.
- **`CMD` runs uvicorn exactly as `main.py` does today** — single worker, same host/port envs, so no behavior change.
- **Volumes:** `uploads/` and `backups/` as bind mounts to the existing host directories (not named Docker volumes) — this means a container replace doesn't lose data, and your existing nightly backup script keeps working against the same host path unchanged.
- **`.env` stays outside the image**, bind-mounted or passed via `--env-file` — secrets never get baked into a layer that could be pushed somewhere.
- **Networking:** container uses `--network host` (simplest, zero behavior change — the app already expects to bind `0.0.0.0:8000` and reach Postgres the same way it does now) rather than Docker's bridge networking + port mapping. Bridge networking is cleaner long-term but adds a networking variable to an already-live cutover; host networking keeps this a pure "same process, different box around it" change.

### Open question before build: is there a reverse proxy today? — RESOLVED (see §9)

Yes — nginx (`deploy/nginx-oxypc-internal.conf`), plain HTTP, proxying `/` to `127.0.0.1:8000`. As predicted, nothing about its config needed to change: it keeps pointing at `127.0.0.1:8000`, now the container's host-networked port instead of a bare uvicorn process, and that swap is transparent to nginx. Confirmed working end-to-end post-cutover via real client traffic in the container's logs, not just synthetic health checks.

---

## 4. New Files (none of these touch the live app until the cutover step)

| File | Purpose |
|---|---|
| `Dockerfile` | Multi-stage build as described above |
| `.dockerignore` | Exclude `.git`, `.venv-migrate`, `__pycache__`, `backups/`, `uploads/`, the loose `_chk_*.py`/`_verify_*.py` scratch scripts, `New folder/`, `*.docx`/`*.xlsx`/`*.pptx` deliverables at repo root — keep the image lean and avoid ever baking local data into a shippable artifact |
| `docker-compose.yml` | Single-service compose file wrapping the `oxypc-app` container — not because multiple services are needed yet, but because `docker compose up -d --build` is a cleaner, more auditable deploy primitive than a raw `docker run` with a dozen flags, and it's the natural place to add Postgres as a second service later if Phase 2 happens |
| `.github/workflows/docker-build-check.yml` (optional) | CI check that the image builds on every PR — catches a broken Dockerfile before it reaches the server, independent of whether you also want full CI/CD |

None of these are destructive or risky to add — they're inert until something runs `docker build`. I can scaffold them now for review if you want to see exact contents before deciding to proceed (see §8).

---

## 5. Migration & Cutover Plan

### Phase A — Build & validate off production (zero downtime, zero risk)

1. Write `Dockerfile`, `.dockerignore`, `docker-compose.yml`.
2. Build the image locally (your machine or a throwaway cloud VM) against a **copy** of the schema (or just against a local Postgres with `db_validator.py` doing its normal create-on-boot) — never against production data during this phase.
3. Smoke-test: container boots, `/health` returns ok, login works, one write-path (e.g. IQC submit) round-trips correctly.
4. Push the validated `Dockerfile`/`docker-compose.yml` to `main` via the normal commit-deploy-gate flow — this alone causes **zero downtime**, because `oxypc.service` keeps running untouched; the new files just sit in the repo unused until Phase B.

**Production impact of Phase A: none.** This can happen entirely in parallel with normal work.

### Phase B — Install Docker on the Internal Server (zero downtime)

1. `ssh oxypc-internal`, install Docker Engine + Compose plugin (standard apt install on the server's distro).
2. Pre-build the image on the server from the already-pushed `Dockerfile`: `cd /opt/oxypc && docker compose build`. This is the slow step (dependency install, ~1–3 min depending on wheel availability) and **it happens while `oxypc.service` is still serving traffic** — building an image does not touch the running process.
3. Confirm the built image's container starts and passes its health check **on a non-production port** (e.g. temporarily bind to `8001` instead of `8000`) so you can verify it end-to-end without touching live traffic at all.

**Production impact of Phase B: none**, if step 3 uses a scratch port.

### Phase C — Cutover (the only step with real downtime)

This is a process swap, not a data migration, so the downtime window is short and bounded:

1. `sudo systemctl stop oxypc.service` — **downtime starts here**.
2. `sudo systemctl disable oxypc.service` (prevents autodeploy or a reboot from racing the container for port 8000).
3. `docker compose up -d` — container starts against the already-built image (from Phase B, so this is near-instant, not a fresh build).
4. `curl -s http://localhost:8000/health` — confirm `{"status":"ok","db":"ok"}`.
5. Smoke-test one real page load (e.g. `/reports/daily-stock` returning its expected 303-to-login) — **downtime ends here**.
6. Watch `docker compose logs -f oxypc-app` for 5–10 minutes alongside normal usage to catch anything the smoke test missed.

**Realistic downtime estimate: 1–3 minutes.** The dominant cost is systemctl stop + container start + health check polling, not image building (which already happened in Phase B). This is comparable to, or faster than, a normal `oxypc.service` restart today.

**Recommended timing:** run Phase C during your lowest-traffic window — given this is an internal inventory/ops tool, likely early morning IST before shift start, or end-of-day after the last shift closes out their stage movements.

### Phase D — Replace autodeploy (zero downtime, done after Phase C is stable)

`oxypc-autodeploy.timer` currently does `git pull` + `systemctl restart`. Its container equivalent is `git pull` + `docker compose up -d --build`. Recommend leaving the **systemd-based** `oxypc.service` fully disabled (not deleted — keep it as the rollback path, see §6) and either:
- adapt the existing timer's script to run the compose command instead, or
- keep it fully manual for the first 1–2 weeks post-cutover, so every deploy during the stabilization period is a conscious action you watch, not an automatic 2-minute-poll restart of a system you're still building confidence in.

I'd recommend the manual option for the first couple weeks — it's a small discipline cost for meaningfully lower risk while this is new.

---

## 6. Rollback Plan

Because `oxypc.service` is **disabled, not deleted**, in Phase C step 2:

1. `docker compose down` — stop the container.
2. `sudo systemctl enable --now oxypc.service` — the bare-metal process comes back exactly as it was before Phase C, same venv, same code.
3. Total rollback time: well under a minute, since nothing about the bare-metal setup was touched or removed.

This is strictly safer than the rollback story you have today (`git revert` + redeploy + hope), which is itself one of the reasons to do this migration.

**Data safety:** since `uploads/` and `backups/` are bind-mounted (not copied into the image or a Docker-managed volume), and Postgres is untouched throughout, there's no scenario in this plan where rollback loses data — the container and the bare-metal process are reading/writing the same files and the same database the whole time.

---

## 7. Timeline (if given go-ahead)

| Phase | Work | Production impact | Elapsed time |
|---|---|---|---|
| A | Write Dockerfile/compose, build+test off-prod, push to `main` | None | 0.5–1 day |
| B | Install Docker on server, pre-build image, test on scratch port | None | 1–2 hours (mostly hands-off build time) |
| C | Cutover | **1–3 min downtime** | 15–30 min including smoke-test and log-watch |
| D | Stabilize, replace autodeploy | None | Ongoing, 1–2 weeks of manual deploys before automating |

**Total hands-on effort: roughly 1 working day**, with the production-visible part of it compressed into a single sub-5-minute window you schedule deliberately. Everything before Phase C is reversible by simply not proceeding; everything in Phase C is reversible via §6 in under a minute.

---

## 8. Next Step

This document is the proposal only — no files have been created in the app repo and nothing on the Internal Server has changed. Two ways to proceed:

1. **Review this plan as-is** — flag anything that doesn't match your intent (e.g. if you *do* want Postgres containerized now, or if there's a reverse proxy I should know about before finalizing the networking approach).
2. **Have me scaffold `Dockerfile` / `.dockerignore` / `docker-compose.yml`** in the repo for review — these are new, inert files with zero production risk to add, and seeing exact contents is usually easier than approving from prose alone.

Neither of these touches production. Phase C (the only step with downtime) only happens on your explicit go-ahead, per the commit-deploy-gate rule already in force for this project.

---

## 9. Final State — As Implemented (2026-10-01)

All four phases executed and verified the same day. Actual outcome vs. the plan above:

### Deviations from plan

- **Phase B's "install Docker" was a no-op.** Docker Engine 29.8.0 + Compose v5.5.1 were already present and already running an unrelated app (`cstmr-portal-app`, bound to `127.0.0.1:3001`) — left untouched throughout.
- **Python version mismatch, deliberately not matched.** The host runs 3.10.12; the image uses `python:3.12-slim` as planned. Decided this didn't need reconciling — the point of containerizing is that the image carries its own runtime, isolated from the host's. Validated by a clean local smoke test against real dependencies and a live schema before the server build.
- **The scratch-port smoke test needed two attempts.** The first used bridge networking + port mapping (`-p 8001:8000`) with `--add-host=host.docker.internal:host-gateway` to reach the host's Postgres — failed (`Connection refused`), because `pg_hba.conf`/`listen_addresses` only trusts `127.0.0.1`, not a Docker bridge gateway IP. Re-ran with `--network host` (matching what `docker-compose.yml` actually uses in production) on port 8001 instead — passed cleanly. This is exactly why the production compose file uses host networking rather than bridge+port-mapping.
- **Local image size needed a fix before it was usable.** First local build came out at 7.27GB — traced to local dev cruft (`.dockerignore` didn't yet know about an untracked 1.7GB `wa-service/` Node service, a stray `venv/`, and the separate OxyQC standalone agent's build/dist artifacts sitting in the working directory). Fixed `.dockerignore`, rebuilt to 545MB. The server-side build (clean checkout, none of that cruft) came out the same size (543MB) without needing those extra excludes, confirming it was local-machine noise, not a repo problem.

### Issues found during cutover (not anticipated by this plan) — both fixed same day

1. **Live file-permission regression.** `uploads/`, `backups/`, `static/stress_reports/` were owned by `www-data` (uid 33, the old bare-metal process owner); the container's `appuser` is uid 1000. Confirmed via a direct write test that in-app uploads were failing with `Permission denied` immediately after cutover. Fixed with `chown -R 1000:1000` on those three directories (one-time; not needed on every deploy — nightly backups run as root via `oxypc-backup.service`, unaffected either way).
2. **Autodeploy health-check race, caught by a deliberate end-to-end test.** The first Docker-aware version of `deploy/oxypc-autodeploy.sh` used a single `sleep 8` + one-shot `curl`. A real test push showed the build and container restart both succeeding, but the health check fired mid-startup, got a bare connection refusal, and reported `DEPLOY UNHEALTHY` for a deploy that was actually fine (confirmed healthy ~25s later on its own). Fixed by replacing the flat sleep with a 20×1s poll loop. Re-tested with a second push — correctly reported `DEPLOYED OK`.

### What actually changed in the repo

- `Dockerfile`, `.dockerignore`, `docker-compose.yml` — new (commit `992255e4`)
- `deploy/oxypc-autodeploy.sh` — rewritten for `docker compose build && up -d` instead of `systemctl restart oxypc`; drops the now-redundant manual pip-install/schema-reconcile steps (both automatic under Docker) and the `chown -R www-data` step (commits `efc7388c`, `e3a90c96` for the health-check fix)

### Verified final state

| Component | State |
|---|---|
| `oxypc-app` container | Running, healthy, host-networked on port 8000 |
| `oxypc.service` (bare metal) | Stopped + disabled — **kept installed as the rollback path**, not deleted |
| `oxypc-autodeploy.timer` | Active; confirmed both a clean no-op (`LOCAL == REMOTE`) and a real deploy (`DEPLOYED OK`) |
| nginx | Unchanged, proxying transparently to the container |
| Uploads/backups/static write access | Fixed, verified with a direct write test |
| Downtime incurred | ~8 seconds (Phase C cutover) |
| Server disk | 45G → 41G used after a `docker builder prune -f` (reclaimed 4.48GB of dangling build cache; 23.37GB of still-useful cache deliberately left alone, shared with the other app on the box) |

### Still open, not urgent

- **Postgres containerization (Phase 2)** — deliberately deferred, per §3's reasoning. Revisit after this setup has run clean for a few weeks.
- **`oxypc-app:local`** — the original manual Phase B build tag on the server, superseded by the compose-built `oxypc-oxypc-app:latest`. Pankaj asked to keep it rather than remove it (2026-10-01) — left in place.
- **`docker builder prune -a`** (the more aggressive pass, clearing cache still useful to the other app on the box) — declined for now (2026-10-01); revisit if disk pressure ever becomes real (currently 44% used, no urgency).

# TraceNews API

TraceNews API is the FastAPI-based backend service for the TraceNews application. It serves news story clusters, aggregates outlet coverage data, and computes real-time reporting verdicts (clear, mixed, dark) using the Monitoring Spirit engine.

## Scheduled Work

There is one in-process scheduler (APScheduler, `app/scheduler.py`) and one cron job. Each job has exactly one owner.

**Web service** (`uvicorn app.main:app`, from `railway.toml` / `Procfile`). The scheduler starts in the FastAPI lifespan and runs only here:

| Job | Schedule | Why it lives here |
| --- | --- | --- |
| Stories sitemap cache | on startup, then every 30 min | the cache is in-memory in this process |
| Sitemap health check | 06:00 UTC daily | |
| Feed heartbeat (alert if no new story in 30 min) | every 30 min | watches the worker from outside it |
| Daily briefing heartbeat (alert unless every row is `complete`) | 07:05 UTC daily, after the briefing window | watches the worker from outside it |
| Version heartbeat (alert if `/version` ≠ latest `main`) | every 15 min | |
| Scheduler alive log (`[heartbeat] Scheduler alive`) | every 5 min | |

**Worker service** (Railway cron, every 20 min, runs `app/worker.py` and exits): fetch → cluster → score → image hydration → event summaries → daily briefing (05:00–06:59 UTC only) → public feed cache. A `worker_locks` row prevents overlapping runs. The worker starts no scheduler.

`railway.toml` sets `startCommand` for every service deployed from this repo. The worker service must override it with its own start command; otherwise it would boot the web app (and a second copy of the scheduler) instead of the pipeline.

## Running Locally

1. Ensure you have **Python 3.12** installed.
2. Create and activate a virtual environment:
   ```bash
   python3.12 -m venv .venv
   source .venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Start the development server:
   ```bash
   uvicorn app.main:app --reload
   ```

## Directory Structure

- `app/` – Core application logic, FastAPI endpoints, database interfaces, and the Monitoring Spirit engine.
- `migrations/` – SQL migrations and schema definitions (formerly executed via Enitan).
- `scripts/` – Diagnostics, local fetchers, and archived legacy scripts (`scripts/archive/`).
- `tests/` – The consolidated test suite for the backend.

## Environment Variables

All required environment variables are stored locally in the `.env` file at the root of the project (gitignored). This includes `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, and other secrets required for the database connection and the AI classification worker.

## Testing

To run the test suite:
```bash
python -m pytest tests/
```

**Important**: Tests require **Python 3.12**. Running the suite on Python 3.14 will cause compilation failures for `pydantic-core` due to incompatible Rust bindings (`PyO3`).

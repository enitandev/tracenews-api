# TraceNews API

TraceNews API is the FastAPI-based backend service for the TraceNews application. It serves news story clusters, aggregates outlet coverage data, and computes real-time reporting verdicts (clear, mixed, dark) using the Monitoring Spirit engine.

## Worker Process
The story aggregation and clustering pipeline does **not** run inside the web process. It runs as a **separate Railway cron service** every 20 minutes to fetch, process, and cluster new articles.

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

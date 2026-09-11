-- Worker overlap prevention lock table.
-- Run this migration before deploying the cron worker.
CREATE TABLE IF NOT EXISTS worker_locks (
    job_name TEXT PRIMARY KEY,
    locked_at TIMESTAMPTZ
);

-- Seed the initial row so the worker can update rather than insert on first run.
INSERT INTO worker_locks (job_name, locked_at)
VALUES ('batch_worker', NULL)
ON CONFLICT (job_name) DO NOTHING;

-- Rebuilt Daily Briefing (counsel, 3 Oct 2026, section B). One row per
-- selected story per day. The old daily_briefings table is left untouched
-- (it is preserved under the record hold).
create table if not exists briefing_editions (
  id              uuid primary key default gen_random_uuid(),
  date            date not null,
  position        integer not null,
  cluster_id      uuid not null,
  summary_id      text not null,
  gate            text not null,
  coverage_counts jsonb not null,
  counts_as_of    timestamptz not null,
  approved_by     text,
  approved_at     timestamptz,
  created_at      timestamptz not null default now(),
  unique (date, cluster_id)
);
-- Read and written by the API with the service key only; no public access.
alter table briefing_editions enable row level security;

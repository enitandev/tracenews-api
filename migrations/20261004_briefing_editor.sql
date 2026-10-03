-- Daily Briefing editor workflow (counsel's review of the 3 Oct samples,
-- items 2, 8 and 9). Adds editor rewrites, leave-outs, approvals that cover
-- the exact text approved, staff-only sample editions, and a change log of
-- every editor action. Additive only: no existing row or column is changed.
alter table briefing_editions
  add column if not exists is_sample           boolean not null default false,
  add column if not exists edited_title        text,
  add column if not exists edited_bullets      jsonb,
  add column if not exists edited_by           text,
  add column if not exists edited_at           timestamptz,
  add column if not exists left_out_by         text,
  add column if not exists left_out_reason     text,
  add column if not exists left_out_at         timestamptz,
  add column if not exists approved_summary_id text,
  add column if not exists approved_edit_at    timestamptz,
  add column if not exists approval_checklist  jsonb;

create table if not exists briefing_edit_log (
  id          uuid primary key default gen_random_uuid(),
  edition_id  uuid not null references briefing_editions(id),
  date        date not null,
  cluster_id  uuid not null,
  is_sample   boolean not null default false,
  editor      text not null,
  action      text not null,          -- rewrite | leave_out | restore | approve
  before      jsonb,
  after       jsonb,
  note        text,
  created_at  timestamptz not null default now()
);
-- Read and written by the API with the service key only; no public access.
alter table briefing_edit_log enable row level security;

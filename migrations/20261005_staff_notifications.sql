-- Staff notifications for the Desk (in-app first; email only for staff who
-- opt in). Additive only: no existing table is changed.
--
-- One row is one condition ("correction X is open", "the feed is late"),
-- not one event: while the condition holds, the row is updated in place
-- (last_seen_at, occurrences, severity), so a problem that persists for six
-- hours is one notification, not twelve. When the condition clears, the row
-- is resolved. dedupe_key names the condition; at most one open row per key.

create table if not exists staff_notifications (
  id             uuid primary key default gen_random_uuid(),
  dedupe_key     text not null,
  kind           text not null,          -- briefing | correction | politician | health
  severity       text not null check (severity in ('urgent', 'action', 'info')),
  section        text not null,          -- permission section that may see it (app/permissions.py)
  title          text not null,
  body           text,
  link           text,                   -- Desk route, e.g. /admin/corrections
  meta           jsonb not null default '{}'::jsonb,
  occurrences    integer not null default 1,
  first_seen_at  timestamptz not null default now(),
  last_seen_at   timestamptz not null default now(),
  escalated_at   timestamptz,            -- last time severity rose (unread again for everyone)
  resolved_at    timestamptz,
  resolved_by    text,                   -- "system" when the condition cleared, else the editor
  emailed_at     timestamptz,
  created_at     timestamptz not null default now()
);

create unique index if not exists staff_notifications_open_key
  on staff_notifications (dedupe_key) where resolved_at is null;
create index if not exists staff_notifications_recent
  on staff_notifications (last_seen_at desc);

-- Per-person read state. A row means "seen since the last escalation".
create table if not exists staff_notification_reads (
  notification_id uuid not null references staff_notifications(id) on delete cascade,
  user_id         uuid not null,
  read_at         timestamptz not null default now(),
  primary key (notification_id, user_id)
);

-- Per-person preferences. Email is off unless the person turns it on.
create table if not exists staff_notification_prefs (
  user_id      uuid primary key,
  email        text,
  email_urgent boolean not null default false,
  updated_at   timestamptz not null default now()
);

-- Read and written by the API with the service key only; no public access.
alter table staff_notifications enable row level security;
alter table staff_notification_reads enable row level security;
alter table staff_notification_prefs enable row level security;

-- Counsel's over-gating ruling (3 Oct 2026), items 5 and 6. Additive only.
--   extras / extras_dropped / extras_error / extras_generated_at: the fuller
--     sections (Who said what, What happens next, Background) as generated
--     and checked, and what the checks dropped.
--   edited_extras: an editor's rewrite of those sections.
--   second_approved_by / second_approved_at: senior-review items need a
--     second, different approver.
alter table briefing_editions
  add column if not exists extras              jsonb,
  add column if not exists extras_dropped      jsonb,
  add column if not exists extras_error        text,
  add column if not exists extras_generated_at timestamptz,
  add column if not exists edited_extras       jsonb,
  add column if not exists second_approved_by  text,
  add column if not exists second_approved_at  timestamptz;

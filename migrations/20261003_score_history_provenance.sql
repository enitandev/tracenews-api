-- Score provenance (counsel's scoping note, 3 Oct 2026, section 4): every
-- score computation is written to tii_score_history with its date, sample
-- size and model/prompt version. The scorer writes these columns and refuses
-- to publish a score if the history write fails, so apply this before the
-- next scoring run.
ALTER TABLE tii_score_history ADD COLUMN IF NOT EXISTS sample_size integer;
ALTER TABLE tii_score_history ADD COLUMN IF NOT EXISTS window_days integer;
ALTER TABLE tii_score_history ADD COLUMN IF NOT EXISTS model text;
ALTER TABLE tii_score_history ADD COLUMN IF NOT EXISTS prompt_version text;

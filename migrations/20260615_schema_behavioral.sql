-- Behavioral Scores table
CREATE TABLE IF NOT EXISTS outlet_behavioral_scores (
    outlet_slug text primary key,
    independence_score integer check (independence_score >= 0 and independence_score <= 100),
    critical_distance_notes text,
    accountability_notes text,
    story_selection_notes text,
    brown_envelope_suspected boolean,
    brown_envelope_evidence text,
    story_sample_size integer,
    analyzed_at timestamptz default now()
);

-- Enable RLS
ALTER TABLE outlet_behavioral_scores ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Public can read outlet_behavioral_scores" ON outlet_behavioral_scores;
CREATE POLICY "Public can read outlet_behavioral_scores"
    ON outlet_behavioral_scores FOR SELECT USING (true);

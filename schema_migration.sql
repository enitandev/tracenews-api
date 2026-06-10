-- schema_migration.sql

-- First, ensure the 'outlets' table has a unique constraint on 'slug' 
-- so that our python script can safely upsert without creating duplicates.
ALTER TABLE outlets ADD CONSTRAINT outlets_slug_key UNIQUE (slug);

-- Add the new 3D Scoring Columns and all properties from the new Master Registry
ALTER TABLE outlets 
  ADD COLUMN IF NOT EXISTS geopolitical_lean text DEFAULT 'National',
  ADD COLUMN IF NOT EXISTS structural_risk text DEFAULT 'Medium',
  ADD COLUMN IF NOT EXISTS credibility_tier text DEFAULT 'Institutional',
  ADD COLUMN IF NOT EXISTS independence_score integer DEFAULT 50,
  ADD COLUMN IF NOT EXISTS last_behavioral_scan timestamptz,
  ADD COLUMN IF NOT EXISTS track_record_status text DEFAULT 'Clean',
  ADD COLUMN IF NOT EXISTS brown_envelope_count integer DEFAULT 0,
  ADD COLUMN IF NOT EXISTS founded_year text,
  ADD COLUMN IF NOT EXISTS headquarters text,
  ADD COLUMN IF NOT EXISTS medium text,
  ADD COLUMN IF NOT EXISTS ownership_name text,
  ADD COLUMN IF NOT EXISTS ownership_type text,
  ADD COLUMN IF NOT EXISTS government_alignment text,
  ADD COLUMN IF NOT EXISTS quality_tier text,
  ADD COLUMN IF NOT EXISTS languages text,
  ADD COLUMN IF NOT EXISTS website text,
  ADD COLUMN IF NOT EXISTS rss_feed text,
  ADD COLUMN IF NOT EXISTS primary_audience text,
  ADD COLUMN IF NOT EXISTS notes text,
  ADD COLUMN IF NOT EXISTS active boolean DEFAULT true;

-- Add source_type to isolate fact-checker stories from the main feed
ALTER TABLE stories 
ADD COLUMN IF NOT EXISTS source_type text DEFAULT 'news';

UPDATE stories 
SET source_type = 'fact_check'
WHERE outlet_slug IN ('dubawa', 'africa-check-nigeria', 'factcheckhub');

-- Add slug to clusters table for SEO-friendly URLs
ALTER TABLE clusters ADD COLUMN IF NOT EXISTS slug text;
ALTER TABLE clusters ADD CONSTRAINT clusters_slug_key UNIQUE (slug);

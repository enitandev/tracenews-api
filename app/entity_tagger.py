import re
import logging
from app.db import supabase

logger = logging.getLogger(__name__)

_politicians_cache = None
_parties_cache = None

def load_registry():
  global _politicians_cache, _parties_cache
  
  if _politicians_cache is not None:
    return
  
  pol_res = supabase.table(
    'politicians'
  ).select(
    'id, common_name, aliases, notes, category'
  ).eq('active', True).execute()
  
  _politicians_cache = pol_res.data or []
  
  party_res = supabase.table(
    'parties'
  ).select(
    'id, abbreviation, aliases'
  ).eq('active', True).execute()
  
  _parties_cache = party_res.data or []
  
  logger.info(
    f"[entity_tagger] Registry loaded: "
    f"{len(_politicians_cache)} politicians,"
    f" {len(_parties_cache)} parties"
  )

def match_politicians(text):
  """
  Returns list of politician IDs 
  found in text via regex.
  Uses aliases array for matching.
  Requires minimum 5-char match to
  avoid false positives on short names.
  """
  if not text or not _politicians_cache:
    return []
  
  matched_ids = set()
  text_lower = text.lower()
  
  for pol in _politicians_cache:
    # Build list of names to match:
    # common_name + all aliases
    names_to_check = []
    
    cn = pol.get('common_name', '')
    if cn and len(cn) >= 5:
      names_to_check.append(cn)
    
    aliases = pol.get('aliases') or []
    for alias in aliases:
      if alias and len(alias) >= 5:
        names_to_check.append(alias)
    
    for name in names_to_check:
      # Word-boundary match, 
      # case insensitive
      pattern = r'\b' + re.escape(name) + r'\b'
      if re.search(pattern, text, re.IGNORECASE):
        matched_ids.add(pol['id'])
        break  # One match per politician is enough
  
  return list(matched_ids)

def match_parties(text):
  """
  Returns list of party IDs found 
  in text via regex.
  """
  if not text or not _parties_cache:
    return []
  
  matched_ids = set()
  text_lower = text.lower()
  
  for party in _parties_cache:
    aliases = party.get('aliases') or []
    abbrev = party.get('abbreviation','')
    
    all_names = aliases.copy()
    if abbrev and abbrev not in ('NONE', 'None'):
      all_names.append(abbrev)
    
    for name in all_names:
      if not name or len(name) < 2:
        continue
      pattern = r'\b' + re.escape(name) + r'\b'
      if re.search(pattern, text, re.IGNORECASE):
        matched_ids.add(party['id'])
        break
  
  return list(matched_ids)

def tag_story(story_id, title, summary, category=None):
  """
  Tags a story with politician and 
  party mentions.
  Called after story insert in fetcher.
  
  Args:
    story_id: UUID of the story
    title: story headline
    summary: 500-char RSS summary
    category: story category string
  """
  try:
    load_registry()
    
    # Combine title + summary for matching
    # Title gets double weight by 
    # including it twice
    text = f"{title} {title} {summary}"
    
    # Always run regex matching
    politician_ids = match_politicians(text)
    party_ids = match_parties(text)
    
    # Build entity rows to insert
    entity_rows = []
    
    for pol_id in politician_ids:
      entity_rows.append({
        'story_id': story_id,
        'entity_type': 'politician',
        'politician_id': pol_id,
        'party_id': None,
        'match_method': 'regex',
        'confidence': 1.0
      })
    
    for party_id in party_ids:
      entity_rows.append({
        'story_id': story_id,
        'entity_type': 'party',
        'politician_id': None,
        'party_id': party_id,
        'match_method': 'regex',
        'confidence': 1.0
      })
    
    # Only insert if we found something
    if entity_rows:
      supabase.table('story_entities').insert(entity_rows).execute()
      
      logger.debug(
        f"[entity_tagger] {story_id}: "
        f"{len(politician_ids)} politicians,"
        f" {len(party_ids)} parties"
      )
    
    return {
      'politicians': len(politician_ids),
      'parties': len(party_ids)
    }
    
  except Exception as e:
    # Never let tagging break ingestion
    logger.error(
      f"[entity_tagger] Failed for "
      f"{story_id}: {e}"
    )
    return {'politicians': 0, 'parties': 0}

if __name__ == '__main__':
  import json
  
  load_registry()
  print(
    f"Registry: "
    f"{len(_politicians_cache)} politicians"
    f", {len(_parties_cache)} parties"
  )
  
  # Test against a real story
  test_res = supabase.table(
    'stories'
  ).select(
    'id, title, summary'
  ).order(
    'created_at', desc=True
  ).limit(5).execute()
  
  for story in (test_res.data or []):
    print(f"\nStory: {story['title']}")
    result = tag_story(
      story['id'],
      story['title'],
      story.get('summary', '')
    )
    print(f"Tagged: {result}")

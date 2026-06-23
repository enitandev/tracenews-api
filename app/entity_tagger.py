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
    'id, common_name, aliases, notes, category, disambiguation_context'
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

def match_politicians(text, title=None):
  """
  Returns list of dicts with match info:
  {
    'politician_id': uuid,
    'match_alias': 'exact string matched',
    'match_location': 'title'|'summary'
  }
  Uses aliases + disambiguation_context.
  """
  if not text or not _politicians_cache:
    return []
  
  results = []
  seen_ids = set()
  
  for pol in _politicians_cache:
    if pol['id'] in seen_ids:
      continue
    
    dc = pol.get(
      'disambiguation_context'
    ) or {}
    positive_ctx = dc.get('positive', [])
    negative_ctx = dc.get('negative', [])
    window = dc.get('window_chars', 150)
    ambiguous = dc.get(
      'ambiguous_aliases', []
    )
    
    names_to_check = []
    cn = pol.get('common_name', '')
    if cn and len(cn) >= 5:
      names_to_check.append(cn)
    
    aliases = pol.get('aliases') or []
    for alias in aliases:
      if alias and len(alias) >= 5:
        names_to_check.append(alias)
    
    for name in names_to_check:
      pattern = r'\b' + re.escape(
        name) + r'\b'
      
      # Check title first, then full text
      matched_location = None
      if (title and re.search(
        pattern, title, re.IGNORECASE
      )):
        matched_location = 'title'
      elif re.search(
        pattern, text, re.IGNORECASE
      ):
        matched_location = 'summary'
      
      if not matched_location:
        continue
      
      # Disambiguation: if this alias 
      # is flagged as ambiguous, 
      # require context validation
      is_ambiguous = (
        name in ambiguous or 
        name.split()[-1] in ambiguous
      )
      
      if is_ambiguous or (
        positive_ctx and 
        len(name.split()) == 1 and 
        len(name) < 8
      ):
        # Check negative context first
        # (faster rejection)
        neg_found = False
        for neg in negative_ctx:
          neg_pattern = r'\b' + re.escape(
            neg) + r'\b'
          if re.search(
            neg_pattern, text, 
            re.IGNORECASE
          ):
            neg_found = True
            break
        
        if neg_found:
          continue
        
        # Check positive context
        if positive_ctx:
          pos_found = False
          for pos in positive_ctx:
            pos_pattern = r'\b' + re.escape(
              pos) + r'\b'
            if re.search(
              pos_pattern, text,
              re.IGNORECASE
            ):
              pos_found = True
              break
          
          if not pos_found:
            continue
      
      # Match confirmed
      results.append({
        'politician_id': pol['id'],
        'match_alias': name,
        'match_location': matched_location
      })
      seen_ids.add(pol['id'])
      break
  
  return results

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
    
    # Build text for matching
    # Keep title separate for 
    # match_location tracking
    full_text = f"{title} {title} {summary}"
    
    # Always run regex matching
    politician_matches = match_politicians(
      full_text, title=title
    )
    party_ids = match_parties(full_text)
    
    # Build entity rows to insert
    entity_rows = []
    
    for match in politician_matches:
      entity_rows.append({
        'story_id': story_id,
        'entity_type': 'politician',
        'politician_id': 
          match['politician_id'],
        'party_id': None,
        'match_method': 'regex',
        'confidence': 1.0,
        'match_alias': 
          match['match_alias'],
        'match_location': 
          match['match_location']
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
      supabase.table(
        'story_entities'
      ).upsert(
        entity_rows,
        on_conflict='story_id,entity_type,politician_id',
        ignore_duplicates=True
      ).execute()
      
      logger.debug(
        f"[entity_tagger] {story_id}: "
        f"{len(politician_matches)} politicians,"
        f" {len(party_ids)} parties"
      )
    
    return {
      'politicians': len(politician_matches),
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
    
    # Since we are testing, let's call match_politicians directly
    # to show the match aliases
    full_text = f"{story['title']} {story['title']} {story.get('summary', '')}"
    politician_matches = match_politicians(full_text, title=story['title'])
    party_ids = match_parties(full_text)
    
    print(
      f"Tagged: politicians="
      f"{len(politician_matches)} "
      f"parties={len(party_ids)}"
    )
    for m in politician_matches:
      print(
        f"  matched: "
        f"{m['match_alias']} "
        f"({m['match_location']})"
      )

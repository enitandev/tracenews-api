import logging
from datetime import datetime, timezone
from app.db import supabase
from app.entity_tagger import (
  tag_story, 
  load_registry
)
import app.entity_tagger as et

logger = logging.getLogger(__name__)

def backfill_entity_tags():
  load_registry()
  print(
    f"Registry loaded: "
    f"{len(et._politicians_cache)} "
    f"politicians, "
    f"{len(et._parties_cache)} parties"
  )
  
  # Get all stories in political 
  # categories that don't already 
  # have entity tags
  # Process in batches of 500
  
  batch_size = 500
  offset = 0
  total_processed = 0
  total_tagged = 0
  total_skipped = 0
  
  # Get cluster IDs for political 
  # categories first
  clusters_res = supabase.table(
    "clusters"
  ).select(
    "id"
  ).in_(
    "category", 
    ["Politics", "Security", "Economy"]
  ).execute()
  
  cluster_ids = [
    c["id"] 
    for c in (clusters_res.data or [])
  ]
  
  print(
    f"Found {len(cluster_ids)} "
    f"political clusters"
  )
  
  if not cluster_ids:
    print("No clusters found. Exiting.")
    return
  
  # Get already-tagged story IDs 
  # to skip them
  tagged_res = supabase.table(
    "story_entities"
  ).select("story_id").execute()
  
  already_tagged = set(
    r["story_id"] 
    for r in (tagged_res.data or [])
  )
  
  print(
    f"Already tagged: "
    f"{len(already_tagged)} stories"
  )
  
  # Process cluster_ids in chunks 
  # of 100 to avoid URL length limits
  cluster_chunk_size = 100
  for chunk_start in range(
    0, len(cluster_ids), cluster_chunk_size
  ):
    cluster_chunk = cluster_ids[
      chunk_start:chunk_start+cluster_chunk_size
    ]
    
    chunk_offset = 0
    while True:
      stories_res = supabase.table(
        "stories"
      ).select(
        "id, title, summary"
      ).in_(
        "cluster_id", cluster_chunk
      ).range(
        chunk_offset,
        chunk_offset + batch_size - 1
      ).execute()
      
      batch = stories_res.data or []
      if not batch:
        break
      
      for story in batch:
        story_id = story["id"]
        
        if story_id in already_tagged:
          total_skipped += 1
          continue
        
        result = tag_story(
          story_id=story_id,
          title=story.get("title", ""),
          summary=story.get("summary","")
        )
        
        if (result["politicians"] > 0
            or result["parties"] > 0):
          total_tagged += 1
        
        total_processed += 1
      
      chunk_offset += batch_size
      
      if len(batch) < batch_size:
        break
    
    print(
      f"Progress: clusters "
      f"{chunk_start+len(cluster_chunk)}"
      f"/{len(cluster_ids)} | "
      f"processed {total_processed} | "
      f"tagged {total_tagged}"
    )
  
  print(
    f"\nBackfill complete."
    f"\nProcessed: {total_processed}"
    f"\nTagged: {total_tagged}"
    f"\nSkipped: {total_skipped}"
  )
  return {
    "processed": total_processed,
    "tagged": total_tagged,
    "skipped": total_skipped
  }

if __name__ == "__main__":
  backfill_entity_tags()

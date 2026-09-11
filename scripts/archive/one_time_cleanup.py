from app.db import supabase
import logging
import sys
import time

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

while True:
    # Fetch ALL clusters with outlet_count < 2
    res = supabase.table("clusters").select("id").lt("outlet_count", 2).execute()
    bad_clusters = res.data or []

    if not bad_clusters:
        logging.info("No bad clusters found. Done.")
        break
        
    ids = [c["id"] for c in bad_clusters]
    logging.info(f"Found {len(ids)} bad clusters to delete.")
    
    # Process in batches
    batch_size = 50
    for i in range(0, len(ids), batch_size):
        batch_ids = ids[i:i+batch_size]
        supabase.table("stories").update({"cluster_id": None}).in_("cluster_id", batch_ids).execute()
        supabase.table("cluster_scores").delete().in_("cluster_id", batch_ids).execute()
        supabase.table("clusters").delete().in_("id", batch_ids).execute()
        
    logging.info(f"Successfully deleted {len(ids)} bad clusters in this pass.")
    time.sleep(1)

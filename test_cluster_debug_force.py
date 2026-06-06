from app.db import supabase
from app.clusterer import run_clustering
import logging
import sys

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

# Get 20 stories from recent single-story clusters
res = supabase.table("clusters").select("id").eq("outlet_count", 1).limit(20).execute()
cluster_ids = [c["id"] for c in res.data]

if cluster_ids:
    # Set their stories cluster_id to null
    supabase.table("stories").update({"cluster_id": None}).in_("cluster_id", cluster_ids).execute()
    # Delete those clusters
    supabase.table("clusters").delete().in_("id", cluster_ids).execute()
    supabase.table("cluster_scores").delete().in_("cluster_id", cluster_ids).execute()

# Now run clustering, which will pick them up
res = run_clustering()
print("Result:", res)

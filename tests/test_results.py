import os
import sys
import logging
from app.db import supabase

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

# How many clusters have outlet_count >= 2
res = supabase.table("clusters").select("id", count="exact").gte("outlet_count", 2).execute()
print(f"\n=== CLUSTERING RESULTS ===")
print(f"Clusters with outlet_count >= 2: {res.count}")

# Check Azeez story
azeez_res = supabase.table("stories").select("id, title, cluster_id, embedding").ilike("title", "%Azeez%").limit(1).execute()
if azeez_res.data:
    azeez = azeez_res.data[0]
    print(f"\n=== AZEEZ STORY ===")
    print(f"Title: {azeez['title']}")
    if azeez.get('embedding'):
        matches = supabase.rpc("match_clusters", {
            "query_embedding": azeez["embedding"],
            "match_threshold": 0.0,  # Show top 3 regardless of threshold
            "match_count": 3
        }).execute()
        for i, m in enumerate(matches.data or []):
            match_status = "MATCH" if m['similarity'] >= 0.82 else "NO MATCH"
            print(f" Rank {i+1} | Score: {m['similarity']:.3f} | [{match_status}] -> {m['representative_title']}")
    else:
        print(" No embedding found.")

# Check Proton story
proton_res = supabase.table("stories").select("id, title, cluster_id, embedding").ilike("title", "%Proton%").limit(1).execute()
if proton_res.data:
    proton = proton_res.data[0]
    print(f"\n=== PROTON STORY ===")
    print(f"Title: {proton['title']}")
    if proton.get('embedding'):
        matches = supabase.rpc("match_clusters", {
            "query_embedding": proton["embedding"],
            "match_threshold": 0.0,  # Show top 3 regardless of threshold
            "match_count": 3
        }).execute()
        for i, m in enumerate(matches.data or []):
            match_status = "MATCH" if m['similarity'] >= 0.82 else "NO MATCH"
            print(f" Rank {i+1} | Score: {m['similarity']:.3f} | [{match_status}] -> {m['representative_title']}")
    else:
        print(" No embedding found.")

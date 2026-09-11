import os
import sys
import logging
from app.db import supabase
from openai import OpenAI

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

def test_story(title_query):
    print(f"\n=== Testing: {title_query} ===")
    res = supabase.table("stories").select("id, title, summary").ilike("title", f"%{title_query}%").limit(1).execute()
    if not res.data:
        print("Story not found.")
        return
        
    story = res.data[0]
    print(f"Title: {story['title']}")
    
    text = f"{story.get('title', '')} {story.get('summary', '')}".strip()
    
    emb_res = openai_client.embeddings.create(
        input=text,
        model="text-embedding-3-small"
    )
    emb = emb_res.data[0].embedding
    
    matches = supabase.rpc("match_clusters", {
        "query_embedding": emb,
        "match_threshold": 0.0,  # show all to see what the closest is
        "match_count": 3
    }).execute()
    
    for i, m in enumerate(matches.data or []):
        match_status = "MATCH" if m['similarity'] >= 0.82 else "NO MATCH"
        print(f" Rank {i+1} | Score: {m['similarity']:.3f} | [{match_status}] -> {m['representative_title']}")

# Also show cluster counts
res = supabase.table("clusters").select("id", count="exact").gte("outlet_count", 2).execute()
print(f"\nClusters with outlet_count >= 2: {res.count}")

test_story("Azeez")
test_story("Proton")

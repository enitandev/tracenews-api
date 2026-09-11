import os
import sys
import logging
from app.db import supabase
from openai import OpenAI

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

res = supabase.table("stories").select("id, title, summary").is_("cluster_id", "null").is_("embedding", "null").execute()
stories = res.data or []

if not stories:
    logging.info("No stories need embeddings.")
    sys.exit(0)

logging.info(f"Found {len(stories)} unclustered stories missing embeddings. Backfilling...")

texts = [f"{s.get('title', '')} {s.get('summary', '')}".strip() for s in stories]

all_embeddings = []
try:
    for i in range(0, len(texts), 2000):
        batch = texts[i:i+2000]
        logging.info(f"Embedding batch {i} to {i+len(batch)}...")
        res = openai_client.embeddings.create(
            input=batch,
            model="text-embedding-3-small"
        )
        all_embeddings.extend([d.embedding for d in res.data])
except Exception as e:
    logging.error(f"Failed to generate embeddings: {e}")
    sys.exit(1)

logging.info("Saving embeddings to database...")
for i in range(0, len(stories), 100):
    batch_stories = stories[i:i+100]
    batch_embs = all_embeddings[i:i+100]
    for story, emb in zip(batch_stories, batch_embs):
        supabase.table("stories").update({"embedding": emb}).eq("id", story["id"]).execute()

logging.info("Backfill complete.")

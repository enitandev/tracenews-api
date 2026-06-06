import os
import sys
import logging
from app.db import supabase
from openai import OpenAI

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

res = supabase.table("clusters").select("id, representative_title").is_("embedding", "null").execute()
clusters = res.data or []

if not clusters:
    logging.info("No clusters need embeddings.")
    sys.exit(0)

logging.info(f"Found {len(clusters)} clusters missing embeddings. Backfilling...")

texts = [c['representative_title'] for c in clusters]

all_embeddings = []
try:
    for i in range(0, len(texts), 2000):
        batch = texts[i:i+2000]
        res = openai_client.embeddings.create(
            input=batch,
            model="text-embedding-3-small"
        )
        all_embeddings.extend([d.embedding for d in res.data])
except Exception as e:
    logging.error(f"Failed to generate embeddings: {e}")
    sys.exit(1)

logging.info("Saving cluster embeddings to database...")
for i in range(0, len(clusters), 100):
    batch_clusters = clusters[i:i+100]
    batch_embs = all_embeddings[i:i+100]
    for cluster, emb in zip(batch_clusters, batch_embs):
        supabase.table("clusters").update({"embedding": emb}).eq("id", cluster["id"]).execute()

logging.info("Cluster backfill complete.")

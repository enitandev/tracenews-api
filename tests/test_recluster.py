import logging
from app.clusterer import backfill_missing_embeddings, run_clustering
from app.scorer import run_scoring

logging.basicConfig(level=logging.INFO)

print("Starting backfill...")
backfill_missing_embeddings()
print("Starting clustering...")
res1 = run_clustering(all_time=True)
print("Clustering result:", res1)
print("Starting scoring...")
res2 = run_scoring(all_time=True)
print("Scoring result:", res2)
print("Done.")

import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from app.db import supabase

start = time.time()
counts = Counter()

def fetch_page(offset):
    res = supabase.table("coverage_snapshots").select("cluster_id").range(offset, offset + 999).execute()
    return res.data

offsets = range(0, 760000, 1000)
print(f"Fetching {len(offsets)} pages...")

with ThreadPoolExecutor(max_workers=20) as executor:
    results = executor.map(fetch_page, offsets)

for page_data in results:
    for row in page_data:
        counts[row["cluster_id"]] += 1

print(f"Total fetched: {sum(counts.values())} in {time.time() - start:.2f}s")

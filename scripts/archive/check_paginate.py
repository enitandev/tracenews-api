import time
from collections import Counter
from app.db import supabase

start = time.time()
counts = Counter()
offset = 0
limit = 10000 # Supabase might cap at 1000, let's see

while True:
    res = supabase.table("coverage_snapshots").select("cluster_id").range(offset, offset + limit - 1).execute()
    data = res.data
    for row in data:
        counts[row["cluster_id"]] += 1
    
    if len(data) < limit:
        break
    offset += limit
    
    if offset % 100000 == 0:
        print(f"Fetched {offset} in {time.time() - start:.2f}s")

print(f"Total fetched: {sum(counts.values())} in {time.time() - start:.2f}s")
top_500 = [cid for cid, _ in counts.most_common(5)]
print(top_500)

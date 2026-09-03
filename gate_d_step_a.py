import statistics
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from app.db import supabase

def verify_sample():
    print("Fetching clusters from campaign window (>= 2026-08-19)...")
    
    # Fetch all clusters with first_seen_at >= 2026-08-19
    all_campaign_clusters = set()
    offset = 0
    limit = 1000
    while True:
        res = supabase.table("clusters").select("id").gte("first_seen_at", "2026-08-19T00:00:00Z").range(offset, offset + limit - 1).execute()
        data = res.data or []
        for row in data:
            all_campaign_clusters.add(row["id"])
        if len(data) < limit:
            break
        offset += limit
        
    print(f"Total clusters with first_seen_at >= 2026-08-19: {len(all_campaign_clusters)}")
    
    if len(all_campaign_clusters) == 0:
        print("No clusters found in campaign window.")
        return
        
    print("Fetching snapshot counts...")
    
    def fetch_snapshot_page(off):
        try:
            return supabase.table("coverage_snapshots").select("cluster_id").range(off, off + 999).execute().data
        except:
            return []

    snapshot_counts = Counter()
    offsets = range(0, 800000, 1000)
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        for page_data in executor.map(fetch_snapshot_page, offsets):
            for row in page_data:
                snapshot_counts[row["cluster_id"]] += 1
                
    print(f"Counted {sum(snapshot_counts.values())} total snapshots.")
    
    campaign_snapshot_counts = {
        cid: count for cid, count in snapshot_counts.items() 
        if cid in all_campaign_clusters
    }
    
    sorted_campaign_counts = sorted(campaign_snapshot_counts.items(), key=lambda x: x[1], reverse=True)
    
    for cid in all_campaign_clusters:
        if cid not in campaign_snapshot_counts:
            sorted_campaign_counts.append((cid, 0))
            
    top_500 = sorted_campaign_counts[:500]
    
    print(f"\nSelected top {len(top_500)} clusters by snapshot count from the campaign window.")
    
    if top_500:
        counts_only = [c[1] for c in top_500]
        print(f"Distribution of snapshot counts in top-500:")
        print(f"  Max: {max(counts_only)}")
        print(f"  Min: {min(counts_only)}")
        print(f"  Median: {statistics.median(counts_only)}")
    
    print("\nTop 5 clusters (Cluster ID, Snapshot Count):")
    for cid, count in top_500[:5]:
        print(f"  {cid}: {count}")

if __name__ == "__main__":
    verify_sample()

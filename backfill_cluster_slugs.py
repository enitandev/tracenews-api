import os
import re
from app.db import supabase

def generate_slug(title: str) -> str:
    if not title:
        return 'story'
    slug = title.lower()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'\s+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    slug = slug[:80].strip('-')
    return slug

def run_backfill():
    print("Fetching all clusters without slugs...")
    res = supabase.table("clusters").select("id, representative_title").is_("slug", "null").execute()
    clusters = res.data or []
    print(f"Found {len(clusters)} clusters to update.")

    used_slugs = set()
    
    # Let's also fetch existing slugs to avoid conflicts just in case
    existing_res = supabase.table("clusters").select("slug").not_.is_("slug", "null").execute()
    for row in (existing_res.data or []):
        if row.get("slug"):
            used_slugs.add(row["slug"])

    updates = []
    for c in clusters:
        base_slug = generate_slug(c["representative_title"])
        slug = base_slug
        counter = 1
        while slug in used_slugs:
            slug = f"{base_slug}-{counter}"
            counter += 1
        
        used_slugs.add(slug)
        
        print(f"Assigning slug {slug} to cluster {c['id']}")
        
        # We update one by one
        try:
            supabase.table("clusters").update({"slug": slug}).eq("id", c["id"]).execute()
        except Exception as e:
            print(f"Error updating cluster {c['id']}: {e}")
            
    print("Backfill complete.")

if __name__ == "__main__":
    run_backfill()

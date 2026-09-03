import os
import time
import httpx
from app.db import supabase

WIKI_API = (
    "https://en.wikipedia.org/api/"
    "rest_v1/page/summary/{}"
)

def fetch_wiki_image(name: str) -> str | None:
    """
    Try to get a Wikipedia thumbnail
    for a politician by name.
    Returns image URL or None.
    """
    try:
        # Try full name first
        url = WIKI_API.format(
            name.replace(' ', '_')
        )
        r = httpx.get(
            url, 
            timeout=10,
            follow_redirects=True,
            headers={
                'User-Agent': 
                'TraceNews/1.0 '
                '(tracenews.ng; '
                'enitan@tracenews.ng)'
            }
        )
        if r.status_code == 200:
            data = r.json()
            thumb = data.get(
                'thumbnail', {}
            )
            src = thumb.get('source')
            if src:
                # Get larger version
                # Wikipedia thumbnails 
                # can be resized via URL
                # Replace width param 
                # with 320px
                import re
                src = re.sub(
                    r'/\d+px-', 
                    '/320px-', 
                    src
                )
                return src
        return None
    except Exception as e:
        print(f"  Error fetching {name}: {e}")
        return None

def main():
    print("Fetching politician images...")
    
    # Get all politicians
    res = supabase.table("politicians")\
        .select(
            "id, full_name, common_name, "
            "wikipedia_image_url"
        )\
        .execute()
    
    politicians = res.data or []
    print(f"Found {len(politicians)} politicians")
    
    updated = 0
    skipped = 0
    failed = 0
    
    for p in politicians:
        pid = p['id']
        name = p.get('common_name') or \
               p.get('full_name')
        existing = p.get(
            'wikipedia_image_url'
        )
        
        # Skip if already has image
        if existing:
            skipped += 1
            continue
        
        print(f"Fetching: {name}...")
        img_url = fetch_wiki_image(name)
        
        if not img_url:
            # Try full_name if common_name 
            # failed
            if p.get('common_name') and \
               p.get('full_name') != \
               p.get('common_name'):
                img_url = fetch_wiki_image(
                    p['full_name']
                )
        
        if img_url:
            supabase.table("politicians")\
                .update({
                    "wikipedia_image_url": 
                        img_url
                })\
                .eq("id", pid)\
                .execute()
            print(f"  ✓ {name}: {img_url[:60]}...")
            updated += 1
        else:
            print(f"  ✗ {name}: no image found")
            failed += 1
        
        # Be polite to Wikipedia API
        time.sleep(0.5)
    
    print()
    print(f"Done.")
    print(f"Updated: {updated}")
    print(f"Skipped (already had): {skipped}")
    print(f"Failed: {failed}")

if __name__ == "__main__":
    main()

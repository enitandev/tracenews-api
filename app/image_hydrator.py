import httpx
import logging
import asyncio
from bs4 import BeautifulSoup
from app.db import supabase

logger = logging.getLogger(__name__)

async def fetch_og_image_async(url: str, client: httpx.AsyncClient) -> str | None:
    """Fetch og:image from article URL."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; TraceNewsBot/1.0)"}
        response = await client.get(url, headers=headers, timeout=10, follow_redirects=True)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            og_img = soup.find("meta", property="og:image")
            if og_img and og_img.get("content"):
                return og_img["content"]
            
            # Fallback to reversed attribute just in case, though BS4 usually handles it
            og_img_name = soup.find("meta", attrs={"name": "og:image"})
            if og_img_name and og_img_name.get("content"):
                return og_img_name["content"]
    except Exception as e:
        logger.debug(f"Failed to fetch og:image for {url}: {e}")
    return None

def is_valid_image(url: str) -> bool:
    if not url:
        return False
    lower_url = url.lower()
    blacklist = ['logo', 'icon', 'avatar', 'default', 'brand', 'masthead']
    if any(b in lower_url for b in blacklist):
        return False
    return True

async def hydrate_images_task():
    logger.info("Starting async image hydration...")
    
    # Get stories from the last 24 hours without images
    from datetime import datetime, timezone, timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    
    res = supabase.table("stories").select("id, url").is_("image_url", "null").gte("published_at", cutoff).execute()
    stories = res.data or []
    
    if not stories:
        logger.info("No stories need image hydration.")
        return
        
    logger.info(f"Hydrating images for {len(stories)} stories.")
    
    updated = 0
    async with httpx.AsyncClient() as client:
        # Process in batches to avoid overwhelming the network
        batch_size = 10
        for i in range(0, len(stories), batch_size):
            batch = stories[i:i+batch_size]
            tasks = [fetch_og_image_async(s["url"], client) for s in batch]
            results = await asyncio.gather(*tasks)
            
            for story, img_url in zip(batch, results):
                if is_valid_image(img_url):
                    supabase.table("stories").update({"image_url": img_url}).eq("id", story["id"]).execute()
                    updated += 1
            
            await asyncio.sleep(1) # Be nice to servers

    logger.info(f"Image hydration complete. {updated} images found and saved.")

def run_image_hydration():
    """Wrapper to run the async task from sync context."""
    asyncio.run(hydrate_images_task())

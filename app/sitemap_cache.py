import asyncio
from app.db import supabase
import logging

logger = logging.getLogger(__name__)

cached_sitemap_xml = None
_sitemap_lock = asyncio.Lock()

async def generate_stories_sitemap_xml() -> str:
    # TODO: We are at ~28,634 URLs and climbing toward Google's 50,000-per-sitemap cap. 
    # Near-term follow-up: split into sitemap-stories-1.xml, sitemap-stories-2.xml etc., 
    # referenced from sitemap-index.xml before we hit 50k.
    
    def fetch_page(offset: int, page_size: int):
        res = supabase.table("clusters").select(
            "slug, first_seen_at, outlet_count"
        ).filter(
            "slug", "not.is", "null"
        ).gte(
            "outlet_count", 2
        ).order(
            "outlet_count", desc=True
        ).range(
            offset, offset + page_size - 1
        ).execute()
        return res.data or []

    page_size = 1000
    # Capped at 49,000 to stay under the 50,000 URL limit
    offsets = [i * page_size for i in range(49)]
    
    # Run all offset queries concurrently using asyncio.to_thread
    results = await asyncio.gather(
        *[asyncio.to_thread(fetch_page, offset, page_size) for offset in offsets]
    )
    
    clusters = []
    for batch in results:
        if not batch:
            continue
        clusters.extend(batch)
            
    # Safety cap at 49,000
    if len(clusters) > 49000:
        clusters = clusters[:49000]

    urls = []
    for c in clusters:
        if not c.get("slug"):
            continue
        loc = f"https://tracenews.ng/story/{c['slug']}"
        lastmod = (c.get("first_seen_at", "") or "")[:10]
        count = c.get("outlet_count", 1)
        
        if count >= 20:
            priority = "0.9"
        elif count >= 10:
            priority = "0.8"
        elif count >= 5:
            priority = "0.7"
        else:
            priority = "0.6"
            
        url_xml = f"  <url>\n"
        url_xml += f"    <loc>{loc}</loc>\n"
        if lastmod:
            url_xml += f"    <lastmod>{lastmod}</lastmod>\n"
        url_xml += f"    <changefreq>weekly</changefreq>\n"
        url_xml += f"    <priority>{priority}</priority>\n"
        url_xml += f"  </url>"
        urls.append(url_xml)

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    )
    xml += "\n".join(urls)
    xml += "\n</urlset>"
    
    return xml

async def regenerate_sitemap_cache():
    global cached_sitemap_xml
    async with _sitemap_lock:
        try:
            logger.info("Regenerating stories sitemap cache...")
            new_xml = await generate_stories_sitemap_xml()
            cached_sitemap_xml = new_xml
            logger.info(f"Sitemap cache regenerated: {len(new_xml)} bytes")
        except Exception as e:
            logger.error(f"Error regenerating sitemap cache: {e}")

def run_sitemap_cache_job_sync():
    """
    Synchronous wrapper for the background scheduler to run the async generation.
    """
    asyncio.run(regenerate_sitemap_cache())

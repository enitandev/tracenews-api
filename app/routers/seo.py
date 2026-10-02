"""Crawler surfaces: story OG page, sitemaps, sitemap health."""
import logging
from fastapi import APIRouter
from fastapi.responses import Response
from app.db import supabase

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/story-og/{slug}")
async def story_og(slug: str):
    from fastapi.responses import HTMLResponse
    import re
    
    cluster_res = supabase.table("clusters")\
      .select("id, representative_title")\
      .eq("slug", slug).execute()
    
    if not cluster_res.data:
      return HTMLResponse(
        content="<html><head>"\
        "<meta http-equiv='refresh' "\
        "content='0;url=https://"\
        "tracenews.ng'/></head></html>"
      )
    
    cluster = cluster_res.data[0]
    cluster_id = cluster["id"]
    title = cluster["representative_title"]
    canonical = f"https://tracenews.ng/story/{slug}"
    
    story_res = supabase.table("stories")\
      .select("image_url, summary")\
      .eq("cluster_id", cluster_id)\
      .not_.is_("image_url", "null")\
      .limit(1).execute()
    
    image_url = "https://tracenews.ng/og-default.png"
    description = "See every side of every Nigerian news story on TraceNews."
    
    if story_res.data:
      image_url = story_res.data[0].get("image_url") or image_url
      raw = story_res.data[0].get("summary") or ""
      clean = re.sub(r'<[^>]+>', '', raw).strip()[:160]
      if clean:
        description = clean
    
    # Escape quotes in title/description for HTML safety
    safe_title = title.replace('"', '&quot;')
    safe_desc = description.replace('"', '&quot;')
    
    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{safe_title}</title>
  <meta property="og:type" content="article">
  <meta property="og:title" content="{safe_title}">
  <meta property="og:description" content="{safe_desc}">
  <meta property="og:image" content="{image_url}">
  <meta property="og:url" content="{canonical}">
  <meta property="og:site_name" content="TraceNews">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{safe_title}">
  <meta name="twitter:description" content="{safe_desc}">
  <meta name="twitter:image" content="{image_url}">
  <meta http-equiv="refresh" content="0;url={canonical}">
</head>
<body>
  <a href="{canonical}">{safe_title}</a>
</body>
</html>"""
    
    return HTMLResponse(content=html)




@router.get("/sitemap.xml")
async def sitemap():
    """
    Generates sitemap.xml for all 
    clusters with slugs.
    Served at tracenews.ng/sitemap.xml
    via Vercel proxy.
    """
    try:
        res = supabase.table(
            "clusters"
        ).select(
            "slug, first_seen_at, "
            "outlet_count"
        ).filter(
            "slug", "not.is", "null"
        ).gte(
            "outlet_count", 2
        ).order(
            "outlet_count",
            desc=True
        ).limit(50000).execute()

        all_clusters = res.data or []
        
        # Also add static pages
        static_pages = [
            {
                "loc": "https://tracenews.ng/",
                "priority": "1.0",
                "changefreq": "hourly"
            },
            {
                "loc": "https://tracenews.ng/daily-briefing",
                "priority": "0.9",
                "changefreq": "daily"
            },
            {
                "loc": "https://tracenews.ng/topics/politics",
                "priority": "0.8",
                "changefreq": "hourly"
            },
            {
                "loc": "https://tracenews.ng/topics/security",
                "priority": "0.8",
                "changefreq": "hourly"
            },
            {
                "loc": "https://tracenews.ng/topics/economy",
                "priority": "0.8",
                "changefreq": "hourly"
            },
            {
                "loc": "https://tracenews.ng/topics/judiciary",
                "priority": "0.7",
                "changefreq": "daily"
            },
            {
                "loc": "https://tracenews.ng/topics/health",
                "priority": "0.7",
                "changefreq": "daily"
            },
            {
                "loc": "https://tracenews.ng/topics/education",
                "priority": "0.7",
                "changefreq": "daily"
            },
            {
                "loc": "https://tracenews.ng/topics/sports",
                "priority": "0.6",
                "changefreq": "daily"
            },
            {
                "loc": "https://tracenews.ng/topics/technology",
                "priority": "0.6",
                "changefreq": "daily"
            },
            {
                "loc": "https://tracenews.ng/topics/entertainment",
                "priority": "0.5",
                "changefreq": "daily"
            },
            {
                "loc": "https://tracenews.ng/topics/international",
                "priority": "0.6",
                "changefreq": "daily"
            },
        ]
        
        # Build XML
        urls = []
        
        # Static pages first
        for page in static_pages:
            urls.append(
                f"  <url>\n"
                f"    <loc>{page['loc']}</loc>\n"
                f"    <changefreq>{page['changefreq']}</changefreq>\n"
                f"    <priority>{page['priority']}</priority>\n"
                f"  </url>"
            )
        
        # Story pages
        for c in all_clusters:
            if not c.get("slug"):
                continue
            loc = f"https://tracenews.ng/story/{c['slug']}"
            lastmod = (
                c.get("first_seen_at", "")
                or ""
            )[:10]  # YYYY-MM-DD
            
            # Priority based on outlet_count
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
        
        # Fetch all active politicians 
        # with slugs
        pol_res = supabase.table(
            "politicians"
        ).select(
            "slug, updated_at"
        ).filter(
            "slug", "not.is", "null"
        ).eq(
            "active", True
        ).execute()
        
        politicians_data = pol_res.data or []
        
        # Add politician URLs to sitemap
        for p in politicians_data:
            if not p.get("slug"):
                continue
            loc = (
                f"https://tracenews.ng"
                f"/politicians/{p['slug']}"
            )
            lastmod = (
                p.get("updated_at", "") or ""
            )[:10]
            
            url_xml = f"  <url>\n"
            url_xml += f"    <loc>{loc}</loc>\n"
            if lastmod:
                url_xml += (
                    f"    <lastmod>"
                    f"{lastmod}"
                    f"</lastmod>\n"
                )
            url_xml += (
                f"    <changefreq>"
                f"weekly"
                f"</changefreq>\n"
            )
            url_xml += (
                f"    <priority>0.7</priority>\n"
            )
            url_xml += f"  </url>"
            urls.append(url_xml)

        # Fetch all active outlets 
        # with slugs
        outlet_res = supabase.table(
            "outlets"
        ).select(
            "slug"
        ).filter(
            "slug", "not.is", "null"
        ).eq(
            "active", True
        ).execute()
        
        outlets_data = outlet_res.data or []
        
        for o in outlets_data:
            if not o.get("slug"):
                continue
            loc = (
                f"https://tracenews.ng"
                f"/outlets/{o['slug']}"
            )
            url_xml = f"  <url>\n"
            url_xml += f"    <loc>{loc}</loc>\n"
            url_xml += (
                f"    <changefreq>"
                f"weekly"
                f"</changefreq>\n"
            )
            url_xml += (
                f"    <priority>0.7</priority>\n"
            )
            url_xml += f"  </url>"
            urls.append(url_xml)
        
        xml = (
            '<?xml version="1.0" '
            'encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        )
        xml += "\n".join(urls)
        xml += "\n</urlset>"
        
        return Response(
            content=xml,
            media_type="application/xml",
            headers={
                "Cache-Control": 
                    "public, max-age=3600"
            }
        )
    except Exception as e:
        logger.error(f"Sitemap error: {e}")
        return Response(
            content='<?xml version="1.0"?>'
                    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"/>',
            media_type="application/xml"
        )


@router.get("/news-sitemap.xml")
async def news_sitemap():
    """
    Google News sitemap — last 48 hours
    only, per Google News spec.
    Max 1000 articles per Google News
    sitemap spec.
    """
    try:
        from datetime import datetime, timezone, timedelta
        
        cutoff = (
            datetime.now(timezone.utc) - 
            timedelta(hours=48)
        ).isoformat()
        
        res = supabase.table(
            "clusters"
        ).select(
            "slug, representative_title, "
            "first_seen_at, category"
        ).filter(
            "slug", "not.is", "null"
        ).gte(
            "first_seen_at", cutoff
        ).order(
            "first_seen_at", desc=True
        ).limit(1000).execute()
        
        clusters = res.data or []
        
        urls = []
        for c in clusters:
            if not c.get("slug"):
                continue
            if not c.get(
                "representative_title"
            ):
                continue
            
            loc = (
                f"https://tracenews.ng"
                f"/story/{c['slug']}"
            )
            
            # Format publication date
            # for Google News
            pub_date = c.get(
                "first_seen_at", ""
            )
            if pub_date:
                # Already ISO format
                pub_date = pub_date
            else:
                pub_date = (
                    datetime.now(
                        timezone.utc
                    ).isoformat()
                )
            
            # Escape title for XML
            title = (
                c.get(
                    "representative_title",
                    ""
                )
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
            )
            
            url_xml = (
                f"  <url>\n"
                f"    <loc>{loc}</loc>\n"
                f"    <news:news>\n"
                f"      <news:publication>\n"
                f"        <news:name>"
                f"TraceNews"
                f"</news:name>\n"
                f"        <news:language>"
                f"en"
                f"</news:language>\n"
                f"      </news:publication>\n"
                f"      <news:publication_date>"
                f"{pub_date}"
                f"</news:publication_date>\n"
                f"      <news:title>"
                f"{title}"
                f"</news:title>\n"
                f"    </news:news>\n"
                f"  </url>"
            )
            urls.append(url_xml)
        
        xml = (
            '<?xml version="1.0" '
            'encoding="UTF-8"?>\n'
            '<urlset '
            'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            'xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">\n'
        )
        xml += "\n".join(urls)
        xml += "\n</urlset>"
        
        return Response(
            content=xml,
            media_type="application/xml",
            headers={
                "Cache-Control": 
                    "public, max-age=1800"
            }
        )
    except Exception as e:
        logger.error(
            f"News sitemap error: {e}"
        )
        return Response(
            content='<?xml version="1.0"?>'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
                'xmlns:news="http://www.google.com/schemas/sitemap-news/0.9"/>',
            media_type="application/xml"
        )

@router.get("/sitemap-index.xml")
async def sitemap_index():
    """
    Sitemap index pointing to all 
    child sitemaps.
    Submit this to Search Console 
    instead of /sitemap.xml.
    """
    base = "https://tracenews.ng"
    
    from datetime import datetime, timezone
    today = datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d")
    
    sitemaps = [
        f"{base}/sitemap-stories.xml",
        f"{base}/sitemap-outlets.xml",
        f"{base}/sitemap-politicians.xml",
        f"{base}/sitemap-static.xml",
    ]
    
    urls = []
    for loc in sitemaps:
        urls.append(
            f"  <sitemap>\n"
            f"    <loc>{loc}</loc>\n"
            f"    <lastmod>{today}</lastmod>\n"
            f"  </sitemap>"
        )
    
    xml = (
        '<?xml version="1.0" '
        'encoding="UTF-8"?>\n'
        '<sitemapindex xmlns="'
        'http://www.sitemaps.org/'
        'schemas/sitemap/0.9">\n'
    )
    xml += "\n".join(urls)
    xml += "\n</sitemapindex>"
    
    return Response(
        content=xml,
        media_type="application/xml",
        headers={
            "Cache-Control": 
                "public, max-age=3600"
        }
    )

@router.get("/sitemap-stories.xml")
async def sitemap_stories():
    """
    All story clusters with outlet_count >= 2.
    Serves from background cache.
    """
    import app.sitemap_cache as sc
    
    if sc.cached_sitemap_xml is None:
        await sc.regenerate_sitemap_cache()
        
    xml = sc.cached_sitemap_xml
    
    if xml is None:
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"/>'
        )

    return Response(
        content=xml,
        media_type="application/xml",
        headers={
            "Cache-Control": "public, max-age=3600"
        }
    )

@router.get("/sitemap-outlets.xml")
async def sitemap_outlets():
    try:
        res = supabase.table(
            "outlets"
        ).select(
            "slug"
        ).filter(
            "slug", "not.is", "null"
        ).eq(
            "active", True
        ).execute()
        
        outlets = res.data or []
        
        urls = []
        for o in outlets:
            if not o.get("slug"):
                continue
            loc = (
                f"https://tracenews.ng"
                f"/outlets/{o['slug']}"
            )
            url_xml = (
                f"  <url>\n"
                f"    <loc>{loc}</loc>\n"
                f"    <changefreq>"
                f"weekly"
                f"</changefreq>\n"
                f"    <priority>"
                f"0.8"
                f"</priority>\n"
                f"  </url>"
            )
            urls.append(url_xml)
        
        xml = (
            '<?xml version="1.0" '
            'encoding="UTF-8"?>\n'
            '<urlset xmlns="http://'
            'www.sitemaps.org/schemas/'
            'sitemap/0.9">\n'
        )
        xml += "\n".join(urls)
        xml += "\n</urlset>"
        
        return Response(
            content=xml,
            media_type="application/xml",
            headers={
                "Cache-Control": 
                    "public, max-age=86400"
            }
        )
    except Exception as e:
        logger.error(
            f"Outlets sitemap error: {e}"
        )
        return Response(
            content=(
                '<?xml version="1.0"?>'
                '<urlset xmlns="http://'
                'www.sitemaps.org/schemas/'
                'sitemap/0.9"/>'
            ),
            media_type="application/xml"
        )

@router.get("/sitemap-politicians.xml")
async def sitemap_politicians():
    try:
        res = supabase.table(
            "politicians"
        ).select(
            "slug, updated_at, "
            "publication_status"
        ).filter(
            "slug", "not.is", "null"
        ).eq(
            "active", True
        ).eq(
            "publication_status", "published"
        ).execute()
        
        politicians = res.data or []
        
        urls = []
        for p in politicians:
            if not p.get("slug"):
                continue
            loc = (
                f"https://tracenews.ng"
                f"/politicians/{p['slug']}"
            )
            lastmod = (
                p.get("updated_at", "") 
                or ""
            )[:10]
            
            url_xml = f"  <url>\n"
            url_xml += (
                f"    <loc>{loc}</loc>\n"
            )
            if lastmod:
                url_xml += (
                    f"    <lastmod>"
                    f"{lastmod}"
                    f"</lastmod>\n"
                )
            url_xml += (
                f"    <changefreq>"
                f"weekly"
                f"</changefreq>\n"
                f"    <priority>"
                f"0.8"
                f"</priority>\n"
                f"  </url>"
            )
            urls.append(url_xml)
        
        xml = (
            '<?xml version="1.0" '
            'encoding="UTF-8"?>\n'
            '<urlset xmlns="http://'
            'www.sitemaps.org/schemas/'
            'sitemap/0.9">\n'
        )
        xml += "\n".join(urls)
        xml += "\n</urlset>"
        
        return Response(
            content=xml,
            media_type="application/xml",
            headers={
                "Cache-Control": 
                    "public, max-age=86400"
            }
        )
    except Exception as e:
        logger.error(
            f"Politicians sitemap error: {e}"
        )
        return Response(
            content=(
                '<?xml version="1.0"?>'
                '<urlset xmlns="http://'
                'www.sitemaps.org/schemas/'
                'sitemap/0.9"/>'
            ),
            media_type="application/xml"
        )

@router.get("/sitemap-static.xml")
async def sitemap_static():
    static_pages = [
        ("https://tracenews.ng/", 
         "1.0", "hourly"),
        ("https://tracenews.ng/daily-briefing", 
         "0.9", "daily"),
        ("https://tracenews.ng/methodology", 
         "0.8", "monthly"),
        ("https://tracenews.ng/about", 
         "0.8", "monthly"),
        ("https://tracenews.ng/corrections", 
         "0.5", "monthly"),
        ("https://tracenews.ng/topics/politics", 
         "0.8", "hourly"),
        ("https://tracenews.ng/topics/security", 
         "0.8", "hourly"),
        ("https://tracenews.ng/topics/economy", 
         "0.8", "hourly"),
        ("https://tracenews.ng/topics/judiciary", 
         "0.7", "daily"),
        ("https://tracenews.ng/topics/health", 
         "0.7", "daily"),
        ("https://tracenews.ng/topics/education", 
         "0.7", "daily"),
        ("https://tracenews.ng/topics/sports", 
         "0.6", "daily"),
        ("https://tracenews.ng/topics/technology", 
         "0.6", "daily"),
        ("https://tracenews.ng/topics/entertainment", 
         "0.5", "daily"),
        ("https://tracenews.ng/topics/international", 
         "0.6", "daily"),
    ]
    
    urls = []
    for loc, priority, changefreq \
            in static_pages:
        urls.append(
            f"  <url>\n"
            f"    <loc>{loc}</loc>\n"
            f"    <changefreq>"
            f"{changefreq}"
            f"</changefreq>\n"
            f"    <priority>"
            f"{priority}"
            f"</priority>\n"
            f"  </url>"
        )
    
    xml = (
        '<?xml version="1.0" '
        'encoding="UTF-8"?>\n'
        '<urlset xmlns="http://'
        'www.sitemaps.org/schemas/'
        'sitemap/0.9">\n'
    )
    xml += "\n".join(urls)
    xml += "\n</urlset>"
    
    return Response(
        content=xml,
        media_type="application/xml",
        headers={
            "Cache-Control": 
                "public, max-age=86400"
        }
    )

@router.get("/sitemap-health")
async def sitemap_health():
    """
    Checks all sitemap endpoints 
    return URLs. Returns 200 if 
    healthy, 503 if any sitemap 
    is empty.
    """
    import httpx
    
    base = "https://tracenews.ng"
    sitemaps_to_check = [
        "/sitemap-stories.xml",
        "/sitemap-outlets.xml",
        "/sitemap-politicians.xml",
        "/sitemap-static.xml",
        "/news-sitemap.xml"
    ]
    
    results = {}
    all_healthy = True
    
    async with httpx.AsyncClient(
        timeout=15
    ) as client:
        for path in sitemaps_to_check:
            try:
                r = await client.get(
                    f"{base}{path}"
                )
                count = r.text.count(
                    "<url>"
                )
                healthy = count > 0
                results[path] = {
                    "url_count": count,
                    "healthy": healthy,
                    "status_code": 
                        r.status_code
                }
                if not healthy:
                    all_healthy = False
            except Exception as e:
                results[path] = {
                    "error": str(e),
                    "healthy": False
                }
                all_healthy = False
    
    from fastapi.responses import (
        JSONResponse
    )
    return JSONResponse(
        status_code=200 
            if all_healthy else 503,
        content={
            "healthy": all_healthy,
            "checked_at": 
                __import__('datetime')
                .datetime.now(
                    __import__('datetime')
                    .timezone.utc
                ).isoformat(),
            "sitemaps": results
        }
    )

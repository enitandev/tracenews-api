import feedparser
import httpx
import logging
from datetime import datetime, timezone
from dateutil import parser as dateparser
from app.db import supabase

logger = logging.getLogger(__name__)


def extract_image_from_entry(entry: dict) -> str | None:
    """Extract image URL from RSS entry using multiple fallback methods."""

    # Method 1: media:content tag
    media_content = entry.get("media_content", [])
    if media_content:
        for media in media_content:
            url = media.get("url", "")
            if url and any(ext in url.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                return url

    # Method 2: media:thumbnail
    media_thumbnail = entry.get("media_thumbnail", [])
    if media_thumbnail:
        url = media_thumbnail[0].get("url", "")
        if url:
            return url

    # Method 3: enclosure tag
    enclosures = entry.get("enclosures", [])
    for enc in enclosures:
        if enc.get("type", "").startswith("image/"):
            return enc.get("href", "") or enc.get("url", "")

    # Method 4: links with image type
    links = entry.get("links", [])
    for link in links:
        if link.get("type", "").startswith("image/"):
            return link.get("href", "")

    # Method 5: parse og:image from summary/content HTML
    content = entry.get("summary", "") or entry.get("content", [{}])[0].get("value", "")
    if content and "<img" in content:
        import re
        match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', content)
        if match:
            url = match.group(1)
            if url.startswith("http"):
                return url

    return None


def fetch_og_image(url: str) -> str | None:
    """Fetch og:image from article URL as last resort."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; TraceNewsBot/1.0)"}
        response = httpx.get(url, headers=headers, timeout=8, follow_redirects=True)
        if response.status_code == 200:
            import re
            match = re.search(
                r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
                response.text
            )
            if match:
                return match.group(1)
            # Also try reversed attribute order
            match = re.search(
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
                response.text
            )
            if match:
                return match.group(1)
    except Exception:
        pass
    return None


def fetch_outlets() -> list[dict]:
    """Fetch all active outlets with RSS feeds from Supabase."""
    response = supabase.table("outlets").select(
        "id, name, slug, rss_feeds, geopolitical_lean, party_proximity, ownership_type"
    ).eq("active", True).execute()
    return [o for o in response.data if o.get("rss_feeds")]


def parse_feed(outlet: dict) -> list[dict]:
    """Parse all RSS feeds for a given outlet and return story dicts."""
    stories = []
    for feed_url in outlet["rss_feeds"]:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                title = entry.get("title", "").strip()
                url = entry.get("link", "").strip()
                summary = entry.get("summary", "").strip()[:500]
                published_raw = entry.get("published", entry.get("updated", ""))

                if not title or not url:
                    continue

                try:
                    published_at = dateparser.parse(published_raw).astimezone(timezone.utc).isoformat()
                except Exception:
                    published_at = datetime.now(timezone.utc).isoformat()

                # Extract image — try RSS first, fall back to og:image scrape
                image_url = extract_image_from_entry(entry)
                if not image_url:
                    image_url = fetch_og_image(url)

                stories.append({
                    "outlet_id":        outlet["id"],
                    "outlet_name":      outlet["name"],
                    "outlet_slug":      outlet["slug"],
                    "geopolitical_lean":outlet["geopolitical_lean"],
                    "party_proximity":  outlet["party_proximity"],
                    "ownership_type":   outlet["ownership_type"],
                    "title":            title,
                    "url":              url,
                    "summary":          summary,
                    "image_url":        image_url,
                    "published_at":     published_at,
                    "fetched_at":       datetime.now(timezone.utc).isoformat(),
                })
        except Exception as e:
            logger.warning(f"Failed to parse feed {feed_url} for {outlet['name']}: {e}")
    return stories


def save_stories(stories: list[dict]) -> int:
    """Insert stories, skip duplicates by URL."""
    if not stories:
        return 0
    saved = 0
    for story in stories:
        try:
            supabase.table("stories").upsert(
                story,
                on_conflict="url"
            ).execute()
            saved += 1
        except Exception as e:
            logger.warning(f"Failed to save story {story.get('url')}: {e}")
    return saved


def run_fetch() -> dict:
    """Main fetch job — runs on schedule."""
    logger.info("Starting RSS fetch run...")
    outlets = fetch_outlets()
    logger.info(f"Found {len(outlets)} active outlets with feeds")

    all_stories = []
    for outlet in outlets:
        stories = parse_feed(outlet)
        all_stories.extend(stories)
        logger.info(f"{outlet['name']}: {len(stories)} stories")

    saved = save_stories(all_stories)
    logger.info(f"Fetch complete. {saved}/{len(all_stories)} stories saved.")
    return {
        "outlets_fetched": len(outlets),
        "stories_found":   len(all_stories),
        "stories_saved":   saved,
    }

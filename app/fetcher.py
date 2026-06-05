import feedparser
import httpx
import logging
from datetime import datetime, timezone
from dateutil import parser as dateparser
from app.db import supabase

logger = logging.getLogger(__name__)


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

                stories.append({
                    "outlet_id": outlet["id"],
                    "outlet_name": outlet["name"],
                    "outlet_slug": outlet["slug"],
                    "geopolitical_lean": outlet["geopolitical_lean"],
                    "party_proximity": outlet["party_proximity"],
                    "ownership_type": outlet["ownership_type"],
                    "title": title,
                    "url": url,
                    "summary": summary,
                    "published_at": published_at,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
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
        "stories_found": len(all_stories),
        "stories_saved": saved,
    }

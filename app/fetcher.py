import feedparser
import logging
from datetime import datetime, timezone
from dateutil import parser as dateparser
import os
import urllib.parse
from bs4 import BeautifulSoup
from app.db import supabase
from openai import OpenAI

logger = logging.getLogger(__name__)

openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

RSS_IMAGE_UNRELIABLE_OUTLETS = ['punch-nigeria', 'punch-metro']
FACT_CHECKER_OUTLETS = ['dubawa', 'africa-check-nigeria', 'factcheckhub']

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

    # Method 5: parse img from summary/content HTML
    content = entry.get("summary", "") or entry.get("content", [{}])[0].get("value", "")
    if content and "<img" in content:
        soup = BeautifulSoup(content, "html.parser")
        img = soup.find("img")
        if img and img.get("src"):
            url = img["src"]
            if url.startswith("http"):
                return url

    return None

def is_valid_image(url: str) -> bool:
    if not url:
        return False
    lower_url = url.lower()
    blacklist = ['logo', 'icon', 'avatar', 'default', 'brand', 'masthead', 'googleusercontent.com']
    if any(b in lower_url for b in blacklist):
        return False
    return True

def fetch_outlets() -> list[dict]:
    """Fetch all active outlets with RSS feeds from Supabase."""
    response = supabase.table("outlets").select(
        "id, name, slug, website, rss_feeds, geopolitical_lean, party_proximity, ownership_type"
    ).eq("active", True).execute()
    return [o for o in response.data if o.get("rss_feeds") or o.get("website")]

def parse_feed(outlet: dict) -> list[dict]:
    """Parse all RSS feeds for a given outlet and return story dicts."""
    stories = []
    is_unreliable = outlet["slug"] in RSS_IMAGE_UNRELIABLE_OUTLETS

    for feed_url in outlet["rss_feeds"]:
        try:
            feed = feedparser.parse(
                feed_url, 
                agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            
            feed_str = str(feed)
            is_cloudflare = "Just a moment" in feed_str or "Enable JavaScript and cookies" in feed_str
            
            # Fallback to Google News RSS if blocked by Cloudflare or 0 entries
            if (len(feed.entries) == 0 or is_cloudflare) and outlet.get("website"):
                website = outlet["website"]
                if not website.startswith("http"):
                    website = "https://" + website
                parsed_url = urllib.parse.urlparse(website)
                domain = parsed_url.netloc.replace("www.", "")
                
                fallback_url = f"https://news.google.com/rss/search?q=site:{domain}&hl=en-NG&gl=NG&ceid=NG:en"
                logger.info(f"Using Google News fallback for {outlet['name']} ({domain})")
                feed = feedparser.parse(
                    fallback_url, 
                    agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )

            for entry in feed.entries:
                title = entry.get("title", "").strip()
                if "Archives -" in title or "Archives Page" in title:
                    continue
                url = entry.get("link", "").strip()
                summary = entry.get("summary", "").strip()[:500]
                published_raw = entry.get("published", entry.get("updated", ""))

                if not title or not url:
                    continue

                try:
                    published_at = dateparser.parse(published_raw).astimezone(timezone.utc).isoformat()
                except Exception:
                    published_at = datetime.now(timezone.utc).isoformat()

                # Extract image
                image_url = None
                if not is_unreliable:
                    extracted = extract_image_from_entry(entry)
                    if is_valid_image(extracted):
                        image_url = extracted

                source_type = 'fact_check' if outlet["slug"] in FACT_CHECKER_OUTLETS else 'news'
                
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
                    "source_type":      source_type,
                })
        except Exception as e:
            logger.warning(f"Failed to parse feed {feed_url} for {outlet['name']}: {e}")
    return stories

def save_stories(stories: list[dict]) -> int:
    """Filter duplicates, batch embed, and insert new stories."""
    if not stories:
        return 0

    # Local deduplication
    unique_stories = {}
    for s in stories:
        unique_stories[s["url"]] = s
    incoming_urls = list(unique_stories.keys())
    
    # Check DB for existing URLs
    existing_urls = set()
    for i in range(0, len(incoming_urls), 200):
        batch = incoming_urls[i:i+200]
        try:
            res = supabase.table("stories").select("url").in_("url", batch).execute()
            if res.data:
                existing_urls.update(row["url"] for row in res.data)
        except Exception as e:
            logger.warning(f"Error checking existing URLs: {e}")

    new_stories = [s for url, s in unique_stories.items() if url not in existing_urls]
    if not new_stories:
        return 0

    logger.info(f"Processing and saving {len(new_stories)} new stories...")
    saved = 0
    for story in new_stories:
        try:
            text_to_embed = f"{story.get('title', '')} {story.get('summary', '')}".strip()
            
            # Generate embedding for the individual story
            res = openai_client.embeddings.create(
                input=[text_to_embed],
                model="text-embedding-3-small"
            )
            story["embedding"] = res.data[0].embedding
            
            # Save the story
            supabase.table("stories").insert(story).execute()
            saved += 1
        except Exception as e:
            logger.warning(f"Failed to process and save story {story.get('url')}: {e}")
            continue
            
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

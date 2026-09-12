# Maintained by observation, not computed.
# These outlets are known to block image hotlinking via Referrer or other checks.
HOTLINK_BLOCKING_DOMAINS = [
    "punchng.com",
    "vanguardngr.com",
    "thecable.ng",
    "premiumtimesng.com",
    "saharareporters.com"
]

def is_image_allowed(url: str) -> bool:
    if not url: return False
    url_lower = url.lower()
    for domain in HOTLINK_BLOCKING_DOMAINS:
        if domain in url_lower:
            return False
    return True

def get_cluster_image(stories: list) -> str | None:
    """Take the first non-empty image_url that is not blocked."""
    for s in (stories or []):
        url = s.get("image_url")
        if url and is_image_allowed(url):
            return url
    return None

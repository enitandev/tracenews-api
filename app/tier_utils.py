import logging

logger = logging.getLogger(__name__)

def get_outlet_tier(government_alignment: str, is_blog: bool = False) -> str:
    """
    Derives the tier (govt_aligned, mainstream, watchdog) from government_alignment.
    If is_blog is True, returns 'blog'.
    Unrecognised values are logged as errors and return 'unscored'.
    """
    if is_blog:
        return "blog"
        
    if not government_alignment:
        return "unscored"
        
    align = government_alignment.lower()
    if align == "pro_government":
        return "govt_aligned"
    elif align == "neutral":
        return "mainstream"
    elif align == "opposition":
        return "watchdog"
    else:
        logger.error(f"Unrecognised government_alignment value: {government_alignment}")
        return "unscored"

def get_distinct_scored_count(coverage_stats: dict) -> int | None:
    """
    Returns the distinct scored outlet count from the tier distribution.
    If the distribution is not available, returns None.
    """
    if not coverage_stats:
        return None
        
    dist = coverage_stats.get("coverage_tier_distribution")
    if not dist:
        return None
        
    return dist.get("govt_aligned", 0) + dist.get("mainstream", 0) + dist.get("watchdog", 0)

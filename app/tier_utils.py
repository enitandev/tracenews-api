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

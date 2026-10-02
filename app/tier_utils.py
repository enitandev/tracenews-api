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

    # Legacy keys are read, an unreadable distribution is unknown (None),
    # never a count of zero.
    dist = normalize_tier_distribution(dist)
    if dist is None:
        return None
    return sum(dist.values())


# Tiers shown on the three-tier coverage surfaces, in display order.
CARD_TIERS = ("govt_aligned", "mainstream", "watchdog")

# Pre-unification keys still present in coverage_snapshots rows written
# before the tier names were unified.
LEGACY_TIER_KEYS = {
    "pro_establishment": "govt_aligned",
    "institutional": "mainstream",
    "adversarial": "watchdog",
}


def normalize_tier_distribution(dist: dict) -> dict | None:
    """
    Returns a stored tier distribution keyed by the canonical card tiers,
    with every card tier present. A tier absent from a stored distribution
    is zero: the scorer counts every story and only writes tiers it saw.
    blog / unscored are dropped. Returns None (unusable) when the value is
    not a dict or carries an unrecognised key.
    """
    if not isinstance(dist, dict):
        return None
    out = {t: 0 for t in CARD_TIERS}
    for key, count in dist.items():
        tier = LEGACY_TIER_KEYS.get(key, key)
        if tier in CARD_TIERS:
            out[tier] += count
        elif tier in ("blog", "unscored"):
            continue
        else:
            logger.error(f"Unrecognised tier key in distribution: {key!r}")
            return None
    return out


# Behavioural s2 bands. Below REPUBLISHER_S2_MAX an outlet counts toward
# churnalism; at or above ORIGINAL_S2_MIN it counts as original reporting
# (the same line the sourcing rail uses). Between the two is undetermined.
REPUBLISHER_S2_MAX = 40
ORIGINAL_S2_MIN = 50


def is_republisher(s2_score) -> bool | None:
    """True = republisher, False = original reporter, None = unknown."""
    if s2_score is None:
        return None
    if s2_score < REPUBLISHER_S2_MAX:
        return True
    if s2_score >= ORIGINAL_S2_MIN:
        return False
    return None


def count_outlet_tiers(outlets) -> dict:
    """
    Distinct-outlet tier counts. `outlets` is an iterable of outlet records
    (each with "id" or "slug", "government_alignment", "is_blog"); an outlet
    appearing more than once — one per article — is counted once.

    Returns every card tier plus "blog" and "unscored", always all present,
    so a zero is an explicit zero and never an absent key.
    """
    counts = {t: 0 for t in CARD_TIERS}
    counts["blog"] = 0
    counts["unscored"] = 0
    seen = set()
    for out in outlets:
        key = out.get("id") or out.get("slug")
        if not key:
            logger.error(f"Outlet record without id or slug excluded from tier counts: {out!r}")
            continue
        if key in seen:
            continue
        seen.add(key)
        counts[get_outlet_tier(out.get("government_alignment"), out.get("is_blog"))] += 1
    return counts


def card_distribution(tier_counts: dict) -> dict:
    """The three card tiers from count_outlet_tiers, all keys present."""
    return {t: tier_counts[t] for t in CARD_TIERS}

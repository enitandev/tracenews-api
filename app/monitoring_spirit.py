TIER_GOVT = "pro_establishment"
TIER_MAINSTREAM = "institutional"  
TIER_WATCHDOG = "adversarial"

from app.monitoring_spirit_strings import VERDICT_LINE

ACCOUNTABILITY_CATEGORIES = [
    "Politics", "Security", "Economy",
    "Judiciary", "Health", "Education"
]

def is_significant(
    category: str,
    has_entity_tag: bool,
    has_money_figure: bool
) -> bool:
    """
    Fires the verdict toward alarm 
    only on accountability-relevant 
    stories. Category alone is not 
    enough — entity tags or money 
    figures catch accountability 
    stories outside the obvious 
    categories (e.g. a health 
    ministry procurement story 
    tagged with a politician).
    """
    if category in ACCOUNTABILITY_CATEGORIES:
        return True
    if has_entity_tag:
        return True
    if has_money_figure:
        return True
    return False

def has_persistence(
    snapshot_reads: list,
    tier_a: str,
    tier_b: str,
    loud_threshold: float = 0.6,
    silent_threshold: float = 0.1
) -> bool:
    """
    Requires >=2 consecutive snapshot 
    reads showing the SAME tier 
    imbalance (tier_a loud, tier_b 
    silent). A single snapshot could 
    be a breaking-story artifact — 
    coverage hasn't caught up yet, 
    not suppression.
    
    snapshot_reads: list of dicts,
    most recent first:
    [{
        "tier_distribution": {...},
        "total": int,
        "snapshot_at": str
    }, ...]
    """
    if len(snapshot_reads) < 2:
        return False
    
    consecutive_matches = 0
    for read in snapshot_reads[:3]:
        dist = read.get(
            "tier_distribution", {}
        )
        total = read.get("total", 0)
        if total == 0:
            continue
        
        a_count = dist.get(tier_a, 0)
        b_count = dist.get(tier_b, 0)
        a_pct = a_count / total
        b_pct = b_count / total
        
        if (a_pct >= loud_threshold and 
            b_pct <= silent_threshold):
            consecutive_matches += 1
        else:
            break
    
    return consecutive_matches >= 2

def has_sourcing(
    sourcing_info: dict
) -> bool:
    """
    The planted-leak guard. If the 
    "loud" tier's coverage all 
    traces to a single outlet, this 
    fails — caps the verdict at 
    MIXED instead of DARK, because 
    one outlet making noise is not 
    the same as multi-source 
    accountability coverage.
    
    sourcing_info: {
        "distinct_outlets_in_loud_tier": int,
        "has_original_reporting_outlet": bool
        # True if at least one 
        # covering outlet has 
        # s2_score >= 50 (doing 
        # original work, not just 
        # aggregating)
    }
    """
    distinct = sourcing_info.get(
        "distinct_outlets_in_loud_tier", 0
    )
    has_original = sourcing_info.get(
        "has_original_reporting_outlet", 
        False
    )
    
    if distinct < 3:
        return False
    if not has_original:
        return False
    return True

def silence_evidence(
    tier_a_label: str,
    tier_b_label: str,
    tier_b_count: int,
    tier_b_total: int
) -> dict:
    """
    NEVER use: hiding, suppressing,
    burying, killing the story.
    ALWAYS use: silent, has not 
    reported, went quiet.
    """
    return {
        "type": "silence",
        "label": "The silence",
        "detail": (
            f"{tier_b_total - tier_b_count} "
            f"of {tier_b_total} "
            f"{tier_b_label} outlets "
            f"have not reported this."
        )
    }

def churnalism_evidence(
    republished_count: int,
    total_scored: int,
    is_govt_wire: bool = False
) -> dict:
    """
    NEVER use: propaganda, mouthpiece,
    the government wrote this.
    ALWAYS use: ran the same report,
    originating from [wire service].
    """
    if is_govt_wire:
        detail = (
            f"{republished_count} of "
            f"{total_scored} outlets "
            f"ran the same report, "
            f"originating from a "
            f"government-owned wire "
            f"service."
        )
    else:
        detail = (
            f"{republished_count} of "
            f"{total_scored} outlets "
            f"ran the same report."
        )
    return {
        "type": "churnalism",
        "label": "Copy and paste",
        "detail": detail
    }

def regional_evidence(
    region: str,
    absent_regions: list
) -> dict:
    """
    Buildable now from geopolitical_lean.
    Folded into the verdict, not a 
    separate signal.
    """
    absent_str = ", ".join(
        absent_regions
    )
    return {
        "type": "regional",
        "label": "Regional gap",
        "detail": (
            f"Coverage concentrated in "
            f"{region}. No coverage "
            f"yet from {absent_str}."
        )
    }

def resolve_verdict(
    tier_distribution: dict,
    total_outlets: int,
    churnalism_ratio: float = None,
    category: str = None,
    has_entity_tag: bool = False,
    has_money_figure: bool = False,
    snapshot_reads: list = None,
    sourcing_info: dict = None,
    geopolitical_data: dict = None
) -> dict:
    """
    Direction-agnostic resolution.
    Takes all firing signals + rails,
    returns ONE of {clear, mixed, 
    dark} + evidence rows.
    
    CRITICAL: this function must 
    produce the SAME verdict structure 
    whether TIER_WATCHDOG or TIER_GOVT 
    is the "loud" tier. No hardcoded 
    asymmetry anywhere in this function.
    """
    snapshot_reads = snapshot_reads or []
    sourcing_info = sourcing_info or {}
    evidence = []
    
    if total_outlets == 0:
        return {
            "verdict": "clear",
            "verdict_line": "Not enough coverage yet to assess.",
            "evidence": [],
            "rails": {
                "significance": False,
                "persistence": False,
                "sourcing": False
            }
        }
    
    govt = tier_distribution.get(
        TIER_GOVT, 0
    )
    main = tier_distribution.get(
        TIER_MAINSTREAM, 0
    )
    watch = tier_distribution.get(
        TIER_WATCHDOG, 0
    )
    
    govt_pct = govt / total_outlets
    watch_pct = watch / total_outlets
    
    # Determine which tier is loud,
    # which is silent — DIRECTION
    # AGNOSTIC. Check both directions
    # symmetrically.
    silence_direction = None
    tier_a = None  # loud
    tier_b = None  # silent
    tier_a_label = None
    tier_b_label = None
    
    if (watch_pct >= 0.6 and 
        govt_pct <= 0.1):
        silence_direction = (
            "watchdog_loud_govt_silent"
        )
        tier_a = TIER_WATCHDOG
        tier_b = TIER_GOVT
        tier_a_label = "watchdog"
        tier_b_label = "government-aligned"
    elif (govt_pct >= 0.7 and 
          watch_pct <= 0.1):
        silence_direction = (
            "govt_loud_watchdog_silent"
        )
        tier_a = TIER_GOVT
        tier_b = TIER_WATCHDOG
        tier_a_label = "government-aligned"
        tier_b_label = "watchdog"
    
    significant = is_significant(
        category, has_entity_tag, 
        has_money_figure
    )
    
    persistent = False
    sourced = False
    
    if silence_direction:
        persistent = has_persistence(
            snapshot_reads, tier_a, tier_b
        )
        sourced = has_sourcing(
            sourcing_info
        )
    
    rails = {
        "significance": significant,
        "persistence": persistent,
        "sourcing": sourced
    }
    
    # DARK: silence detected + 
    # all three rails satisfied
    if (silence_direction and 
        significant and 
        persistent and 
        sourced):
        tier_b_count = (
            govt if tier_b == TIER_GOVT 
            else watch
        )
        evidence.append(
            silence_evidence(
                tier_a_label,
                tier_b_label,
                tier_b_count,
                total_outlets
            )
        )
        if (churnalism_ratio and 
            churnalism_ratio >= 0.6):
            evidence.append(
                churnalism_evidence(
                    int(
                        churnalism_ratio * 
                        total_outlets
                    ),
                    total_outlets
                )
            )
        return {
            "verdict": "dark",
            "verdict_line": VERDICT_LINE["dark"],
            "evidence": evidence,
            "rails": rails
        }
    
    # MIXED: churnalism endemic, 
    # OR silence detected but rails 
    # not fully satisfied (capped 
    # at mixed, not dark)
    if (churnalism_ratio and 
        churnalism_ratio >= 0.5 and
        is_significant(
            category, 
            has_entity_tag, 
            has_money_figure
        )):
        evidence.append(
            churnalism_evidence(
                int(
                    churnalism_ratio * 
                    total_outlets
                ),
                total_outlets
            )
        )
        return {
            "verdict": "mixed",
            "verdict_line": VERDICT_LINE["mixed"],
            "evidence": evidence,
            "rails": rails
        }
    
    if silence_direction and significant:
        # Silence pattern exists but 
        # persistence or sourcing 
        # rail not satisfied — 
        # capped at mixed, not dark.
        # This is the planted-leak 
        # guard and the breaking-news 
        # guard working together.
        tier_b_count = (
            govt if tier_b == TIER_GOVT 
            else watch
        )
        evidence.append(
            silence_evidence(
                tier_a_label,
                tier_b_label,
                tier_b_count,
                total_outlets
            )
        )
        return {
            "verdict": "mixed",
            "verdict_line": VERDICT_LINE["mixed"],
            "evidence": evidence,
            "rails": rails
        }
    
    # CLEAR: covered widely, no 
    # significant imbalance, low 
    # churnalism
    if total_outlets >= 5:
        evidence.append({
            "type": "broad_coverage",
            "label": "Widely covered",
            "detail": (
                f"Reported by "
                f"{total_outlets} "
                f"outlets across "
                f"editorial tiers."
            )
        })
    
    return {
        "verdict": "clear",
        "verdict_line": VERDICT_LINE["clear"],
        "evidence": evidence,
        "rails": rails
    }

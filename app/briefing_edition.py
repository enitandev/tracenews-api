"""
Builds and serves the rebuilt Daily Briefing (counsel, 3 Oct 2026, section B).
Rules and strings live in app/briefingStrings.py.

An edition is one row per selected story in briefing_editions. Rows are built
whether or not the Briefing is public, so staff can review and approve them;
publication is decided when an edition is read, from the summary's current
state and the editor approval.
"""
import logging
from datetime import datetime, timedelta, timezone

from app.briefingStrings import (
    FORBIDDEN_TOKENS, GATE_NEEDS_EDITOR_APPROVAL, GATE_PUBLISHES_WITHOUT_APPROVAL,
    MAX_STORIES, MIN_DISTINCT_OUTLETS, WINDOW_HOURS,
)
from app.db import supabase
from app.summarizer import is_generation_failure
from app.tier_utils import card_distribution, count_outlet_tiers, get_distinct_scored_count

logger = logging.getLogger(__name__)
LAGOS = timezone(timedelta(hours=1))


def lagos_today():
    return datetime.now(LAGOS).date()


def select_clusters(clusters):
    """Widest coverage first: distinct outlets, then most recent. Never by tier imbalance."""
    eligible = []
    for c in clusters:
        distinct = get_distinct_scored_count(c.get("coverage_stats"))
        if distinct is None or distinct < MIN_DISTINCT_OUTLETS:
            continue
        if not any(s.get("image_url") for s in (c.get("stories") or [])):
            continue
        eligible.append((distinct, c.get("first_seen_at") or "", c))
    eligible.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [c for _, _, c in eligible[:MAX_STORIES]]


def has_forbidden_token(texts):
    joined = " ".join(t for t in texts if isinstance(t, str)).lower()
    return next((tok for tok in FORBIDDEN_TOKENS if tok in joined), None)


def summary_usable(summary):
    """The cleared summary may appear in a Briefing at all (before approval)."""
    if not summary or summary.get("superseded") or is_generation_failure(summary):
        return False
    if summary.get("flags"):
        return False
    gate = summary.get("gate")
    return gate in GATE_PUBLISHES_WITHOUT_APPROVAL or gate in GATE_NEEDS_EDITOR_APPROVAL


def is_publishable(row, summary):
    """Whether a built item may be shown publicly right now."""
    if not summary_usable(summary) or has_forbidden_token(summary.get("bullets") or []):
        return False
    gate = summary.get("gate")
    if gate in GATE_PUBLISHES_WITHOUT_APPROVAL:
        return bool(summary.get("published"))
    return gate in GATE_NEEDS_EDITOR_APPROVAL and bool(row.get("approved_by"))


def latest_summary(cluster_id):
    res = supabase.table("cluster_summaries").select("*").eq("cluster_id", cluster_id) \
        .order("generated_at", desc=True).limit(1).execute()
    return (res.data or [None])[0]


def coverage_counts(cluster_id):
    """Distinct outlets per tier for the story, counted now."""
    from app.coverage import get_outlets_cache
    outlets_map, _ = get_outlets_cache()
    stories = supabase.table("stories").select("outlet_id").eq("cluster_id", cluster_id).execute().data or []
    outlets = [outlets_map[s["outlet_id"]] for s in stories if s.get("outlet_id") in outlets_map]
    return card_distribution(count_outlet_tiers(outlets))


CANDIDATE_POOL = 500
IMAGE_LOOKUP_CHUNK = 100


def candidate_clusters(start, end):
    """Stories first seen in [start, end) with enough rows to qualify, each with
    the image URLs of its articles under "stories" (the shape select_clusters
    reads). Two plain queries: embedding stories in the cluster query times out
    on wider date ranges."""
    clusters = supabase.table("clusters").select(
        "id, slug, representative_title, category, first_seen_at, coverage_stats"
    ).gte("first_seen_at", start.isoformat()).lt("first_seen_at", end.isoformat()) \
        .gte("outlet_count", MIN_DISTINCT_OUTLETS) \
        .order("first_seen_at", desc=True).limit(CANDIDATE_POOL).execute().data or []
    images = {}
    ids = [c["id"] for c in clusters]
    for i in range(0, len(ids), IMAGE_LOOKUP_CHUNK):
        rows = supabase.table("stories").select("cluster_id, image_url") \
            .in_("cluster_id", ids[i:i + IMAGE_LOOKUP_CHUNK]).not_.is_("image_url", "null").execute().data or []
        for r in rows:
            images.setdefault(r["cluster_id"], []).append({"image_url": r["image_url"]})
    for c in clusters:
        c["stories"] = images.get(c["id"], [])
    return clusters


def build_edition(day=None):
    """Select today's stories and record them. Idempotent per day."""
    day = day or lagos_today()
    if supabase.table("briefing_editions").select("id").eq("date", day.isoformat()).limit(1).execute().data:
        return {"status": "already_built", "date": day.isoformat()}

    end = datetime.now(timezone.utc)
    clusters = candidate_clusters(end - timedelta(hours=WINDOW_HOURS), end)

    rows, skipped = [], {}
    for cluster in select_clusters(clusters):
        summary = latest_summary(cluster["id"])
        if not summary_usable(summary):
            skipped[cluster["slug"]] = "no usable summary (missing, flagged, suppressed or failed)"
            continue
        token = has_forbidden_token(summary.get("bullets") or [])
        if token:
            skipped[cluster["slug"]] = f"forbidden token: {token}"
            continue
        rows.append({
            "date": day.isoformat(),
            "position": len(rows) + 1,
            "cluster_id": cluster["id"],
            "summary_id": str(summary["id"]),
            "gate": summary.get("gate"),
            "coverage_counts": coverage_counts(cluster["id"]),
            "counts_as_of": datetime.now(timezone.utc).isoformat(),
        })
    if rows:
        supabase.table("briefing_editions").insert(rows).execute()
    for slug, why in skipped.items():
        logger.info(f"[briefing] left out {slug}: {why}")
    return {"status": "built", "date": day.isoformat(), "items": len(rows), "left_out": len(skipped)}


def edition_items(day, publishable_only=True):
    """Items for a day, with their summary and story. Staff see everything."""
    rows = supabase.table("briefing_editions").select("*").eq("date", day.isoformat()).order("position").execute().data or []
    items = []
    for row in rows:
        # The current summary is used: if a correction replaced the one the
        # edition was built with, the replacement is shown under the same rules.
        summary = latest_summary(row["cluster_id"])
        publishable = is_publishable(row, summary)
        if publishable_only and not publishable:
            continue
        cluster = (supabase.table("clusters").select("slug, representative_title, category, stories(image_url)")
                   .eq("id", row["cluster_id"]).limit(1).execute().data or [{}])[0]
        items.append({
            "id": row["id"],
            "position": row["position"],
            "slug": cluster.get("slug"),
            "title": cluster.get("representative_title"),
            "category": cluster.get("category"),
            "image_url": next((s.get("image_url") for s in (cluster.get("stories") or []) if s.get("image_url")), None),
            "bullets": (summary or {}).get("bullets") or [],
            "coverage_counts": row.get("coverage_counts"),
            "counts_as_of": row.get("counts_as_of"),
            **({} if publishable_only else {
                "gate": (summary or {}).get("gate"),
                "flags": (summary or {}).get("flags"),
                "publishable": publishable,
                "approved_by": row.get("approved_by"),
                "approved_at": row.get("approved_at"),
            }),
        })
    return items

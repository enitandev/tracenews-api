"""
Builds and serves the rebuilt Daily Briefing (counsel, 3 Oct 2026, section B,
amended by counsel's review of the 3 Oct samples). Rules and strings live in
app/briefingStrings.py.

An edition is one row per selected story in briefing_editions. Rows are built
whether or not the Briefing is public, so staff can review them. Each item is
routed (assess_item) when it is read, from its current text: the cleaned
source headline and the cleared summary, or an editor's rewrite of either.
"""
import logging
import re
import time as _time
from datetime import datetime, time, timedelta, timezone

from app.briefingStrings import (
    COMMENTARY_PHRASES, COMMENTARY_STATEMENT_PATTERN, EDITION_CUTOFF_HOUR_LAGOS, FORBIDDEN_TOKENS,
    HEADLINE_BODY_TERMS, HEADLINE_PREFIXES, HEADLINE_TRAILING_PHRASES, LANE_AUTO,
    LANE_LEFT_OUT, LANE_REVIEW, LANES_NEEDING_EDITOR, MAX_STORIES,
    MIN_DISTINCT_OUTLETS, PARTY_NAMES, POLITICAL_OFFICES, POLITICAL_REVIEW_LANE,
    REPORTED_PHRASES, SURNAME_CHECK_IGNORE, SURNAME_CHECK_ORG_WORDS, WINDOW_HOURS,
)
from app.db import supabase
from app.storySummaryStrings import ADVERSE_CONTEXT_TERMS, GATE_SUPPRESS_CLAIM
from app.summarizer import cluster_articles_text, evaluate_summary, is_generation_failure
from app.tier_utils import card_distribution, count_outlet_tiers, get_distinct_scored_count

logger = logging.getLogger(__name__)
LAGOS = timezone(timedelta(hours=1))
PROTECTED_STATUSES = ("pending_review", "excluded")   # held, private


def lagos_today():
    return datetime.now(LAGOS).date()


def edition_window(day):
    end = datetime.combine(day, time(EDITION_CUTOFF_HOUR_LAGOS, 0), LAGOS)
    return end - timedelta(hours=WINDOW_HOURS), end


# ═══ SELECTION ═══════════════════════════════════════════════════════════════

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


# ═══ TEXT CHECKS ═════════════════════════════════════════════════════════════

def _has(term, text, case_sensitive=False):
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.search(r"(?<![\w-])" + re.escape(term) + r"(?![\w-])", text, flags) is not None


def has_forbidden_token(texts):
    joined = " ".join(t for t in texts if isinstance(t, str))
    return next((tok for tok in FORBIDDEN_TOKENS if _has(tok, joined)), None)


_SEP = r"\s*[:\-–—|!]+\s*"


def clean_headline(title):
    """Source headline without prefix words or trailing virality phrases (item 1a)."""
    t = (title or "").strip()
    changed = True
    while changed:
        changed = False
        for p in HEADLINE_PREFIXES:
            m = re.match(r"^\W*" + re.escape(p) + _SEP, t, re.IGNORECASE)
            if m:
                t, changed = t[m.end():].strip(), True
        for p in HEADLINE_TRAILING_PHRASES:
            m = re.search(r"(?:\s*[:\-–—|!,]+\s*|\s+)" + re.escape(p) + r"\W*$", t, re.IGNORECASE)
            if m:
                t, changed = t[:m.start()].strip(), True
    return t


def headline_body_conflict(title, bullets):
    """A headline allegation/escalation term the body lacks (item 1c)."""
    body = " ".join(b for b in bullets if isinstance(b, str))
    for group in HEADLINE_BODY_TERMS:
        hit = next((t for t in group if _has(t, title)), None)
        if hit and not any(_has(t, body) for t in group):
            return hit
    return None


_registry = {"at": 0, "rows": []}
REGISTRY_TTL_SECONDS = 600


def load_registry():
    """Politician registry names and status, cached for ten minutes."""
    if _time.time() - _registry["at"] < REGISTRY_TTL_SECONDS and _registry["rows"]:
        return _registry["rows"]
    rows, start = [], 0
    while True:
        page = supabase.table("politicians").select("full_name, common_name, publication_status") \
            .range(start, start + 999).execute().data or []
        rows += page
        if len(page) < 1000:
            break
        start += 1000
    _registry.update(at=_time.time(), rows=rows)
    return rows


def registry_matches(text, registry):
    out = []
    for r in registry:
        names = {n.strip() for n in (r.get("full_name"), r.get("common_name")) if n and len(n.strip()) > 3}
        if any(_has(n, text) for n in names):
            out.append(r)
    return out


def parties_in(text):
    return [p for p in PARTY_NAMES if _has(p, text, case_sensitive=p.isupper())]


def offices_in(text):
    return [o for o in POLITICAL_OFFICES if _has(o, text)]


# Capitalised runs; an initial such as "A." stays inside the run ("Peter A. Okebukola").
_CAP_RUN = re.compile(r"[A-Z][\w'’\-]*\.?(?:\s+[A-Z][\w'’\-]*\.?)*")
_IGNORE = set(SURNAME_CHECK_IGNORE)
_ORG = set(SURNAME_CHECK_ORG_WORDS)


def _name_runs(text):
    """Capitalised runs of words, each as (position, [name words]) with title
    words dropped and possessives stripped."""
    runs = []
    for m in _CAP_RUN.finditer(text):
        words = [re.sub(r"(['’]s|['’])$", "", w.rstrip(".")) for w in m.group(0).split()]
        words = [w for w in words if _is_name_word(w)]
        if words:
            runs.append((m.start(), words))
    return runs


def _is_name_word(w):
    """A word that can be part of a person's name: not a title or common
    capitalised word, not an acronym (SSCE, ADC), not an initial, no digits,
    and not a hyphenated common noun ("T-shirts")."""
    if not w or w in _IGNORE or len(w) < 2:
        return False
    if w.isupper() or any(ch.isdigit() for ch in w):
        return False
    if "-" in w and any(part[:1].islower() for part in w.split("-")[1:]):
        return False
    return True


def _registry_words(registry):
    """First and last names from the registry (not middle words), so a
    one-name reference to a registry person is recognised."""
    words = set()
    for r in registry:
        for n in (r.get("full_name"), r.get("common_name")):
            parts = [w for w in (n or "").split() if len(w) > 2 and _is_name_word(w)]
            if parts:
                words |= {parts[0], parts[-1]}
    return words


def surname_issues(title, bullets, registry):
    """Names of people used alone with no earlier full name containing them
    (item 3i). Body in order; a headline name must appear in full in the body."""
    body = " ".join(b for b in bullets if isinstance(b, str))
    runs = _name_runs(body)
    known = _registry_words(registry)
    known |= {ws[-1] for _, ws in runs if 2 <= len(ws) <= 4 and ws[-1] not in _ORG}
    introduced, issues = set(), []
    for _, words in runs:
        if len(words) >= 2:
            introduced |= set(words)
        elif words[0] in known and words[0] not in introduced and words[0] not in issues:
            issues.append(words[0])
    for _, words in _name_runs(title or ""):
        if len(words) == 1 and words[0] in known and words[0] not in introduced and words[0] not in issues:
            issues.append(words[0])
    return issues


def names_a_person_or_party(text, registry):
    if registry_matches(text, registry) or parties_in(text):
        return True
    return any(len(ws) >= 2 and ws[-1] not in _ORG for _, ws in _name_runs(text))


def commentary_in(bullets):
    text = " ".join(b for b in bullets if isinstance(b, str))
    found = [p for p in COMMENTARY_PHRASES if _has(p, text)]
    found += [m.group(0) for m in re.finditer(COMMENTARY_STATEMENT_PATTERN, text, re.IGNORECASE)]
    return found


def assess_item(raw_title, bullets, articles_text, registry):
    """Route one item from its current text. Returns the cleaned title, the
    lane (auto / review / senior_review / left_out) and every reason."""
    bullets = bullets if isinstance(bullets, list) else [bullets]
    title = clean_headline(raw_title)
    text_bullets = [b for b in bullets if isinstance(b, str)]
    full = " ".join([title] + text_bullets)

    def left_out(reason):
        return {"title": title, "lane": LANE_LEFT_OUT, "reasons": [reason]}

    if not title:
        return left_out("headline empty after cleaning")
    token = has_forbidden_token([title] + text_bullets)
    if token:
        return left_out(f"forbidden word: {token}")
    conflict = headline_body_conflict(title, text_bullets)
    if conflict:
        return left_out(f"headline term not in body: {conflict}")
    ev = evaluate_summary(bullets, articles_text, title=title)
    if ev["flags"]:
        return left_out("cleared check flagged: " + "; ".join(ev["flags"]))
    if ev["gate"] == GATE_SUPPRESS_CLAIM:
        return left_out("cleared gate: suppress (adverse claim with no public-record anchor)")

    lane, reasons = ev["gate"], []
    if lane != LANE_AUTO:
        reasons.append(f"cleared gate: {lane}")
    matches = registry_matches(full, registry)
    if POLITICAL_REVIEW_LANE:
        political = [m.get("common_name") or m.get("full_name") for m in matches] + parties_in(full) + offices_in(full)
        if political:
            reasons.append("political review lane: " + ", ".join(dict.fromkeys(political)))
    surnames = surname_issues(title, text_bullets, registry)
    if surnames:
        reasons.append("named by one name only: " + ", ".join(surnames))
    reported = [p for p in REPORTED_PHRASES if _has(p, full)]
    if reported and names_a_person_or_party(full, registry):
        reasons.append("reported speech without origin: " + ", ".join(reported))
    commentary = commentary_in(text_bullets)
    if commentary:
        reasons.append("commentary: " + ", ".join(commentary))
    if any(_has(t, full) for t in ADVERSE_CONTEXT_TERMS):
        protected = [m.get("common_name") or m.get("full_name") for m in matches
                     if m.get("publication_status") in PROTECTED_STATUSES]
        if protected:
            reasons.append("adverse item naming a held or private person: " + ", ".join(protected))
    if lane == LANE_AUTO and reasons:
        lane = LANE_REVIEW
    return {"title": title, "lane": lane, "reasons": reasons}


# ═══ SUMMARIES AND COUNTS ════════════════════════════════════════════════════

def summary_usable(summary):
    """A cleared summary exists that may be considered at all."""
    if not summary or summary.get("superseded") or is_generation_failure(summary):
        return False
    if summary.get("flags"):
        return False
    return summary.get("gate") in (LANE_AUTO,) + LANES_NEEDING_EDITOR


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


def named_people(cluster_id):
    """Registry people tagged in the source articles. Reviewer-only (item 7)."""
    stories = supabase.table("stories").select("id").eq("cluster_id", cluster_id).execute().data or []
    ids = [s["id"] for s in stories][:100]
    if not ids:
        return []
    ents = supabase.table("story_entities").select("politician_id").in_("story_id", ids) \
        .eq("entity_type", "politician").execute().data or []
    pids = sorted({e["politician_id"] for e in ents if e.get("politician_id")})
    if not pids:
        return []
    rows = supabase.table("politicians").select("common_name").in_("id", pids).execute().data or []
    return sorted(r["common_name"] for r in rows if r.get("common_name"))


def source_articles(cluster_id):
    """The story's source articles, for the editor to check and rewrite against. Reviewer-only."""
    return supabase.table("stories").select("title, summary, url, published_at") \
        .eq("cluster_id", cluster_id).order("published_at").limit(40).execute().data or []


# ═══ EDITIONS ════════════════════════════════════════════════════════════════

def build_edition(day=None, sample=False):
    """Select a day's stories and record them. Idempotent per day.
    sample=True builds a staff-only sample edition for counsel."""
    day = day or lagos_today()
    if supabase.table("briefing_editions").select("id").eq("date", day.isoformat()).limit(1).execute().data:
        # One edition per date, real or sample (unique date + story).
        return {"status": "already_built", "date": day.isoformat()}

    start, end = edition_window(day)
    rows, skipped = [], {}
    for cluster in select_clusters(candidate_clusters(start, end)):
        summary = latest_summary(cluster["id"])
        if not summary_usable(summary):
            skipped[cluster["slug"]] = "no usable summary (missing, flagged, suppressed or failed)"
            continue
        rows.append({
            "date": day.isoformat(),
            "position": len(rows) + 1,
            "cluster_id": cluster["id"],
            "summary_id": str(summary["id"]),
            "gate": summary.get("gate"),
            "coverage_counts": coverage_counts(cluster["id"]),
            "counts_as_of": datetime.now(timezone.utc).isoformat(),
            "is_sample": sample,
        })
    if rows:
        supabase.table("briefing_editions").insert(rows).execute()
    for slug, why in skipped.items():
        logger.info(f"[briefing] left out {slug}: {why}")
    return {"status": "built", "date": day.isoformat(), "items": len(rows), "left_out": len(skipped)}


def current_text(row, cluster, summary):
    edited = row.get("edited_bullets")
    return (row.get("edited_title") or cluster.get("representative_title") or "",
            edited if edited else (summary or {}).get("bullets") or [])


def approval_valid(row, summary):
    """An approval covers the exact text approved (summary id + edit time)."""
    if not row.get("approved_by"):
        return False
    if str(row.get("approved_summary_id") or "") != str((summary or {}).get("id") or ""):
        return False
    return (row.get("approved_edit_at") or None) == (row.get("edited_at") or None)


def edition_items(day, publishable_only=True):
    """Items for a day. Readers get publishable items of the real edition only;
    staff get every item, with routing, reasons and reviewer-only fields."""
    q = supabase.table("briefing_editions").select("*").eq("date", day.isoformat())
    if publishable_only:
        q = q.eq("is_sample", False)
    rows = q.order("position").execute().data or []
    registry = load_registry() if rows else []
    items = []
    for row in rows:
        # The current summary is used: if a correction replaced the one the
        # edition was built with, the replacement is routed afresh.
        summary = latest_summary(row["cluster_id"])
        cluster = (supabase.table("clusters").select("slug, representative_title, category")
                   .eq("id", row["cluster_id"]).limit(1).execute().data or [{}])[0]
        raw_title, bullets = current_text(row, cluster, summary)
        if row.get("left_out_by"):
            a = {"title": raw_title, "lane": LANE_LEFT_OUT,
                 "reasons": [f"left out by {row['left_out_by']}: {row.get('left_out_reason') or ''}".strip()]}
        elif not summary_usable(summary):
            a = {"title": raw_title, "lane": LANE_LEFT_OUT, "reasons": ["no usable cleared summary"]}
        else:
            a = assess_item(raw_title, bullets, cluster_articles_text(row["cluster_id"]), registry)
        approved = approval_valid(row, summary)
        publishable = a["lane"] == LANE_AUTO or (a["lane"] in LANES_NEEDING_EDITOR and approved)
        if publishable_only and not publishable:
            continue
        image = (supabase.table("stories").select("image_url").eq("cluster_id", row["cluster_id"])
                 .not_.is_("image_url", "null").limit(1).execute().data or [{}])[0].get("image_url")
        item = {
            "id": row["id"],
            "position": row["position"],
            "slug": cluster.get("slug"),
            "title": a["title"],
            "category": cluster.get("category"),
            "image_url": image,
            "bullets": bullets,
            "coverage_counts": row.get("coverage_counts"),
            "counts_as_of": row.get("counts_as_of"),
        }
        if not publishable_only:
            item.update({
                "lane": a["lane"],
                "reasons": a["reasons"],
                "publishable": publishable,
                "is_sample": row.get("is_sample"),
                "source_headline": cluster.get("representative_title"),
                "summary_bullets": (summary or {}).get("bullets") or [],
                "summary_gate": (summary or {}).get("gate"),
                "edited_by": row.get("edited_by"),
                "edited_at": row.get("edited_at"),
                "approved_by": row.get("approved_by") if approved else None,
                "approved_at": row.get("approved_at") if approved else None,
                "stale_approval_by": row.get("approved_by") if row.get("approved_by") and not approved else None,
                "left_out_by": row.get("left_out_by"),
                "named_in_sources": named_people(row["cluster_id"]),
                "sources": source_articles(row["cluster_id"]),
            })
        items.append(item)
    return items


def item_lane(row):
    """Routing for one stored row (used by the approve endpoint)."""
    summary = latest_summary(row["cluster_id"])
    if row.get("left_out_by") or not summary_usable(summary):
        return LANE_LEFT_OUT, summary
    cluster = (supabase.table("clusters").select("representative_title")
               .eq("id", row["cluster_id"]).limit(1).execute().data or [{}])[0]
    raw_title, bullets = current_text(row, cluster, summary)
    return assess_item(raw_title, bullets, cluster_articles_text(row["cluster_id"]), load_registry())["lane"], summary


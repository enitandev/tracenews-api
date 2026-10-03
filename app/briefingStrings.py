"""
CONSTANTS FOR THE REBUILT DAILY BRIEFING — for counsel's clearance.

Counsel's consolidated instruction of 3 October 2026, section B. The Briefing
is off publicly (BRIEFING_PUBLIC in app/withdrawals.py and
src/constants/features.js) until counsel clears this file and the sample
editions.

WHAT A BRIEFING ITEM IS
  - The story's cleared event summary: the same function, prompt, strings,
    gate and evaluation as app/storySummaryStrings.py (generate_cluster_summary
    and evaluate_summary). There is no separate Briefing prompt.
  - The model sees article headlines and feed summaries only, labelled
    "Source 1", "Source 2", ... It receives no outlet name, identifier or tier.
  - No model-written grouping by tier, no "sides", no "Common ground", no
    "Why it matters", no follow-up questions.
  - Beside the summary: how many distinct outlets in each tier reported the
    story, as counts, with the time they were counted. No percentages.
  - Every item carries ATTRIBUTION_LABEL, the correction link and the
    methodology link. Search and social previews use the same text.

WHICH STORIES
  - Stories first seen in the last WINDOW_HOURS, reported by at least
    MIN_DISTINCT_OUTLETS distinct outlets, with an image; widest coverage
    first (most distinct outlets), at most MAX_STORIES. Never selected or
    ordered by tier imbalance.

GATE (from the cleared summary gate)
  - auto, nothing flagged      -> published
  - review / senior_review     -> published only after a named editor approves
  - suppress, or anything flagged, or a forbidden token -> left out

Do NOT edit any string or rule here without counsel's sign-off.
"""
from app.storySummaryStrings import UI as SUMMARY_UI

WINDOW_HOURS = 24
MIN_DISTINCT_OUTLETS = 5
MAX_STORIES = 9

GATE_PUBLISHES_WITHOUT_APPROVAL = ("auto",)
GATE_NEEDS_EDITOR_APPROVAL = ("review", "senior_review")
# Anything else (suppress, unknown) never publishes.

# Words that must never appear in a Briefing item or its labels. A summary
# containing one is left out of the edition, not edited.
FORBIDDEN_TOKENS = (
    "bias", "biased", "dramatic", "side a", "side b", "sides",
    "common ground", "why it matters", "%", "percent",
)

UI = {
    "title": "Daily Briefing",
    "attribution_label": SUMMARY_UI["attribution_label"],   # "AI-generated summary of the sources"
    "correction_link": SUMMARY_UI["correction_link"],       # "Report an error in this summary"
    "methodology_link": "How TraceNews classifies outlets",
    "coverage_heading": "Outlets that reported this story",
    "coverage_as_of": "Counted at {time} WAT",
    "tier_labels": {"govt_aligned": "Govt", "mainstream": "Mainstream", "watchdog": "Watchdog"},
    "empty": "Today's briefing is not ready yet.",
}

"""
TraceNews Monitoring Spirit — Frozen Language Constants
GATE B ARTIFACT · COUNSEL-REVIEWED MARKUP (The Bridge Chambers)

STATUS: CONDITIONAL. Named sign-off is WITHHELD on the file as submitted.
It signs when the three blocking changes below are folded in. This file IS
those changes, applied, so it can serve as the buildable target.

REVIEW = {
    "version": "gateB-1.0.0-counsel-markup",
    "signed_off_by": None,   # set to reviewer name + date once the card,
    "signed_off_at": None,   # as assembled, is reviewed (not just this file)
}

WHAT WAS WRONG (all three pass the old token guard clean — that is the point):
  1. VERDICT_LINE (all three) asserted a conclusion, not an observation.
     - dark "You're not getting the full story" = second-person accusation of
       concealment against the silent outlets. Defamatory by innuendo.
     - clear "This looks like the full picture" = overclaim of informational
       completeness the system cannot verify; vouches for the story itself.
     - mixed "Something's a little off" = unanchored insinuation of impropriety.
  2. EVIDENCE_LABELS "The silence" / "Copy and paste" editorialise the rows.
  3. SYNTHESIS_TEMPLATE_FUTURE attaches a suppression narrative to a NAMED
     subject with no baseline. Quarantined below. Do not ship without counsel.

THE RULE (unchanged, now actually enforced above the evidence rows too):
Strings name WHAT WAS OBSERVED. They never assert WHY, and never grade the
story. Coverage breadth is observable. "The full picture" is not.
"""

# ============================
# VERDICT LINES  [REWRITTEN]
# Observation, not grade. Speaks to COVERAGE, never to the story's completeness
# or to anyone's motive. Kept in the same register as the sub-lines.
# ============================

VERDICT_LINE = {
    "clear": (
        "Covered widely, across outlet types"
    ),
    "mixed": (
        "Widely carried — mostly the same report"
    ),
    "dark": (
        "Covered by some outlet types, not yet by others"
    ),
}

# ============================
# VERDICT SUB-LINES  [minor fixes]
# clear: no "full picture" claim — breadth only.
# dark: "stayed quiet" -> "has not reported it" (removes imputed choice).
# ============================

VERDICT_SUBLINE = {
    "clear": (
        "Reported across editorial tiers, "
        "with outlets running their own reports."
    ),
    "mixed": (
        "Most outlets covering this ran the "
        "same report, rather than reporting it "
        "themselves."
    ),
    "dark": (
        "Some outlet types have reported this. "
        "Others have not reported it yet."
    ),
}

# ============================
# EVIDENCE LABELS  [2 of 4 rewritten]
# Row headers must be neutral descriptors, never headlines.
# "The silence" -> "Not yet reported"
# "Copy and paste" -> "Same report"
# ============================

EVIDENCE_LABELS = {
    "silence": "Not yet reported",
    "churnalism": "Same report",
    "regional": "Regional spread",
    "broad_coverage": "Widely covered",
}

# ============================
# EVIDENCE DETAIL TEMPLATES
# The safe core of the file. Confirmed by counsel, with two fixes:
#  - regional: dropped "yet"; added explicit {as_of}.
#  - govt_wire: only where the wire's govt ownership is public record (e.g. NAN),
#    stated as bare fact. Never as a nudge toward coordination.
# ============================

EVIDENCE_TEMPLATES = {
    "silence": (
        "{missing_count} of {total} {tier_label} "
        "outlets have not reported this."
    ),
    "silence_with_window": (
        "{missing_count} of {total} {tier_label} "
        "outlets have not reported this over "
        "{read_count} consecutive checks."
    ),
    "churnalism": (
        "{count} of {total} outlets ran the "
        "same report."
    ),
    "churnalism_govt_wire": (
        # Use ONLY where the wire is government-owned as a matter of public
        # record. State it as fact; draw no inference for the reader.
        "{count} of {total} outlets ran the same "
        "report, originating from a state-owned "
        "wire service ({wire_name})."
    ),
    "regional": (
        "Coverage concentrated in {region}. "
        "No coverage from {absent_regions} "
        "as of {as_of}."
    ),
    "broad_coverage": (
        "Reported by {total} outlets across "
        "editorial tiers."
    ),
}

# ============================
# TAP TARGET  [rewritten]
# "and who isn't" -> neutral, no ongoing-refusal framing.
# ============================

TAP_TARGET_TEXT = (
    "See who has and hasn't reported it"
)

# ============================
# COVERAGE ANATOMY SCREEN  [2 labels adjusted]
# "Stayed silent" -> "Not yet reported"
# "A pattern over time" -> "Coverage over time" ("pattern" implies system/intent)
# ============================

ANATOMY_BLOCK_LABELS = {
    "who_covered": "Who covered it",
    "who_reported_how": "Who reported it — and how",
    "stayed_silent": "Not yet reported",
    "pattern_over_time": "Coverage over time",
}

OUTLET_BEHAVIOUR_LABEL = {
    "original": "own report",
    "republished": "same wire",
}

STAYED_SILENT_TEMPLATE = (
    "{missing_count} of {total} {tier_label} "
    "outlets have not reported this in "
    "{time_window}."
)

ANATOMY_FOOTER = (
    "Every outlet, source & timestamp · exportable."
)

# ============================
# RESERVED SYNTHESIS SLOT  [QUARANTINED]
# The placeholder is fine. The FUTURE template is NOT cleared and must not ship
# in its submitted form. See blocking item 3.
# ============================

SYNTHESIS_SLOT_PLACEHOLDER = (
    "Coverage history for this topic is still "
    "building. Check back as more data "
    "accumulates."
)

# -------------------------------------------------------------------
# DO NOT SHIP. NOT CLEARED BY COUNSEL. Requires separate review before
# the August activation. Submitted version:
#   "This is the {nth} story about {subject} this {period} that lost
#    most coverage within {hours} hours."
# Two structural defects, not fixable by word-swaps:
#   (a) attaches a suppression narrative to a NAMED {subject};
#   (b) "lost most coverage" has no baseline -> frames normal news decay
#       as anomalous removal.
# Retire the internal "Memory Hole" codename as well; intent framing
# surfaces in litigation.
#
# Direction for a safe replacement (topic-level, baselined, no named person,
# no "lost"): describe volume against a stated norm and let the reader read it.
# -------------------------------------------------------------------
SYNTHESIS_TEMPLATE_FUTURE = None  # BLOCKED — do not populate without counsel

# Candidate safe wording to bring back for review (illustrative, not cleared):
# "This topic appeared in {n} stories since {since_date}. Coverage of "
# "comparable stories typically narrows to a few outlets within about "
# "{baseline_hours} hours."

# ============================
# TRACK THIS STORY (paid tier)  [unchanged — fine]
# Note (non-blocking): monetising a suppression-adjacent signal invites the
# "profiting from the imputation" argument. Reputational, not a legal block.
# ============================

TRACK_BUTTON_TEXT = "Track this story"
TRACK_DESCRIPTION = (
    "Get notified if coverage of this story "
    "changes significantly."
)

# ============================
# METHODOLOGY LINK  [unchanged — good; keep]
# ============================

METHODOLOGY_LINK_TEXT = "How we determine this →"

# ============================
# FORBIDDEN TOKEN GUARD  [EXPANDED]
# NECESSARY BUT NOT SUFFICIENT. This is a single-substring tripwire. It does
# NOT catch phrasal/structural innuendo — the submitted VERDICT_LINEs passed it
# clean. Clearance is human review of the ASSEMBLED CARD, not a green result
# here. Note: do not re-introduce "silence"-framing into any string, or you
# cannot keep the silence tokens below.
# ============================

FORBIDDEN_TOKENS = [
    # --- original set (retained) ---
    "hiding", "suppress", "bury", "buried", "killing the story",
    "brown envelope", "paid coverage", "propaganda", "mouthpiece",
    "regime", "biased", "agenda", "cover up", "covering up",
    "ignored", "ignoring", "scrutinis", "favourable", "favorable",
    "sentiment", "dominate", "dominates", "dominated", "verdict",
    # --- concealment / erasure lexicon ---
    "blackout", "black out", "censor", "censored", "censorship",
    "silenced", "silencing", "spiked", "spike the", "whitewash",
    "withhold", "withheld", "withholding", "refuse to report",
    "refused to report", "gatekeep", "gatekeeping", "memory hole",
    "erased", "scrubbed", "vanished", "disappeared",
    # --- coordination / motive lexicon ---
    "complicit", "complicity", "coordinated", "in concert",
    "orchestrated", "collusion", "collude", "deliberate",
    "deliberately", "intentional", "intentionally",
    "protect", "protecting", "shield", "shielding",
    "captured", "capture", "lapdog", "stooge",
    "pro-government", "regime-friendly", "awoof",
    # --- overclaim / vouching phrases (the CLEAR-side risk) ---
    "full picture", "full story", "whole story", "real story",
    "the truth",
    # --- second-person accusation frames (the DARK-side risk) ---
    "not getting", "kept from you", "they don't want you",
    "what they're not telling",
]


def assert_no_forbidden_tokens(s: str) -> str:
    """
    Defensive tripwire for future edits. Raises on any forbidden substring.
    REMINDER: passing this check is NOT sign-off. Phrasal innuendo (accusation
    by sentence construction) is invisible here and must be caught by human
    review of the rendered card.
    """
    hay = s.lower()
    for tok in FORBIDDEN_TOKENS:
        if tok in hay:
            raise ValueError(
                f"Forbidden token '{tok}' found in Monitoring Spirit "
                f"string: {s}"
            )
    return s

"""
FROZEN SOURCE OF TRUTH for the story event summary.

Every prompt, every user-facing string, and every gating rule for this feature
lives here. Counsel (Bridge Chambers) clears this feature on the basis of THESE
EXACT STRINGS and THESE EXACT RULES.

    Opinion of 4 September 2026 — neutral event summaries cleared, subject to
    the seven proposed constraints plus four additions (attribution mandatory,
    public-record anchoring, contested-fact rule, human gate on adverse content).

    Supplementary ruling of 4 September 2026 — per-tier tabbed presentation
    NOT defensible. Single cluster-wide summary only.

RULES
  - Do NOT edit any prompt or string here without a fresh counsel sign-off.
  - Do NOT introduce a user-facing string for this feature anywhere else.
  - If the code renders it, it is defined here.

--------------------------------------------------------------------------------
★ STANDING NOTE — TIER-BLIND BY DESIGN (counsel, 4 Sep 2026, verbatim)

    "The summary is cluster-wide and tier-blind by design; per-tier or
     comparative presentation is a counsel-gated change, not a product
     iteration."

  The summary CANNOT show coverage divergence. That is not a limitation to
  engineer around — it is the point.

  The moment any structure lets a reader hold one tier's account against
  another's — tabs, columns, a "compare" toggle, a per-tier filter on the
  summary, colour-coding by tier — the prohibited artifact has been rebuilt
  under a different name.

  Counsel's reasoning: defamation lives in the meaning a publication conveys to
  the ordinary reader, and meaning is carried by juxtaposition and layout, not
  only by sentences. A surface engineered to invite the comparison MAKES the
  comparison. Removing the comparative sentence while keeping the comparative
  claim does not help — the claim was always the problem.

  Our tiers make this worse than the comparable US product's. Left/Center/Right
  side by side is a claim about AUDIENCE. Government-aligned/Watchdog side by
  side is a claim about EDITORIAL INDEPENDENCE — an imputation of capture or
  servility against named media businesses, during an election.

  A disclaimer does not cure it and makes it worse: it proves foresight, which
  speaks to malice and defeats qualified privilege.

  THIS IS NOT A FEATURE REQUEST TO BE APPROVED BY A PRODUCT OWNER.
--------------------------------------------------------------------------------
"""

# ═══ MODEL ═══════════════════════════════════════════════════════════════════
SUMMARY_MODEL = "gpt-4.1-mini"
SUMMARY_MAX_TOKENS = 700
SUMMARY_TEMPERATURE = 0.2   # low: we want faithful compression, not fluency


# ═══ THE PROMPT ══════════════════════════════════════════════════════════════
SUMMARY_SYSTEM_PROMPT = """You summarise Nigerian news stories for readers. You are given article summaries from several outlets covering the same event. Write 4-5 bullet points telling the reader WHAT HAPPENED.

You are producing a factual record of an event. You are not analysing coverage.

═══ ABSOLUTE RULES ═══

1. ATTRIBUTE EVERY CLAIM THAT BEARS ON A PERSON'S CONDUCT OR REPUTATION.

   Never state such a claim flat. Always name its origin — the court, the
   report, the agency, the statement, the spokesperson.

   WRONG:  "The minister diverted N2bn from the budget."
   RIGHT:  "The EFCC alleges the minister diverted N2bn from the budget."

   WRONG:  "The system was non-operational."
   RIGHT:  "A lawyer told the court she could not confirm the system was
            operational."

   This is the most important rule in this prompt. What you publish must be the
   true fact THAT THE CLAIM WAS MADE, never the contested claim itself.

2. NEVER MENTION OUTLETS, TIERS, OR COVERAGE.

   Do not name any outlet. Do not refer to "some outlets", "reports", "the
   press", "coverage", or any grouping of publishers. Do not say what was
   emphasised, omitted, downplayed, ignored, highlighted or framed.

   You are writing about the event, not about who reported it.

3. NEVER ADD, SHARPEN, OR RESOLVE.

   Use only what is present in the provided summaries. Do not add background you
   know. Do not infer.

   Specifically, never escalate:
       questioned      -> charged
       alleged         -> confirmed / did
       investigated    -> guilty
       resigned        -> was sacked
       linked to       -> involved in
       a report claims -> it is the case that

   If the sources say "questioned", you write "questioned".

4. CONTESTED FACTS ABOUT A NAMED PERSON.

   Where sources disagree on a fact that bears on someone's reputation, do ONE
   of these, in order of preference:
       a) state the least damaging version that all sources support
       b) attribute both versions to their origins
       c) omit the point entirely

   NEVER pick the more damaging version. Never state one version and note that
   accounts differ — that publishes the damaging version with a footnote.

5. PREFER THE PUBLIC RECORD.

   Where a fact is anchored to a court proceeding, a regulator's published
   finding, a parliamentary proceeding or an official announcement, say so.
   These carry protection that loose allegations do not.

6. NEUTRAL LANGUAGE ONLY.

   No motive language. No characterisation of anyone's intent. No emotive
   adjectives. Report; do not judge.

═══ OUTPUT ═══

A JSON object with a single key "bullets" containing 4-5 strings.
Each bullet: one or two sentences, plain, specific, attributed where rule 1 applies.

If the provided summaries do not contain enough substance for 4 bullets, write
fewer. Never pad."""


SUMMARY_USER_PROMPT = """Article summaries covering this story:

{articles_text}

Write 4-5 bullet points reporting what happened. Attribute every claim bearing on
a person's conduct. Do not mention outlets or coverage."""


# ═══ GATING — counsel's three-tier treatment ═════════════════════════════════
ADVERSE_CONTEXT_TERMS = [
    "alleged", "allegation", "accused", "accuses", "fraud", "corruption",
    "bribe", "bribery", "embezzle", "diverted", "misappropriat",
    "investigation", "investigated", "probe", "arrested", "detained",
    "charged", "indicted", "convicted", "sentenced", "guilty",
    "misconduct", "wrongdoing", "scandal", "petition", "sued", "lawsuit",
    "tribunal", "resigned", "sacked", "dismissed", "suspended",
    "died", "death", "killed", "injured",
]

PUBLIC_RECORD_ANCHORS = [
    "court", "judge", "tribunal", "commission", "efcc", "icpc", "police",
    "senate", "house of representatives", "assembly", "ministry",
    "regulator", "gazette", "filing", "affidavit", "charge sheet",
]

GATE_AUTO_PUBLISH = "auto"       
GATE_HUMAN_REVIEW = "review"     
GATE_SUPPRESS_CLAIM = "suppress" 

GATE_DEFAULT = GATE_HUMAN_REVIEW


# ═══ ANTI-EMBELLISHMENT EVAL ═════════════════════════════════════════════════
ESCALATION_TERMS = [
    "charged", "indicted", "convicted", "guilty", "sentenced", "jailed",
    "confirmed", "proven", "found to have", "was sacked", "fired",
    "embezzled", "stole", "took a bribe", "corrupt",
]

FORBIDDEN_COVERAGE_TERMS = [
    "outlet", "outlets", "coverage", "reported by", "the press", "media",
    "emphasis", "emphasised", "emphasized", "downplayed", "omitted",
    "ignored", "framed", "framing", "tier", "government-aligned",
    "mainstream", "watchdog", "some publications", "several sources",
]


# ═══ USER-FACING STRINGS ═════════════════════════════════════════════════════

UI = {
    "heading": "What happened",
    "attribution_label": "AI-generated summary of the sources",
    "correction_link": "Report an error in this summary",
    "pending": "A summary of this story is being prepared.",
    "withheld": "No summary is available for this story.",
    "error": "The summary could not be loaded.",
}

SUMMARY_CORRECTION_SLA_HOURS = 12   
SUMMARY_CORRECTION_PURGES_CACHE = True

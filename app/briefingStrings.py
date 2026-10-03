"""
CONSTANTS FOR THE REBUILT DAILY BRIEFING — for counsel's clearance.

Counsel's consolidated instruction of 3 October 2026, section B, as amended by
counsel's review of the 3 October samples ("Daily Briefing fixes before
launch"). The Briefing is off publicly (BRIEFING_PUBLIC in app/withdrawals.py
and src/constants/features.js) until counsel clears this file and the sample
editions.

WHAT A BRIEFING ITEM IS
  - Headline: the source headline after cleaning (HEADLINE_* below).
  - Body: the story's cleared event summary (app/storySummaryStrings.py,
    generate_cluster_summary). There is no separate Briefing prompt.
  - The model sees article headlines and feed summaries only, labelled
    "Source 1", "Source 2", ... It receives no outlet name, identifier or tier.
  - Beside it: how many distinct outlets in each tier reported the story, as
    counts, with the time they were counted. No percentages.
  - Every item carries the attribution label, the correction link and the
    methodology link. Search and social previews use the same text.

WHICH STORIES
  - Stories first seen in the WINDOW_HOURS before 06:00 Lagos time, reported by
    at least MIN_DISTINCT_OUTLETS distinct outlets, with an image; widest
    coverage first, at most MAX_STORIES. Never selected or ordered by tier
    imbalance. Items that do not pass are left out, not replaced: a short
    edition is acceptable; the gate is never loosened to fill one.

HOW AN ITEM IS ROUTED (checked on the item's current text, including any
editor rewrite)
  Left out:
    - no usable cleared summary (missing, superseded, failed, flagged, suppressed)
    - a FORBIDDEN_TOKENS word (whole words) in the headline or body
    - the headline is empty after cleaning
    - the headline carries a HEADLINE_BODY_TERMS term the body lacks
    - the cleared gate, run over headline + body, flags it or suppresses it
    - an editor left it out
  Senior review: the cleared gate, run over headline + body, says senior_review.
  Review (at least):
    - the cleared gate says review
    - POLITICAL_REVIEW_LANE: a registry name, a party or a political office
    - SURNAME CHECK: a person referred to by one name with no earlier full name
    - REPORTED_PHRASES in an item naming a person or party
    - COMMENTARY_PHRASES / COMMENTARY_STATEMENT_PATTERN
    - an adverse item naming an excluded, held or private registry person
  Auto: none of the above.

  auto publishes. review and senior_review publish only after a named editor
  ticks every line of EDITOR_CHECKLIST and approves. An approval covers the
  exact text approved: a rewrite, or a corrected summary, needs a fresh
  approval. Every editor action (rewrite, leave out, restore, approve) is
  written to briefing_edit_log.

Do NOT edit any string or rule here without counsel's sign-off.
"""
from app.storySummaryStrings import UI as SUMMARY_UI

WINDOW_HOURS = 24
EDITION_CUTOFF_HOUR_LAGOS = 6
MIN_DISTINCT_OUTLETS = 5
MAX_STORIES = 9

LANE_AUTO = "auto"
LANE_REVIEW = "review"
LANE_SENIOR_REVIEW = "senior_review"
LANE_LEFT_OUT = "left_out"
LANES_NEEDING_EDITOR = (LANE_REVIEW, LANE_SENIOR_REVIEW)

# ═══ FORBIDDEN WORDS (whole words, headline and body) ═══════════════════════
# Counsel, 3 Oct review, item 5: "%", "percent", "sides", "side a/b" removed
# from the summary-text check. The coverage panel is built from counts only
# and is tested never to contain "%" or "bias".
FORBIDDEN_TOKENS = ("bias", "biased", "dramatic", "common ground", "why it matters")

# ═══ HEADLINES (item 1) ═════════════════════════════════════════════════════
# Stripped from the start of the source headline, repeatedly, with any
# following ":", "-", "|" or "!".
HEADLINE_PREFIXES = (
    "breaking news", "breaking", "just in", "exclusive", "confirmed",
    "full list", "watch", "photos", "video", "update", "developing",
)
# Stripped from the end of the headline.
HEADLINE_TRAILING_PHRASES = (
    "video trends", "video goes viral", "see photos", "see video", "watch video",
    "photos", "video", "(photos)", "(video)", "[photos]", "[video]",
)
# An item is left out when its headline contains a term from one of these
# groups and the body contains no term from the same group.
HEADLINE_BODY_TERMS = (
    ("alleged", "allegedly", "alleges", "allege", "allegation", "allegations"),
    ("forgery", "forged", "forging", "forge"),
    ("fake",),
    ("fraud", "fraudulent", "fraudster", "fraudsters"),
    ("guilty", "guilt"),
    ("confirmed", "confirms", "confirm"),
    ("charged", "charges", "charge"),
    ("convicted", "convicts", "conviction", "convict"),
    ("arrested", "arrests", "arrest"),
    ("detained", "detains", "detention", "detain"),
    ("indicted", "indictment", "indicts", "indict"),
    ("sentenced", "sentence", "sentences"),
    ("jailed", "jail", "jails"),
    ("sacked", "sacks", "sack"),
    ("corrupt", "corruption"),
    ("embezzled", "embezzlement", "embezzle"),
    ("looted", "looting", "loot"),
    ("arraigned", "arraignment", "arraign"),
)

# ═══ POLITICAL REVIEW LANE (item 2; narrowed by counsel's ruling, 3 Oct) ════
# For the first 30 days after public launch an item is held for review only
# when a political figure (registry person or political office) or a party
# appears together with one of the POLITICAL_TRIGGERS below. Routine
# announcements and ceremonial messages publish automatically. Court and
# adjudication items about named persons or companies are held for review
# (COURT_TERMS). At day 30 counsel receives the change log
# (scripts/briefing_change_log.py). Ending the lane is counsel's decision.
POLITICAL_REVIEW_LANE = True
PARTY_NAMES = (
    "APC", "All Progressives Congress", "PDP", "Peoples Democratic Party",
    "LP", "Labour Party", "ADC", "African Democratic Congress", "NNPP",
    "New Nigeria Peoples Party", "APGA", "All Progressives Grand Alliance",
    "SDP", "Social Democratic Party", "YPP", "Young Progressives Party",
    "ADP", "Action Democratic Party", "PRP", "Peoples Redemption Party",
    "NDC", "National Democratic Congress", "AA", "Action Alliance",
    "ZLP", "Zenith Labour Party", "Accord", "Accord Party", "APM", "BP", "NRM", "AAC",
)
POLITICAL_OFFICES = (
    "president", "vice president", "vice-president", "presidency",
    "governor", "deputy governor", "governorship",
    "senator", "senate", "senate president", "deputy senate president",
    "house of representatives", "reps", "speaker", "deputy speaker",
    "lawmaker", "lawmakers", "legislator", "legislators", "national assembly",
    "state assembly", "house of assembly",
    "minister", "ministers", "minister of state", "commissioner", "commissioners",
    "local government chairman", "lg chairman", "council chairman",
    "party chairman", "national chairman", "campaign council", "campaign manager",
    "candidate", "candidates", "candidacy", "running mate", "primaries", "primary election",
    "presidential", "aspirant", "aspirants", "director-general of the campaign",
)

# Triggers that hold a political item (counsel's ruling, 3 Oct, item 2).
POLITICAL_CONTEST_TERMS = (
    "candidacy", "candidate", "candidates", "campaign", "campaigns", "campaigning",
    "primaries", "primary election", "running mate", "defect", "defects", "defected",
    "defecting", "defection", "decamp", "decamped", "decamping",
)
POLITICAL_ENDORSE_TERMS = (
    "re-elect", "re-elected", "re-election", "reelect", "reelected", "reelection",
    "endorse", "endorses", "endorsed", "endorsing", "endorsement",
)
# One political actor accusing, condemning or criticising another (two or
# more political actors in the item, plus one of these verbs).
POLITICAL_ATTACK_TERMS = (
    "accuse", "accuses", "accused", "accusing", "condemn", "condemns", "condemned",
    "condemning", "criticise", "criticises", "criticised", "criticising", "criticize",
    "criticizes", "criticized", "criticizing", "criticism", "slam", "slams", "slammed",
    "attack", "attacks", "attacked", "fault", "faults", "faulted", "berate", "berated",
    "tackle", "tackles", "tackled", "rebuke", "rebuked", "blast", "blasts", "blasted",
    "fires back", "fired back", "lambast", "lambasted", "knocks", "knocked",
)
# The health of a named office-holder.
POLITICAL_HEALTH_TERMS = (
    "health", "healthy", "ill", "illness", "sick", "sickness", "ailment", "hospital",
    "hospitalised", "hospitalized", "medical", "medical treatment", "unwell",
)
# "Candidates" in an exam context is not political.
EXAM_CONTEXT_TERMS = (
    "exam", "exams", "examination", "examinations", "WAEC", "NECO", "JAMB", "UTME",
    "SSCE", "WASSCE", "NABTEB", "admission", "admissions", "results", "credits",
)
# Court and adjudication: an item using one of these and naming a person or
# company is held for review for the first 30 days.
COURT_TERMS = (
    "court", "courts", "judge", "judges", "tribunal", "tribunals", "magistrate",
    "court ruling", "ruled that", "judgment", "judgement", "verdict", "arraign", "arraigned",
    "arraignment", "lawsuit", "suit", "adjourned", "convicted", "acquitted",
    "sentenced", "found guilty", "panel found", "commission found",
)

# ═══ HEADLINE CHECKS (counsel's ruling, 3 Oct, item 3) — route to review ════
# A number or quantity word in the headline that the body does not support.
HEADLINE_QUANTITY_WORDS = (
    "scores", "dozens", "hundreds", "thousands", "millions", "many", "several",
    "numerous", "countless", "mass",
)
# A flat killing or casualty claim in the headline with no attribution.
HEADLINE_CASUALTY_TERMS = (
    "kill", "kills", "killed", "die", "dies", "died", "dead", "death", "deaths",
    "casualties", "massacre", "massacred", "slaughter", "slaughtered", "slain",
    "neutralise", "neutralised", "neutralize", "neutralized",
)
# Any of these in the headline counts as attribution ("Military says...",
# "... — Police", "Police: ...").
HEADLINE_ATTRIBUTION_PATTERN = (
    r"\b(says?|said|claims?|claimed|according to|confirms?|confirmed|announces?|announced|reports?)\b"
    r"|[—–-]\s*[A-Z][\w .'’-]+$|^[A-Z][\w .'’-]{1,40}:\s"
)

# ═══ AUTOMATIC CHECKS (item 3) — each routes the item to review ═════════════
# (i) SURNAME CHECK: a name of a person (a registry name part, or the last
#     word of a capitalised full name in the item) used alone before any full
#     name containing it. Headline names must appear in full in the body.
SURNAME_CHECK_IGNORE = (
    "President", "Vice", "Senate", "Senator", "Governor", "Minister", "Speaker",
    "State", "Federal", "National", "Nigeria", "Nigerian", "Nigerians", "Abuja",
    "Lagos", "Court", "High", "Supreme", "Appeal", "Police", "Army", "Party",
    "Assembly", "House", "Commission", "Council", "Chief", "Justice", "General",
    "Director", "Director-General", "Chairman", "Secretary", "Mr", "Mrs", "Ms",
    "Dr", "Prof", "Alhaji", "Sen", "Hon", "Gov", "Rt", "Barr", "Engr",
    "Oba", "Emir", "Sultan", "Ooni", "Monday", "Tuesday", "Wednesday",
    "Thursday", "Friday", "Saturday", "Sunday", "January", "February", "March",
    "April", "May", "June", "July", "August", "September", "October",
    "November", "December", "The", "A", "An", "In", "On", "At", "He", "She",
    "They", "It", "This", "That", "According", "Deputy", "Former", "Late",
    "First", "Lady", "Acting", "Executive", "Permanent", "Minority", "Majority",
    "African", "American", "European", "Asian", "Kenyan", "Ugandan", "Ghanaian",
)

# A capitalised run of words ending in one of these is an organisation or a
# place, not a person, so its last word is not treated as a surname.
SURNAME_CHECK_ORG_WORDS = (
    "City", "United", "League", "Party", "Congress", "Group", "Company",
    "University", "Bank", "Club", "FC", "Council", "Commission", "Agency",
    "Refinery", "Limited", "Ltd", "Plc", "Ministry", "Court", "Hospital",
    "School", "Church", "Mosque", "Market", "Airport", "Road", "Street",
    "Stadium", "Square", "Association", "Union", "Forum", "Foundation",
    "Initiative", "Centre", "Center", "Organisation", "Organization",
    "Service", "Services", "Corporation", "Authority", "Board", "Bureau",
    "Office", "Department", "Assembly", "House", "Senate", "Police", "Army",
    "Navy", "Force", "Command", "Zone", "State", "States", "Nigeria", "Africa",
    "Republic", "Petroleum", "Petrochemicals", "Panel", "Tribunal",
    "Programme", "Program", "Project", "Fund", "Exchange", "Airways", "Airline",
    "Network", "Movement", "Front", "Alliance", "Coalition", "Committee",
    "Institute", "Polytechnic", "College", "Academy", "Prize", "Awards", "Cup",
    "Examination", "Examinations", "Council", "Games", "Championship",
    "Officer", "Area", "Battalion", "Brigade", "Division", "Theatre", "Headquarters",
    "Correctional", "Centre", "Prison", "Hospital", "Government",
)

# (ii) Reported-speech phrases, in an item naming a person or a party.
REPORTED_PHRASES = (
    "reportedly", "according to reports", "according to the reports",
    "according to report", "according to the report",
    "as stated in the report", "as stated in the reports", "it is reported",
    "it was reported", "reports say", "reports said", "reports indicate",
    "reports indicated", "reports from", "match reports",
)

# (iii) Commentary on what something means.
COMMENTARY_PHRASES = (
    "significant development", "marked a", "underscores", "highlights", "signals that",
    "indicating", "reflecting", "suggesting",
)
# A bullet saying what a statement, decision or event "links" or "marks"
# (counsel's wording). Plain uses such as "marking the 66th anniversary" or
# "costs linked to security" are reporting, not commentary, and do not match.
COMMENTARY_STATEMENT_PATTERN = (
    r"\b(statement|remarks?|comments?|speech|address|decision|move|ruling|development|"
    r"appointment|which|this|it)\s+(links|linked|marks|marked)\b"
)

# ═══ EDITOR (item 9) ════════════════════════════════════════════════════════
# The approving editor must tick every line. The ticks are stored with the
# approval and in the change log.
EDITOR_CHECKLIST = (
    ("full_names", "Every person is named in full on first mention."),
    ("conduct_origin", "Every claim about conduct has an origin (court, agency, named person)."),
    ("no_reportedly", "No \"reportedly\" or \"according to reports\" without an origin."),
    ("headline", "The headline matches the body and has no prefix words."),
    ("party_live", "Every candidacy or party descriptor was checked live today (source and time entered for each below)."),
    ("no_commentary", "No commentary words."),
    ("no_protected_adverse", "No held or private person appears in an adverse context."),
)

# ═══ READER-FACING STRINGS ══════════════════════════════════════════════════
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

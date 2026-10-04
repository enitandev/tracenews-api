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

HOW AN ITEM IS ROUTED (counsel's ruling of 3 Oct 2026 adopting the owner's
prompt-first decision; supersedes the earlier routing)
  Automatic corrections when the edition is built, each written to
  briefing_edit_log with the actor "system":
    - Headline: the cleaned source headline if it passes HEADLINE checks,
      otherwise another outlet's headline for the same story that passes;
      none passes -> the item is left out of that edition.
    - A bullet with a banned coverage word, a FORBIDDEN_TOKENS word or an
      escalation the sources do not support is removed (the bullet only);
      fewer than two bullets left -> the item is left out.
    - Quotes not inside quotation marks in a source and attributed there to
      the named speaker, and unattributed next steps, are removed.
    - A party or candidacy descriptor on a registry person is replaced from
      the registry; if the registry has none, the descriptor is dropped.
  One editor lane:
    - Review: an EDITOR_LANE_TRIGGERS word (allege, accuse, arrest, charge,
      arraign, convict, sentence, indict, probe, investigate, sue, court)
      about a named person or organisation, or a named person suspended or
      dismissed; or an adverse item about a held or private registry person.
      "corruption", "fraud", "bribery", "embezzle", "divert" alone never
      trigger it; nor do harm words (kill, die, injure).
    - Senior review: the same about a principal office-holder. Needs a second,
      different named approver from SENIOR_SECOND_APPROVERS; without one the
      item does not publish.
  Everything else publishes automatically.

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

# ═══ PARTIES (descriptor correction) ═════════════════════════════════════════
PARTY_NAMES = (
    "APC", "All Progressives Congress", "PDP", "Peoples Democratic Party",
    "LP", "Labour Party", "ADC", "African Democratic Congress", "NNPP",
    "New Nigeria Peoples Party", "APGA", "All Progressives Grand Alliance",
    "SDP", "Social Democratic Party", "YPP", "Young Progressives Party",
    "ADP", "Action Democratic Party", "PRP", "Peoples Redemption Party",
    "NDC", "Nigeria Democratic Congress", "AA", "Action Alliance",
    "ZLP", "Zenith Labour Party", "Accord", "Accord Party", "APM", "BP", "NRM", "AAC",
)
# Full name -> abbreviation, so "Peoples Democratic Party" and "PDP" count as the same party.
PARTY_ALIASES = {
    "All Progressives Congress": "APC", "Peoples Democratic Party": "PDP", "Labour Party": "LP",
    "African Democratic Congress": "ADC", "New Nigeria Peoples Party": "NNPP",
    "All Progressives Grand Alliance": "APGA", "Social Democratic Party": "SDP",
    "Young Progressives Party": "YPP", "Action Democratic Party": "ADP",
    "Peoples Redemption Party": "PRP", "Nigeria Democratic Congress": "NDC",
    "Action Alliance": "AA", "Zenith Labour Party": "ZLP", "Accord Party": "Accord",
}
CANDIDACY_WORDS = ("candidate", "flagbearer", "flag bearer", "running mate", "aspirant", "presidential hopeful")

# ═══ THE EDITOR LANE (counsel's ruling, 3 Oct, items 3-5) ═══════════════════
# Each trigger counts only in a sentence that names a person or an
# organisation that is not itself the authority acting (police, court,
# agency): "the police arrested Musa Bello" triggers; "the police are
# investigating the abduction" does not.
EDITOR_LANE_TRIGGERS = {
    "allege": r"\balleg(e|es|ed|edly|ing|ation|ations)\b",
    "accuse": r"\baccus(e|es|ed|ing|ation|ations)\b",
    "arrest": r"\barrest(s|ed|ing)?\b",
    "charge": r"\bcharg(e|es|ed|ing)\b",
    "arraign": r"\barraign(s|ed|ing|ment)?\b",
    "convict": r"\bconvict(s|ed|ing|ion|ions)?\b",
    "sentence": r"\bsentenc(e|es|ed|ing)\b",
    "indict": r"\bindict(s|ed|ing|ment|ments)?\b",
    "probe": r"\bprob(e|es|ed|ing)\b",
    "investigate": r"\binvestigat(e|es|ed|ing|ion|ions)\b",
    "sue": r"\b(sue|sues|sued|suing|lawsuit|lawsuits)\b",
    "court": r"\bcourts?\b",
    # Counsel, 4 Oct 2026, fix 5.
    "legal challenge": r"\blegal challenges?\b",
    "petition": r"\bpetition(s|ed|ing|er|ers)?\b",
}
# A named person suspended or dismissed: counts only where the person is the
# object ("suspended Musa Bello", "Musa Bello was suspended", "suspension of
# Musa Bello"), never for a ban or an activity (counsel, 4 Oct 2026, fix 5).
SUSPENSION_TRIGGERS = {
    "suspend": r"suspen(?:d|ds|ded|ding|sion)",
    "dismiss": r"dismiss(?:es|ed|ing|al)?",
}
# Organisations that act (arrest, charge, try, investigate) rather than being
# the subject. A sentence naming only these does not trigger the lane.
AUTHORITY_WORDS = (
    "Police", "Command", "Army", "Navy", "Force", "Court", "Courts", "Tribunal",
    "Commission", "Agency", "Ministry", "Government", "Service", "Office",
    "Department", "Directorate", "Corps", "Bureau", "Authority", "Board",
    "Assembly", "Senate", "House", "Council", "Prison", "Correctional", "EFCC",
    "ICPC", "NDLEA", "DSS", "NSCDC", "INEC", "Federal", "State", "Judiciary",
)
# Role words just before a name that make the person the actor, not the
# subject ("police spokesperson Henry Okoye said two suspects were arrested").
ACTOR_ROLE_WORDS = (
    "spokesperson", "spokesman", "spokeswoman", "Justice", "Judge", "judge",
    "Magistrate", "prosecutor", "counsel", "lawyer", "Commissioner of Police",
    "Inspector-General", "Attorney-General", "Chairman of the EFCC",
    "Public Relations Officer", "PRO", "Police Public Relations Officer", "PPRO",
    "Director of Public Prosecutions", "Solicitor-General",
)
# Senior review: the lane triggers about one of these.
# (PRINCIPAL_OFFICEHOLDERS in app/storySummaryStrings.py.)
SENIOR_SECOND_APPROVERS = ("Enitan Bello",)   # counsel's ruling, 3 Oct, 4a

# ═══ HEADLINE CHECKS — a headline that fails is replaced by another outlet's ═
# A number or quantity word in the headline that the body does not support.
HEADLINE_QUANTITY_WORDS = (
    "scores", "dozens", "hundreds", "thousands", "millions", "many", "several",
    "numerous", "countless", "mass",
)
# A flat killing or casualty claim in the headline with no attribution.
HEADLINE_CASUALTY_TERMS = (
    "kill", "kills", "killed", "die", "dies", "died", "dead", "death", "deaths",
    "casualties", "massacre", "massacred", "slaughter", "slaughtered", "slain",
    "neutralise", "neutralised", "neutralises", "neutralize", "neutralized", "neutralizes",
    # Counsel, 4 Oct 2026, fix 1.
    "eliminate", "eliminated", "eliminates", "wipe out", "wiped out", "wipes out",
    "gun down", "gunned down", "guns down", "success", "successes",
)
# Counsel, 4 Oct 2026, fix 1: an offender label in a headline needs a
# conviction or sentence in the body, or "suspected", "alleged" or a "says"
# attribution in the headline itself.
HEADLINE_OFFENDER_LABELS = (
    "kingpin", "kingpins", "fraudster", "fraudsters", "kidnapper", "kidnappers", "thief", "thieves",
    "cultist", "cultists", "robber", "robbers", "trafficker", "traffickers", "smuggler", "smugglers",
    "rapist", "rapists", "murderer", "murderers", "killer", "killers", "drug baron", "drug barons",
    "drug lord", "drug lords", "ritualist", "ritualists", "impostor", "impostors", "imposter", "imposters",
    "embezzler", "embezzlers", "looter", "looters",
)
HEADLINE_OFFENDER_QUALIFIERS = r"\b(suspected|alleged|allegedly|says|said|accused)\b"
BODY_CONVICTION_PATTERN = r"\b(convicted|sentenced|found guilty|pleaded guilty|guilty verdict)\b"
# ═══ COUNSEL, 4 OCT 2026, FIXES 2-4 ════════════════════════════════════════
# Fix 2: a critical or adverse characterisation whose origin is collective or
# unnamed is removed from every section.
COLLECTIVE_ORIGINS = (
    "critics", "commentators", "public figures", "some voices", "voices", "lawyers",
    "civil society", "observers", "early users", "analysts", "experts", "some nigerians",
    "many nigerians", "stakeholders", "pundits",
)
ADVERSE_CHARACTERISATION_TERMS = (
    "concern", "concerns", "criticise", "criticised", "criticize", "criticized", "criticism",
    "critical of", "condemn", "condemned", "condemnation", "decry", "decried", "fault", "faulted",
    "slam", "slammed", "lament", "lamented", "described the", "colonised", "colonized",
    "disappointment", "mixed feelings", "failure", "failures", "bad governance", "corruption",
    "nepotism", "insecurity", "mismanagement", "incompetence", "questioned", "questioning",
    "worried", "worries", "alarm", "outrage", "backlash", "uproar", "complain", "complained",
)
# Fewer than this many What happened points after corrections: item left out.
BRIEFING_MIN_POINTS = 3
# Fix 4: an outlet named in reader text is allowed only where the outlet is
# the story's subject (named in the headline) or the venue of a statement.
EXTRA_OUTLET_NAMES = ("News Agency of Nigeria", "NAN", "Reuters", "AFP", "Agence France-Presse",
                      "Associated Press", "BBC", "Al Jazeera", "CNN")
# Outlet names that are also ordinary words: counted only in a reporting
# context ("told The Nation", "according to Leadership").
AMBIGUOUS_OUTLET_NAMES = ("Leadership", "Independent", "The Nation", "Nation", "The Sun", "Sun", "Tribune",
                          "The Guardian", "Guardian", "Blueprint", "Pulse", "Daily Post", "The Cable", "Punch")
OUTLET_REPORTING_CONTEXT = r"(according to|reported by|made available to|obtained by|seen by|learnt by|quoted by|told|in an interview with|speaking (?:to|with|on)|said on|appearing on)\s+(?:the\s+)?"
OUTLET_VENUE_CONTEXT = r"(told|in an interview with|speaking (?:to|with|on)|said on|appearing on|in a chat with)\s+(?:the\s+)?"
SOURCE_NUMBER_PATTERN = r"\s*\((?:Sources?|Src\.?)\s*\d+(?:\s*(?:,|and|&|-|–)\s*\d+)*\)"
# Court phrases that contain a casualty word but report no death.
HEADLINE_NON_CASUALTY_PHRASES = (
    "sentenced to death", "death sentence", "death sentences", "death penalty",
    "death row", "death warrant", "death warrants",
)
# A headline in Nigerian Pidgin is not used: the Briefing is written in English.
HEADLINE_PIDGIN_MARKERS = ("kpai", "wetin", "afta", "dem don", "make dem", "say make", "una", "wat next", "don kpai", "dey")
# A speaker "emphasised" something: reported speech, written as "said"
# (the model never sees outlets, so the word cannot describe coverage).
SPEECH_VERB_FIXES = {"emphasised": "said", "emphasized": "said", "emphasises": "says", "emphasizes": "says"}
# "the press" inside these is about journalists' access, not about coverage.
PRESS_ACCESS_PHRASES = r"\bthe press (?:pass(?:es)?|conference|secretary|freedom|briefing|room|corps|access|office|pool|gallery)\b"
# Any of these in the headline counts as attribution ("Military says...",
# "... — Police", "Police: ...").
HEADLINE_ATTRIBUTION_PATTERN = (
    r"\b(says?|said|claims?|claimed|according to|confirms?|confirmed|announces?|announced|reports?)\b"
    r"|[—–-]\s*[A-Z][\w .'’-]+$|^[A-Z][\w .'’-]{1,40}:\s"
)

# ═══ NAME DETECTION (used to tell whether a sentence names someone) ════════
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
    # Places are not surnames: the states, the FCT, and countries in the news.
    "Abia", "Adamawa", "Akwa", "Ibom", "Anambra", "Bauchi", "Bayelsa", "Benue", "Borno",
    "Cross", "River", "Delta", "Ebonyi", "Edo", "Ekiti", "Enugu", "Gombe", "Imo", "Jigawa",
    "Kaduna", "Kano", "Katsina", "Kebbi", "Kogi", "Kwara", "Nasarawa", "Niger", "Ogun",
    "Ondo", "Osun", "Oyo", "Plateau", "Rivers", "Sokoto", "Taraba", "Yobe", "Zamfara", "FCT",
    "Maiduguri", "Ibadan", "Kenya", "Ghana", "Uganda", "Tanzania", "Morocco", "Madagascar",
    "Guinea-Bissau", "Guinea", "Senegal", "Cameroon", "Benin", "Togo", "Egypt", "Paris",
    "London", "France", "Britain", "China", "America", "Washington", "Tennessee",
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

# ═══ FULLER SECTIONS (counsel's ruling, 3 Oct, item 6) ══════════════════════
# "What happened" is the cleared summary itself (up to 8 points, same prompt
# and rules, never pad). The three sections below are generated by
# EXTRAS_SYSTEM_PROMPT from the same source text (headlines and feed
# summaries, labelled Source 1, 2, ...; no outlet names or tiers), then
# checked in code before anything is stored:
#   Who said what  - each quote must appear verbatim in the source text
#                    (string match); named speaker with role; rendered with
#                    the verb "said" only; kept in source order, never
#                    arranged as rebuttal pairs; adverse quotes follow the
#                    same gate as the summary.
#   What happens next - only dates and steps stated in the sources, each
#                    attributed; no predictions.
#   Background     - at most 3 points, source-only; no background about a
#                    named person's conduct, litigation or party history
#                    unless it is a public record and attributed.
#   Coverage       - counts only; no "%" and no "bias".
QUOTES_MAX = 4
NEXT_MAX = 3
BACKGROUND_MAX = 3
QUOTE_VERB = "said"

EXTRAS_SYSTEM_PROMPT = """You prepare three short sections of a news briefing about one Nigerian news story. You are given article headlines and summaries from several sources, labelled Source 1, Source 2 and so on. Use only what is in them.

Return a JSON object with three keys: "quotes", "next" and "background".

"quotes": up to 4 direct quotes. Each is an object {"speaker": the person's full name, "role": their role as the sources state it, "quote": the exact words}.
- Copy the words exactly as they appear inside quotation marks in a source. Do not paraphrase, shorten, correct or join quotes.
- Include a quote only if a source shows it in quotation marks and names who said it.
- List quotes in the order they appear in the sources. Never arrange them as a reply and a counter-reply.
- Never quote or name a person under 18.

"next": up to 3 items. Each is a date or a next step stated in the sources, with who stated or set it. Example: "The court adjourned the case to October 13, 2026." No predictions. Do not write "is expected to", "likely" or "could" unless a named source said it, and then attribute it.

"background": up to 3 short points of context taken only from the sources. Do not give background about a named person's conduct, court cases or party history unless the sources tie it to a public record (a court, a published finding, an official announcement), and then attribute it.

The summary rules apply to every section:
- Never mention outlets, coverage, reports or tiers, and never say what was emphasised or omitted.
- Attribute every claim that bears on a person's conduct or reputation to its origin.
- Neutral language. No commentary on what anything means, signals, highlights or marks.
- Give each person's full name and role at first mention.

If a section has nothing that meets these rules, return an empty list for it. Never pad."""

EXTRAS_USER_PROMPT = """Source material for this story:

{articles_text}

Return the JSON object with "quotes", "next" and "background"."""

# Words that make a "next" item a prediction unless it is attributed.
NEXT_PREDICTION_TERMS = ("likely", "expected to", "could", "might", "may well", "set to", "poised to")
NEXT_ATTRIBUTION_PATTERN = (
    r"\b(according to|said|says|stated|announced|directed|ordered|fixed|adjourned|"
    r"scheduled|set|declared|told|confirmed)\b"
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
    "sections": {
        "what_happened": "What happened",
        "quotes": "Who said what",
        "next": "What happens next",
        "background": "Background",
    },
    "coverage_as_of": "Counted at {time} WAT",
    "tier_labels": {"govt_aligned": "Govt", "mainstream": "Mainstream", "watchdog": "Watchdog"},
    "empty": "Today's briefing is not ready yet.",
}

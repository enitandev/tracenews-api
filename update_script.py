import re

with open("app/behavioral_analyzer.py", "r") as f:
    content = f.read()

combined_prompt = """PROMPT_COMBINED = \"\"\"You are analyzing a Nigerian 
news article for the TraceNews Independence Index.

Analyze the headline and summary for ALL of 
the following signals in one pass and return 
a single JSON object.

SIGNAL 1 - Government Framing:
How is government framed in this text?
- "deferential": praises or presents official 
  claims uncritically
- "accountability": critical, exposes wrongdoing, 
  challenges official claims
- "neutral": factual, no clear framing
- "none": no government mentioned

SIGNAL 2 - Churnalism:
Does this read like original journalism or 
a reproduced press release/wire copy?
Strong churnalism indicators: "in a statement", 
"NAN reports", bureaucratic language, reads 
entirely as official announcement.
Original indicators: investigative language, 
fieldwork, critical tone.
Default to "mixed" when in doubt.

SIGNAL 4 - Lexical Deference:
Count deferential terms in EDITORIAL COPY ONLY 
(not in quotes): "His Excellency", "visionary", 
"Renewed Hope Agenda", "landmark achievement", 
"performing governor", "hardworking minister" etc.
Estimate word count.

SIGNAL 6 - Editorial Independence:
Does this article contain corrections, 
retractions, or clarifications of previous 
reporting? Look for: "Correction:", "Retraction:", 
"We earlier reported...", "Editor's Note:"

BROWN ENVELOPE:
Is this likely paid-for content? Only flag if 
ALL THREE apply:
1. Overwhelmingly positive toward a specific 
   official (in editorial voice, NOT in quotes)
2. No clear news hook
3. Single source dependency

Return ONLY a raw JSON object:

{
  "s1": {
    "government_framing": "deferential|accountability|neutral|none",
    "has_non_government_voice": true/false,
    "s1_classification": "independent|captured|neutral",
    "framing_explanation": "one sentence"
  },
  "s2": {
    "reporting_type": "original|press_release|wire_copy|mixed",
    "is_churnalism": true/false,
    "churnalism_evidence": "one sentence or empty string"
  },
  "s4": {
    "deferential_count": integer,
    "approximate_word_count": integer,
    "deference_density_per_1000_words": float
  },
  "s6": {
    "is_correction_or_retraction": true/false,
    "correction_type": "correction|retraction|clarification|follow_up|none"
  },
  "brown_envelope": {
    "overwhelmingly_positive_toward_official": true/false,
    "has_clear_news_hook": true/false,
    "single_source_dependent": true/false,
    "brown_envelope_suspected": true/false,
    "evidence": "one sentence or null"
  }
}

Article headline + summary:
{article_text}\"\"\""""

content = re.sub(r'PROMPT_S1 = """.*?{article_text}"""\s+PROMPT_S2 = """.*?{article_text}"""\s+PROMPT_S4 = """.*?{article_text}"""\s+PROMPT_S5_HEADLINES', combined_prompt + "\n\n\nPROMPT_S5_HEADLINES", content, flags=re.DOTALL)
content = re.sub(r'PROMPT_S6 = """.*?{article_text}"""\s+PROMPT_BROWN_ENVELOPE = """.*?{article_text}"""\s+', '', content, flags=re.DOTALL)

with open("app/behavioral_analyzer.py", "w") as f:
    f.write(content)


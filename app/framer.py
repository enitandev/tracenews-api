import os
import json
from openai import OpenAI

openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

def generate_framing_summary(stories: list, alignment: str) -> dict:
    """
    Generate an AI framing summary for a specific group of aligned stories.
    
    Args:
        stories: List of story objects (containing title, description/summary, etc.)
        alignment: String indicating the alignment group (e.g., 'government', 'balanced', 'opposition')
    """
    if not stories:
        return {"bullets": []}

    articles_text = ""
    for s in stories:
        title = s.get("title", "No Title")
        summary = s.get("summary", s.get("description", ""))
        articles_text += f"- Title: {title}\n  Summary: {summary}\n\n"

    if len(stories) == 1:
        prompt = f"""You are a Nigerian media intelligence analyst.

Based on this single article from a {alignment}-aligned Nigerian outlet, analyze how they are framing this story:
- What facts do they emphasize?
- Whose voices do they quote?
- What context do they include or leave out?
- What language or framing choices reveal their editorial stance?

Write 3-4 concise bullet points. Be specific to the Nigerian political and media context. Do not be generic.

Article:
{articles_text}
"""
    else:
        prompt = f"""You are a Nigerian media intelligence analyst.

The following headlines and summaries are from {alignment}-aligned Nigerian news outlets covering the same story.

Analyze how this group is framing the story:
- What facts do they emphasize?
- Whose voices do they quote?
- What context do they include or leave out?
- What language or framing choices reveal their editorial stance?

Write 3-4 concise bullet points. Be specific to the Nigerian political and media context. Do not be generic.

Articles:
{articles_text}
"""

    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a Nigerian media intelligence analyst. Output your response as a JSON object with a single key 'bullets' containing a list of strings."},
            {"role": "user", "content": prompt}
        ],
        response_format={ "type": "json_object" },
        max_tokens=500
    )

    try:
        content = response.choices[0].message.content
        return json.loads(content)
    except Exception as e:
        print(f"Error parsing framing summary JSON: {e}")
        return {"bullets": ["Error generating framing analysis."]}

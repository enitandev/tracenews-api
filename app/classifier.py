import os
import json
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)

openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

CATEGORIES = [
    'Politics', 'Economy', 'Security', 'Judiciary', 'Entertainment', 
    'Sports', 'Technology', 'Health', 'Education', 'Religion', 
    'International', 'Niger Delta', 'General'
]

def classify_cluster(title: str, summary: str) -> dict:
    """
    Classify a cluster into one of the predefined categories using an LLM.
    Returns a dict with 'category' and 'confidence'.
    """
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": f"You are an expert Nigerian news editor. Classify the given news article into EXACTLY ONE of the following categories: {', '.join(CATEGORIES)}. Respond in JSON with a 'category' string and a 'confidence' float (0.0 to 1.0)."},
                {"role": "user", "content": f"Title: {title}\nSummary: {summary[:1000]}"}
            ],
            response_format={ "type": "json_object" },
            temperature=0.0
        )
        
        result = json.loads(response.choices[0].message.content)
        predicted_cat = result.get('category', 'General')
        confidence = result.get('confidence', 0.0)
        
        if predicted_cat not in CATEGORIES:
            predicted_cat = 'General'
            
        return {"category": predicted_cat, "confidence": confidence}
        
    except Exception as e:
        logger.error(f"LLM Classification failed: {e}")
        return {"category": "General", "confidence": 0.0}

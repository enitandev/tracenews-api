import os
import json
import logging
import openai
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

    Returns {"category", "confidence", "retry"}:
    - a valid answer: the category and the model's confidence; retry False
    - an unusable answer (category missing or not in CATEGORIES, confidence
      not a number in [0, 1]): logged at ERROR, 'General' with confidence
      0.0 so the scorer flags it for review; retry False, because asking
      the same paid model the same question every cycle would repeat the
      same answer
    - a failed call: 'General' with confidence 0.0; retry True
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
    except openai.RateLimitError as e:
        logger.error(f"LLM Classification failed due to Rate Limit/Quota: {e}")
        if "insufficient_quota" in str(e) or "credit_balance_exhausted" in str(e):
            try:
                from app.heartbeat import send_alert
                send_alert("TraceNews ALERT: OpenAI Quota Exhausted", f"Classifier hit billing failure: {e}")
            except Exception:
                logger.exception("Failed to send quota alert")
        return {"category": "General", "confidence": 0.0, "retry": True}
    except Exception:
        logger.exception("LLM Classification failed")
        return {"category": "General", "confidence": 0.0, "retry": True}

    return validate_classification(result, title)


def validate_classification(result, title: str = "") -> dict:
    """Checks a parsed model answer; never absorbs a bad value silently."""
    predicted_cat = result.get("category") if isinstance(result, dict) else None
    confidence = result.get("confidence") if isinstance(result, dict) else None

    if predicted_cat not in CATEGORIES:
        logger.error(f"Classifier returned unrecognised category {predicted_cat!r} for {title!r}; flagged for review")
        return {"category": "General", "confidence": 0.0, "retry": False}

    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0.0 <= confidence <= 1.0:
        logger.error(f"Classifier returned invalid confidence {confidence!r} for {title!r}; flagged for review")
        return {"category": predicted_cat, "confidence": 0.0, "retry": False}

    return {"category": predicted_cat, "confidence": float(confidence), "retry": False}

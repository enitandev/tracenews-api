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

KEYWORD_RULES = {
    'Politics': ['apc', 'pdp', 'lp', 'tinubu', 'buhari', 'atiku', 'obi', 'senate', 'house of reps', 'lawmakers', 'gubernatorial', 'election', 'inec', 'governor', 'presidency', 'nass'],
    'Economy': ['cbn', 'naira', 'inflation', 'gdp', 'nnpc', 'dangote', 'budget', 'fx', 'fuel price', 'subsidy', 'investors', 'stock market', 'imf', 'world bank'],
    'Security': ['boko haram', 'bandits', 'kidnap', 'dss', 'police', 'military', 'troops', 'gunmen', 'ipob', 'esn', 'herdsmen', 'insurgency', 'iswap', 'igp'],
    'Judiciary': ['supreme court', 'appeal court', 'tribunal', 'judge', 'justice', 'efcc', 'icpc', 'lawsuit', 'litigation', 'court of appeal'],
    'Entertainment': ['nollywood', 'afrobeats', 'wizkid', 'burna boy', 'davido', 'actor', 'actress', 'movie', 'album', 'concert', 'don jazzy', 'tiwa savage', 'olamide', 'bbnaija'],
    'Sports': ['super eagles', 'nff', 'premier league', 'champions league', 'afcon', 'npfl', 'osimhen', 'arsenal', 'chelsea', 'man utd', 'real madrid', 'fifa', 'football', 'basketball'],
    'Technology': ['startup', 'fintech', 'flutterwave', 'paystack', 'crypto', 'bitcoin', 'cybersecurity', 'artificial intelligence', 'nitda', 'ncc', 'broadband', 'tech'],
    'Health': ['who', 'ncdc', 'cholera', 'vaccine', 'hospitals', 'doctors strike', 'nma', 'disease'],
    'Education': ['asuu', 'jamb', 'waec', 'unilag', 'nuc', 'university', 'polytechnic', 'students protest'],
    'Religion': ['pastor', 'bishop', 'can ', 'islamic', 'muslim', 'christian', 'church', 'mosque', 'adeboye', 'oyedepo', 'sultan'],
    'International': ['biden', 'putin', 'gaza', 'israel', 'ukraine', 'russia', 'un ', 'united nations', 'ecowas', 'foreign affairs'],
    'Niger Delta': ['nddc', 'militants', 'oil spill', 'pipeline vandalism', 'tompolo', 'amnesty program', 'port harcourt refinery', 'warri']
}

def classify_cluster_hybrid(title: str, summary: str) -> str:
    """
    Classify a cluster into one of the predefined categories.
    Returns the category string.
    """
    text = f"{title} {summary}".lower()
    
    # 1. FAST PATH: Keyword Matching
    category_scores = {cat: 0 for cat in CATEGORIES}
    
    for category, keywords in KEYWORD_RULES.items():
        for kw in keywords:
            # We use strict word boundary checks to avoid partial matches like "can" in "cancel"
            # Since some keywords are multi-word, simple string ' in ' check is fine for them, 
            # but single words need spacing to be safe, or just accept the slight noise.
            # To keep it simple and fast, we just do string inclusion for now.
            if f" {kw} " in f" {text} ":
                category_scores[category] += 1
                
    # Find the top category
    top_category = 'General'
    max_score = 0
    for cat, score in category_scores.items():
        if score > max_score:
            max_score = score
            top_category = cat
            
    # If we have a definitive match (score >= 2 or it's the only one that matched)
    active_categories = [cat for cat, score in category_scores.items() if score > 0]
    
    if len(active_categories) == 1 and max_score >= 1:
        logger.debug(f"Hybrid Classifier: Keyword match -> {top_category}")
        return top_category
    elif max_score >= 2 and len([c for c in active_categories if category_scores[c] == max_score]) == 1:
        # One clear winner
        logger.debug(f"Hybrid Classifier: Keyword match -> {top_category}")
        return top_category
        
    # 2. LLM FALLBACK: Ambiguous cases
    logger.debug(f"Hybrid Classifier: Falling back to LLM for '{title}'")
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
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
        
        if predicted_cat in CATEGORIES and confidence >= 0.6:
            return predicted_cat
        return 'General'
        
    except Exception as e:
        logger.error(f"LLM Classification failed: {e}")
        return 'General'

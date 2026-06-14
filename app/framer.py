import os
import json
import logging
import traceback
from openai import OpenAI
from app.db import supabase

logger = logging.getLogger(__name__)
openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

def generate_tier_summary(stories: list, tier_label: str) -> dict:
    if not stories:
        return {"bullets": []}

    articles_text = ""
    for s in stories:
        title = s.get("title", "No Title")
        summary = s.get("summary", s.get("description", ""))
        articles_text += f"- Title: {title}\n  Summary: {summary}\n\n"

    system_message = f"You are a Nigerian news analyst. You will be given summaries from multiple Nigerian news outlets covering the same story. All outlets share the same editorial tier: {tier_label}.\n\nYour job is to write 4 bullet points that tell the reader WHAT HAPPENED according to these outlets. Each bullet must:\n- State a specific fact, detail, or development reported in the summaries\n- Be written as news reporting, not as analysis of how it was covered\n- Ground every claim in something actually present in the provided summaries\n- Note significant omissions, contradictions, or framing choices ONLY as a final observation if genuinely notable - not as the primary focus\n\nDo NOT write bullets about \"terminology choices,\" \"editorial stances,\" or \"framing patterns\" unless they are strikingly significant. Write about what happened.\n\nOutput your response as a JSON object with a single key 'bullets' containing a list of strings."

    user_message = f"Here are the article summaries from {tier_label} outlets covering this story:\n\n{articles_text}\n\nWrite 4 bullet points reporting what happened according to these outlets."

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message}
            ],
            response_format={ "type": "json_object" },
            max_tokens=600
        )
        content = response.choices[0].message.content
        return json.loads(content)
    except Exception as e:
        logger.error(f"[generate_tier_summary] generation failed for {tier_label}: {type(e).__name__}: {e}")
        logger.error(traceback.format_exc())
        return {"bullets": [], "error": str(e), "cached": False}

def generate_comparison_summary(pro_summary: list, inst_summary: list, adv_summary: list) -> dict:
    def clean_summary(summary, tier_name):
        if not summary or (len(summary) == 1 and "insufficient" in summary[0].lower()):
            return f"No {tier_name} outlets covered this story."
        return chr(10).join(summary)

    pro_text = clean_summary(pro_summary, "Pro-Establishment")
    inst_text = clean_summary(inst_summary, "Institutional")
    adv_text = clean_summary(adv_summary, "Adversarial")
    
    if "No Pro-Establishment" in pro_text and "No Institutional" in inst_text and "No Adversarial" in adv_text:
        return {"bullets": ["Insufficient data across all tiers to generate a comparison."]}

    system_message = f"You are a Nigerian media analyst specializing in editorial independence. You will be given AI-generated summaries of how three editorial tiers covered the same news story: Pro-Establishment outlets (tend toward official narratives), Institutional outlets (mainstream, balanced), and Adversarial outlets (independent, scrutiny-focused).\n\nYour job is to write a GENUINE COMPARISON of how these tiers covered the story differently. Specifically:\n- What facts or angles appear in Adversarial coverage that are ABSENT from Pro-Establishment coverage?\n- What facts or angles appear in Pro-Establishment coverage that Adversarial outlets ignored or downplayed?\n- What language or framing choices differ meaningfully between tiers?\n- Where do all tiers agree on the facts?\n\nIf a tier has insufficient coverage (flagged as such in its summary), explicitly note: \"No [Tier] outlets covered this story\" or \"Only N [Tier] outlet(s) covered this story - comparison limited.\"\n\nBe specific. Name actual facts and angles, not general observations about \"framing tendencies.\" Write 3-5 bullet points.\n\nOutput your response as a JSON object with a single key 'bullets' containing a list of strings."

    user_message = f"Here are the tier summaries for the same story:\n\nPRO-ESTABLISHMENT OUTLETS:\n{pro_text}\n\nINSTITUTIONAL OUTLETS:\n{inst_text}\n\nADVERSARIAL OUTLETS:\n{adv_text}\n\nWrite a specific comparison of how these tiers covered the story differently."

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message}
            ],
            response_format={ "type": "json_object" },
            max_tokens=600
        )
        content = response.choices[0].message.content
        return json.loads(content)
    except Exception as e:
        logger.error(f"[generate_comparison_summary] comparison generation failed: {type(e).__name__}: {e}")
        logger.error(traceback.format_exc())
        return {"bullets": [], "error": str(e), "cached": False}

def run_framing_job():
    """Scheduled job to preemptively generate AI framings for recent clusters."""
    try:
        from datetime import datetime, timezone, timedelta
        forty_eight_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        
        # Fetch 50 and limit to 20 missing cache
        res = supabase.table("clusters") \
            .select("id, representative_title, framing_cache") \
            .gte("first_seen_at", forty_eight_hours_ago) \
            .gte("outlet_count", 3) \
            .order("first_seen_at", desc=True) \
            .limit(50) \
            .execute()
        
        clusters = res.data or []
        to_process = []
        for c in clusters:
            fc = c.get("framing_cache")
            if not fc or len(fc) == 0:
                to_process.append(c)
            if len(to_process) >= 20:
                break
                
        if not to_process:
            logger.info("[framing] No new clusters need framing.")
            return

        behav_res = supabase.table("outlet_behavioral_scores").select("*").execute()
        behavioral_map = {b["outlet_slug"]: b for b in (behav_res.data or [])}

        for c in to_process:
            try:
                generate_single_cluster_framing(c["id"], c["representative_title"], behavioral_map)
            except Exception as e:
                logger.error(f"[run_framing_job] framing regen failed for cluster {c['id']}: {type(e).__name__}: {e}")
                logger.error(traceback.format_exc())
                continue
            
    except Exception as e:
        logger.error(f"[run_framing_job] scheduled job initialization failed: {type(e).__name__}: {e}")
        logger.error(traceback.format_exc())

def generate_single_cluster_framing(cluster_id: str, title: str = None, behavioral_map: dict = None) -> dict:
    if not behavioral_map:
        behav_res = supabase.table("outlet_behavioral_scores").select("*").execute()
        behavioral_map = {b["outlet_slug"]: b for b in (behav_res.data or [])}
        
    stories_res = supabase.table("stories").select(
        "title, summary, outlets(slug, government_alignment, independence_score, credibility_tier, logo_url)"
    ).eq("cluster_id", cluster_id).execute()
    
    stories = stories_res.data or []
    groups = {"pro_establishment": [], "institutional": [], "adversarial": []}
    
    for s in stories:
        if s.get("outlets"):
            out = s["outlets"]
            slug = out.get("slug")
            behav = behavioral_map.get(slug) if slug else None
            tier = "unscored"
            if out.get("credibility_tier") == "blog":
                tier = "blog"
            elif behav and behav.get("independence_score") is not None:
                score = behav.get("independence_score")
                if behav.get("brown_envelope_suspected") or score < 35:
                    tier = "pro_establishment"
                elif score < 60:
                    tier = "institutional"
                else:
                    tier = "adversarial"
            else:
                g_align = out.get("government_alignment")
                if g_align == "pro_government": tier = "pro_establishment"
                elif g_align == "opposition": tier = "adversarial"
                elif g_align == "neutral": tier = "institutional"
            
            if tier in groups:
                groups[tier].append(s)

    pro = generate_tier_summary(groups["pro_establishment"], "Pro-Establishment").get("bullets", [])
    inst = generate_tier_summary(groups["institutional"], "Institutional").get("bullets", [])
    adv = generate_tier_summary(groups["adversarial"], "Adversarial").get("bullets", [])
    
    comp = generate_comparison_summary(pro, inst, adv).get("bullets", [])
    
    new_cache = {
        "pro_establishment": pro,
        "institutional": inst,
        "adversarial": adv,
        "comparison": comp
    }
    
    supabase.table("clusters").update({"framing_cache": new_cache}).eq("id", cluster_id).execute()
    logger.info(f"[framing] Cached 4 framings for cluster {cluster_id}")
    return new_cache

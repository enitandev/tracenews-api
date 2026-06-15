import re

# 1. Update app/main.py
with open("app/main.py", "r") as f:
    main_content = f.read()

# For /clusters/by-slug/{slug}
old_main_slug = """            if behav and behav.get("independence_score") is not None:
                if behav.get("brown_envelope_suspected"):
                    s["outlet_coverage_tier"] = "captured"
                else:
                    score = behav.get("independence_score")
                    if score >= 70: s["outlet_coverage_tier"] = "independent"
                    elif score >= 35: s["outlet_coverage_tier"] = "deferential"
                    else: s["outlet_coverage_tier"] = "captured"
            else:
                g_align = out.get("government_alignment")
                if g_align == "pro_government":
                    s["outlet_coverage_tier"] = "captured"
                elif g_align == "opposition":
                    s["outlet_coverage_tier"] = "independent"
                elif g_align == "neutral":
                    s["outlet_coverage_tier"] = "deferential"
                else:
                    s["outlet_coverage_tier"] = "unscored" """

new_main_slug = """            if behav and behav.get("independence_score") is not None:
                score = behav.get("independence_score")
                if behav.get("brown_envelope_suspected") or score < 35:
                    s["outlet_coverage_tier"] = "pro_establishment"
                elif score < 60:
                    s["outlet_coverage_tier"] = "institutional"
                else:
                    s["outlet_coverage_tier"] = "adversarial"
            else:
                g_align = out.get("government_alignment")
                if g_align == "pro_government":
                    s["outlet_coverage_tier"] = "pro_establishment"
                elif g_align == "opposition":
                    s["outlet_coverage_tier"] = "adversarial"
                elif g_align == "neutral":
                    s["outlet_coverage_tier"] = "institutional"
                else:
                    s["outlet_coverage_tier"] = "unscored" """

# For /clusters/{id}/deep-dive and /clusters/{id}/framing
old_main_tier = """            if behav and behav.get("independence_score") is not None:
                if behav.get("brown_envelope_suspected"):
                    tier = "captured"
                else:
                    score = behav.get("independence_score")
                    if score >= 70: tier = "independent"
                    elif score >= 35: tier = "deferential"
                    else: tier = "captured"
            else:
                g_align = out.get("government_alignment")
                if g_align == "pro_government": tier = "captured"
                elif g_align == "opposition": tier = "independent"
                elif g_align == "neutral": tier = "deferential" """

new_main_tier = """            if behav and behav.get("independence_score") is not None:
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
                elif g_align == "neutral": tier = "institutional" """

main_content = main_content.replace(old_main_slug, new_main_slug)
main_content = main_content.replace(old_main_tier, new_main_tier)
# Also fix the mapping for framing
main_content = main_content.replace('"government": "captured",\n        "balanced": "deferential",\n        "opposition": "independent"', '"government": "pro_establishment",\n        "balanced": "institutional",\n        "opposition": "adversarial"')

with open("app/main.py", "w") as f:
    f.write(main_content)

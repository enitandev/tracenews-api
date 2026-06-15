import re

with open("app/scorer.py", "r") as f:
    content = f.read()

# 1. Add safe_execute helper
safe_execute_code = """
def safe_execute(query_builder, retries=3, delay=3):
    for attempt in range(retries):
        try:
            return query_builder.execute()
        except (httpx.HTTPError, httpx.TransportError) as e:
            logger.warning(f"Network error (attempt {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                raise
"""

if "def safe_execute" not in content:
    content = content.replace("logger = logging.getLogger(__name__)", "logger = logging.getLogger(__name__)\n" + safe_execute_code)

# 2. Re-write the loop logic to remove `for attempt in range(3):` and use generic `try/except Exception`

# We need to un-indent the block that was inside `for attempt... try...` by 8 spaces.
# The block starts right after `        for attempt in range(3):\n            try:\n`
# and ends at `            except (httpx.ReadTimeout, httpx.ConnectTimeout) as e:`

parts = content.split("        for attempt in range(3):\n            try:\n")

if len(parts) == 2:
    top = parts[0]
    rest = parts[1]
    
    body_parts = rest.split("            except (httpx.ReadTimeout, httpx.ConnectTimeout) as e:")
    body = body_parts[0]
    bottom_parts = body_parts[1].split("print(f\"Backfill complete: {total} clusters updated\")")
    bottom = "    print(f\"Backfill complete: {total} clusters updated\")" + bottom_parts[1]
    
    # We want to replace the `for attempt... try...` with just `try:`
    # And unindent the body by 4 spaces (since it was inside `try:`) wait, it was:
    #         for attempt ...
    #             try:
    #                 body
    # We want:
    #         try:
    #             body
    # So we un-indent the body by 4 spaces.
    
    new_body_lines = []
    new_body_lines.append("        try:")
    for line in body.split("\n"):
        if line.startswith("    "):
            new_body_lines.append(line[4:])
        else:
            new_body_lines.append(line)
            
    # Add the broad exception catcher
    new_body_lines.append("        except Exception as e:")
    new_body_lines.append("            logger.error(f\"Skipping cluster {cluster['id']} due to error: {e}\")")
    new_body_lines.append("            continue\n")
    
    content = top + "\n".join(new_body_lines) + bottom

# 3. Replace all `.execute()` with `safe_execute()`
# We'll use regex to find supabase.table(...)...execute()
# Actually, the user says "Change: behav_res = supabase.table(...).execute() to behav_res = safe_execute(supabase.table(...))"
# We need to be careful with `.execute()`

# 1. query.execute()
content = content.replace("query.execute()", "safe_execute(query)")
# 2. supabase.table("stories").select("*").eq("cluster_id", cluster["id"]).execute()
content = content.replace(".eq(\"cluster_id\", cluster[\"id\"]).execute()", ".eq(\"cluster_id\", cluster[\"id\"])")
content = content.replace("supabase.table(\"stories\").select(\"*\").eq(\"cluster_id\", cluster[\"id\"])", "safe_execute(supabase.table(\"stories\").select(\"*\").eq(\"cluster_id\", cluster[\"id\"]))")
# 3. supabase.table("clusters").update({"category": category}).eq("id", cluster["id"]).execute()
content = content.replace(".update({\"category\": category}).eq(\"id\", cluster[\"id\"]).execute()", ".update({\"category\": category}).eq(\"id\", cluster[\"id\"])")
content = content.replace("supabase.table(\"clusters\").update({\"category\": category}).eq(\"id\", cluster[\"id\"])", "safe_execute(supabase.table(\"clusters\").update({\"category\": category}).eq(\"id\", cluster[\"id\"]))")
# 4. supabase.table("outlets").select("*").in_("id", outlet_ids).execute()
content = content.replace(".in_(\"id\", outlet_ids).execute()", ".in_(\"id\", outlet_ids)")
content = content.replace("supabase.table(\"outlets\").select(\"*\").in_(\"id\", outlet_ids)", "safe_execute(supabase.table(\"outlets\").select(\"*\").in_(\"id\", outlet_ids))")
# 5. supabase.table("outlet_behavioral_scores").select("*").in_("outlet_slug", outlet_slugs).execute()
content = content.replace(".in_(\"outlet_slug\", outlet_slugs).execute()", ".in_(\"outlet_slug\", outlet_slugs)")
content = content.replace("supabase.table(\"outlet_behavioral_scores\").select(\"*\").in_(\"outlet_slug\", outlet_slugs)", "safe_execute(supabase.table(\"outlet_behavioral_scores\").select(\"*\").in_(\"outlet_slug\", outlet_slugs))")
# 6. supabase.table("clusters").update({...}).eq("id", cluster["id"]).execute()
content = re.sub(
    r'supabase\.table\("clusters"\)\.update\(\{\s*"coverage_stats": coverage_stats,\s*"monitoring_flags": monitoring_flags\s*\}\)\.eq\("id", cluster\["id"\]\)\.execute\(\)',
    r'safe_execute(supabase.table("clusters").update({"coverage_stats": coverage_stats, "monitoring_flags": monitoring_flags}).eq("id", cluster["id"]))',
    content
)

with open("app/scorer.py", "w") as f:
    f.write(content)


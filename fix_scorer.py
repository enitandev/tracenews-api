import re

with open("app/scorer.py", "r") as f:
    content = f.read()

# 1. Add imports
if "import httpx" not in content:
    content = content.replace("import os", "import os\nimport time\nimport httpx")

# 2. Add resume logic to run_scoring
if ".or_(\"coverage_stats.is.null,coverage_stats.eq.{}\")" not in content:
    content = content.replace(
        """    query = supabase.table("clusters").select("id, outlet_count, category, representative_title")
    if not all_time:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        query = query.gte("first_seen_at", cutoff)""",
        """    query = supabase.table("clusters").select("id, outlet_count, category, representative_title")
    if not all_time:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        query = query.gte("first_seen_at", cutoff)
    else:
        query = query.or_("coverage_stats.is.null,coverage_stats.eq.{}")"""
    )

# 3. Indent the cluster loop and wrap in try/except
loop_start_str = """        # Fetch all stories for this cluster
        stories_res = supabase.table("stories").select("*").eq("cluster_id", cluster["id"]).execute()"""

if "for attempt in range(3):" not in content:
    # Find the block inside `for cluster in clusters:` after `print(f"Backfill progress: ...")`
    # We want to indent everything from `stories_res = ...` to `scored_count += 1`
    
    parts = content.split("""        if processed % 100 == 0:
            print(f"Backfill progress: {processed}/{total} clusters")""")
            
    if len(parts) == 2:
        top = parts[0] + """        if processed % 100 == 0:
            print(f"Backfill progress: {processed}/{total} clusters")"""
            
        rest = parts[1]
        
        # find where the loop ends. it ends right before `print(f"Backfill complete: {total} clusters updated")`
        loop_end_str = """    print(f"Backfill complete: {total} clusters updated")"""
        rest_parts = rest.split(loop_end_str)
        
        if len(rest_parts) == 2:
            loop_body = rest_parts[0]
            bottom = loop_end_str + rest_parts[1]
            
            # The loop body starts with a newline
            lines = loop_body.split('\n')
            indented_lines = []
            
            indented_lines.append("        for attempt in range(3):")
            indented_lines.append("            try:")
            
            for line in lines:
                if line.strip() == "":
                    indented_lines.append("")
                else:
                    # check if the line is scored_count += 1
                    if line == "        scored_count += 1":
                        indented_lines.append("                scored_count += 1")
                        indented_lines.append("                break")
                    # check if it's continue
                    elif line == "            continue":
                        indented_lines.append("                break  # Break retry loop, effectively continuing to next cluster")
                    else:
                        indented_lines.append("    " + line)
                        
            indented_lines.append("            except (httpx.ReadTimeout, httpx.ConnectTimeout) as e:")
            indented_lines.append("                if attempt < 2:")
            indented_lines.append("                    logger.warning(f\"Timeout on cluster {cluster['id']}, retrying in 5s...\")")
            indented_lines.append("                    time.sleep(5)")
            indented_lines.append("                else:")
            indented_lines.append("                    logger.error(f\"Skipping cluster {cluster['id']} after 3 timeouts.\")")
            indented_lines.append("")
            
            new_content = top + "\n" + "\n".join(indented_lines) + bottom
            content = new_content

with open("app/scorer.py", "w") as f:
    f.write(content)


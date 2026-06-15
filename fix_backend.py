with open("app/main.py", "r") as f:
    content = f.read()

old_block = """    # Compute covered_most_by via RPC
    outlets_map, behavioral_map = get_outlets_cache()
    covered_most_by = []
    
    try:
        rpc_res = supabase.rpc("get_category_top_outlets", {"p_category": category, "p_days": 30}).execute()
        top_outlets_data = rpc_res.data or []
        for row in top_outlets_data:
            slug = row["outlet_slug"]
            out = outlets_map.get(slug)"""

new_block = """    # Compute covered_most_by via RPC
    outlets_map, behavioral_map = get_outlets_cache()
    outlets_by_slug = {
        o.get('slug'): o 
        for o in outlets_map.values() 
        if o.get('slug')
    }
    
    covered_most_by = []
    
    try:
        rpc_res = supabase.rpc("get_category_top_outlets", {"p_category": category, "p_days": 30}).execute()
        top_outlets_data = rpc_res.data or []
        for row in top_outlets_data:
            slug = row["outlet_slug"]
            out = outlets_by_slug.get(slug)"""

content = content.replace(old_block, new_block)

with open("app/main.py", "w") as f:
    f.write(content)


with open("app/routers/reader.py", "r") as f:
    code = f.read()

old_code = """        # Follows (no mock data)
        try:
            follows_res = supabase.table("reader_follows").select("*", count="exact").eq("user_id", user_id).execute()
            follow_count = follows_res.count if follows_res.count is not None else 0
        except Exception:
            follow_count = 0"""

new_code = """        # Follows (no mock data)
        # Table reader_follows does not exist yet (Phase 2)
        follow_count = 0"""

if old_code in code:
    code = code.replace(old_code, new_code)
    with open("app/routers/reader.py", "w") as f:
        f.write(code)
    print("Patched reader.py")
else:
    print("Old code not found in reader.py!")

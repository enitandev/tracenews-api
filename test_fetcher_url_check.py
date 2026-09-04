from app.db import supabase

# Generate 200 long URLs
batch = [f"https://www.example.com/very/long/url/path/that/takes/up/space/{i}?foo=bar&baz=qux&other=param" for i in range(200)]

try:
    res = supabase.table("stories").select("url").in_("url", batch).execute()
    print("Success")
except Exception as e:
    print("Failed:", e)

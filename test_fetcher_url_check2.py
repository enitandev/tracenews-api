from app.db import supabase

# Generate 50 long URLs
batch = [f"https://www.example.com/very/long/url/path/that/takes/up/space/{i}?foo=bar&baz=qux&other=param" for i in range(50)]

try:
    res = supabase.table("stories").select("url").in_("url", batch).execute()
    print("Success 50")
except Exception as e:
    print("Failed 50:", e)
    
# Generate 25 long URLs
batch25 = [f"https://www.example.com/very/long/url/path/that/takes/up/space/{i}?foo=bar&baz=qux&other=param" for i in range(25)]

try:
    res = supabase.table("stories").select("url").in_("url", batch25).execute()
    print("Success 25")
except Exception as e:
    print("Failed 25:", e)

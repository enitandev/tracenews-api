from app.db import supabase
try:
    res = supabase.table("reader_analytics_consent").select("at").limit(1).execute()
    print("Consent at Success")
except Exception as e:
    print("Consent at Error:", e)

try:
    res = supabase.table("reader_analytics_consent").select("created_at").limit(1).execute()
    print("Consent created_at Success")
except Exception as e:
    print("Consent created_at Error:", e)

try:
    res = supabase.table("reader_follows").select("*").limit(1).execute()
    print("Follows Success")
except Exception as e:
    print("Follows Error:", e)


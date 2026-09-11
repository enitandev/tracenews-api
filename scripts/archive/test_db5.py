from app.db import supabase
try:
    res = supabase.table("reader_analytics_consent").select("user_id, granted, copy_version, shown_strings, method, at").limit(1).execute()
    print("Consent Insert Columns Success")
except Exception as e:
    print("Consent Insert Error:", e)


import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()
supabase = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])

from datetime import datetime, timezone, timedelta

now = datetime.now(timezone.utc)
thirty_days_ago = now - timedelta(days=30)
thirty_days_str = thirty_days_ago.isoformat()

res = supabase.table('clusters').select('id').eq('category', 'Politics').gte('first_seen_at', thirty_days_str).execute()
print("Clusters in last 30 days:", len(res.data))

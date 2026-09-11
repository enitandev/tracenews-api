import os
import requests
import json

url = 'https://yqqysehsnwicppejgfky.supabase.co/rest/v1/'
key = os.environ.get('SUPABASE_SERVICE_KEY', '')

print(f"Service key exists: {bool(key)}")
# We can't actually run DDL via REST API. Let's just create a test record in the stories table to verify connectivity if we wanted to, but the user must run the DDL manually in the Supabase Dashboard.

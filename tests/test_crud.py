from app.db import supabase
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
headers = {'Authorization': 'Bearer dummy_token_for_import_test'}

# Get a valid cluster_id
c_res = supabase.table('clusters').select('id').order('created_at', desc=True).limit(1).execute()
cluster_id = c_res.data[0]['id']

print('\n3. Create Override')
override_payload = {
    'cluster_id': cluster_id,
    'original_verdict': 'mixed',
    'reason': 'test override',
    'actor': 'test agent'
}
resp = client.post('/api/admin/monitoring-spirit/overrides', json=override_payload, headers=headers)
print('Create status:', resp.status_code)
override_data = resp.json()
override_id = override_data['id']
print('Created override:', override_id)

print('\n4. Check Audit Log for Create')
audit_res = supabase.table('admin_audit_log').select('*').eq('target_id', override_id).execute()
print('Audit log entries for create:', len(audit_res.data))
print('First entry action:', audit_res.data[0]['action'] if audit_res.data else None)

print('\n5. Reinstate Override')
reinstate_payload = {'actor': 'test agent 2'}
resp = client.post(f'/api/admin/monitoring-spirit/overrides/{override_id}/reinstate', json=reinstate_payload, headers=headers)
print('Reinstate status:', resp.status_code)

print('\n6. Check Audit Log for Reinstate')
audit_res2 = supabase.table('admin_audit_log').select('*').eq('target_id', override_id).execute()
print('Total audit log entries:', len(audit_res2.data))

print('\n7. Cleanup')
supabase.table('admin_audit_log').delete().eq('target_id', override_id).execute()
supabase.table('verdict_overrides').delete().eq('id', override_id).execute()
print('Cleanup done.')

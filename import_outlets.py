import json
import re
from app.db import supabase

def clean_year(year_str):
    if not year_str:
        return None
    match = re.search(r'\d{4}', str(year_str))
    if match:
        return int(match.group())
    return None

def clean_array(val_str):
    if not val_str:
        return []
    if isinstance(val_str, list):
        return val_str
    return [v.strip() for v in val_str.split('/') if v.strip()]

def clean_languages(val_str):
    if not val_str:
        return []
    if isinstance(val_str, list):
        return val_str
    return [v.strip() for v in val_str.split(',') if v.strip()]

def run_import():
    print("Loading JSON data...")
    with open('outlets.json', 'r', encoding='utf-8') as f:
        outlets_data = json.load(f)

    print(f"Found {len(outlets_data)} outlets. Starting import...")

    # Fetch current max ID to manually increment and avoid sequence clashes
    max_id_resp = supabase.table('outlets').select('id').order('id', desc=True).limit(1).execute()
    next_id = (max_id_resp.data[0]['id'] + 1) if max_id_resp.data else 1

    successful = 0
    errors = 0

    for index, outlet in enumerate(outlets_data):
        try:
            if 'founded_year' in outlet:
                outlet['founded_year'] = clean_year(outlet['founded_year'])
            
            if 'languages' in outlet:
                outlet['languages'] = clean_languages(outlet['languages'])
                
            if 'medium' in outlet:
                outlet['medium'] = clean_array(outlet['medium'])
                
            response = supabase.table('outlets').select('id, slug').eq('slug', outlet['slug']).execute()
            
            if response.data and len(response.data) > 0:
                outlet_id = response.data[0]['id']
                supabase.table('outlets').update(outlet).eq('id', outlet_id).execute()
            else:
                # Manually assign ID to bypass broken postgres sequence
                outlet['id'] = next_id
                next_id += 1
                supabase.table('outlets').insert(outlet).execute()
            
            successful += 1
            if successful % 20 == 0:
                print(f"Imported {successful} outlets...")
                
        except Exception as e:
            print(f"Error importing {outlet.get('name', 'Unknown')}: {str(e)}")
            errors += 1

    print(f"\nImport Complete!")
    print(f"Successfully processed: {successful}")
    if errors > 0:
        print(f"Failed: {errors}")

if __name__ == "__main__":
    run_import()

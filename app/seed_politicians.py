import csv
import logging
from app.db import supabase

logger = logging.getLogger(__name__)

def seed_politicians():
    rows = []
    with open(
      '/tmp/politicians_final.csv', 
      'r'
    ) as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Convert aliases from 
            # comma-separated string 
            # to array
            aliases_str = row.get(
              'aliases', '')
            if aliases_str:
                aliases = [
                  a.strip() 
                  for a in 
                  aliases_str.split(',')
                  if a.strip()
                ]
            else:
                aliases = []
            
            rows.append({
                'full_name': 
                  row['full_name'].strip(),
                'common_name': 
                  row['common_name'].strip(),
                'aliases': aliases,
                'party': 
                  row.get('party','')
                  .strip() or None,
                'state': 
                  row.get('state','')
                  .strip() or None,
                'geopolitical_region': 
                  row.get(
                    'geopolitical_region',
                    '').strip() or None,
                'category': 
                  row.get('category','')
                  .strip() or None,
                'current_position': 
                  row.get(
                    'current_position',
                    '').strip() or None,
                'positions_held': 
                  row.get(
                    'positions_held',
                    '').strip() or None,
                'notes': 
                  row.get('notes','')
                  .strip() or None,
                'active': True
            })
    
    print(f"Prepared {len(rows)} rows")
    
    # Insert in batches of 100
    batch_size = 100
    total_inserted = 0
    
    for i in range(
      0, len(rows), batch_size
    ):
        batch = rows[i:i+batch_size]
        result = supabase.table(
          'politicians'
        ).insert(batch).execute()
        total_inserted += len(batch)
        print(
          f"Inserted {total_inserted}"
          f"/{len(rows)}"
        )
    
    print(
      f"Done. {total_inserted} "
      f"politicians imported."
    )
    return total_inserted

if __name__ == '__main__':
    seed_politicians()

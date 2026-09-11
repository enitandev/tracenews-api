from app.db import supabase

def run_task3():
    # Update Business category -> excluded
    res_bus = supabase.table('politicians').update({
        'publication_status': 'excluded',
        'publication_status_reason': 'Category: Business — private figure, no public office held. Not covered by June 27 2026 counsel sign-off. Excluded July 3 2026.'
    }).eq('category', 'Business').eq('active', True).execute()
    print(f"Updated Business: {len(res_bus.data)} rows")

    # Update Traditional, CivilSociety, and Simon Bagaiya Shaibu -> pending_review
    # Supabase postgrest doesn't easily support complex OR statements without specialized string syntax in python,
    # so we'll do them in two separate calls for simplicity and reliability.
    
    # 1. Update categories
    res_cat = supabase.table('politicians').update({
        'publication_status': 'pending_review',
        'publication_status_reason': 'Category requires per-subject counsel review before publication. Not covered by June 27 2026 sign-off. Held July 3 2026.'
    }).in_('category', ['Traditional', 'CivilSociety']).eq('active', True).execute()
    print(f"Updated Traditional/CivilSociety: {len(res_cat.data)} rows")

    # 2. Update specific slug
    res_slug = supabase.table('politicians').update({
        'publication_status': 'pending_review',
        'publication_status_reason': 'Category requires per-subject counsel review before publication. Not covered by June 27 2026 sign-off. Held July 3 2026.'
    }).eq('slug', 'simon-bagaiya-shaibu').eq('active', True).execute()
    print(f"Updated simon-bagaiya-shaibu: {len(res_slug.data)} rows")

    # Verify results using python since we can't do arbitrary GROUP BY easily via PostgREST
    # Actually we can just fetch all non-published
    verify = supabase.table('politicians').select('publication_status, category').neq('publication_status', 'published').execute()
    
    counts = {}
    for row in verify.data:
        key = (row['publication_status'], row['category'])
        counts[key] = counts.get(key, 0) + 1
        
    print("\nVerification Results:")
    for (status, cat), count in sorted(counts.items()):
        print(f"{status}: {cat} ({count})")

if __name__ == "__main__":
    run_task3()

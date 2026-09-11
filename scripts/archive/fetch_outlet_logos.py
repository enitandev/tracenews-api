import os
import sys
import logging
import requests
from urllib.parse import urlparse
from app.db import supabase

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

def extract_domain(url):
    if not url:
        return None
    if not url.startswith('http://') and not url.startswith('https://'):
        url = 'http://' + url
    parsed = urlparse(url)
    domain = parsed.netloc
    if domain.startswith('www.'):
        domain = domain[4:]
    return domain

def check_favicon(domain):
    url = f"https://www.google.com/s2/favicons?domain={domain}&sz=128"
    try:
        # requests follows redirects by default
        r = requests.get(url, timeout=5)
        # Google returns 404 for generic fallback images, 200 for actual found favicons
        if r.status_code == 200:
            return 'favicon', url
    except requests.RequestException:
        pass
    return 'none', None

def run():
    logger.info("Fetching outlets...")
    res = supabase.table("outlets").select("id, name, slug, website").execute()
    outlets = res.data
    
    if not outlets:
        logger.info("No outlets found.")
        return

    logger.info(f"Found {len(outlets)} outlets. Checking logos via Google Favicon API...")
    
    stats = {
        'favicon': [],
        'none': []
    }
    
    for outlet in outlets:
        domain = extract_domain(outlet.get('website'))
        if not domain:
            stats['none'].append(outlet)
            continue
            
        # Try Google Favicon
        source, logo_url = check_favicon(domain)
        stats[source].append(outlet)
        
        # Update database only if good
        if source == 'favicon':
            try:
                supabase.table("outlets").update({
                    "logo_url": logo_url,
                    "logo_source": source
                }).eq("id", outlet["id"]).execute()
                print(f"[favicon] Updated {outlet['name']}")
            except Exception as e:
                print(f"Error updating {outlet['name']}: {e}")
        else:
            print(f"[{source}] Skipped writing to DB for {outlet['name']}")

    # Output Summary Report
    print("\n" + "="*40)
    print("LOGO FETCH SUMMARY REPORT")
    print("="*40)
    print(f"- {len(stats['favicon'])} outlets: favicon (successful)")
    print(f"- {len(stats['none'])} outlets: none (REVIEW/NO LOGO)")
            
    if stats['none']:
        print("\nREVIEW: none list")
        for o in stats['none']:
            print(f"  - {o['name']} ({o['slug']}) - {o.get('website', 'No URL')}")

if __name__ == "__main__":
    run()

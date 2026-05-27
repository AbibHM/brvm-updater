import os, json, urllib.request

SB_URL = os.environ['SUPABASE_URL'].rstrip('/')
SB_KEY = os.environ['SUPABASE_KEY']
HEADERS = {'apikey': SB_KEY, 'Authorization': f'Bearer {SB_KEY}', 'Content-Type': 'application/json', 'Prefer': 'resolution=merge-duplicates'}

# 4 tickers manquants à upsert dans brvm_fundamentals
rows = [
    {'ticker': 'CROWN', 'name': 'Crown Siem CI',       'sector': 'Industrie',    'country': 'Côte d\'Ivoire'},
    {'ticker': 'MOVIS', 'name': 'Movis CI',             'sector': 'Transport',    'country': 'Côte d\'Ivoire'},
    {'ticker': 'SVOC',  'name': 'Movis CI (SVOC)',      'sector': 'Transport',    'country': 'Côte d\'Ivoire'},
    {'ticker': 'TTRC',  'name': 'Tractafric Motors CI', 'sector': 'Distribution', 'country': 'Côte d\'Ivoire'},
]

payload = json.dumps(rows).encode()
req = urllib.request.Request(
    f'{SB_URL}/rest/v1/brvm_fundamentals',
    data=payload, method='POST',
    headers=HEADERS
)
with urllib.request.urlopen(req) as r:
    print(f'Status: {r.status} - {len(rows)} tickers upsertés')
    print(r.read().decode()[:200])

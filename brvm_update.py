#!/usr/bin/env python3
"""
BRVM Daily Updater — version corrigée
Scrape brvm.org → Supabase (table brvm_prices + brvm_meta)

Corrections vs version précédente :
- Utilise SUPABASE_KEY depuis les secrets GitHub (service_role obligatoire avec RLS)
- Plus de clé hardcodée dans le code
- DATE_OVERRIDE correctement lu depuis l'env du workflow
- brvm_meta : une seule ligne globale (pas par ticker)
- Cron aligné sur 16h30 GMT (fin séance BRVM)
"""

import os
import re
import sys
import requests
import urllib3
from datetime import datetime, date, timezone

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─── Configuration ────────────────────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")  # doit être la clé service_role

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ SUPABASE_URL et SUPABASE_KEY doivent être définis (secrets GitHub)")
    sys.exit(1)

HEADERS_SB = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "resolution=merge-duplicates",
}

BRVM_URL   = "https://www.brvm.org/fr/cours-actions/0"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"

_date_override = os.environ.get("DATE_OVERRIDE", "").strip()
try:
    TODAY = datetime.strptime(_date_override, "%Y-%m-%d").date().isoformat() if _date_override else date.today().isoformat()
except ValueError:
    TODAY = date.today().isoformat()

TICKERS_KNOWN = {
    "ABJC","BICB","BICC","BNBC","BOAB","BOABF","BOAC","BOAM","BOAN","BOAS",
    "CABC","CBIBF","CFAC","CIEC","ECOC","ETIT","FTSC","LNBB","NEIC","NSBC",
    "NTLC","ONTBF","ORAC","ORGT","PALC","PRSC","SAFC","SCRC","SDCC","SDSC",
    "SEMC","SGBC","SHEC","SIBC","SICC","SIVC","SLBC","SMBC","SNTS","SOGC",
    "SPHC","STAC","STBC","SVOC","TTLC","TTLS","UNLC","UNXC",
}

def clean(s):
    return re.sub(r"[\u00a0\u202f\s]+", "", s.strip())

def to_float(s):
    try: return float(clean(s).replace(",", "."))
    except: return None

def to_int(s):
    try: return int(float(clean(s).replace(",", ".")))
    except: return None

def today_already_in_supabase():
    url = f"{SUPABASE_URL}/rest/v1/brvm_prices?date=eq.{TODAY}&limit=1&select=ticker"
    try:
        resp = requests.get(url, headers=HEADERS_SB, timeout=15)
        da

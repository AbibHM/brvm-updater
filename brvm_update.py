#!/usr/bin/env python3
import os
import re
import sys
import requests
import urllib3
from datetime import datetime, date, timezone

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERREUR: SUPABASE_URL et SUPABASE_KEY requis")
    sys.exit(1)

HEADERS_SB = {
    "apikey": SUPABASE_KEY,
    "Authorization": "Bearer " + SUPABASE_KEY,
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates",
}

BRVM_URL = "https://www.brvm.org/fr/cours-actions/0"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"

_date_override = os.environ.get("DATE_OVERRIDE", "").strip()
if _date_override:
    try:
        TODAY = datetime.strptime(_date_override, "%Y-%m-%d").date().isoformat()
    except ValueError:
        TODAY = date.today().isoformat()
else:
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
    try:
        return float(clean(s).replace(",", "."))
    except Exception:
        return None

def to_int(s):
    try:
        return int(float(clean(s).replace(",", ".")))
    except Exception:
        return None

def today_already_in_supabase():
    url = SUPABASE_URL + "/rest/v1/brvm_prices?date=eq." + TODAY + "&limit=1&select=ticker"
    try:
        resp = requests.get(url, headers=HEADERS_SB, timeout=15)
        data = resp.json()
        return isinstance(data, list) and len(data) > 0
    except Exception as e:
        print("Erreur verification doublon: " + str(e))
        return False

def scrape_brvm():
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "fr-FR,fr;q=0.9"}
    try:
        resp = requests.get(BRVM_URL, headers=headers, timeout=30, verify=False)
        resp.raise_for_status()
    except Exception as e:
        print("Erreur fetch brvm.org: " + str(e))
        return []

    rows = []
    tr_pattern  = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
    td_pattern  = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL | re.IGNORECASE)
    tag_pattern = re.compile(r"<[^>]+>")

    for tr_match in tr_pattern.finditer(resp.text):
        tr = tr_match.group(1)
        ticker_m = re.search(r"/fr/cours/([A-Z]{3,6})", tr, re.IGNORECASE)
        if not ticker_m:
            continue
        ticker = ticker_m.group(1).upper()
        if ticker not in TICKERS_KNOWN:
            continue

        tds = [clean(tag_pattern.sub("", td.group(1))) for td in td_pattern.finditer(tr)]
        tds = [t for t in tds if t]
        if len(tds) < 2:
            continue

        numerics = [v for t in tds if (v := to_float(t)) is not None and v > 0]
        if not numerics:
            continue

        close = numerics[0]
        open_ = numerics[2] if len(numerics) > 2 else close
        high  = numerics[3] if len(numerics) > 3 else close
        low   = numerics[4] if len(numerics) > 4 else close

        volume = 0
        for t in reversed(tds):
            v = to_int(t)
            if v is not None and v >= 0:
                volume = v
                break

        rows.append({
            "ticker": ticker,
            "date": TODAY,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        })

    return rows

def upsert_prices(rows):
    if not rows:
        return 0
    url = SUPABASE_URL + "/rest/v1/brvm_prices"
    inserted = 0
    for i in range(0, len(rows), 50):
        batch = rows[i:i+50]
        resp = requests.post(url, headers=HEADERS_SB, json=batch, timeout=30)
        if resp.status_code in (200, 201):
            inserted += len(batch)
        else:
            print("Supabase error " + str(resp.status_code) + ": " + resp.text[:300])
    return inserted

def update_meta(tickers_count, source="brvm.org"):
    url = SUPABASE_URL + "/rest/v1/brvm_meta"
    payload = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "tickers_count": tickers_count,
        "notes": "Seance du " + TODAY,
    }
    resp = requests.post(url, headers=HEADERS_SB, json=payload, timeout=15)
    if resp.status_code in (200, 201):
        print("brvm_meta mis a jour - " + str(tickers_count) + " tickers")
    else:
        print("brvm_meta erreur " + str(resp.status_code) + ": " + resp.text[:200])

def main():
    print("BRVM Daily Updater - " + TODAY)
    print("=" * 50)

    if today_already_in_supabase():
        print("Donnees du " + TODAY + " deja dans Supabase - rien a faire.")
        sys.exit(0)

    print("Scraping brvm.org...")
    rows = scrape_brvm()
    print(str(len(rows)) + " tickers recuperes")

    if not rows:
        print("Aucune donnee - cours pas encore publies.")
        sys.exit(0)

    print("Envoi vers Supabase...")
    inserted = upsert_prices(rows)
    print(str(inserted) + "/" + str(len(rows)) + " lignes upsertees")

    update_meta(tickers_count=inserted)
    print("Termine: " + datetime.now().strftime("%H:%M:%S UTC"))
    sys.exit(0 if inserted > 0 else 1)

if __name__ == "__main__":
    main()

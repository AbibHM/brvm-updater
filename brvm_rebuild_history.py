#!/usr/bin/env python3
"""
BRVM Historical Rebuild
=======================
Reconstruit brvm_prices depuis les BOC PDF officiels BRVM
pour la periode juin 2023 -> aujourd'hui.

Usage:
    python brvm_rebuild_history.py
    python brvm_rebuild_history.py --from 2024-01-01 --to 2024-12-31
    python brvm_rebuild_history.py --dry-run
    python brvm_rebuild_history.py --skip-existing
"""

import os, re, io, sys, time, argparse, requests, urllib3
from datetime import date, timedelta, datetime

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

TICKERS_KNOWN = {
    "ABJC","BICB","BICC","BNBC","BOAB","BOABF","BOAC","BOAM","BOAN","BOAS",
    "CABC","CBIBF","CFAC","CIEC","ECOC","ETIT","FTSC","LNBB","NEIC","NSBC",
    "NTLC","ONTBF","ORAC","ORGT","PALC","PRSC","SAFC","SCRC","SDCC","SDSC",
    "SEMC","SGBC","SHEC","SIBC","SICC","SIVC","SLBC","SMBC","SNTS","SOGC",
    "SPHC","STAC","STBC","TTLC","TTLS","UNLC","UNXC",
}

JOURS_FERIES = {
    "01-01","05-01","08-15","11-01","12-25",
    "2023-04-10","2023-04-21","2023-05-18","2023-05-29","2023-06-21",
    "2024-04-01","2024-04-10","2024-05-09","2024-05-20","2024-06-17",
    "2025-03-30","2025-04-21","2025-05-27","2025-05-29","2025-06-06","2025-06-09",
    "2026-04-18","2026-04-21","2026-05-14","2026-05-25","2026-05-27","2026-06-05",
}

def is_market_open(d):
    if d.weekday() >= 5:
        return False
    return d.strftime("%m-%d") not in JOURS_FERIES and d.strftime("%Y-%m-%d") not in JOURS_FERIES

def get_trading_days(start, end):
    days, current = [], start
    while current <= end:
        if is_market_open(current):
            days.append(current)
        current += timedelta(days=1)
    return days

def fetch_pdf(d):
    dc = d.strftime("%Y%m%d")
    urls = [
        f"https://www.brvm.org/sites/default/files/boc_{dc}_2.pdf",
        f"https://www.brvm.org/sites/default/files/boc_{dc}_1.pdf",
        f"https://www.brvm.org/sites/default/files/BOC_{dc}_2.pdf",
        f"https://www.brvm.org/sites/default/files/BOC_{dc}.pdf",
    ]
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.brvm.org/fr/bulletins-officiels-de-la-cote"}
    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=60, verify=False)
            if r.status_code == 200 and r.content[:4] == b"%PDF" and len(r.content) > 10000:
                print(f"    PDF: {url.split('/')[-1]} ({len(r.content)//1024} KB)")
                return r.content
        except:
            pass
    return None

def parse_boc_pdf(pdf_bytes, date_str):
    try:
        import pdfplumber
    except ImportError:
        print("  pip install pdfplumber")
        return []

    rows, seen = [], set()
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                for table in (page.extract_tables() or []):
                    for row in table:
                        cells = [re.sub(r"[\s\u00a0\u202f]+", "", str(c or "")).strip() for c in row if c]
                        ticker, t_idx = None, None
                        for i, c in enumerate(cells[:4]):
                            if c.upper() in TICKERS_KNOWN:
                                ticker, t_idx = c.upper(), i
                                break
                        if not ticker or ticker in seen:
                            continue
                        nums = []
                        for c in cells[t_idx+1:]:
                            try:
                                v = float(c.replace(",","."))
                                if v > 0:
                                    nums.append(v)
                            except:
                                pass
                        if len(nums) < 2:
                            continue
                        close = nums[2] if len(nums) >= 3 else nums[-1]
                        open_ = nums[1] if len(nums) >= 3 else nums[0]
                        if close <= 0 or close > 10_000_000:
                            continue
                        vol = 0
                        for c in reversed(cells[t_idx+1:]):
                            try:
                                v = int(float(c.replace(",",".")))
                                if 0 < v < 100_000_000:
                                    vol = v
                                    break
                            except:
                                pass
                        seen.add(ticker)
                        rows.append({"ticker": ticker, "date": date_str, "open": open_,
                                     "high": max(open_, close), "low": min(open_, close),
                                     "close": close, "volume": vol})
    except Exception as e:
        print(f"  Erreur PDF: {e}")
    return rows

def delete_date(date_str):
    try:
        r = requests.delete(f"{SUPABASE_URL}/rest/v1/brvm_prices?date=eq.{date_str}", headers=HEADERS_SB, timeout=15)
        return r.status_code in (200, 204)
    except:
        return False

def upsert_rows(rows):
    if not rows:
        return 0
    inserted = 0
    for i in range(0, len(rows), 50):
        try:
            r = requests.post(f"{SUPABASE_URL}/rest/v1/brvm_prices", headers=HEADERS_SB, json=rows[i:i+50], timeout=30)
            if r.status_code in (200, 201):
                inserted += len(rows[i:i+50])
        except Exception as e:
            print(f"  Upsert: {e}")
    return inserted

def dates_in_supabase(start, end):
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/brvm_prices?date=gte.{start}&date=lte.{end}&select=date&limit=10000",
            headers=HEADERS_SB, timeout=30)
        return {x["date"] for x in r.json()} if r.ok else set()
    except:
        return set()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="date_from", default="2023-06-01")
    parser.add_argument("--to",   dest="date_to",   default=date.today().isoformat())
    parser.add_argument("--dry-run",       action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--delay", type=float, default=2.0)
    args = parser.parse_args()

    start = date.fromisoformat(args.date_from)
    end   = date.fromisoformat(args.date_to)
    days  = get_trading_days(start, end)

    print(f"Periode: {start} -> {end} | {len(days)} seances | dry={args.dry_run}")

    existing = dates_in_supabase(start, end) if args.skip_existing and not args.dry_run else set()
    ok, missing, total = 0, 0, 0

    for i, d in enumerate(days):
        ds = d.isoformat()
        print(f"[{i+1}/{len(days)}] {ds}", end="")
        if ds in existing:
            print(" → skip")
            continue
        pdf = fetch_pdf(d)
        if not pdf:
            print(" → PDF non trouve")
            missing += 1
            time.sleep(args.delay)
            continue
        rows = parse_boc_pdf(pdf, ds)
        if not rows:
            print(f" → 0 tickers")
            missing += 1
            time.sleep(args.delay)
            continue
        print(f" → {len(rows)} tickers")
        total += len(rows)
        ok += 1
        if not args.dry_run:
            delete_date(ds)
            upserted = upsert_rows(rows)
            print(f"   Supabase: {upserted}/{len(rows)}")
        time.sleep(args.delay)

    print(f"\nRESUME: {ok} seances OK | {missing} manquantes | {total} lignes")

if __name__ == "__main__":
    main()


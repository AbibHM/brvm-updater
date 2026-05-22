#!/usr/bin/env python3
"""
BRVM Daily Updater
Source : Bulletin Officiel de la Cote (BOC) PDF - brvm.org
Fallback: scraping HTML brvm.org/fr/cours-actions/0
"""
import os
import re
import sys
import io
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

BRVM_SCRAPE_URL = "https://www.brvm.org/fr/cours-actions/0"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"

# Date cible
_date_override = os.environ.get("DATE_OVERRIDE", "").strip()
if _date_override:
    try:
        TODAY = datetime.strptime(_date_override, "%Y-%m-%d").date().isoformat()
    except ValueError:
        TODAY = date.today().isoformat()
else:
    TODAY = date.today().isoformat()

TODAY_COMPACT = TODAY.replace("-", "")

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

def delete_date_prices(date_str):
    """Supprime toutes les lignes pour une date donnee avant re-insert."""
    url = SUPABASE_URL + "/rest/v1/brvm_prices?date=eq." + date_str
    try:
        resp = requests.delete(url, headers=HEADERS_SB, timeout=15)
        if resp.status_code in (200, 204):
            print("Suppression " + date_str + " OK")
        else:
            print("Suppression echouee " + str(resp.status_code) + ": " + resp.text[:100])
    except Exception as e:
        print("Erreur suppression: " + str(e))

def scrape_indices():
    """Scrape les indices BRVM depuis brvm.org et les met a jour dans brvm_meta."""
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "fr-FR,fr;q=0.9"}
    try:
        resp = requests.get(BRVM_SCRAPE_URL, headers=headers, timeout=30, verify=False)
        resp.raise_for_status()
    except Exception as e:
        print("  Erreur indices HTML: " + str(e))
        return

    now = datetime.now(timezone.utc).isoformat()
    text = re.sub(r"<[^>]+>", " ", resp.text)  # strip HTML tags
    text = re.sub(r"[\xa0\u202f]", " ", text)  # espaces insecables

    indrows = []
    for code in ["BRVM-C", "BRVM-30", "BRVM-PRES"]:
        idx = text.find(code)
        if idx < 0:
            continue
        snippet = text[idx + len(code):idx + len(code) + 60]
        # Extraire tous les nombres decimaux (format francais: 421,55)
        nums = re.findall(r"-?\d[\d ]*,\d+", snippet)
        if not nums:
            continue
        try:
            # Le premier nombre positif > 10 est la valeur de l index
            val = None
            var_pct = 0.0
            for n in nums:
                v = float(n.replace(" ", "").replace(",", "."))
                if val is None and abs(v) > 10:
                    val = v
                elif val is not None:
                    var_pct = v
                    break
            if val is None:
                continue
        except Exception:
            continue

        # Upsert dans brvm_meta
        url = SUPABASE_URL + "/rest/v1/brvm_meta?ticker=eq." + code
        payload = {"last_updated": now, "last_close": val, "last_volume": 0, "change_pct": var_pct}
        r = requests.patch(url, headers=HEADERS_SB, json=payload, timeout=10)
        if r.status_code not in (200, 204):
            requests.post(SUPABASE_URL + "/rest/v1/brvm_meta", headers=HEADERS_SB,
                json={"ticker": code, **payload, "total_rows": 0}, timeout=10)
        print(f"  Indice {code}: {val} ({var_pct:+.2f}%)")
    # Upsert batch
    if indrows:
        r = requests.post(SUPABASE_URL + "/rest/v1/brvm_meta",
            headers={**HEADERS_SB, "Prefer": "resolution=merge-duplicates"},
            json=indrows, timeout=15)
        print("  Indices upsert: " + str(r.status_code))

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

def update_meta(rows):
    """Met a jour brvm_meta avec last_updated, last_close, last_volume pour chaque ticker."""
    if not rows:
        return
    now = datetime.now(timezone.utc).isoformat()
    ok = 0
    for row in rows:
        url = SUPABASE_URL + "/rest/v1/brvm_meta?ticker=eq." + row["ticker"]
        payload = {
            "last_updated": now,
            "last_close": row.get("close"),
            "last_volume": row.get("volume", 0),
        }
        resp = requests.patch(url, headers=HEADERS_SB, json=payload, timeout=10)
        if resp.status_code in (200, 204):
            ok += 1
        else:
            # Ligne inexistante -> INSERT
            requests.post(
                SUPABASE_URL + "/rest/v1/brvm_meta",
                headers=HEADERS_SB,
                json={"ticker": row["ticker"], **payload, "total_rows": 0},
                timeout=10
            )
    print("brvm_meta mis a jour: " + str(ok) + "/" + str(len(rows)) + " tickers")

def get_pdf_urls():
    d = TODAY_COMPACT
    return [
        f"https://www.brvm.org/sites/default/files/boc_{d}_2.pdf",
        f"https://www.brvm.org/sites/default/files/boc_{d}_1.pdf",
        f"http://bfin.brvm.org/boc/BOC_JOUR/BOC_{d}.pdf",
    ]

def fetch_pdf_bytes(url):
    headers = {"User-Agent": USER_AGENT, "Referer": "https://www.brvm.org/fr/bulletins-officiels-de-la-cote"}
    try:
        r = requests.get(url, headers=headers, timeout=30, verify=False)
        if r.status_code == 200 and r.headers.get("Content-Type", "").startswith("application/pdf"):
            return r.content
        if r.status_code == 200 and len(r.content) > 10000 and r.content[:4] == b"%PDF":
            return r.content
        print(f"  PDF non disponible ({r.status_code}) : {url}")
        return None
    except Exception as e:
        print(f"  Erreur fetch PDF: {e}")
        return None

def parse_pdf_boc(pdf_bytes):
    try:
        import pdfplumber
    except ImportError:
        print("  pdfplumber non installe")
        return []
    rows = []
    seen_tickers = set()
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            print(f"  PDF: {len(pdf.pages)} pages")
            for page_num, page in enumerate(pdf.pages, 1):
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        if not row: continue
                        cells = [clean(str(c or "")) for c in row]
                        cells = [c for c in cells if c]
                        ticker = None
                        for cell in cells[:3]:
                            if cell.upper() in TICKERS_KNOWN:
                                ticker = cell.upper()
                                break
                        if not ticker or ticker in seen_tickers: continue
                        numerics = [v for c in cells if (v := to_float(c)) is not None and v > 0]
                        if not numerics: continue
                        close = numerics[0]
                        open_ = numerics[1] if len(numerics) >= 2 else close
                        high  = numerics[2] if len(numerics) >= 3 else close
                        low   = numerics[3] if len(numerics) >= 4 else close
                        volume = 0
                        for c in reversed(cells):
                            v = to_int(c)
                            if v is not None and v >= 0: volume = v; break
                        seen_tickers.add(ticker)
                        rows.append({"ticker": ticker, "date": TODAY, "open": open_, "high": high, "low": low, "close": close, "volume": volume})
    except Exception as e:
        print(f"  Erreur parsing PDF: {e}")
        return []
    return rows

def scrape_from_pdf():
    for url in get_pdf_urls():
        print(f"  Tentative PDF : {url}")
        pdf_bytes = fetch_pdf_bytes(url)
        if pdf_bytes:
            print(f"  PDF telecharge {len(pdf_bytes)//1024} KB) - parsing...")
            rows = parse_pdf_boc(pdf_bytes)
            if rows:
                print(f"  {len(rows)} tickers extraits du PDF")
                return rows, url
            else:
                print("  PDF recupere mais aucun ticker extrait")
    return [], None

def scrape_from_html():
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "fr-FR,fr;q=0.9"}
    try:
        resp = requests.get(BRVM_SCRAPE_URL, headers=headers, timeout=30, verify=False)
        resp.raise_for_status()
    except Exception as e:
        print("  Erreur HTML: " + str(e))
        return []
    rows = []
    tr_p = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL|re.IGNORECASE)
    td_p = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL|re.IGNORECASE)
    tag_p = re.compile(r"<[^>]+>")
    for trm in tr_p.finditer(resp.text):
        tr = trm.group(1)
        tm = re.search(r"/fr/cours/([A-Z]{3,6})", tr, re.IGNORECASE)
        if not tm: continue
        ticker = tm.group(1).upper()
        if ticker not in TICKERS_KNOWN: continue
        tds = [clean(tag_p.sub("", td.group(1))) for td in td_p.finditer(tr)]
        tds = [t for t in tds if t]
        if len(tds) < 2: continue
        nums = [v for t in tds if (v := to_float(t)) is not None and v > 0]
        if not nums: continue
        close = nums[0]; open_ = nums[2] if len(nums)>2 else close
        high = nums[3] if len(nums)>3 else close; low = nums[4] if len(nums)>4 else close
        volume = 0
        for t in reversed(tds):
            v = to_int(t)
            if v is not None and v >= 0: volume = v; break
        rows.append({"ticker": ticker, "date": TODAY, "open": open_, "high": high, "low": low, "close": close, "volume": volume})
    return rows

def main():
    print("BRVM Daily Updater - " + TODAY)
    print("=" * 50)
    # Supprimer les données existantes du jour (peut être corrompues)
    delete_date_prices(TODAY)
    print("\n[1/2] Scraping HTML brvm.org (source principale)...")
    rows = scrape_from_html()
    pdf_source = None
    if not rows:
        print("\n[2/2] Fallback: Bulletin Officiel de la Cote (PDF)...")
        rows, pdf_source = scrape_from_pdf()
    print(f"\n{len(rows)} tickers recuperes")
    if not rows:
        print("Aucune donnee disponible. Repassage au prochain cron.")
        sys.exit(0)
    print("Envoi vers Supabase...")
    inserted = upsert_prices(rows)
    print(f"{inserted}/{len(rows)} lignes upsertees")
    update_meta(rows)
    # Mettre a jour les indices BRVM
    print("Mise a jour des indices BRVM...")
    scrape_indices()
    print("Termine: " + datetime.now().strftime("%H:%M:%S UTC"))
    sys.exit(0 if inserted > 0 else 1)


if __name__ == "__main__":
    main()

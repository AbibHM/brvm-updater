#!/usr/bin/env python3
# v2.1 Ã¢ÂÂ fix: change_pct_prev removed, imports corrected
"""
BRVM Daily Updater
Source : Bulletin Officiel de la Cote (BOC) PDF - brvm.org
Fallback: scraping HTML brvm.org/fr/cours-actions/0
"""h
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

# Jours fÃÂ©riÃÂ©s BRVM/UEMOA Ã¢ÂÂ la bourse est fermÃÂ©e ces jours-lÃÂ 
# Format: "MM-DD" (rÃÂ©currents chaque annÃÂ©e) ou "YYYY-MM-DD" (ponctuels)
JOURS_FERIES = {
    # FÃÂ©riÃÂ©s rÃÂ©currents UEMOA
    "01-01",  # Jour de l'An
    "05-01",  # FÃÂªte du Travail
    "08-15",  # Assomption
    "11-01",  # Toussaint
    "12-25",  # NoÃÂ«l
    # FÃÂ©riÃÂ©s CÃÂ´te d'Ivoire (pays siÃÂ¨ge BRVM)
    "04-07",  # JournÃÂ©e nationale CI
    "08-07",  # FÃÂªte Nationale CI
    "11-15",  # JournÃÂ©e Nationale de la Paix CI
    # FÃÂ©riÃÂ©s mobiles 2026 (ÃÂ  mettre ÃÂ  jour chaque annÃÂ©e)
    "2026-04-18",  # Vendredi Saint
    "2026-04-21",  # Lundi de PÃÂ¢ques
    "2026-05-14",  # Ascension
    "2026-05-25",  # Lundi de PentecÃÂ´te
    "2026-05-27",  # FÃÂªte Nationale (27 mai CI)
    "2026-06-05",  # AÃÂ¯d el-Fitr (approx)
    # 2025
    "2025-04-21",  # Lundi de PÃÂ¢ques
    "2025-05-29",  # Ascension
    "2025-06-09",  # Lundi de PentecÃÂ´te
}

def is_market_open(date_str=None):
    """VÃÂ©rifie si le marchÃÂ© BRVM est ouvert (lun-ven, hors fÃÂ©riÃÂ©s)."""
    from datetime import datetime
    d = datetime.strptime(date_str or TODAY, "%Y-%m-%d")
    # Weekend
    if d.weekday() >= 5:
        return False
    # Jours fÃÂ©riÃÂ©s
    mmdd = d.strftime("%m-%d")
    yyyymmdd = d.strftime("%Y-%m-%d")
    if mmdd in JOURS_FERIES or yyyymmdd in JOURS_FERIES:
        return False
    return True

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
    "CABC","CBIBF","CFAC","CIEC","CROWN","ECOC","ETIT","FTSC","LNBB","MOVIS",
    "NEIC","NSBC","NTLC","ONTBF","ORAC","ORGT","PALC","PRSC","SAFC","SCRC",
    "SDCC","SDSC","SEMC","SGBC","SHEC","SIBC","SICC","SIVC","SLBC","SMBC",
    "SNTS","SOGC","SPHC","STAC","STBC","SVOC","TTLC","TTLS","TTRC","UNLC","UNXC",
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

def scrape_news():
    """
    Scrape les actualitÃÂ©s officielles BRVM :
    1. Ticker tape BRVM (annonces dividendes, AGO/AGE depuis la page principale)
    2. Avis et publications brvm.org
    3. RSS AgenceEcofin (fallback, sans dÃÂ©pendance Sika Finance)
    """
    import xml.etree.ElementTree as ET
    import hashlib
    now = datetime.now(timezone.utc).isoformat()
    news_rows = []
    seen_hashes = set()

    # Artefacts de navigation a filtrer (pas de vraies news)
    JUNK_PHRASES = ["je suis un","investissons pour","je m'identifie",
                    "accueil","menu","connexion","s'inscrire","login","logout",
                    "age", "home", "retour", "suivant", "précédent",
                    "en savoir plus", "voir plus", "lire la suite",
                    "notre portail", "bienvenue", "rejoignez"]

    def add_news(headline, source, ticker="BRVM", url="", pub_date=None):
        h_clean = headline.strip().lower()
        # Filtrer headlines trop courtes
        if len(headline.strip()) < 30:
            return
        # Filtrer artefacts de navigation
        if any(j in h_clean for j in JUNK_PHRASES):
            return
        h = hashlib.md5(headline.encode()).hexdigest()
        if h in seen_hashes:
            return
        seen_hashes.add(h)
        news_rows.append({
            "published_at": pub_date or now,
            "source": source,
            "ticker": ticker,
            "headline": headline[:500],
            "url": url[:500],
        })

    headers_web = {"User-Agent": USER_AGENT, "Accept-Language": "fr-FR,fr;q=0.9"}

    # Ã¢ÂÂÃ¢ÂÂ 1. Ticker tape BRVM Ã¢ÂÂ annonces dividendes + avis Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
    try:
        resp = requests.get("https://www.brvm.org/fr", headers=headers_web, timeout=20, verify=False)
        if resp.status_code == 200 and len(resp.text) > 500:
            text = resp.text
            # Le ticker tape contient des annonces dividendes
            tape_items = re.findall(
                r'([A-Z]{2,6})\s*:\s*([^|<]{20,200}?)(?:\||<)',
                text, re.IGNORECASE
            )
            for ticker_found, message in tape_items:
                t = ticker_found.upper()
                if t in TICKERS_KNOWN:
                    add_news(f"{t} : {message.strip()}", "BRVM Officiel", t)

            # AGO/AGE et autres ÃÂ©vÃÂ©nements
            events = re.findall(
                r'(AG[OE]|AssemblÃÂ©e|Dividende|Coupon|RÃÂ©sultats?|ÃÂmission)[^<]{10,150}',
                text, re.IGNORECASE
            )
            for ev in events[:10]:
                add_news(ev.strip(), "BRVM Officiel")
    except Exception as e:
        print(f"  Ticker tape scrape erreur: {e}")

    # Ã¢ÂÂÃ¢ÂÂ 2. Avis et publications BRVM Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
    try:
        avis_url = "https://www.brvm.org/fr/marche/avis-et-publications/avis"
        resp = requests.get(avis_url, headers=headers_web, timeout=20, verify=False)
        if resp.status_code == 200 and len(resp.text) > 500:
            # Extraire les titres des avis
            titles = re.findall(
                r'<(?:h[23]|a)[^>]*class="[^"]*(?:title|view-field)[^"]*"[^>]*>\s*([^<]{20,200})\s*</(?:h[23]|a)>',
                resp.text, re.IGNORECASE
            )
            for title in titles[:15]:
                t = title.strip()
                # DÃÂ©tecter le ticker
                ticker = "BRVM"
                for tk in TICKERS_KNOWN:
                    if tk in t.upper():
                        ticker = tk
                        break
                add_news(t, "BRVM Officiel", ticker, avis_url)
    except Exception as e:
        print(f"  Avis BRVM scrape erreur: {e}")

    # Ã¢ÂÂÃ¢ÂÂ 3. RSS AgenceEcofin Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
    rss_sources = [
        ("https://www.agenceecofin.com/rss/toute-actualite", "AgenceEcofin"),
        ("https://www.brvm.org/fr/rss.xml", "BRVM RSS"),
        ("https://www.sikafinance.com/rss/flux_actu", "Sika Finance"),
    ]
    for rss_url, source_name in rss_sources:
        try:
            resp = requests.get(rss_url, timeout=15, headers=headers_web, verify=False)
            if resp.status_code != 200:
                continue
            root = ET.fromstring(resp.content)
            items = root.findall(".//item")[:15]
            for item in items:
                title = item.findtext("title", "").strip()
                link  = item.findtext("link",  "")
                pub   = item.findtext("pubDate", now)
                if not title:
                    continue
                # Filtrer les articles BRVM/marchÃÂ©s africains
                keywords = ["BRVM","bourse","boursier","action","marchÃÂ©","Afrique",
                            "FCFA","dividende","rÃÂ©sultat","obligation"] + list(TICKERS_KNOWN)
                if not any(kw.upper() in title.upper() for kw in keywords):
                    continue
                ticker = "BRVM"
                for tk in TICKERS_KNOWN:
                    if tk in title.upper():
                        ticker = tk
                        break
                add_news(title, source_name, ticker, link, now)
        except Exception as e:
            print(f"  RSS {source_name} erreur: {e}")

    # Ã¢ÂÂÃ¢ÂÂ 4. Scraper les ÃÂ©vÃÂ©nements (dividendes, AGO) Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
    scrape_events()

    print(f"  {len(news_rows)} news collectÃÂ©es")
    if not news_rows:
        print("  Aucune news Ã¢ÂÂ brvm.org peut ÃÂªtre indisponible")
        return

    # Récupérer les headlines déjà en base (déduplication côté Python)
    try:
        r_existing = requests.get(
            SUPABASE_URL + "/rest/v1/brvm_news?select=headline&limit=500&order=published_at.desc",
            headers=HEADERS_SB, timeout=10
        )
        if r_existing.status_code == 200:
            existing_headlines = {row['headline'] for row in r_existing.json()}
            news_rows = [n for n in news_rows if n['headline'] not in existing_headlines]
            print(f"  Après déduplication: {len(news_rows)} nouvelles news")
    except Exception as e:
        print(f"  Déduplication erreur (non bloquant): {e}")

    # Upsert par batch de 20
    ok = 0
    for i in range(0, len(news_rows), 20):
        batch = news_rows[i:i+20]
        try:
            resp = requests.post(
                SUPABASE_URL + "/rest/v1/brvm_news",
                headers={**HEADERS_SB, "Prefer": "resolution=merge-duplicates"},
                json=batch, timeout=15
            )
            if resp.status_code in (200, 201):
                ok += len(batch)
            else:
                print(f"  News batch erreur {resp.status_code}: {resp.text[:100]}")
        except Exception as e:
            print(f"  News batch exception: {e}")
    print(f"  News upsert: {ok}/{len(news_rows)} OK")


def scrape_events():
    """
    Scrape les ÃÂ©vÃÂ©nements du calendrier BRVM :
    dividendes, AGO/AGE, rÃÂ©sultats depuis le ticker tape brvm.org.
    Alimente brvm_events.
    """
    now = datetime.now(timezone.utc).isoformat()
    events = []
    headers_web = {"User-Agent": USER_AGENT, "Accept-Language": "fr-FR,fr;q=0.9"}

    try:
        resp = requests.get("https://www.brvm.org/fr", headers=headers_web, timeout=20, verify=False)
        if resp.status_code != 200 or len(resp.text) < 500:
            return

        text = resp.text
        # Pattern: "TICKER : Paiement de dividendes le JJ mois AAAA, XXX FCFA par action"
        div_pat = re.compile(
            r'([A-Z]{3,6})\s*:\s*Paiement\s+de\s+dividendes?\s+le\s+(\d+\s+\w+\s+\d{4})'
            r'[^,]*,?\s*([\d\s,.]+)\s*FCFA\s*par\s+action',
            re.IGNORECASE
        )
        for m in div_pat.finditer(text):
            ticker   = m.group(1).upper()
            date_str = m.group(2).strip()
            amount   = m.group(3).strip().replace(' ','').replace(',','.')
            if ticker not in TICKERS_KNOWN:
                continue
            try:
                amount_f = float(amount)
            except:
                amount_f = None

            # Parser la date franÃÂ§aise
            mois = {"janvier":"01","fÃÂ©vrier":"02","mars":"03","avril":"04",
                    "mai":"05","juin":"06","juillet":"07","aoÃÂ»t":"08",
                    "septembre":"09","octobre":"10","novembre":"11","dÃÂ©cembre":"12"}
            parts = date_str.lower().split()
            event_date = None
            if len(parts) == 3:
                m_num = mois.get(parts[1], "01")
                event_date = f"{parts[2]}-{m_num}-{parts[0].zfill(2)}"

            events.append({
                "ticker": ticker,
                "event_type": "dividende",
                "event_date": event_date or TODAY,
                "description": f"Dividende {amount_f} FCFA/action" if amount_f else "Paiement dividende",
                "amount": amount_f,
                "created_at": now,
            })

        # Coupon obligations
        coupon_pat = re.compile(
            r'([A-Z]{3,6})\s*:\s*Paiement\s+des?\s+coupons?[^<]{0,100}le\s+(\d+\s+\w+\s+\d{4})',
            re.IGNORECASE
        )
        for m in coupon_pat.finditer(text):
            ticker = m.group(1).upper()
            if ticker not in TICKERS_KNOWN:
                continue
            events.append({
                "ticker": ticker,
                "event_type": "coupon",
                "event_date": TODAY,
                "description": "Paiement coupon obligation",
                "amount": None,
                "created_at": now,
            })

    except Exception as e:
        print(f"  scrape_events erreur: {e}")
        return

    if not events:
        return

    print(f"  {len(events)} ÃÂ©vÃÂ©nements dÃÂ©tectÃÂ©s")
    try:
        resp = requests.post(
            SUPABASE_URL + "/rest/v1/brvm_events",
            headers={**HEADERS_SB, "Prefer": "resolution=merge-duplicates"},
            json=events, timeout=15
        )
        print(f"  Events upsert: {resp.status_code}")
    except Exception as e:
        print(f"  Events upsert erreur: {e}")


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
    """Met a jour brvm_meta avec last_updated, last_close, last_volume,
       change_pct (variation intraday J) et change_pct_prev (variation J-1/J)."""
    if not rows:
        return
    now = datetime.now(timezone.utc).isoformat()

    # --- Variation J-1/J : rÃÂ©cupÃÂ©rer le close de la sÃÂ©ance prÃÂ©cÃÂ©dente ---
    tickers_csv = ",".join(r["ticker"] for r in rows)
    prev_close = {}
    try:
        url_prev = (SUPABASE_URL + "/rest/v1/brvm_prices"
                    + "?ticker=in.(" + tickers_csv + ")"
                    + "&date=lt." + TODAY
                    + "&select=ticker,date,close"
                    + "&order=date.desc"
                    + "&limit=" + str(len(rows) * 3))
        resp_prev = requests.get(url_prev, headers=HEADERS_SB, timeout=15)
        if resp_prev.ok:
            for r in resp_prev.json():
                # Garder uniquement le close le plus rÃÂ©cent par ticker
                if r["ticker"] not in prev_close and r.get("close"):
                    prev_close[r["ticker"]] = r["close"]
    except Exception as e:
        print("  Avertissement closes J-1: " + str(e))

    ok = 0
    for row in rows:
        ticker      = row["ticker"]
        close_today = row.get("close") or 0
        open_today  = row.get("open")  or 0
        close_prev  = prev_close.get(ticker) or 0

        # Variation intraday (BOC) : (close_J - open_J) / open_J
        # ReprÃÂ©sente le mouvement pendant la sÃÂ©ance du jour
        if open_today > 0 and close_today > 0:
            var_intra = round((close_today - open_today) / open_today * 100, 2)
        else:
            var_intra = 0.0

        # Variation inter-sÃÂ©ances : (close_J - close_J-1) / close_J-1
        # C'est la variation officielle BRVM affichÃÂ©e dans le terminal (principale)
        if close_prev > 0 and close_today > 0:
            change_pct = round((close_today - close_prev) / close_prev * 100, 2)
        else:
            change_pct = 0.0

        url = SUPABASE_URL + "/rest/v1/brvm_meta?ticker=eq." + ticker
        payload = {
            "last_updated":     now,
            "last_close":       close_today,
            "last_volume":      row.get("volume", 0),
            "change_pct":       change_pct,   # Variation principale : inter-sÃÂ©ances (close_J / close_J-1)
            "var_intra":        var_intra,    # Variation intraday BOC : (close_J - open_J) / open_J
        }
        resp = requests.patch(url, headers=HEADERS_SB, json=payload, timeout=10)
        if resp.status_code in (200, 204):
            ok += 1
        else:
            requests.post(
                SUPABASE_URL + "/rest/v1/brvm_meta",
                headers=HEADERS_SB,
                json={"ticker": ticker, **payload, "total_rows": 0},
                timeout=10
            )
    print("brvm_meta mis a jour: " + str(ok) + "/" + str(len(rows)) + " tickers")

def get_pdf_urls():
    d = TODAY_COMPACT
    # Format alternatif avec tirets
    d2 = TODAY[:4] + "-" + TODAY[5:7] + "-" + TODAY[8:10]  # YYYY-MM-DD
    return [
        # brvm.org Ã¢ÂÂ format standard (suffixe _2 = sÃÂ©ance complÃÂ¨te, _1 = partiel)
        f"https://www.brvm.org/sites/default/files/boc_{d}_2.pdf",
        f"https://www.brvm.org/sites/default/files/boc_{d}_1.pdf",
        # bfin.brvm.org Ã¢ÂÂ mirror secondaire
        f"http://bfin.brvm.org/boc/BOC_JOUR/BOC_{d}.pdf",
        # Variantes de nommage observÃÂ©es
        f"https://www.brvm.org/sites/default/files/BOC_{d}_2.pdf",
        f"https://www.brvm.org/sites/default/files/BOC_{d}.pdf",
        f"https://www.brvm.org/sites/default/files/boc_{d}.pdf",
    ]

def fetch_pdf_bytes(url):
    headers = {"User-Agent": USER_AGENT, "Referer": "https://www.brvm.org/fr/bulletins-officiels-de-la-cote"}
    try:
        r = requests.get(url, headers=headers, timeout=60, verify=False)
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
        tds_raw = [clean(tag_p.sub("", td.group(1))) for td in td_p.finditer(tr)]
        tds = [t for t in tds_raw if t]
        if len(tds) < 2: continue
        ticker = tds[0].upper().strip()
        if ticker not in TICKERS_KNOWN: continue
        volume = to_int(tds[2]) if len(tds) > 2 else 0
        if volume is None: volume = 0
        price_nums = [to_float(tds[i]) for i in range(2, len(tds))
                      if to_float(tds[i]) is not None and to_float(tds[i]) > 100]
        if not price_nums: continue
        # Colonnes: Symbole|Nom|Volume|Cours_veille|Cours_ouverture|Cours_cloture|Variation
        # cours_veille = dernier cours officiel confirme (reference fiable)
        # cours_cloture = cours du jour, = cours_veille si seance pas terminee
        cours_veille    = to_float(tds[3]) if len(tds) > 3 else None
        cours_ouverture = to_float(tds[4]) if len(tds) > 4 else None
        cours_cloture   = to_float(tds[5]) if len(tds) > 5 else None
        # close = cours_veille (fiable), sauf si seance terminee et cloture differente
        seance_terminee = (cours_cloture and cours_cloture > 0 and cours_cloture != cours_veille)
        open_  = cours_ouverture if cours_ouverture and cours_ouverture > 0 else cours_veille
        close  = cours_cloture if seance_terminee else cours_veille
        high = close; low = close
        rows.append({"ticker": ticker, "date": TODAY, "open": open_, "high": high, "low": low, "close": close, "volume": volume})
    print(f"  HTML scrape: {len(rows)} tickers")
    return rows

def ensure_fundamentals_base():
    """Upsert les tickers manquants dans brvm_fundamentals (name/sector/country seulement).
    N'ÃÂ©crase pas les donnÃÂ©es existantes grÃÂ¢ce ÃÂ  merge-duplicates."""
    BASE_INFO = [
        {"ticker": "CROWN", "name": "Crown Siem CI",       "sector": "Industrie",    "country": "CÃÂ´te d'Ivoire"},
        {"ticker": "MOVIS", "name": "Movis CI",             "sector": "Transport",    "country": "CÃÂ´te d'Ivoire"},
        {"ticker": "SVOC",  "name": "Movis CI",             "sector": "Transport",    "country": "CÃÂ´te d'Ivoire"},
        {"ticker": "TTRC",  "name": "Tractafric Motors CI", "sector": "Distribution", "country": "CÃÂ´te d'Ivoire"},
    ]
    # RÃÂ©cupÃÂ©rer les tickers dÃÂ©jÃÂ  prÃÂ©sents
    try:
        existing = requests.get(
            SUPABASE_URL + "/rest/v1/brvm_fundamentals?select=ticker",
            headers=HEADERS_SB, timeout=10
        ).json()
        existing_tickers = {r["ticker"] for r in existing} if isinstance(existing, list) else set()
        to_insert = [r for r in BASE_INFO if r["ticker"] not in existing_tickers]
        if to_insert:
            r = requests.post(
                SUPABASE_URL + "/rest/v1/brvm_fundamentals",
                headers={**HEADERS_SB, "Prefer": "resolution=merge-duplicates"},
                json=to_insert, timeout=10
            )
            print(f"brvm_fundamentals base: {len(to_insert)} tickers ajoutÃÂ©s ({[r['ticker'] for r in to_insert]})")
        else:
            print("brvm_fundamentals base: OK (aucun ticker manquant)")
    except Exception as e:
        print(f"brvm_fundamentals base: erreur Ã¢ÂÂ {e}")




def install_deps():
    """Installer pdfplumber si absent."""
    try:
        import pdfplumber
    except ImportError:
        import subprocess
        subprocess.run(["pip", "install", "pdfplumber", "--quiet"], check=True)

def main():
    print("BRVM Daily Updater - " + TODAY)
    print("=" * 50)
    ensure_fundamentals_base()
    if not is_market_open():
        print(f"Marche BRVM ferme le {TODAY} (weekend ou ferie) Ã¢ÂÂ skip cours.")
        try: scrape_indices()
        except: pass
        try: scrape_news()
        except: pass
        sys.exit(0)
    print("\n[1/2] Scraping HTML brvm.org (source principale)...")
    rows = scrape_from_html()
    pdf_source = None
    if not rows:
        print("\n[2/2] Fallback: Bulletin Officiel de la Cote (PDF)...")
        rows, pdf_source = scrape_from_pdf()
    print(f"\n{len(rows)} tickers recuperes")
    if not rows:
        print("Aucune donnee disponible pour les cours. Repassage au prochain cron.")
        # Tenter quand meme les rapports annuels (fonctions definies apres main)
        try:
            install_deps()
            scrape_rapports_annuels()
        except NameError:
            pass
        sys.exit(0)
    # Supprimer les donnÃÂ©es existantes uniquement si scraping rÃÂ©ussi
    delete_date_prices(TODAY)
    print("Envoi vers Supabase...")
    inserted = upsert_prices(rows)
    print(f"{inserted}/{len(rows)} lignes upsertees")
    update_meta(rows)
    # Mettre a jour les indices BRVM
    print("Mise a jour des indices BRVM...")
    scrape_indices()
    print("Scraping news BRVM...")
    scrape_news()
    # Ã¢ÂÂÃ¢ÂÂ Rapports annuels (chaque lundi ou si FORCE_RAPPORTS=1) Ã¢ÂÂÃ¢ÂÂ
    # Vérification quotidienne - on ne télécharge que les PDFs nouveaux
    install_deps()
    scrape_rapports_annuels()
    print("Termine: " + datetime.now().strftime("%H:%M:%S UTC"))
    sys.exit(0 if inserted > 0 else 1)




# ============================================================
# SCRAPER RAPPORTS ANNUELS Ã¢ÂÂ brvm_financials
# ============================================================

# Mapping ticker Ã¢ÂÂ mots-clÃÂ©s dans le nom du fichier PDF
TICKER_PDF_KEYWORDS = {
    "ABJC": ["abjc","abdijan","abidjan_bus"],
    "BICC": ["bici","bicici"],
    "BICB": ["bic_benin","bic-benin"],
    "BNBC": ["bnb","bank_of_africa_niger_benin","bnbc"],
    "BOAB": ["boa_benin","bank_of_africa_benin"],
    "BOABF": ["boa_burkina","bank_of_africa_burkina"],
    "BOAC": ["boa_ci","bank_of_africa_ci","boa_cote"],
    "BOAM": ["boa_mali","bank_of_africa_mali"],
    "BOAN": ["boa_niger","bank_of_africa_niger"],
    "BOAS": ["boa_senegal","bank_of_africa_senegal"],
    "CABC": ["cabc","sicable","sica_cable"],
    "CBIBF": ["coris_bank","cbi"],
    "CFAC": ["cfac","compagnie_financiere"],
    "CIEC": ["ciec","cie","compagnie_ivoirienne"],
    "ECOC": ["ecobank_ci","ecobank_cote"],
    "ETIT": ["ecobank_transnational","etit","eti"],
    "FTSC": ["filtisac","filtisaci"],
    "NEIC": ["neinvestment","nei"],
    "NSBC": ["nsia_banque","nsia-banque","nsbc"],
    "NTLC": ["nestle","nestl"],
    "ONTBF": ["onatel","office_national"],
    "ORAC": ["orange_ci","orange_cote"],
    "ORGT": ["oragroup","ora_group"],
    "PALC": ["palm_ci","palm_cote","palmci"],
    "PRSC": ["prs","peyrissac"],
    "SAFC": ["safca","saf"],
    "SCRC": ["sucrivoire","sucr"],
    "SDCC": ["sodeci","societe_dist"],
    "SDSC": ["sdsc","sds"],
    "SEMC": ["semc","sem"],
    "SGBC": ["societe_generale_ci","societe_generale_cote","sgbc","sgbci"],
    "SHEC": ["shec","solibra","saph","soci_africaine"],
    "SIBC": ["sib_ci","sib_cote","sibc"],
    "SICC": ["sicc","sicable"],
    "SIVC": ["siveng","sivci"],
    "SLBC": ["slbc","societe_laitiere"],
    "SMBC": ["smbc","smi","smb_ci","scierie_menuiserie"],
    "SNTS": ["sentelec","sentel","sonatel","sonatel_sa"],
    "SOGC": ["sogc","sogeci"],
    "SPHC": ["sphc","sphere"],
    "STAC": ["stac","setao","setao_ci"],
    "STBC": ["stbc","solibra","sitab"],
    "SVOC":  ["svoc","vivo_energy","vivo_ci","shell_ci"],
    "TTLC": ["ttlc","totalenergies_ci","total_cote"],
    "TTLS": ["ttls","totalenergies_senegal","total_senegal"],
    "UNLC": ["unilever_ci","unilever_cote"],
    "UNXC": ["unxc","unix"],
}

def fetch_rapport_list(year=None):
    """Scrape la liste des rapports annuels depuis brvm.org/fr/rapports-societe-cotes/0"""
    if year is None:
        from datetime import datetime
        year = datetime.now().year - 1  # Exercice N-1
    
    urls_to_try = [
        f"https://www.brvm.org/fr/rapports-societe-cotes/0",
        f"https://www.brvm.org/fr/type-document/rapports-annuels",
        f"https://www.brvm.org/fr/rapports-0",
    ]
    
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Referer": "https://www.brvm.org/fr/",
    }
    
    pdf_entries = []  # [{ticker, url, year, date_pub}]
    
    for url in urls_to_try:
        try:
            r = requests.get(url, headers=headers, timeout=20, verify=False)
            if r.status_code != 200 or len(r.text) < 100:
                continue
            
            # Chercher les liens PDF et les noms de fichiers
            # Pattern: href="/sites/default/files/YYYYMMDD_-_rapport_..._YYYY_-_nom.pdf"
            pdf_pat = re.compile(
                r'href="(/sites/default/files/(\d{8})_-_(rapport[^"]*?|etats_financiers[^"]*?)(\d{4})[^"]*?\.pdf)"',
                re.IGNORECASE
            )
            for m in pdf_pat.finditer(r.text):
                path      = m.group(1)
                date_pub  = m.group(2)
                year_doc  = int(m.group(4))
                fname_lower = path.lower()
                if any(x in fname_lower for x in ["semestriel","semestre","semi_annuel","s1_","s2_"]):
                    period_type = "semi-annual"
                else:
                    period_type = "annual"
                full_url  = "https://www.brvm.org" + path
                filename  = path.split("/")[-1].lower()
                
                # Identifier le ticker
                ticker = None
                for t, kws in TICKER_PDF_KEYWORDS.items():
                    if any(kw in filename for kw in kws):
                        ticker = t
                        break
                
                if ticker and year_doc >= year - 2:
                    pdf_entries.append({
                        "ticker": ticker,
                        "url": full_url,
                        "fiscal_year": str(year_doc),
                        "date_pub": date_pub,
                        "period_type": period_type,
                    })
            
            if pdf_entries:
                break  # On a ce qu'il faut
        except Exception as e:
            print(f"  fetch_rapport_list err: {e}")
            continue
    
    return pdf_entries


def extract_financials_from_pdf(pdf_bytes, ticker):
    """
    Extrait les donnÃÂ©es financiÃÂ¨res d'un rapport annuel PDF BRVM.
    Retourne un dict avec ca, rn, cap_propres, bpa, dividende etc.
    """
    data = {}
    
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            full_text = ""
            for page in pdf.pages[:60]:  # Max 60 pages
                text = page.extract_text() or ""
                full_text += text + "\n"
            
            # Ã¢ÂÂÃ¢ÂÂ Patterns de recherche (SYSCOHADA / comptes BRVM) Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
            patterns = {
                # Chiffre d'affaires
                "ca": [
                    r"chiffre\s+d.affaires\s+net[^\d]*?([\d\s]+(?:,\d+)?)\s*(?:FCFA|F CFA|millions?)?",
                    r"produits\s+d.exploitation[^\d]*?([\d\s]+(?:,\d+)?)",
                    r"revenus?\s+nets?[^\d]*?([\d\s]+(?:,\d+)?)",
                ],
                # RÃÂ©sultat net
                "rn": [
                    r"r[eÃÂ©]sultat\s+net\s*(?:de\s+l.exercice)?[^\d]*?([+-]?[\d\s]+(?:,\d+)?)\s*(?:FCFA|F CFA|millions?)?",
                    r"b[eÃÂ©]n[eÃÂ©]fice\s+net[^\d]*?([+-]?[\d\s]+(?:,\d+)?)",
                    r"perte\s+nette[^\d]*?([+-]?[\d\s]+(?:,\d+)?)",
                ],
                # Capitaux propres
                "cap_propres": [
                    r"capitaux\s+propres[^\d]*?([\d\s]+(?:,\d+)?)",
                    r"fonds\s+propres[^\d]*?([\d\s]+(?:,\d+)?)",
                    r"situation\s+nette[^\d]*?([\d\s]+(?:,\d+)?)",
                ],
                # Total bilan / Actif total
                "actif_total": [
                    r"total\s+(?:du\s+)?bilan[^\d]*?([\d\s]+(?:,\d+)?)",
                    r"total\s+actif[^\d]*?([\d\s]+(?:,\d+)?)",
                    r"total\s+g[eÃÂ©]n[eÃÂ©]ral[^\d]*?([\d\s]+(?:,\d+)?)",
                ],
                # RÃÂ©sultat d'exploitation / EBIT
                "res_exp": [
                    r"r[eÃÂ©]sultat\s+(?:d.exploitation|opÃÂ©rationnel)[^\d]*?([+-]?[\d\s]+(?:,\d+)?)",
                    r"ebit[^\d]*?([+-]?[\d\s]+(?:,\d+)?)",
                ],
                # Dividende
                "dividende": [
                    r"dividende[s]?\s+(?:par\s+action)?[^\d]*?([\d\s]+(?:,\d+)?)\s*(?:FCFA|F CFA)?",
                    r"distribution[^\d]*?([\d\s]+(?:,\d+)?)\s*(?:FCFA|F CFA)?\s*(?:par\s+action)?",
                ],
                # BPA
                "bpa": [
                    r"b[eÃÂ©]n[eÃÂ©]fice\s+(?:net\s+)?par\s+action[^\d]*?([+-]?[\d\s]+(?:,\d+)?)",
                    r"bpa[^\d]*?([+-]?[\d\s]+(?:,\d+)?)",
                    r"r[eÃÂ©]sultat\s+(?:net\s+)?par\s+action[^\d]*?([+-]?[\d\s]+(?:,\d+)?)",
                ],
                # Nombre de titres
                "nb_titres": [
                    r"(?:nombre\s+de\s+)?(?:titres|actions)\s+(?:en\s+circulation|composant)[^\d]*?([\d\s]+)",
                    r"capital\s+divis[eÃÂ©]\s+en\s+([\d\s]+)\s+actions",
                ],
            }
            
            def clean_num(s):
                """Nettoie un nombre extrait du PDF: '1 234 567,00' Ã¢ÂÂ 1234567.0"""
                s = re.sub(r'\s+', '', s.strip())
                s = s.replace(',', '.')
                try:
                    return float(s)
                except:
                    return None
            
            for field, pats in patterns.items():
                for pat in pats:
                    m = re.search(pat, full_text, re.IGNORECASE | re.MULTILINE)
                    if m:
                        val = clean_num(m.group(1))
                        if val is not None and val > 0:
                            # DÃÂ©tecter l'unitÃÂ© Ã¢ÂÂ "en millions" ou "en milliers"
                            # (les comptes BRVM sont souvent en millions FCFA)
                            data[field] = val
                            break
            
            # DÃÂ©tecter l'unitÃÂ© globale du document
            if "millions" in full_text.lower() or "en millions" in full_text.lower():
                # DÃÂ©jÃÂ  en millions Ã¢ÂÂ OK
                pass
            elif "milliers" in full_text.lower() or "en milliers" in full_text.lower():
                # En milliers Ã¢ÂÂ diviser par 1000 pour avoir des millions
                for k in ["ca","rn","cap_propres","actif_total","res_exp","ebitda"]:
                    if k in data:
                        data[k] = data[k] / 1000
    
    except Exception as e:
        print(f"  extract_financials err ({ticker}): {e}")
    
    return data


def compute_ratios(data, cours, nb_titres_brvm=None):
    """Calcule les ratios ÃÂ  partir des donnÃÂ©es extraites du PDF et du cours BRVM."""
    r = {}
    
    ca    = data.get("ca")
    rn    = data.get("rn")
    cp    = data.get("cap_propres")
    total = data.get("actif_total")
    nb    = data.get("nb_titres") or nb_titres_brvm
    
    if rn is not None and cp and cp > 0:
        r["roe"] = round(rn / cp * 100, 2)
    if rn is not None and total and total > 0:
        r["roa"] = round(rn / total * 100, 2)
    if ca and ca > 0:
        if rn is not None:
            r["marge_nette"] = round(rn / ca * 100, 2)
        if data.get("res_exp") is not None:
            r["marge_op"] = round(data["res_exp"] / ca * 100, 2)
    if nb and nb > 0:
        if rn is not None:
            r["bpa"] = round((rn * 1e6) / nb, 2)  # rn en M FCFA Ã¢ÂÂ FCFA par action
    
    return r


def scrape_rapports_annuels():
    """
    Fonction principale : scrape les rapports annuels BRVM et 
    met ÃÂ  jour brvm_financials + brvm_fundamentals.
    """
    from datetime import datetime
    current_year = datetime.now().year
    target_year  = current_year - 1  # Exercice N-1
    
    print(f"\n[RAPPORTS] Scraping rapports annuels exercice {target_year}...")
    
    # 1. RÃÂ©cupÃÂ©rer la liste des PDFs disponibles
    pdf_entries = fetch_rapport_list(target_year)
    if not pdf_entries:
        print("  Aucun rapport trouvÃÂ© Ã¢ÂÂ vÃÂ©rifier l'accÃÂ¨s ÃÂ  brvm.org")
        return
    
    print(f"  {len(pdf_entries)} rapports trouvÃÂ©s")
    
    headers = {"User-Agent": USER_AGENT, "Referer": "https://www.brvm.org/fr/"}
    now     = datetime.now(timezone.utc).isoformat()
    ok_count = 0
    
    for entry in pdf_entries:
        ticker      = entry["ticker"]
        url         = entry["url"]
        fiscal_year = entry["fiscal_year"]
        period_type = entry.get("period_type", "annual")
        
        # VÃÂ©rifier si dÃÂ©jÃÂ  parsÃÂ© rÃÂ©cemment
        check_url = f"{SUPABASE_URL}/rest/v1/brvm_financials?ticker=eq.{ticker}&fiscal_year=eq.{fiscal_year}&select=parsed_at"
        check_r   = requests.get(check_url, headers=HEADERS_SB, timeout=10)
        if check_r.ok:
            existing = check_r.json()
            if existing and existing[0].get("parsed_at"):
                print(f"  {ticker} {fiscal_year} Ã¢ÂÂ dÃÂ©jÃÂ  parsÃÂ©, skip")
                continue
        
        print(f"  TÃÂ©lÃÂ©chargement {ticker} {fiscal_year}...")
        try:
            pdf_r = requests.get(url, headers=headers, timeout=60, verify=False)
            if pdf_r.status_code != 200:
                print(f"    Ã¢ÂÂ HTTP {pdf_r.status_code}")
                continue
            
            pdf_bytes = pdf_r.content
            if not pdf_bytes[:4] == b"%PDF":
                print(f"    Ã¢ÂÂ Pas un PDF valide")
                continue
            
            # Extraire les donnÃÂ©es
            fin_data = extract_financials_from_pdf(pdf_bytes, ticker)
            if not fin_data:
                print(f"    Ã¢ÂÂ Aucune donnÃÂ©e extraite")
                continue
            
            # Calculer les ratios
            ticker_meta = requests.get(
                f"{SUPABASE_URL}/rest/v1/brvm_meta?ticker=eq.{ticker}&select=last_close",
                headers=HEADERS_SB, timeout=10
            ).json()
            cours = ticker_meta[0].get("last_close") if ticker_meta else None
            
            ratios   = compute_ratios(fin_data, cours)
            row_data = {**fin_data, **ratios,
                        "ticker": ticker, "fiscal_year": fiscal_year,
                        "period_type": period_type,
                        "source_url": url,
                        "source_type": "pdf_annuel", "parsed_at": now}
            
            # Upsert dans brvm_financials
            upsert_url = f"{SUPABASE_URL}/rest/v1/brvm_financials"
            r = requests.post(upsert_url,
                headers={**HEADERS_SB, "Prefer": "resolution=merge-duplicates"},
                json=row_data, timeout=15)
            
            if r.status_code in (200, 201):
                print(f"    Ã¢ÂÂ {ticker} {fiscal_year}: CA={fin_data.get('ca','?')}M, RN={fin_data.get('rn','?')}M")
                ok_count += 1
                
                # Mettre ÃÂ  jour brvm_fundamentals avec les donnÃÂ©es les plus rÃÂ©centes
                if period_type == "annual":
                    fund_update = {k: v for k, v in {**fin_data, **ratios}.items()
                                   if k in ["ca","rn","ebitda","cap_propres","bpa","dividende",
                                            "roe","roa","marge_nette","marge_op","debt_equity"]}
                    fund_update["fiscal_year"] = fiscal_year
                    requests.patch(
                        f"{SUPABASE_URL}/rest/v1/brvm_fundamentals?ticker=eq.{ticker}",
                        headers=HEADERS_SB, json=fund_update, timeout=10)
                else:
                    print(f"    semestriel {ticker} {fiscal_year} — financials seulement")
            else:
                print(f"    Ã¢ÂÂ Supabase {r.status_code}: {r.text[:100]}")
        
        except Exception as e:
            print(f"    Ã¢ÂÂ Erreur {ticker}: {e}")
    
    print(f"\n[RAPPORTS] {ok_count}/{len(pdf_entries)} rapports traitÃÂ©s")


if __name__ == "__main__":
    main()

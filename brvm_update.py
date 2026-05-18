#!/usr/bin/env python3
"""
BRVM Daily Updater
Scrape brvm.org → Supabase
Source unique : brvm.org (pas de dépendance GitHub/Fredysessie)
"""

import os
import re
import sys
import json
import time
import requests
from datetime import datetime, date, timezone

# ─── Configuration ───────────────────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://jblrvlmxrjkwcpadcmny.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "sb_publishable_kv6SyXEAcc4vi3wgKjofmQ_kaZ-pb0f")

HEADERS_SB = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates",
}

BRVM_URL  = "https://www.brvm.org/fr/cours-actions/0"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"

TODAY = date.today().strftime("%Y-%m-%d")

TICKERS_KNOWN = {
    "ABJC","BICB","BICC","BNBC","BOAB","BOABF","BOAC","BOAM","BOAN","BOAS",
    "CABC","CBIBF","CFAC","CIEC","ECOC","ETIT","FTSC","LNBB","NEIC","NSBC",
    "NTLC","ONTBF","ORAC","ORGT","PALC","PRSC","SAFC","SCRC","SDCC","SDSC",
    "SEMC","SGBC","SHEC","SIBC","SICC","SIVC","SLBC","SMBC","SNTS","SOGC",
    "SPHC","STAC","STBC","SVOC","TTLC","TTLS","UNLC","UNXC",
}

# ─── Helpers ─────────────────────────────────────────────────────────────────

def clean(s: str) -> str:
    """Supprime les espaces insécables et caractères parasites."""
    return re.sub(r"[\u00a0\u202f\s]+", "", s.strip())

def to_float(s: str):
    try:
        return float(clean(s).replace(",", "."))
    except (ValueError, AttributeError):
        return None

def to_int(s: str):
    try:
        return int(float(clean(s).replace(",", ".")))
    except (ValueError, AttributeError):
        return None

# ─── Vérification doublon ─────────────────────────────────────────────────────

def today_already_in_supabase() -> bool:
    """Retourne True si des lignes pour TODAY existent déjà dans Supabase."""
    url = f"{SUPABASE_URL}/rest/v1/brvm_prices?date=eq.{TODAY}&limit=1&select=ticker"
    try:
        resp = requests.get(url, headers=HEADERS_SB, timeout=15)
        data = resp.json()
        return isinstance(data, list) and len(data) > 0
    except Exception as e:
        print(f"  ⚠ Erreur vérification doublon : {e}")
        return False

# ─── Scraping brvm.org ────────────────────────────────────────────────────────

def scrape_brvm() -> list[dict]:
    """
    Scrape la page de cours de brvm.org.
    Retourne une liste de dict {ticker, date, open, high, low, close, volume}.
    """
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "fr-FR,fr;q=0.9"}
    try:
        resp = requests.get(BRVM_URL, headers=headers, timeout=30, verify=False)
        resp.raise_for_status()
    except requests.exceptions.SSLError:
        print("  ⚠ SSL error — retry sans vérification SSL")
        resp = requests.get(BRVM_URL, headers=headers, timeout=30, verify=False)
    except Exception as e:
        print(f"  ❌ Erreur fetch brvm.org : {e}")
        return []

    html = resp.text
    rows = []

    # Chercher toutes les lignes <tr> contenant un lien vers /fr/cours/<ticker>
    tr_pattern = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
    td_pattern = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL | re.IGNORECASE)
    tag_pattern = re.compile(r"<[^>]+>")

    for tr_match in tr_pattern.finditer(html):
        tr = tr_match.group(1)

        # Détecter le ticker via le lien /fr/cours/TICKER
        ticker_m = re.search(r"/fr/cours/([A-Z]{3,6})", tr, re.IGNORECASE)
        if not ticker_m:
            continue
        ticker = ticker_m.group(1).upper()

        # Filtrer sur les tickers connus (ignore les lignes parasites)
        if ticker not in TICKERS_KNOWN:
            continue

        # Extraire toutes les cellules, nettoyer le HTML
        tds = [clean(tag_pattern.sub("", td.group(1))) for td in td_pattern.finditer(tr)]
        tds = [t for t in tds if t]  # virer les cellules vides

        if len(tds) < 2:
            continue

        # Colonnes attendues sur brvm.org (ordre variable selon la page) :
        # Valeur | Référence | Cours | Variation% | Ouverture | Haut | Bas | Volume | Capital
        # On essaie plusieurs stratégies de parsing

        close = high = low = open_ = volume = None

        # Stratégie 1 : chercher dans l'ordre les valeurs numériques connues
        numerics = []
        for t in tds:
            v = to_float(t)
            if v is not None and v > 0:
                numerics.append(v)

        if len(numerics) >= 1:
            close = numerics[0]

        # Essayer de trouver open/high/low si assez de colonnes
        if len(numerics) >= 4:
            # brvm.org : Cours | Var% | Open | High | Bas | Vol
            close = numerics[0]
            open_ = numerics[2] if len(numerics) > 2 else close
            high  = numerics[3] if len(numerics) > 3 else close
            low   = numerics[4] if len(numerics) > 4 else close

        # Volume : chercher le dernier entier cohérent (> 0, sans décimale utile)
        for t in reversed(tds):
            v = to_int(t)
            if v is not None and v >= 0:
                volume = v
                break

        if close is None or close <= 0:
            continue

        rows.append({
            "ticker": ticker,
            "date":   TODAY,
            "open":   open_ or close,
            "high":   high  or close,
            "low":    low   or close,
            "close":  close,
            "volume": volume or 0,
        })

    return rows

# ─── Upsert Supabase ──────────────────────────────────────────────────────────

def upsert_supabase(rows: list[dict]) -> int:
    if not rows:
        return 0
    url = f"{SUPABASE_URL}/rest/v1/brvm_prices"
    # Envoyer par batch de 50
    inserted = 0
    for i in range(0, len(rows), 50):
        batch = rows[i:i+50]
        resp = requests.post(url, headers=HEADERS_SB, json=batch, timeout=30)
        if resp.status_code in (200, 201):
            inserted += len(batch)
        else:
            print(f"  ⚠ Supabase upsert error {resp.status_code}: {resp.text[:300]}")
    return inserted

def update_meta(rows: list[dict]):
    """Met à jour brvm_meta avec le dernier close/volume de chaque ticker."""
    ticker_latest = {}
    for r in rows:
        t = r["ticker"]
        if t not in ticker_latest or r["date"] > ticker_latest[t]["date"]:
            ticker_latest[t] = r

    url = f"{SUPABASE_URL}/rest/v1/brvm_meta"
    now = datetime.now(timezone.utc).isoformat()
    for t, r in ticker_latest.items():
        meta = {
            "ticker":       t,
            "last_updated": now,
            "last_close":   r.get("close"),
            "last_volume":  r.get("volume"),
        }
        requests.post(url, headers=HEADERS_SB, json=meta, timeout=15)

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print(f"🕐 BRVM Daily Updater — {TODAY}")
    print("=" * 50)

    # Vérifier si données déjà présentes
    if today_already_in_supabase():
        print(f"ℹ  Données du {TODAY} déjà présentes dans Supabase — rien à faire.")
        sys.exit(0)

    # Scrape brvm.org
    print(f"📡 Scraping brvm.org...")
    rows = scrape_brvm()
    print(f"   {len(rows)} tickers récupérés depuis brvm.org")

    if not rows:
        print("⚠  Aucune donnée récupérée — brvm.org peut ne pas avoir encore publié les cours du jour.")
        sys.exit(1)

    # Upsert
    print(f"📤 Envoi vers Supabase...")
    inserted = upsert_supabase(rows)
    print(f"✅ {inserted} lignes upsertées")

    # Meta
    update_meta(rows)
    print(f"📊 {len({r['ticker'] for r in rows})} tickers mis à jour dans brvm_meta")
    print(f"🕐 Terminé : {datetime.now().strftime('%H:%M:%S')}")

if __name__ == "__main__":
    # Supprimer le warning SSL urllib3
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    main()

import json
import os
import re
import time

import requests

# Trumf (NorgesGruppen) — henter kjøpshistorikk ved å scrape RSC-payloaden
# fra www.trumf.no/trumf-profil/kvitteringer (det gamle REST-API-et
# platform-rest-prod.ngdata.no/trumf/husstand/… svarer 404, lagt ned ~nov 2025).
# Auth: session-cookie (TRUMF_TOKEN) kopiert fra en innlogget trumf.no-nettleser.
BASE = "https://www.trumf.no"
RECEIPTS_PATH = "/trumf-profil/kvitteringer"
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "nb-NO,nb;q=0.9,en;q=0.8",
}


def _extract_json_after(html, key):
    """Finn og parse JSON-verdien som følger '<key>\"' i RSC-escaped HTML."""
    marker = key + r'\"'
    at = html.find(marker)
    if at < 0:
        return None
    i = at + len(marker)
    while i < len(html) and html[i] not in ('[', '{'):
        i += 1
    if i >= len(html):
        return None
    open_ch = html[i]
    close_ch = ']' if open_ch == '[' else '}'
    depth = 0
    in_str = False
    j = i
    n = len(html)
    while j < n:
        c = html[j]
        nxt = html[j + 1] if j + 1 < n else ''
        if c == '\\' and nxt == '"':
            # RSC flytt: strengar er avgrensa av \" — kvar forekomst slår av/på.
            in_str = not in_str
            j += 2
            continue
        if c == '\\':
            # Annan escape (t.d. \\) — hopp over teiknet, endrar ikkje tilstand.
            j += 2
            continue
        if in_str:
            j += 1
            continue
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                j += 1
                break
        j += 1
    raw = html[i:j]
    unescaped = raw.replace('\\"', '"').replace('\\\\', '\\').replace('"$D', '"')
    try:
        return json.loads(unescaped)
    except (json.JSONDecodeError, ValueError):
        return None


def _fetch_page(path, cookie):
    res = requests.get(
        BASE + path,
        headers={**BROWSER_HEADERS, "Cookie": cookie},
        timeout=30,
    )
    res.raise_for_status()
    return res.text


def fetch_trumf_items(batch_id, cookie):
    try:
        html = _fetch_page(f"{RECEIPTS_PATH}/{batch_id}", cookie)
        details = _extract_json_after(html, "purchaseDetails")
        if not details:
            return []
        items = []
        for line in details.get("varelinjer", []):
            name = (line.get("produktBeskrivelse") or "").strip()
            qty = float(line.get("antall", 1) or 1)
            amt = float(line.get("belop", 0) or 0)
            if not name or qty <= 0:
                continue
            ean = str(line.get("ean") or "")
            items.append({
                "name": name,
                "quantity": qty,
                "amount": amt,
                # Trumf gir ikke lenger EAN (alt "$undefined" fra sept 2026)
                "ean": ean if re.fullmatch(r"\d{8,14}", ean) else None,
            })
        return items
    except Exception as e:
        print(f"⚠️ Kunne ikke hente varelinjer for Trumf-tur {batch_id}: {e}")
        return []


def fetch_trumf_data(skip_ids=None):
    if skip_ids is None:
        skip_ids = set()

    cookie = os.getenv("TRUMF_TOKEN")
    if not cookie:
        print("ℹ️ TRUMF_TOKEN ikke satt, hopper over Trumf.")
        return []

    print("🛒 Henter transaksjoner fra Trumf (Kiwi/Meny/Spar)...")
    try:
        html = _fetch_page(RECEIPTS_PATH, cookie)
    except Exception as e:
        print(f"❌ Kunne ikke laste Trumf-siden: {e}")
        raise

    transactions = _extract_json_after(html, "transactionsData")
    if not transactions:
        print("❌ Ingen transaksjonsdata i Trumf-siden (cookie utløpt?).")
        raise RuntimeError("ingen Trumf-data i siden")

    print(f"   Trumf: {len(transactions)} handleturer")

    receipts = []
    for t in transactions:
        batch_id = str(t.get("batchId", ""))
        date_str = str(t.get("transaksjonsTidspunkt", ""))[:10]
        if not batch_id or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
            continue
        if t.get("harKvittering") is False:
            continue

        receipt = {
            "date": date_str,
            "payee": t.get("beskrivelse", "Trumf"),
            "amount": float(t.get("belop", 0)),
            "batch_id": batch_id,
        }
        if batch_id in skip_ids:
            receipts.append({**receipt, "items": [], "is_skipped": True})
            continue
        receipts.append({**receipt, "items": fetch_trumf_items(batch_id, cookie), "is_skipped": False})
        time.sleep(0.5)
    return receipts

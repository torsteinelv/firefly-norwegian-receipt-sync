import datetime
import os
import re
import time

import requests

# Trumf-nettsiden (Auth.js) henter kvitteringene fra NorgesGruppens API med en
# token som ligger i /api/auth/session. Vi bruker nettleser-cookien (TRUMF_TOKEN)
# til å hente den tokenen, og kaller så samme API som nettsiden.
API = "https://platform-rest-prod.ngdata.no"
SESSION_URL = "https://www.trumf.no/api/auth/session"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
FELTER = "dato,beskrivelse,kjedeid,partnerid,batchid,belop,trumf,ekstratrumf,trumfvisa,literbensin,trumftotal"


def _finn_token(obj, sti=""):
    """Første tekstfelt med 'token' i navnet og lengde > 20: (sti, verdi), ellers None."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and re.search("token", k, re.I) and len(v) > 20:
                return f"{sti}.{k}".lstrip("."), v
            funnet = _finn_token(v, f"{sti}.{k}")
            if funnet:
                return funnet
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            funnet = _finn_token(v, f"{sti}[{i}]")
            if funnet:
                return funnet
    return None


def _feltnavn(obj, sti="", ut=None):
    """Bare feltnavn og typer (aldri verdier) - til feilsøking."""
    ut = [] if ut is None else ut
    if isinstance(obj, dict):
        for k, v in obj.items():
            ut.append(f"{sti}.{k}".lstrip(".") + f":{type(v).__name__}")
            _feltnavn(v, f"{sti}.{k}", ut)
    elif isinstance(obj, list) and obj:
        _feltnavn(obj[0], f"{sti}[]", ut)
    return ut


def _dato(t):
    batch = str(t.get("batchid", ""))
    d = str(t.get("dato", ""))[:10]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
        return d
    return f"20{batch[0:2]}-{batch[2:4]}-{batch[4:6]}"


def fetch_trumf_items(batch_id, api_headers):
    try:
        res = requests.get(f"{API}/trumf/husstand/transaksjoner/detaljer/{batch_id}",
                           headers=api_headers, timeout=15)
        res.raise_for_status()
        linjer = res.json()
        if isinstance(linjer, dict):
            linjer = linjer.get("varer", linjer.get("linjer", []))
        items = []
        for d in linjer:
            items.append({
                "name": d.get("vareTekst") or d.get("produktBeskrivelse") or "Ukjent vare",
                "quantity": float(d.get("antall", 1) or 1),
                "amount": float(d.get("belop", 0) or 0),
                "ean": d.get("ean"),
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
        res = requests.get(SESSION_URL, headers={"User-Agent": UA, "Cookie": cookie}, timeout=15)
        res.raise_for_status()
        sesjon = res.json()
    except Exception as e:
        print(f"❌ Kunne ikke hente Trumf-sesjon: {e}")
        raise

    funnet = _finn_token(sesjon)
    if not funnet:
        print(f"❌ Ingen token i {SESSION_URL} (cookie utløpt, eller tokenen ligger et annet sted).")
        print(f"   Diagnose: status={res.status_code}, felter i svaret: {_feltnavn(sesjon)[:30]}")
        raise RuntimeError("ingen Trumf-token i sesjonen")
    sti, token = funnet
    print(f"   Trumf: token funnet i feltet '{sti}'")
    api_headers = {
        "User-Agent": UA,
        "Accept": "application/json",
        "Authorization": token if token.lower().startswith("bearer ") else f"Bearer {token}",
    }

    i_dag = datetime.date.today()
    try:
        res = requests.get(f"{API}/trumf/husstand/transaksjoner", headers=api_headers, timeout=30, params={
            "felter": FELTER,
            "fra": (i_dag - datetime.timedelta(days=730)).isoformat(),
            "til": (i_dag + datetime.timedelta(days=1)).isoformat(),
            "format": "crm",
        })
        if res.status_code >= 400:
            print(f"❌ Trumf-API svarte {res.status_code}: {res.text[:300]!r}")
        res.raise_for_status()
        transaksjoner = res.json()
    except Exception as e:
        print(f"❌ Feil ved henting av Trumf-data: {e}")
        raise
    print(f"   Trumf: {len(transaksjoner)} handleturer, felter: {_feltnavn(transaksjoner)[:15]}")

    receipts = []
    for t in transaksjoner:
        batch_id = str(t["batchid"])
        kvittering = {
            "date": _dato(t),
            "payee": t.get("beskrivelse", "Trumf"),
            "amount": float(t.get("belop", 0)),
            "batch_id": batch_id,
        }
        if batch_id in skip_ids:
            receipts.append({**kvittering, "items": [], "is_skipped": True})
            continue
        receipts.append({**kvittering, "items": fetch_trumf_items(batch_id, api_headers), "is_skipped": False})
        time.sleep(0.5)
    return receipts

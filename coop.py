import os
import requests

API_BASE = "https://api.coop.no"
ISSUER = "https://login.coop.no/"
# Auth0 sin standard token-endepunkt-konvensjon ({issuer}oauth/token) - IKKE
# eksplisitt bekreftet mot Coop sin egen APK-dekompilering (kilden ga kun
# issuer + /.well-known/openid-configuration, ikke selve token-URL-en). Sjekk
# https://login.coop.no/.well-known/openid-configuration sitt
# "token_endpoint"-felt hvis dette feiler.
TOKEN_URL = f"{ISSUER}oauth/token"

# Reverse-engineert fra Coop Medlem-appen (Android APK) - se
# https://helgesver.re/articles/reverse-engineering-norwegian-grocery-apps
# MERK: Coop bruker BankID (Aera SDK, api.aerahost.com) for Strong Customer
# Authentication (SCA) ved førstegangs-innlogging - vesentlig tyngre
# bootstrap enn Trumf/Rema. COOP_REFRESH_TOKEN hentes manuelt med
# bootstrap_oauth.py (krever ekte BankID-innlogging i nettleser), og det er
# uklart fra kildematerialet hvor lenge Coop sin refresh_token faktisk
# lever før SCA må gjøres på nytt - anta at denne må fornyes manuelt oftere
# enn Trumf/Rema sine til det motsatte er bekreftet.


def _refresh_access_token(refresh_token):
    res = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": os.getenv("COOP_CLIENT_ID", ""),
        },
        timeout=10,
    )
    res.raise_for_status()
    return res.json()


def _headers(access_token):
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }


def _fetch_coop_items(summary_id, headers):
    url = f"{API_BASE}/user/pay/history/details"
    try:
        res = requests.get(url, headers=headers, params={"summaryId": summary_id}, timeout=10)
        res.raise_for_status()
        detail = res.json()
        items = []
        for line in detail.get("lines", []):
            items.append({
                "name": line.get("productName", "Ukjent vare"),
                "quantity": float(line.get("quantity", 1)),
                "amount": float(line.get("amount", 0)),
            })
        return items
    except Exception as e:
        print(f"⚠️ Kunne ikke hente varelinjer for Coop-kjøp {summary_id}: {e}")
        return []


def fetch_coop_data(skip_ids=None):
    if skip_ids is None:
        skip_ids = set()

    refresh_token = os.getenv("COOP_REFRESH_TOKEN")
    if not refresh_token:
        print("ℹ️ COOP_REFRESH_TOKEN ikke satt, hopper over Coop.")
        return []

    print("🛒 Henter transaksjoner fra Coop (Extra/Obs/Mega/Prix)...")
    try:
        token_data = _refresh_access_token(refresh_token)
        access_token = token_data["access_token"]
    except Exception as e:
        print(f"❌ Kunne ikke fornye Coop-token (COOP_REFRESH_TOKEN kan være utløpt, ev. krever ny BankID-SCA - kjør bootstrap_oauth.py på nytt): {e}")
        return []

    headers = _headers(access_token)
    url = f"{API_BASE}/user/pay/history/list"

    try:
        res = requests.get(url, headers=headers, timeout=15)
        res.raise_for_status()
        purchases = res.json()

        receipts = []
        for p in purchases.get("purchases", purchases if isinstance(purchases, list) else []):
            summary_id = p.get("summaryId")
            batch_id = f"coop-{summary_id}"
            date_str = (p.get("purchaseDate") or "")[:10]
            if not date_str:
                continue

            if batch_id in skip_ids:
                receipts.append({
                    "date": date_str,
                    "payee": p.get("storeName", "Coop"),
                    "amount": float(p.get("amount", 0)),
                    "batch_id": batch_id,
                    "items": [],
                    "is_skipped": True,
                })
                continue

            items = _fetch_coop_items(summary_id, headers)
            receipts.append({
                "date": date_str,
                "payee": p.get("storeName", "Coop"),
                "amount": float(p.get("amount", 0)),
                "batch_id": batch_id,
                "items": items,
                "is_skipped": False,
            })
        return receipts
    except Exception as e:
        print(f"❌ Feil ved henting av Coop-data: {e}")
        return []

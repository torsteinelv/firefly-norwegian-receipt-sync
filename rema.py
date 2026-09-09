import os
import requests

TOKEN_URL = "https://id.rema.no/token"
API_BASE = "https://api.rema.no"
CLIENT_ID = "android-251010"
# Offentlig kjent verdi (hardkodet i sjølve Android-APK-en, se
# https://helgesver.re/articles/reverse-engineering-norwegian-grocery-apps)
# - likevel som env var med denne som default, ikke hardkodet rått i kilden.
SUBSCRIPTION_KEY = os.getenv("REMA_SUBSCRIPTION_KEY", "fb5e24884b504d0bad761098f77e6605")

# Reverse-engineert fra Æ-appen (Android APK) - se
# https://helgesver.re/articles/reverse-engineering-norwegian-grocery-apps
# Samme kategori teknikk som trumf.py bruker mot trumf.no, bare med et ekte
# OAuth2/PKCE-token i stedet for en rå cookie. REMA_REFRESH_TOKEN hentes ÉN
# gang manuelt med bootstrap_oauth.py, ikke noe denne modulen selv kan gjøre
# (krever ekte innlogging i nettleser).


def _refresh_access_token(refresh_token):
    res = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": CLIENT_ID,
        },
        timeout=10,
    )
    res.raise_for_status()
    return res.json()


def _headers(access_token):
    return {
        "Authorization": f"Bearer {access_token}",
        "ocp-apim-subscription-key": SUBSCRIPTION_KEY,
        "x-platform": "android",
        "x-device-id": "firefly-norwegian-receipt-sync",
        "x-app": "bella",
        "x-app-version": "3.0.12",
    }


def _fetch_rema_items(transaction_id, headers):
    url = f"{API_BASE}/v1/bella/transaction/v2/rows/{transaction_id}"
    try:
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        rows = res.json()
        items = []
        for row in rows.get("rows", rows if isinstance(rows, list) else []):
            items.append({
                "name": row.get("prodtxt1", "Ukjent vare"),
                "quantity": float(row.get("quantity", 1)),
                "amount": float(row.get("amount", 0)),
            })
        return items
    except Exception as e:
        print(f"⚠️ Kunne ikke hente varelinjer for Rema-kjøp {transaction_id}: {e}")
        return []


def fetch_rema_data(skip_ids=None):
    if skip_ids is None:
        skip_ids = set()

    refresh_token = os.getenv("REMA_REFRESH_TOKEN")
    if not refresh_token:
        print("ℹ️ REMA_REFRESH_TOKEN ikke satt, hopper over Rema 1000.")
        return []

    print("🛒 Henter transaksjoner fra Rema 1000 (Æ)...")
    try:
        token_data = _refresh_access_token(refresh_token)
        access_token = token_data["access_token"]
    except Exception as e:
        print(f"❌ Kunne ikke fornye Rema-token (REMA_REFRESH_TOKEN kan være utløpt - kjør bootstrap_oauth.py på nytt): {e}")
        return []

    headers = _headers(access_token)
    url = f"{API_BASE}/v1/bella/transaction/v2/heads"

    try:
        res = requests.get(url, headers=headers, timeout=15)
        res.raise_for_status()
        heads = res.json()

        receipts = []
        for head in heads.get("heads", heads if isinstance(heads, list) else []):
            batch_id = f"rema-{head.get('id')}"
            purchase_ms = head.get("purchaseDate")
            date_str = (
                __import__("datetime")
                .datetime.utcfromtimestamp(purchase_ms / 1000)
                .strftime("%Y-%m-%d")
                if purchase_ms
                else None
            )
            if not date_str:
                continue

            if batch_id in skip_ids:
                receipts.append({
                    "date": date_str,
                    "payee": head.get("storeName", "Rema 1000"),
                    "amount": float(head.get("amount", 0)),
                    "batch_id": batch_id,
                    "items": [],
                    "is_skipped": True,
                })
                continue

            items = _fetch_rema_items(head.get("id"), headers)
            receipts.append({
                "date": date_str,
                "payee": head.get("storeName", "Rema 1000"),
                "amount": float(head.get("amount", 0)),
                "batch_id": batch_id,
                "items": items,
                "is_skipped": False,
            })
        return receipts
    except Exception as e:
        print(f"❌ Feil ved henting av Rema-data: {e}")
        return []

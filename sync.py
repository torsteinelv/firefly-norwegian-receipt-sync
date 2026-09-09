import os
import sys
import datetime
import re
import requests
from dotenv import load_dotenv

from trumf import fetch_trumf_data
from rema import fetch_rema_data
from coop import fetch_coop_data
from classifier import splitt_kvittering_til_actual

load_dotenv()

FIREFLY_URL = os.getenv("FIREFLY_INSTANCE_URL")
FIREFLY_PAT = os.getenv("FIREFLY_PAT")
SOURCE_ACCOUNT = os.getenv("FIREFLY_ASSET_ACCOUNT")

if FIREFLY_URL and FIREFLY_URL.endswith('/'):
    FIREFLY_URL = FIREFLY_URL[:-1]

headers = {
    "Authorization": f"Bearer {FIREFLY_PAT}",
    "Accept": "application/json",
    "Content-Type": "application/json"
}


def validate_environment():
    missing = [v for v, val in {
        "FIREFLY_INSTANCE_URL": FIREFLY_URL,
        "FIREFLY_PAT": FIREFLY_PAT,
        "FIREFLY_ASSET_ACCOUNT": SOURCE_ACCOUNT
    }.items() if not val]

    if missing:
        print(f"❌ Mangler miljøvariabler: {', '.join(missing)}")
        sys.exit(1)


def hent_firefly_status():
    url = f"{FIREFLY_URL}/api/v1/transactions"
    params = {"limit": 1000}

    prosessert_batch_ids = set()
    ubehandlede_bank_transaksjoner = []
    firefly_vare_cache = {}  # 🔥 Vi lagrer alle tidligere varer her!

    res = requests.get(url, headers=headers, params=params, timeout=10)
    res.raise_for_status()
    data = res.json()

    for tx_group in data.get("data", []):
        group_id = tx_group["id"]
        attributes = tx_group.get("attributes", {})
        splits = attributes.get("transactions", [])

        if not splits: continue

        first_split = splits[0]
        if first_split.get("source_name") != SOURCE_ACCOUNT:
            continue

        notes = first_split.get("notes", "")
        bank_ext_id = first_split.get("external_id", "")

        # Generisk "Batch: <kilde>-<id>" - matcher trumf-/rema-/coop-batcher
        # med samme regex, siden kilden allerede er kodet inn i selve
        # batch-ID-en (se merge_and_prefix_batch_ids under).
        batch_match = re.search(r"Batch:\s*(\S+)", notes) if notes else None

        if batch_match:
            prosessert_batch_ids.add(batch_match.group(1))

            # 🔥 LÆR FRA FIREFLY: Vi ser igjennom de tidligere splittene
            for split in splits:
                varenavn = split.get("description")
                kategori = split.get("category_name")
                if varenavn and kategori and varenavn != "Rabatter / Pant / Avrunding":
                    firefly_vare_cache[varenavn] = kategori

        elif len(splits) == 1 and first_split.get("type") == "withdrawal":
            ubehandlede_bank_transaksjoner.append({
                "group_id": group_id,
                "amount": float(first_split["amount"]),
                "date": first_split["date"][:10],
                "description": first_split["description"],
                "destination_name": first_split.get("destination_name", "Ukjent butikk"),
                "external_id": bank_ext_id
            })

    return prosessert_batch_ids, ubehandlede_bank_transaksjoner, firefly_vare_cache


def finn_matchende_banktransaksjon(kvittering_dato, kvittering_belop, ubehandlede_txs):
    q_dato = datetime.datetime.strptime(kvittering_dato, "%Y-%m-%d").date()

    for tx in ubehandlede_txs:
        tx_dato = datetime.datetime.strptime(tx["date"], "%Y-%m-%d").date()
        dager_forskjell = (tx_dato - q_dato).days
        if abs(tx["amount"] - float(kvittering_belop)) < 0.01 and 0 <= dager_forskjell <= 4:
            return tx

    return None


def hent_alle_kvitteringer(skip_ids):
    """Henter fra alle tre kilder. Trumf sin batch_id er et rått tall
    ("260315") - prefikser den her (ikke i trumf.py selv, for å ikke røre
    den allerede fungerende koden) slik at alle tre kildene har samme
    "<kilde>-<id>"-format som rema.py/coop.py allerede produserer selv."""
    alle = []

    for r in fetch_trumf_data(skip_ids={bid[len("trumf-"):] for bid in skip_ids if bid.startswith("trumf-")}):
        r["batch_id"] = f"trumf-{r['batch_id']}"
        alle.append(r)

    alle.extend(fetch_rema_data(skip_ids=skip_ids))
    alle.extend(fetch_coop_data(skip_ids=skip_ids))

    return alle


def run_sync_process():
    validate_environment()

    print(f"🔌 Kobler til Firefly III for å lese bankstatus ({SOURCE_ACCOUNT})...")
    prosessert_ids, ubehandlede_txs, firefly_cache = hent_firefly_status()
    print(f"🔍 Fant {len(prosessert_ids)} allerede ferdige handleturer.")
    print(f"🏦 Fant {len(ubehandlede_txs)} potensielle nye bank-transaksjoner å matche mot.")
    print(f"🧠 Firefly-fasit har lært {len(firefly_cache)} varer fra historikken din!")

    alle_kvitteringer = hent_alle_kvitteringer(skip_ids=prosessert_ids)
    alle_kvitteringer.sort(key=lambda x: x['date'])

    oppdaterte_turer = 0

    for r in alle_kvitteringer:
        if r.get('is_skipped', False) or r['batch_id'] in prosessert_ids:
            continue

        print(f"\n🛒 Sjekker ny handletur: {r['date']} - {r['payee']} ({r['amount']} kr)")

        match = finn_matchende_banktransaksjon(r['date'], r['amount'], ubehandlede_txs)

        if not match:
            print(f"   ⏳ Ingen match i banken ennå. Venter til bank-synken får hentet denne!")
            continue

        print(f"   🎯 MATCH FUNNET i banken! Oppdaterer (Bankdato: {match['date']})")

        vare_linjer = splitt_kvittering_til_actual(r['items'], firefly_cache)
        splits = []
        sub_sum = 0.0

        bank_ext_id = match.get("external_id")

        for i, vare in enumerate(vare_linjer):
            amount = float(vare['amount'])
            sub_sum += amount
            qty_prefix = f"{vare['quantity']}x " if 'quantity' in vare else ""

            split_note = f"{qty_prefix}{vare['name']}"
            if i == 0:
                split_note = f"Batch: {r['batch_id']} | " + split_note

            split_obj = {
                "type": "withdrawal",
                "date": f"{r['date']}T12:00:00+01:00",
                "amount": f"{amount:.2f}",
                "description": vare['name'],
                "source_name": SOURCE_ACCOUNT,
                "destination_name": r['payee'],
                "notes": split_note
            }

            # Ingen kategori funnet i cache -> IKKE send category_name i det
            # hele tatt. Firefly sitt eget regelverk (apply_rules: true
            # under) kategoriserer da varen selv, basert på description.
            if vare['category']:
                split_obj["category_name"] = vare['category']

            if i == 0 and bank_ext_id:
                split_obj["external_id"] = bank_ext_id

            splits.append(split_obj)

        diff = float(r['amount']) - sub_sum
        if abs(diff) > 0.01:
            splits.append({
                "type": "withdrawal",
                "date": f"{r['date']}T12:00:00+01:00",
                "amount": f"{diff:.2f}",
                "description": "Rabatter / Pant / Avrunding",
                "source_name": SOURCE_ACCOUNT,
                "destination_name": r['payee'],
                "category_name": "Matvarer",
                "notes": "Automatisert justering"
            })

        payload = {
            "group_title": match['description'],
            "apply_rules": True,
            "fire_webhooks": True,
            "transactions": splits
        }

        try:
            tx_url = f"{FIREFLY_URL}/api/v1/transactions/{match['group_id']}"
            res = requests.put(tx_url, headers=headers, json=payload, timeout=15)
            res.raise_for_status()
            print(f"   ✅ Banktransaksjonen ble oppdatert og splittet med varelinjer!")
            oppdaterte_turer += 1
            prosessert_ids.add(r['batch_id'])
            ubehandlede_txs = [tx for tx in ubehandlede_txs if tx['group_id'] != match['group_id']]

            for vare in vare_linjer:
                if vare['category']:
                    firefly_cache[vare['name']] = vare['category']

        except Exception as e:
            print(f"❌ Kunne ikke oppdatere banktransaksjon i Firefly: {e}")
            if 'res' in locals(): print(f"Svar fra server: {res.text}")

    if oppdaterte_turer == 0:
        print("\nℹ️ Ingen nye kvitteringer ble oppdatert.")


def job():
    print(f"\n=== Synk startet: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
    run_sync_process()
    print("=== Jobb ferdig ===\n")


if __name__ == "__main__":
    job()

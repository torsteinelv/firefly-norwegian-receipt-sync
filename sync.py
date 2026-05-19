import os
import sys
import datetime
import re
import requests
from dotenv import load_dotenv

from trumf import fetch_trumf_data
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
    # Økt grensen kraftig for å fange opp historikken fra 2025
    params = {"limit": 1000} 
    
    prosessert_batch_ids = set()
    ubehandlede_bank_transaksjoner = []
    
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
        
        # Vi ser i notat-feltet for å finne ut om VI har fikset den
        trumf_match = re.search(r"Trumf-batch:\s*(\d+)", notes) if notes else None
        
        if trumf_match:
            prosessert_batch_ids.add(trumf_match.group(1))
        elif len(splits) == 1 and first_split.get("type") == "withdrawal":
            # Hvis den ikke har "Trumf-batch:" i notatene, og bare er 1 linje, er det banken!
            ubehandlede_bank_transaksjoner.append({
                "group_id": group_id,
                "amount": float(first_split["amount"]),
                "date": first_split["date"][:10],
                "description": first_split["description"],
                "destination_name": first_split.get("destination_name", "Ukjent butikk"),
                "external_id": bank_ext_id # Beholder bankens ID i minnet!
            })
            
    return prosessert_batch_ids, ubehandlede_bank_transaksjoner

def finn_matchende_banktransaksjon(kvittering_dato, kvittering_belop, ubehandlede_txs):
    q_dato = datetime.datetime.strptime(kvittering_dato, "%Y-%m-%d").date()
    
    for tx in ubehandlede_txs:
        tx_dato = datetime.datetime.strptime(tx["date"], "%Y-%m-%d").date()
        dager_forskjell = (tx_dato - q_dato).days
        if abs(tx["amount"] - float(kvittering_belop)) < 0.01 and 0 <= dager_forskjell <= 4:
            return tx
            
    return None

def run_sync_process():
    validate_environment()
    
    print(f"🔌 Kobler til Firefly III for å lese bankstatus ({SOURCE_ACCOUNT})...")
    prosessert_ids, ubehandlede_txs = hent_firefly_status()
    print(f"🔍 Fant {len(prosessert_ids)} allerede ferdige Trumf-turer.")
    print(f"🏦 Fant {len(ubehandlede_txs)} potensielle nye bank-transaksjoner å matche mot.")
    
    alle_kvitteringer = fetch_trumf_data(skip_ids=prosessert_ids)
    alle_kvitteringer.sort(key=lambda x: x['date'])
    
    standard_kategorier = ["Matvarer", "Ferdigmat & Ferskvare", "Godteri & Snacks", "Drikkevarer", "Energidrikk", "Husholdning & Pleie", "Snus & Tobakk", "Underholdning & Medier"]
    oppdaterte_turer = 0
    
    for r in alle_kvitteringer:
        if r.get('is_skipped', False) or r['batch_id'] in prosessert_ids:
            continue
            
        print(f"\n🛒 Sjekker ny Trumf-tur: {r['date']} - {r['payee']} ({r['amount']} kr)")
        
        match = finn_matchende_banktransaksjon(r['date'], r['amount'], ubehandlede_txs)
        
        if not match:
            print(f"   ⏳ Ingen match i banken ennå. Venter til bank-synken får hentet denne!")
            continue
            
        print(f"   🎯 MATCH FUNNET i banken! Oppdaterer (Bankdato: {match['date']})")
        
        vare_linjer = splitt_kvittering_til_actual(r['items'], standard_kategorier)
        splits = []
        sub_sum = 0.0
        
        # Vi må ta vare på bankens ID, hvis den finnes
        bank_ext_id = match.get("external_id")
        
        for i, vare in enumerate(vare_linjer):
            amount = float(vare['amount'])
            sub_sum += amount
            qty_prefix = f"{vare['quantity']}x " if 'quantity' in vare else ""
            
            # Vi skriver batch_id inn i notatfeltet på den første varen i kvitteringen
            split_note = f"{qty_prefix}{vare['name']}"
            if i == 0:
                split_note = f"Trumf-batch: {r['batch_id']} | " + split_note
            
            split_obj = {
                "type": "withdrawal",
                "date": f"{r['date']}T12:00:00+01:00",
                "amount": f"{amount:.2f}",
                "description": vare['name'],
                "source_name": SOURCE_ACCOUNT,
                "destination_name": r['payee'],
                "category_name": vare['category'],
                "notes": split_note
            }
            
            # Putt bankens ID på første split så bank-synken gjenkjenner den neste gang
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
            "group_title": f"Kvittering: {r['payee']}", # 🔥 Dette er fiksen!
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

import os
import re
import time
import requests

def fetch_trumf_items(batch_id, trumf_token):
    url = f"https://www.trumf.no/profil/kvitteringer/{batch_id}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Cookie": trumf_token
    }
    try:
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        
        clean_text = res.text.replace('\\"', '"')
        
        kvittering_match = re.search(r'"kvitteringsId":"(\d+)"', clean_text)
        kvittering_id = kvittering_match.group(1) if kvittering_match else "Ukjent"
        
        pattern = r'"produktBeskrivelse":"([^"]+)","antall":([0-9.]+),"belop":([0-9.]+)'
        matches = list(re.finditer(pattern, clean_text))
        
        items = []
        seen_items = set()
        for match in matches:
            name = match.group(1)
            qty = float(match.group(2))
            price = float(match.group(3))
            
            unique_hash = f"{name}-{qty}-{price}"
            if unique_hash not in seen_items:
                items.append({"name": name, "quantity": qty, "amount": price})
                seen_items.add(unique_hash)
        return kvittering_id, items
    except Exception as e:
        print(f"⚠️ Kunne ikke hente varelinjer for Trumf-tur {batch_id}: {e}")
        return "Ukjent", []

def fetch_trumf_data(skip_ids=None):
    if skip_ids is None:
        skip_ids = set()
        
    trumf_token = os.getenv("TRUMF_TOKEN")
    if not trumf_token:
        print("ℹ️ TRUMF_TOKEN ikke satt, hopper over Trumf.")
        return []
        
    print("🛒 Henter transaksjoner fra Trumf (Kiwi/Meny/Spar)...")
    url = "https://www.trumf.no/profil/kvitteringer"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Cookie": trumf_token
    }
    try:
        res = requests.get(url, headers=headers, timeout=15)
        res.raise_for_status() 
        
        clean_text = res.text.replace('\\"', '"')
        pattern = r'"batchId":"(\d+)","belop":([0-9.]+),"beskrivelse":"([^"]+)"'
        matches = list(re.finditer(pattern, clean_text))
        
        receipts = []
        seen_ids = set()
        
        for match in matches:
            batch_id = match.group(1)
            total_amount = float(match.group(2))
            store = match.group(3)
            
            if batch_id not in seen_ids:
                seen_ids.add(batch_id)
                date_str = f"20{batch_id[0:2]}-{batch_id[2:4]}-{batch_id[4:6]}"
                
                if batch_id in skip_ids:
                    receipts.append({
                        "date": date_str, "payee": store, "amount": total_amount,
                        "batch_id": batch_id, "kvittering_id": "Skipped", "items": [], "is_skipped": True
                    })
                    continue
                
                kvittering_id, items = fetch_trumf_items(batch_id, trumf_token)
                time.sleep(1) 
                
                receipts.append({
                    "date": date_str,
                    "payee": store,
                    "amount": total_amount,
                    "batch_id": batch_id,
                    "kvittering_id": kvittering_id,
                    "items": items,
                    "is_skipped": False
                })
        return receipts
    except Exception as e:
        print(f"❌ Feil ved henting av Trumf-data: {e}")
        return []

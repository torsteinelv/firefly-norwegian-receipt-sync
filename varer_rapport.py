"""Skriver varer.csv: alle unike varenavn fra kvitteringene, størst forbruk først.

    python varer_rapport.py [antall_uker=0 (alle)]

Gå gjennom øverste rader, legg til manglende ord i regler.json, kjør
apply_rules.py --apply, og kjør reglene på eksisterende i Firefly
(Regler > gruppen > Kjør på eksisterende). Gjenta til 'uten kategori' er lav.
"""
import csv
import os
import sys
from collections import defaultdict

import requests
from dotenv import load_dotenv

load_dotenv()
URL = os.getenv("FIREFLY_INSTANCE_URL", "").rstrip("/")
H = {"Authorization": f"Bearer {os.getenv('FIREFLY_PAT')}", "Accept": "application/json"}


def main():
    if not URL or not os.getenv("FIREFLY_PAT"):
        sys.exit("❌ FIREFLY_INSTANCE_URL / FIREFLY_PAT mangler.")
    vare = defaultdict(lambda: {"antall": 0, "sum": 0.0, "kategorier": set()})
    side = 1
    while True:
        r = requests.get(f"{URL}/api/v1/transactions", headers=H,
                         params={"type": "withdrawal", "page": side, "limit": 200}, timeout=60)
        r.raise_for_status()
        d = r.json()
        for g in d["data"]:
            for s in g["attributes"]["transactions"]:
                if "atch:" not in (s.get("notes") or ""):  # bare kvitteringer vi har splittet ("Batch:" og gamle "Trumf-batch:")
                    continue
                v = vare[s["description"]]
                v["antall"] += 1
                v["sum"] += abs(float(s["amount"]))
                v["kategorier"].add(s.get("category_name") or "")
        if side >= d["meta"]["pagination"]["total_pages"]:
            break
        side += 1
    rader = sorted(vare.items(), key=lambda kv: -kv[1]["sum"])
    with open("varer.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["vare", "antall", "sum_kr", "kategori_na"])
        for navn, v in rader:
            w.writerow([navn, v["antall"], f"{v['sum']:.2f}", " | ".join(sorted(v["kategorier"]))])
    uten = sum(v["sum"] for v in vare.values() if v["kategorier"] <= {""})
    tot = sum(v["sum"] for v in vare.values()) or 1
    print(f"{len(rader)} unike varer skrevet til varer.csv. Uten kategori: {uten / tot:.0%} av kronebeløpet.")


if __name__ == "__main__":
    main()

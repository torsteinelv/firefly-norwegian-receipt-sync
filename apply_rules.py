"""Oppretter/oppdaterer Firefly III-regler fra regler.json (idempotent).

    python apply_rules.py            # tørrkjøring, skriver bare ut
    python apply_rules.py --apply    # oppretter/oppdaterer reglene i Firefly

En regel per kategori med flere "beskrivelsen inneholder X"-vilkår der ETT
treff holder (strict=false). Reglene kjører i filens rekkefølge og første treff
stopper resten (stop_processing). Ikke testet mot en ekte Firefly - les
feilmeldingen fra API-et hvis --apply feiler.
"""
import json
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()
URL = os.getenv("FIREFLY_INSTANCE_URL", "").rstrip("/")
H = {"Authorization": f"Bearer {os.getenv('FIREFLY_PAT')}", "Accept": "application/json",
     "Content-Type": "application/json"}


def hent_alle(path):
    ut, side = [], 1
    while True:
        r = requests.get(f"{URL}/api/v1/{path}", headers=H, params={"page": side}, timeout=30)
        r.raise_for_status()
        d = r.json()
        ut += d["data"]
        if side >= d.get("meta", {}).get("pagination", {}).get("total_pages", 1):
            return ut
        side += 1


def payload(gruppe_id, tittel, kategori, ord_, rekkefolge):
    return {
        "title": tittel, "rule_group_id": gruppe_id, "order": rekkefolge,
        "trigger": "update-journal",  # sync.py oppdaterer banktransaksjonen med apply_rules=true
        "active": True, "strict": False, "stop_processing": True,
        "triggers": [{"type": "description_contains", "value": o, "order": i, "active": True,
                      "stop_processing": False} for i, o in enumerate(ord_)],
        "actions": [{"type": "set_category", "value": kategori, "order": 1, "active": True,
                     "stop_processing": False}],
    }


def main():
    apply = "--apply" in sys.argv
    if not URL or not os.getenv("FIREFLY_PAT"):
        sys.exit("❌ FIREFLY_INSTANCE_URL / FIREFLY_PAT mangler.")
    cfg = json.load(open(os.path.join(os.path.dirname(__file__), "regler.json"), encoding="utf-8"))
    for r in cfg["regler"]:
        print(f"{r['kategori']:<22} {len(r['ord'])} ord")
    if not apply:
        return print("\nTørrkjøring. Kjør med --apply for å opprette.")

    gruppe = next((g for g in hent_alle("rule-groups") if g["attributes"]["title"] == cfg["gruppe"]), None)
    if not gruppe:
        r = requests.post(f"{URL}/api/v1/rule-groups", headers=H, timeout=30,
                          json={"title": cfg["gruppe"], "active": True})
        r.raise_for_status()
        gruppe = r.json()["data"]
    gid = gruppe["id"]
    eksisterende = {x["attributes"]["title"]: x["id"] for x in hent_alle(f"rule-groups/{gid}/rules")}

    for i, r in enumerate(cfg["regler"], 1):
        tittel = f"Kategori: {r['kategori']}"
        body = payload(gid, tittel, r["kategori"], r["ord"], i)
        if tittel in eksisterende:
            res = requests.put(f"{URL}/api/v1/rules/{eksisterende[tittel]}", headers=H, json=body, timeout=30)
        else:
            res = requests.post(f"{URL}/api/v1/rules", headers=H, json=body, timeout=30)
        if res.status_code >= 300:
            sys.exit(f"❌ {tittel}: {res.status_code} {res.text}")
        print(f"✅ {tittel}")


if __name__ == "__main__":
    main()

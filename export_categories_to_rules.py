"""Engangs-script: bygger et startsett med Firefly III-regler fra
vare_cache.json (varenavn -> kategori du allerede har bekreftet, enten via
den gamle LLM-en eller manuelle rettelser i Firefly selv).

Kjøres LOKALT, ikke i k8s. Trenger samme FIREFLY_INSTANCE_URL/FIREFLY_PAT
som sync.py - hent vare_cache.json ut av firefly-receipt-cache-pvc først:

    kubectl cp firefly-iii/<pod-med-pvc-mountet>:/app/vare_cache.json ./vare_cache.json

Bruk:
    python export_categories_to_rules.py            # dry-run, skriver ut hva som VILLE blitt laget
    python export_categories_to_rules.py --apply     # oppretter reglene i Firefly

MERK: trigger-/action-type-strengene under ("description_contains",
"set_category") er IKKE 100% bekreftet mot Firefly sin egen API-kildekode -
docs.firefly-iii.org sine referansesider bruker dette navnemønsteret, men
jeg fant ikke selve enum-definisjonen for å double-checke. Dry-run FØRST,
og les feilmeldingen nøye hvis --apply feiler på første regel - Firefly sine
egne valideringsfeil er vanligvis presise nok til å vise riktig verdi.
"""

import json
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

FIREFLY_URL = os.getenv("FIREFLY_INSTANCE_URL", "").rstrip("/")
FIREFLY_PAT = os.getenv("FIREFLY_PAT")
RULE_GROUP_TITLE = "Dagligvarer (auto-generert fra vare_cache)"

headers = {
    "Authorization": f"Bearer {FIREFLY_PAT}",
    "Accept": "application/json",
    "Content-Type": "application/json",
}


def build_rule_payload(order, varenavn, kategori):
    return {
        "title": f"Kategoriser: {varenavn}",
        "rule_group_title": RULE_GROUP_TITLE,
        "order": order,
        "active": True,
        "strict": True,
        "stop_processing": False,
        "triggers": [
            {
                "type": "description_contains",
                "value": varenavn,
                "order": 0,
                "active": True,
                "stop_processing": False,
            }
        ],
        "actions": [
            {
                "type": "set_category",
                "value": kategori,
                "order": 0,
                "active": True,
                "stop_processing": False,
            }
        ],
    }


def main():
    apply = "--apply" in sys.argv

    if not FIREFLY_URL or not FIREFLY_PAT:
        print("❌ FIREFLY_INSTANCE_URL / FIREFLY_PAT mangler.")
        sys.exit(1)

    with open("vare_cache.json", "r", encoding="utf-8") as f:
        cache = json.load(f)

    print(f"Fant {len(cache)} varer i cachen.\n")

    for i, (varenavn, kategori) in enumerate(sorted(cache.items())):
        payload = build_rule_payload(i, varenavn, kategori)

        if not apply:
            print(f"[DRY RUN] '{varenavn}' -> {kategori}")
            continue

        res = requests.post(f"{FIREFLY_URL}/api/v1/rules", headers=headers, json=payload, timeout=10)
        if res.status_code >= 300:
            print(f"❌ Feilet på '{varenavn}': {res.status_code} {res.text}")
            print("   Sjekk trigger/action-type-strengene i build_rule_payload() mot feilmeldingen over.")
            sys.exit(1)
        print(f"✅ Regel opprettet: '{varenavn}' -> {kategori}")

    if not apply:
        print(f"\n{len(cache)} regler ville blitt opprettet. Kjør med --apply for å faktisk gjøre det.")


if __name__ == "__main__":
    main()

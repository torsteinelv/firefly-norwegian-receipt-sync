import os
import json

CACHE_FILE = "vare_cache.json"

if os.path.exists(CACHE_FILE):
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            local_cache = json.load(f)
    except json.JSONDecodeError:
        local_cache = {}
else:
    local_cache = {}


def splitt_kvittering_til_actual(items, firefly_cache=None):
    """Slår opp kategori for hver vare - ingen LLM lenger.

    Rekkefølge: Firefly sin egen historikk (fasit) -> lokal cache -> None.
    None betyr "ukategorisert" - Firefly sitt eget regelverk (apply_rules:
    true i sync.py sitt PUT-kall) kategoriserer varen selv, basert på
    description-feltet (varenavnet). Se export_categories_to_rules.py for
    å generere et startsett med regler fra denne cachen.
    """
    if not items:
        return []
    if firefly_cache is None:
        firefly_cache = {}

    kategoriserte_linjer = []
    for item in items:
        varenavn = item["name"]

        if "PANT" in varenavn.upper() or "RETUR" in varenavn.upper():
            kategori = "Matvarer"
        else:
            kategori = firefly_cache.get(varenavn) or local_cache.get(varenavn)

        kategoriserte_linjer.append({
            "name": varenavn,
            "amount": item["amount"],
            "category": kategori,
            "quantity": item.get("quantity", 1),
        })

    return kategoriserte_linjer

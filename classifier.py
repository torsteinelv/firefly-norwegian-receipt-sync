import os
import time

import requests

KASSALAPP_KEY = (os.getenv("KASSALAPP") or "").strip()
KASSALAPP_URL = "https://kassal.app/api/v1"


def hovedkategori(produkt):
    """Kassalapp gir kategoritreet som liste med depth (-2 = rot, 0 = blad),
    f.eks. Meieri & egg > Melk > Lettmelk. Vi bruker roten."""
    kategorier = (produkt or {}).get("category") or []
    if not kategorier:
        return None
    return min(kategorier, key=lambda k: k.get("depth", 0))["name"]


def kassalapp_kategori(varenavn, ean=None):
    """Slår opp hovedkategori i Kassalapp: EAN først, ellers fritekstsøk på
    varenavnet (Coop og Trumf gir ikke EAN). Feil gir None, aldri unntak."""
    if not KASSALAPP_KEY:
        return None
    headers = {"Authorization": f"Bearer {KASSALAPP_KEY}"}
    try:
        # ponytail: fast pause holder oss under hobby-grensen (60/min); bytt til 429-retry om den blir for treg
        time.sleep(1.05)
        if ean:
            res = requests.get(f"{KASSALAPP_URL}/products/ean/{ean}", headers=headers, timeout=15)
            if res.ok:
                for produkt in (res.json().get("data") or {}).get("products") or []:
                    if hovedkategori(produkt):
                        return hovedkategori(produkt)
            time.sleep(1.05)
        # ponytail: første søketreff er en heuristikk; avkortede kvitteringsnavn kan treffe feil vare
        res = requests.get(f"{KASSALAPP_URL}/products", headers=headers,
                           params={"search": varenavn, "size": 5}, timeout=15)
        if res.ok:
            for produkt in res.json().get("data") or []:
                if hovedkategori(produkt):
                    return hovedkategori(produkt)
    except (requests.RequestException, ValueError) as e:
        print(f"   ⚠️ Kassalapp-oppslag feilet for '{varenavn}': {e}")
    return None


def splitt_kvittering_til_actual(items, firefly_cache=None):
    """Slår opp kategori for hver vare - ingen LLM lenger.

    Rekkefølge: Firefly sin egen historikk (fasit, inkl. manuelle rettelser)
    -> Kassalapp (EAN/navn) -> None.
    None betyr "ukategorisert" - Firefly sitt eget regelverk (apply_rules:
    true i sync.py sitt PUT-kall) kategoriserer varen selv, basert på
    description-feltet (varenavnet).
    """
    if not items:
        return []
    if firefly_cache is None:
        firefly_cache = {}

    kategoriserte_linjer = []
    for item in items:
        varenavn = item["name"]

        if "PANT" in varenavn.upper() or "RETUR" in varenavn.upper():
            kategori = "Pant & rabatter"
        else:
            kategori = (firefly_cache.get(varenavn)
                        or kassalapp_kategori(varenavn, item.get("ean")))
            if kategori:
                # Samme vare flere ganger i samme kjøring -> ett oppslag
                firefly_cache[varenavn] = kategori

        kategoriserte_linjer.append({
            "name": varenavn,
            "amount": item["amount"],
            "category": kategori,
            "quantity": item.get("quantity", 1),
            "ean": item.get("ean"),
        })

    return kategoriserte_linjer


if __name__ == "__main__":
    assert hovedkategori({"category": [{"depth": 0, "name": "Lettmelk"}, {"depth": -2, "name": "Meieri & egg"},
                                       {"depth": -1, "name": "Melk"}]}) == "Meieri & egg"
    assert hovedkategori({"category": []}) is None
    assert hovedkategori(None) is None
    print("ok")

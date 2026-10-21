"""Husker fornyet refresh-token mellom kjøringer (PVC montert på TOKEN_DIR).

Tjenester som bytter ut refresh-tokenen ved hver bruk ville ellers slutte å virke
etter første kjøring, siden secreten alltid har den første tokenen. Legger du en NY
token i secreten, vinner den (vi sammenligner mot den secret-verdien lagret token kom fra).
"""
import json
import os

TOKEN_DIR = os.getenv("TOKEN_DIR", "/data/tokens")


def _fil(navn):
    return os.path.join(TOKEN_DIR, f"{navn}.json")


def hent_token(navn, fra_env):
    """Returnerer refresh-token å bruke: lagret (nyere) hvis den hører til samme secret-verdi, ellers secret."""
    try:
        with open(_fil(navn), encoding="utf-8") as f:
            lagret = json.load(f)
        if lagret.get("fra_env") == fra_env and lagret.get("token"):
            return lagret["token"]
    except (OSError, ValueError):
        pass
    return fra_env


def lagre_token(navn, fra_env, ny_token):
    try:
        os.makedirs(TOKEN_DIR, exist_ok=True)
        with open(_fil(navn), "w", encoding="utf-8") as f:
            json.dump({"fra_env": fra_env, "token": ny_token}, f)
    except OSError as e:
        print(f"⚠️ Kunne ikke lagre fornyet {navn}-token ({e}). Neste kjøring bruker secreten på nytt.")

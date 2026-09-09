"""Engangs-verktøy for å hente REMA_REFRESH_TOKEN / COOP_REFRESH_TOKEN.

Kjøres LOKALT (ikke i k8s CronJob-en) - krever en nettleser og at DU logger
inn med din egen konto (BankID for Coop). Skriver ut refresh_token-en på
slutten; lim den inn i secreten (kubeseal, se README.md).

Bruk:
    python bootstrap_oauth.py rema
    python bootstrap_oauth.py coop

Begge er reverse-engineert fra Android-appene, se
https://helgesver.re/articles/reverse-engineering-norwegian-grocery-apps -
IKKE offisielt støttede innloggingsflyter, kan slutte å virke uten varsel.

Coop-spesifikt: redirect_uri er et mobil-app-scheme
(no.coop.members://auth/callback), som ikke fanges opp av en vanlig
skrivebords-nettleser. Etter innlogging vil nettleseren vise en feilside
("kan ikke åpne siden") - koden ligger i URL-en i adressefeltet der
("...callback?code=XXXX&..."), lim inn HELE den URL-en når scriptet spør,
ikke bare koden.
"""

import base64
import hashlib
import os
import secrets
import sys
import urllib.parse

import requests

PROVIDERS = {
    "rema": {
        "auth_url": "https://id.rema.no/authorization",
        "token_url": "https://id.rema.no/token",
        "client_id": "android-251010",
        "redirect_uri": "https://ae-appen.appspot.com/redirect/redirect.html",
        "scope": "all",
    },
    "coop": {
        "auth_url": "https://login.coop.no/authorize",
        "token_url": "https://login.coop.no/oauth/token",
        # Client ID ikke funnet i kildematerialet - må fylles inn manuelt,
        # se .env.example / README.md for hvordan finne den (proxy appens
        # trafikk, f.eks. med mitmproxy, én gang).
        "client_id": os.getenv("COOP_CLIENT_ID", ""),
        "redirect_uri": "no.coop.members://auth/callback",
        "scope": "openid profile offline_access email phone address",
    },
}


def make_pkce_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(40)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in PROVIDERS:
        print(f"Bruk: python {sys.argv[0]} <rema|coop>")
        sys.exit(1)

    provider = sys.argv[1]
    cfg = PROVIDERS[provider]

    if provider == "coop" and not cfg["client_id"]:
        print("❌ COOP_CLIENT_ID er ikke satt (se docstring øverst i fila).")
        sys.exit(1)

    verifier, challenge = make_pkce_pair()

    params = {
        "response_type": "code",
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "scope": cfg["scope"],
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    auth_url = f"{cfg['auth_url']}?{urllib.parse.urlencode(params)}"

    print(f"\n1. Åpne denne URL-en i en nettleser og logg inn:\n\n{auth_url}\n")
    print("2. Etter innlogging redirectes du (eller nettleseren feiler å åpne")
    print("   redirect-URL-en, det er forventet) - kopiér HELE URL-en fra")
    print("   adressefeltet på det tidspunktet.\n")
    redirected_url = input("Lim inn hele redirect-URL-en her: ").strip()

    parsed = urllib.parse.urlparse(redirected_url)
    query = urllib.parse.parse_qs(parsed.query)
    code = query.get("code", [None])[0]
    if not code:
        print("❌ Fant ingen 'code'-parameter i URL-en du limte inn.")
        sys.exit(1)

    res = requests.post(
        cfg["token_url"],
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": cfg["redirect_uri"],
            "client_id": cfg["client_id"],
            "code_verifier": verifier,
        },
        timeout=10,
    )
    res.raise_for_status()
    tokens = res.json()

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        print("❌ Fikk ikke refresh_token tilbake. Rått svar:")
        print(tokens)
        sys.exit(1)

    env_var = "REMA_REFRESH_TOKEN" if provider == "rema" else "COOP_REFRESH_TOKEN"
    print(f"\n✅ Suksess! {env_var}=\n\n{refresh_token}\n")
    print("Legg denne i secret-template.yaml og kubeseal den (se README.md).")


if __name__ == "__main__":
    main()

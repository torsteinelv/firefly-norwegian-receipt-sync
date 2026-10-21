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

Coop-spesifikt: klient-id, redirect-adresse og evt. audience oppgis som miljøvariabler
(COOP_CLIENT_ID, COOP_REDIRECT_URI, COOP_AUDIENCE) når du logger inn, de ligger ikke i repoet.
Standard redirect er et mobil-app-scheme (no.coop.members://auth/callback), som ikke fanges
opp av en vanlig nettleser: etter innlogging vises en feilside, men koden ligger i adressen
("...callback?code=XXXX&..."). Lim inn HELE adressen når scriptet spør, ikke bare koden.
Bruker du nettsidens klient, bruk et privat vindu så nettsiden ikke bruker opp koden først.
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
        # Ingen faste verdier for klienten i repoet: oppgi dem når du logger inn.
        #   COOP_CLIENT_ID     (påkrevd) klientens id
        #   COOP_REDIRECT_URI  (valgfri) må være en adresse klienten tillater
        #   COOP_AUDIENCE      (valgfri) sendes som audience hvis satt
        "client_id": os.getenv("COOP_CLIENT_ID", ""),
        "redirect_uri": os.getenv("COOP_REDIRECT_URI", "no.coop.members://auth/callback"),
        "scope": "openid profile offline_access email phone address",
        "extra": {"audience": os.getenv("COOP_AUDIENCE")} if os.getenv("COOP_AUDIENCE") else {},
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
        print("❌ COOP_CLIENT_ID er ikke satt. Eksempel: COOP_CLIENT_ID=... COOP_REDIRECT_URI=... python bootstrap_oauth.py coop")
        sys.exit(1)

    verifier, challenge = make_pkce_pair()
    state = secrets.token_urlsafe(16)  # Rema avviser forespørselen (invalid_request) uten state

    params = {
        "response_type": "code",
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "scope": cfg["scope"],
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        **cfg.get("extra", {}),
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
    if query.get("error"):
        print(f"❌ Innloggingen ble avvist: {query['error'][0]} - {query.get('error_description', [''])[0]}")
        sys.exit(1)
    if query.get("state", [None])[0] != state:
        print("❌ state i URL-en stemmer ikke med den vi sendte. Start på nytt og lim inn URL-en fra DEN innloggingen.")
        sys.exit(1)
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

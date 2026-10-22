# firefly-norwegian-receipt-sync

Henter kvitteringer fra norske dagligvarekjeder og splitter de tilhørende
bank-transaksjonene i Firefly III til varelinjer, matchet på beløp+dato.

## Kilder

| Kilde | Kjeder | Auth | Status |
|---|---|---|---|
| Trumf | Kiwi, Meny, Spar | Cookie (manuell) | Fungerer |
| Rema 1000 | Rema 1000 | OAuth2/PKCE (Æ-appen) | Ny |
| Coop | Extra, Obs, Mega, Prix | OAuth2/OIDC (PKCE) | Ny |

Rema og Coop sine API-er er reverse-engineert fra de offisielle Android-appene
(ikke offisielt støttet, kan slutte å virke uten varsel) - se
https://helgesver.re/articles/reverse-engineering-norwegian-grocery-apps.
Trumf sitt oppsett var allerede sånn.

## Hvordan varekategorisering fungerer

**Endret:** brukte tidligere en lokal LLM (Ollama) til å gjette kategori per
vare. Fjernet - upålitelig nok til at det ikke var verdt kompleksiteten.

Nå: hver vare sjekkes mot (1) Firefly sin egen transaksjonshistorikk (varer
du/Firefly allerede har kategorisert før), så (2) Kassalapp (`KASSALAPP`-nøkkel;
EAN-oppslag, ellers navnesøk - hovedkategorien brukes, f.eks. "Meieri & egg"),
så (3) en lokal cache
(`vare_cache.json`, på PVC-en i k8s). Finnes den ikke i noen av delene,
sendes IKKE `category_name` med i det hele tatt - transaksjonen opprettes
med `apply_rules: true`, så **Firefly sitt eget regelverk** kategoriserer
den, basert på `description` (varenavnet).

Kjør `export_categories_to_rules.py` for å bygge et startsett med regler fra
det du allerede har i `vare_cache.json`.

## Oppsett

1. Kopiér `.env.example` til `.env`, fyll inn Firefly-verdiene.
2. Trumf: se den gamle fremgangsmåten (cookie fra innlogget nettleser-sesjon).
3. Rema: `python bootstrap_oauth.py rema` - logg inn i nettleseren som åpnes,
   lim inn redirect-URL-en, lim `REMA_REFRESH_TOKEN` inn i `.env`.
4. Coop: samme som Rema, men `python bootstrap_oauth.py coop` - vanlig
   brukarnamn/passord (IKKE BankID). `COOP_CLIENT_ID` er IKKE i appen (sjekket
   `libapp.so` i v4.32.0) - få den én gang ved å proxye appens trafikk
   (mitmproxy) eller fra Coop, og legg den i `.env`/secret.
5. `pip install -r requirements.txt && python sync.py` for en manuell test.
6. I k3s-gitops: kubeseal `.env`-verdiene inn i
   `firefly-receipt-sync-secrets` (samme mønster som i dag, se
   `apps/firefly-iii/receipt-sync-secrets.sealedsecret.yaml`).

## Kjente begrensninger

- Rema/Coop sine refresh-tokens har ukjent levetid - hvis synken slutter å
  finne nye kjøp derfra, kjør `bootstrap_oauth.py` på nytt for den kilden.
- `COOP_CLIENT_ID` er IKKE i appen (bekreftet ved statisk analyse av `libapp.so`,
  v4.32.0) - den må fanges én gang via proxy eller fås fra Coop.
- `bootstrap_oauth.py` sin Coop-redirect
  (`https://login.coop.no/android/no.coop.members/callback`) er appens
  registrerte Android-URL: nettleseren viser koden i adressefeltet etter
  innlogging (se docstring i fila).

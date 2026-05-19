import os
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

base_url = os.getenv("LOCAL_LLM_URL", "http://localhost:11434/v1")
model_name = os.getenv("LOCAL_LLM_MODEL", "llama3")
api_key = os.getenv("OPENAI_API_KEY", "ollama")

client = OpenAI(base_url=base_url, api_key=api_key)

CACHE_FILE = "vare_cache.json"

if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        local_cache = json.load(f)
else:
    local_cache = {}

def kategoriser_varer_med_llm(vareliste, gyldige_kategorier):
    if not vareliste: return {}

    prompt = f"""
    Du er en nøyaktig økonomi-assistent som kategoriserer norske dagligvarer for et budsjettsystem.
    
    Bruk DISSE STANDARD-KATEGORIENE så langt det overhodet lar seg gjøre:
    - "Matvarer" (Brød, grønnsaker, kjøtt, melk, ost, pålegg, kaffe)
    - "Ferdigmat & Ferskvare" (Frossenpizza, varm hamburger, sushi, ferdigsmurte baguetter)
    - "Godteri & Snacks" (Sjokolade, is, potetgull, smågodt, kjeks)
    - "Drikkevarer" (Brus, juice, farris - men IKKE energidrikk)
    - "Energidrikk" (Monster, Red Bull, Battery, Nocco)
    - "Husholdning & Pleie" (Såpe, dopapir, sjampo, vaskemiddel)
    - "Snus & Tobakk" (Snus, sigaretter)
    - "Underholdning & Medier" (Tegneserier, aviser, blader)
    
    VIKTIGE REGLER:
    1. PANT (f.eks. "PANT" eller "RETUR") skal ALLTID i "Matvarer".
    2. Svar KUN med en gyldig JSON der varen er nøkkel (key) og kategorien er verdi (value).
    3. IKKE skriv markdown-tegn (som ```json) eller introduksjon. Bare rå JSON.

    Vareliste:
    {json.dumps(vareliste, ensure_ascii=False)}
    """

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=1500
        )
        svar_tekst = response.choices[0].message.content.strip()
        if "```" in svar_tekst:
            svar_tekst = svar_tekst.split("```")[1]
            if svar_tekst.startswith("json"):
                svar_tekst = svar_tekst[4:]
            svar_tekst = svar_tekst.strip()
        return json.loads(svar_tekst)
    except Exception as e:
        print(f"⚠️ LLM feilet: {e}")
        return {vare: "Dagligvarer" for vare in vareliste}

def splitt_kvittering_til_actual(items, gyldige_kategorier):
    if not items: return []

    kategoriserte_linjer = []
    varer_som_maa_sjekkes = []
    kategori_kart = {}

    for item in items:
        varenavn = item["name"]
        if varenavn in local_cache:
            kategori_kart[varenavn] = local_cache[varenavn]
        else:
            varer_som_maa_sjekkes.append(varenavn)

    if varer_som_maa_sjekkes:
        unike_nye = list(set(varer_som_maa_sjekkes))
        print(f"🧠 Spør lokal LLM om {len(unike_nye)} nye varer...")
        llm_svar = kategoriser_varer_med_llm(unike_nye, gyldige_kategorier)
        kategori_kart.update(llm_svar)
        local_cache.update(llm_svar)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(local_cache, f, ensure_ascii=False, indent=4)

    for item in items:
        varenavn = item["name"]
        valgt_kategori = kategori_kart.get(varenavn, "Dagligvarer")
        kategoriserte_linjer.append({
            "name": varenavn,
            "amount": item["amount"],
            "category": valgt_kategori,
            "quantity": item.get("quantity", 1)
        })
        
    return kategoriserte_linjer

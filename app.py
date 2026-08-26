from flask import Flask, render_template, request, jsonify
from Bio import Entrez
from google import genai
import os
import json

app = Flask(__name__)

# Konfiguration
PUBMED_EMAIL = "josef_koenig@hotmail.com"
PUBMED_API_KEY = "2d6671c4cc19fcc9bf7c972e504abf763b09"

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
client = genai.Client(api_key=GOOGLE_API_KEY)

def search_pubmed(query: str) -> str:
    """Sucht direkt in PubMed nach medizinischer Evidenz."""
    Entrez.email = PUBMED_EMAIL
    Entrez.api_key = PUBMED_API_KEY
    try:
        handle = Entrez.esearch(db="pubmed", term=f"{query} AND (review[pt] OR guideline[pt])", retmax=3)
        record = Entrez.read(handle)
        handle.close()
        id_list = record["IdList"]
        if not id_list: 
            return "Keine PubMed-Ergebnisse gefunden."
        fetch_handle = Entrez.efetch(db="pubmed", id=id_list, rettype="abstract", retmode="xml")
        articles = Entrez.read(fetch_handle)
        fetch_handle.close()
        res = []
        for art in articles['PubmedArticle']:
            title = art['MedlineCitation']['Article'].get('ArticleTitle', 'Kein Titel')
            res.append(title)
        return "PubMed Treffer: " + " ; ".join(res)
    except Exception as e: 
        return f"PubMed Fehler: {str(e)}"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/evaluate', methods=['POST'])
def evaluate():
    data = request.json
    text = data.get('text', '')
    
    if not text:
        return jsonify({"error": "Kein Text übergeben"}), 400

    try:
        # 1. PubMed-Evidenz einholen
        pubmed_kontext = search_pubmed(text[:80])

        # 2. Agent A: Lektorat (Verwende hier das blitzschnelle Flash-Modell)
        prompt_a = f"Du bist ein akademischer Lektor. Reviewe den Text auf Grammatik, Stil und Logik: {text}"
        res_a = client.models.generate_content(model="gemini-2.5-flash", contents=prompt_a)

        # 3. Agent B: Fachprüfung
        prompt_b = (
            f"Du bist ein medizinischer Reviewer und Informatiker. Prüfe die Fakten im Text: {text}\n\n"
            f"Evidenz-Datenbankauszug:\n{pubmed_kontext}"
        )
        res_b = client.models.generate_content(model="gemini-2.5-flash", contents=prompt_b)

        # 4. Agent C: Finales JSON erzwingen (über striktes Prompting statt fehleranfälligem Schema-Mapping)
        prompt_c = (
            f"Du bist der Prüfungsvorsitzende. Erstelle ein finales Gutachten basierend auf:\n"
            f"Originaltext: {text}\n\n"
            f"Lektorat: {res_a.text}\n\n"
            f"Fachprüfung: {res_b.text}\n\n"
            f"Antworte AUSSCHLIESSLICH im folgenden JSON-Format (ohne Markdown-Bloecke wie ```json):\n"
            "{\n"
            '  "gesamtnote_tendenz": "string",\n'
            '  "kritikpunkte": [\n'
            "    {\n"
            '      \"kategorie\": \"Stil/Logik oder Fachliche Evidenz\",\n'
            '      \"original_zitat\": \"string\",\n'
            '      \"kritikpunkt\": \"string\",\n'
            '      \"evidenz_nachweis\": \"string\"\n'
            "    }\n"
            "  ],\n"
            '  "ueberarbeiteter_absatz": "string"\n'
            "}"
        )
        
        res_c = client.models.generate_content(model="gemini-2.5-flash", contents=prompt_c)
        
        # Rohtextbereinigung falls nötig und direkt als JSON zurückgeben
        raw_response = res_c.text.strip()
        if raw_response.startswith("```"):
            raw_response = raw_response.split("```")[1]
            if raw_response.startswith("json"):
                raw_response = raw_response[4:]
        raw_response = raw_response.strip()

        # Validieren, dass es valides JSON ist
        json_data = json.loads(raw_response)
        
        return jsonify(json_data), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
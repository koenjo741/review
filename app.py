from flask import Flask, render_template, request, jsonify
from Bio import Entrez
import requests
import os
import json

app = Flask(__name__)

PUBMED_EMAIL = "josef_koenig@hotmail.com"
PUBMED_API_KEY = "2d6671c4cc19fcc9bf7c972e504abf763b09"
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")

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

def search_semanticscholar(query: str) -> str:
    """Sucht in der Semantic Scholar API nach wissenschaftlicher Evidenz."""
    url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={requests.utils.quote(query)}&limit=3&fields=title,abstract,year"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            papers = data.get("data", [])
            if not papers:
                return "Keine Semantic Scholar Ergebnisse gefunden."
            res = []
            for p in papers:
                title = p.get("title", "Kein Titel")
                year = p.get("year", "k.A.")
                res.append(f"{title} ({year})")
            return "Semantic Scholar Treffer: " + " ; ".join(res)
        else:
            return f"Semantic Scholar Fehler: Status {response.status_code}"
    except Exception as e:
        return f"Semantic Scholar Fehler: {str(e)}"

def call_gemini(prompt: str) -> str:
    """Ruft Gemini direkt über die offizielle REST-API auf."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GOOGLE_API_KEY}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    response = requests.post(url, headers=headers, json=payload, timeout=60)
    if response.status_code == 200:
        data = response.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception:
            return "Fehler beim Parsen der Gemini-Antwort."
    else:
        return f"API-Fehler: {response.status_code} - {response.text}"

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
        # 1. Parallele Evidenz-Abfrage aus PubMed UND Semantic Scholar
        search_query = text[:80]
        pubmed_kontext = search_pubmed(search_query)
        s2_kontext = search_semanticscholar(search_query)

        # 2. Agent A: Lektorat
        prompt_a = f"Du bist ein akademischer Lektor. Reviewe den Text auf Grammatik, Stil und Logik: {text}"
        res_a_text = call_gemini(prompt_a)

        # 3. Agent B: Fachprüfung unter Einbeziehung beider Datenbanken
        prompt_b = (
            f"Du bist ein wissenschaftlicher Reviewer. Prüfe die Fakten im Text: {text}\n\n"
            f"PubMed-Evidenz:\n{pubmed_kontext}\n\n"
            f"Semantic Scholar-Evidenz:\n{s2_kontext}"
        )
        res_b_text = call_gemini(prompt_b)

        # 4. Agent C: Finales JSON-Gutachten
        prompt_c = (
            f"Du bist der Prüfungsvorsitzende. Erstelle ein finales Gutachten basierend auf:\n"
            f"Originaltext: {text}\n\n"
            f"Lektorat: {res_a_text}\n\n"
            f"Fachprüfung: {res_b_text}\n\n"
            f"Antworte AUSSCHLIESSLICH im folgenden JSON-Format (ohne Markdown-Blocks):\n"
            "{\n"
            '  "gesamtnote_tendenz": "string",\n'
            '  "kritikpunkte": [\n'
            "    {\n"
            '      "kategorie": "Stil/Logik oder Fachliche Evidenz",\n'
            '      "original_zitat": "string",\n'
            '      "kritikpunkt": "string",\n'
            '      "evidenz_nachweis": "string"\n'
            "    }\n"
            "  ],\n"
            '  "ueberarbeiteter_absatz": "string"\n'
            "}"
        )
        
        raw_res = call_gemini(prompt_c).strip()
        
        if raw_res.startswith("```"):
            raw_res = raw_res.split("```")[1]
            if raw_res.startswith("json"):
                raw_res = raw_res[4:]
        raw_res = raw_res.strip()

        json_data = json.loads(raw_res)
        return jsonify(json_data), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
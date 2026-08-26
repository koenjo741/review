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

def call_gemini_multimodal(prompt: str, image_data: str = None, mime_type: str = "image/png") -> str:
    """Ruft Gemini multimodal (Text + optionales Bild) über die REST-API auf."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GOOGLE_API_KEY}"
    headers = {"Content-Type": "application/json"}
    
    parts = [{"text": prompt}]
    if image_data:
        parts.append({
            "inline_data": {
                "mime_type": mime_type,
                "data": image_data
            }
        })
        
    payload = {
        "contents": [{"parts": parts}]
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
    image_base64 = data.get('image', None)
    mime_type = data.get('mime_type', 'image/png')
    
    if not text and not image_base64:
        return jsonify({"error": "Kein Text oder Bild übergeben"}), 400

    try:
        # 1. PubMed Abfrage (falls Text vorhanden)
        pubmed_kontext = search_pubmed(text[:80]) if text else "Kein Text für PubMed-Suche."

        # 2. Agent A: Lektorat
        prompt_a = f"Du bist ein akademischer Lektor. Reviewe den Text bzw. das Bild auf Grammatik, Stil, Layout und Logik:\nText: {text}"
        res_a_text = call_gemini_multimodal(prompt_a, image_base64, mime_type)

        # 3. Agent B: Fachprüfung
        prompt_b = (
            f"Du bist ein medizinischer Reviewer und Informatiker. Prüfe die Fakten im eingereichten Material:\n"
            f"Text: {text}\n\n"
            f"Evidenz-Datenbankauszug:\n{pubmed_kontext}"
        )
        res_b_text = call_gemini_multimodal(prompt_b, image_base64, mime_type)

        # 4. Agent C: JSON-Gutachten erzwingen
        prompt_c = (
            f"Du bist der Prüfungsvorsitzende. Erstelle ein finales Gutachten basierend auf:\n"
            f"Originaltext: {text}\n\n"
            f"Lektorat: {res_a_text}\n\n"
            f"Fachprüfung: {res_b_text}\n\n"
            f"Anweisungen zur Sprachregelung:\n"
            f"- Erkenne die Originalsprache des eingereichten Materials (z. B. Englisch).\n"
            f"- Die Felder 'gesamtnote_tendenz' und 'kritikpunkte' müssen zwingend auf DEUTSCH verfasst werden.\n"
            f"- Das Feld 'ueberarbeiteter_absatz' muss strikt in der URSPRUNGSSPRACHE des Originaltextes verfasst werden.\n"
            f"- Markiere in dem 'ueberarbeiteter_absatz' alle geänderten Textstellen gelb: <mark style=\"background-color: #fff3cd; color: #856404;\">Textstelle</mark>.\n\n"
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
        
        raw_res = call_gemini_multimodal(prompt_c, image_base64, mime_type).strip()
        
        # Markdown-Codeblöcke sicherheitshalber entfernen
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
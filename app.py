from flask import Flask, render_template, request, jsonify
import requests
import os
import json
import base64
from pydantic import BaseModel, Field
from typing import List, Optional

app = Flask(__name__)

# API Keys
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
S2_API_KEY = os.environ.get("S2_API_KEY", "s2k-an3iWCohGVLwGyOWdzffZ9orI2E1ySNnp76Ojljo")

# --- PYDANTIC MODELS ---

class BibEntry(BaseModel):
    status: str
    id: int
    text: str
    reason: str

class BibList(BaseModel):
    entries: List[BibEntry]

class Kritikpunkt(BaseModel):
    kategorie: str
    original_zitat: str
    kritikpunkt: str
    evidenz_nachweis: Optional[str] = None

class EvaluationResult(BaseModel):
    gesamtnote_tendenz: str
    kritikpunkte: List[Kritikpunkt]
    ueberarbeiteter_absatz: str

class PDFExtraction(BaseModel):
    toc: str
    bibliography: str
    draft_text: str

# --- CORE API FUNCTION ---

def call_gemini(prompt: str, is_json: bool = False, pdf_data: bytes = None) -> str:
    # v1beta ist oft stabiler für die neuesten Multimodal-Features (PDF)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GOOGLE_API_KEY}"
    headers = {"Content-Type": "application/json"}
    
    parts = [{"text": prompt}]
    if pdf_data:
        parts.append({
            "inline_data": {
                "mime_type": "application/pdf",
                "data": base64.b64encode(pdf_data).decode('utf-8')
            }
        })

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "response_mime_type": "application/json" if is_json else "text/plain",
            "temperature": 0.1
        }
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=120)
        if response.status_code == 200:
            return response.json()["candidates"][0]["content"]["parts"][0]["text"]
        else:
            # Wir werfen hier einen Fehler, damit die Route ihn sauber fangen kann
            raise Exception(f"Google API Fehler {response.status_code}: {response.text}")
    except Exception as e:
        raise Exception(f"Verbindungsfehler: {str(e)}")

def call_semantic_scholar(query: str):
    endpoint = "https://api.semanticscholar.org/graph/v1/paper/search"
    headers = {"x-api-key": S2_API_KEY}
    params = {"query": query, "limit": 3, "fields": "title,year,abstract"}
    try:
        res = requests.get(endpoint, headers=headers, params=params, timeout=15)
        return res.json().get("data", []) if res.status_code == 200 else []
    except:
        return []

# --- ROUTES ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/process_pdf', methods=['POST'])
def process_pdf():
    if 'file' not in request.files:
        return jsonify({"error": "Keine Datei hochgeladen"}), 400
    
    file = request.files['file']
    pdf_bytes = file.read()

    prompt = (
        "Du bist ein wissenschaftlicher Lektor. Analysiere das PDF dieser Masterarbeit.\n"
        "Extrahiere die folgenden Bereiche funktional (auch wenn sie anders benannt sind, z.B. 'Outline' statt 'TOC'):\n"
        "1. 'toc': Das Inhaltsverzeichnis.\n"
        "2. 'bibliography': Das Literaturverzeichnis.\n"
        "3. 'draft_text': Ein langer Ausschnitt des Hauptteils.\n"
        "Gib das Ergebnis STRENG als JSON zurück. Schema: " + json.dumps(PDFExtraction.model_json_schema())
    )

    try:
        raw_res = call_gemini(prompt, is_json=True, pdf_data=pdf_bytes)
        data = PDFExtraction.model_validate_json(raw_res)
        return jsonify(data.model_dump()), 200
    except Exception as e:
        print(f"DEBUG ERROR: {str(e)}") # Sichtbar in Render Logs
        return jsonify({"error": str(e)}), 500

@app.route('/initialize', methods=['POST'])
def initialize_work():
    try:
        data = request.json
        toc = data.get('toc', '')
        bib = data.get('bibliography', '')
        draft = data.get('draft_text', '')

        parsing_prompt = (
            f"Prüfe dieses Literaturverzeichnis auf Korrektheit. Gib eine JSON-Liste zurück.\n"
            f"Schema: {json.dumps(BibList.model_json_schema())}\n\nQuellen:\n{bib}"
        )
        raw_bib = call_gemini(parsing_prompt, is_json=True)
        bib_data = BibList.model_validate_json(raw_bib)

        struct_prompt = f"Analysiere die wissenschaftliche Struktur & Stringenz:\nInhalt: {toc}\nText: {draft}"
        analysis = call_gemini(struct_prompt)

        return jsonify({
            "status": "success",
            "bibliography_check": [e.model_dump() for e in bib_data.entries],
            "structural_analysis": analysis,
            "full_context": f"STRUKTUR:\n{analysis}\n\nLITERATUR:\n{bib}"
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/evaluate', methods=['POST'])
def evaluate():
    try:
        data = request.json
        paragraph = data.get('paragraph', '')
        context = data.get('context_summary', '')

        kw_res = call_gemini(f"Extrahiere 3 medizinische Suchbegriffe für: {paragraph}")
        evidence = call_semantic_scholar(kw_res)
        evidence_text = "\n".join([f"- {p['title']} ({p['year']}): {p.get('abstract','')[:200]}" for p in evidence])

        res_a = call_gemini(f"Akademisches Lektorat (Stil, Logik): {paragraph}")
        res_b = call_gemini(f"Fachprüfung. Evidenz:\n{evidence_text}\n\nText:\n{paragraph}")

        prompt_c = (
            f"Erstelle ein finales Gutachten als JSON.\n"
            f"Lektorat: {res_a}\nFachprüfung: {res_b}\nOriginal: {paragraph}\n"
            f"Schema: {json.dumps(EvaluationResult.model_json_schema())}\n"
            "WICHTIG: Sprache des Originals beibehalten!"
        )
        
        raw_eval = call_gemini(prompt_c, is_json=True)
        eval_obj = EvaluationResult.model_validate_json(raw_eval)

        return jsonify(eval_obj.model_dump()), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
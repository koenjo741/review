from flask import Flask, render_template, request, jsonify
import requests
import os
import json
import base64
from pydantic import BaseModel, Field
from typing import List, Optional

app = Flask(__name__)

# API Keys - Werden aus den Render-Umgebungsvariablen geladen
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
S2_API_KEY = os.environ.get("S2_API_KEY", "s2k-an3iWCohGVLwGyOWdzffZ9orI2E1ySNnp76Ojljo")

# --- TAG 5: PYDANTIC MODELS FÜR STRUKTURIERTE DATEN ---

class BibEntry(BaseModel):
    status: str = Field(description="OK oder FLAG")
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

# --- CORE FUNKTIONEN ---

def call_gemini(prompt: str, is_json: bool = False, pdf_data: bytes = None) -> str:
    """Ruft Gemini 1.5 Flash auf. Unterstützt PDF-Upload und JSON-Modus."""
    url = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={GOOGLE_API_KEY}"
    headers = {"Content-Type": "application/json"}
    
    parts = [{"text": prompt}]
    
    # Tag 8: Multimodalität - PDF direkt an die API senden
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
            "temperature": 0.1 # Niedrige Temperatur für wissenschaftliche Stabilität
        }
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=120)
        if response.status_code == 200:
            return response.json()["candidates"][0]["content"]["parts"][0]["text"]
        else:
            return f'{{"error": "API Fehler {response.status_code}: {response.text}"}}'
    except Exception as e:
        return f'{{"error": "Verbindungsfehler: {str(e)}"}}'

def call_semantic_scholar(query: str):
    """Tag 9: RAG - Holt echte Literatur-Abstracts."""
    endpoint = "https://api.semanticscholar.org/graph/v1/paper/search"
    headers = {"x-api-key": S2_API_KEY}
    params = {"query": query, "limit": 3, "fields": "title,year,abstract,url"}
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
    """Extrahiert TOC, Bib und Text aus dem PDF (Tag 8)."""
    if 'file' not in request.files:
        return jsonify({"error": "Keine Datei"}), 400
    
    file = request.files['file']
    pdf_bytes = file.read()

    prompt = (
        "Du bist ein wissenschaftlicher Assistent. Analysiere das beigefügte PDF einer Masterarbeit.\n"
        "Extrahiere folgende Bereiche und gib sie als JSON zurück:\n"
        "1. 'toc': Das Inhaltsverzeichnis.\n"
        "2. 'bibliography': Das Literaturverzeichnis.\n"
        "3. 'draft_text': Ein aussagekräftiger Ausschnitt des Hauptteils.\n"
        "Nutze exakt dieses JSON-Schema: " + json.dumps(PDFExtraction.model_json_schema())
    )

    try:
        raw_res = call_gemini(prompt, is_json=True, pdf_data=pdf_bytes)
        data = PDFExtraction.model_validate_json(raw_res)
        return jsonify(data.model_dump()), 200
    except Exception as e:
        return jsonify({"error": f"PDF-Analyse fehlgeschlagen: {str(e)}"}), 500

@app.route('/initialize', methods=['POST'])
def initialize_work():
    """Prüft die Literatur und analysiert die Struktur."""
    try:
        data = request.json
        toc = data.get('toc', '')
        bib = data.get('bibliography', '')
        draft = data.get('draft_text', '')

        # Literatur-Check via Pydantic
        parsing_prompt = (
            f"Prüfe dieses Literaturverzeichnis auf Korrektheit. Gib eine Liste im JSON-Format zurück.\n"
            f"Schema: {json.dumps(BibList.model_json_schema())}\n\nQuellen:\n{bib}"
        )
        raw_bib = call_gemini(parsing_prompt, is_json=True)
        bib_data = BibList.model_validate_json(raw_bib)

        # Struktur-Analyse
        struct_prompt = f"Analysiere die Struktur dieser Arbeit:\nInhalt: {toc}\nText: {draft}"
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
    """Das 3-Agenten-Lektorat mit RAG-Support."""
    try:
        data = request.json
        paragraph = data.get('paragraph', '')
        context = data.get('context_summary', '')

        # 1. Keywords für RAG
        kw_res = call_gemini(f"Extrahiere 3 medizinische Suchbegriffe für: {paragraph}")
        
        # 2. Externe Evidenz (Semantic Scholar)
        evidence = call_semantic_scholar(kw_res)
        evidence_text = "\n".join([f"- {p['title']} ({p['year']}): {p.get('abstract','')[:200]}" for p in evidence])

        # 3. Agenten-Prompts
        res_a = call_gemini(f"Akademisches Lektorat (Stil, Logik): {paragraph}")
        res_b = call_gemini(f"Fachprüfung. Evidenz:\n{evidence_text}\n\nText:\n{paragraph}")

        # 4. Synthesizer (Agent C) mit Pydantic-Erzwingung
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
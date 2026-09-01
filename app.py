from flask import Flask, render_template, request, jsonify
import requests
import os
import json
from pydantic import BaseModel, Field
from typing import List, Optional

app = Flask(__name__)

# API Keys
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
S2_API_KEY = os.environ.get("S2_API_KEY", "s2k-an3iWCohGVLwGyOWdzffZ9orI2E1ySNnp76Ojljo")

# --- TAG 5: PYDANTIC MODELS FÜR STRUKTURIERTE AUSGABEN ---

class BibEntry(BaseModel):
    status: str = Field(description="OK oder FLAG")
    id: int
    text: str
    reason: str

class BibList(BaseModel):
    entries: List[BibEntry]

class Kritikpunkt(BaseModel):
    kategorie: str = Field(description="Stil/Logik oder Fachliche Evidenz")
    original_zitat: str
    kritikpunkt: str
    evidenz_nachweis: Optional[str] = None

class EvaluationResult(BaseModel):
    gesamtnote_tendenz: str
    kritikpunkte: List[Kritikpunkt]
    ueberarbeiteter_absatz: str

# --- API FUNKTIONEN ---

def call_gemini(prompt: str, is_json: bool = False) -> str:
    """Ruft Gemini auf. Wenn is_json=True, wird striktes JSON erzwungen (Tag 5)."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GOOGLE_API_KEY}"
    headers = {"Content-Type": "application/json"}
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    
    if is_json:
        payload["generationConfig"] = {"response_mime_type": "application/json"}

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=120)
        if response.status_code == 200:
            return response.json()["candidates"][0]["content"]["parts"][0]["text"]
        return f"Error: {response.status_code}"
    except Exception as e:
        return str(e)

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

@app.route('/initialize', methods=['POST'])
def initialize_work():
    try:
        data = request.json
        toc = data.get('toc', '')
        bibliography = data.get('bibliography', '')
        draft_text = data.get('draft_text', '')

        # Literatur-Check mit Pydantic-Struktur
        parsing_prompt = (
            f"Analysiere diese Literaturquellen und gib sie als JSON-Liste zurück.\n"
            f"Format: {{'entries': [{{'status': 'OK/FLAG', 'id': int, 'text': '...', 'reason': '...'}}]}}\n"
            f"Quellen:\n{bibliography}"
        )
        raw_bib = call_gemini(parsing_prompt, is_json=True)
        bib_data = BibList.model_validate_json(raw_bib)

        # Struktur-Analyse (Freitext)
        prompt_init = f"Analysiere Struktur & Ist-Stand:\nInhalt: {toc}\nText: {draft_text}"
        analysis = call_gemini(prompt_init)

        return jsonify({
            "status": "success",
            "bibliography_check": [e.model_dump() for e in bib_data.entries],
            "structural_analysis": analysis,
            "full_context": f"--- STRUKTUR ---\n{analysis}\n\n--- LITERATUR ---\n{bibliography}"
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/evaluate', methods=['POST'])
def evaluate():
    try:
        data = request.json
        paragraph = data.get('paragraph', '')
        context_summary = data.get('context_summary', '')

        # RAG: Keywords & Semantic Scholar
        kw_prompt = f"Keywords für: {paragraph}"
        keywords = call_gemini(kw_prompt)
        evidence = call_semantic_scholar(keywords)
        evidence_text = "\n".join([f"- {p['title']}: {p.get('abstract','')[:200]}" for p in evidence])

        # Agenten-Logik
        res_a = call_gemini(f"Lektorat für: {paragraph}")
        res_b = call_gemini(f"Fachprüfung mit Evidenz:\n{evidence_text}\n\nText: {paragraph}")

        # Agent C: Synthesizer mit Pydantic-Erzwingung
        prompt_c = (
            f"Erstelle ein Gutachten als JSON.\n"
            f"Lektorat: {res_a}\nFachprüfung: {res_b}\n"
            f"Originaltext: {paragraph}\n"
            f"Schema: {EvaluationResult.model_json_schema()}"
        )
        
        raw_eval = call_gemini(prompt_c, is_json=True)
        eval_obj = EvaluationResult.model_validate_json(raw_eval)

        return jsonify(eval_obj.model_dump()), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
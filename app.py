from flask import Flask, render_template, request, jsonify
import requests
import os
import json
import base64
import re

app = Flask(__name__)

# API Keys
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
S2_API_KEY = os.environ.get("S2_API_KEY", "s2k-an3iWCohGVLwGyOWdzffZ9orI2E1ySNnp76Ojljo")

def call_gemini(prompt: str, pdf_data: bytes = None) -> str:
    """Direkter REST-Aufruf an Gemini 1.5 Flash."""
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

    payload = {"contents": [{"parts": parts}]}
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=120)
        if response.status_code == 200:
            res_json = response.json()
            if "candidates" in res_json and res_json["candidates"]:
                return res_json["candidates"][0]["content"]["parts"][0]["text"]
            return "FEHLER: Keine Antwort von KI erhalten."
        else:
            return f"FEHLER_API_{response.status_code}: {response.text}"
    except Exception as e:
        return f"FEHLER_VERBINDUNG: {str(e)}"

def extract_json_safely(text: str):
    """Versucht JSON aus dem Text zu extrahieren, egal wie viel Müll drumherum steht."""
    if not text or "FEHLER" in text:
        return None
    try:
        # Suche nach dem ersten { und dem letzten }
        start = text.find('{')
        end = text.rfind('}') + 1
        if start != -1 and end > 0:
            return json.loads(text[start:end])
        return None
    except:
        return None

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
    """Extrahiert Daten in drei kleinen, stabilen Schritten."""
    if 'file' not in request.files:
        return jsonify({"error": "Keine Datei"}), 400
    
    file = request.files['file']
    pdf_bytes = file.read()

    # Schritt 1: TOC
    res_toc = call_gemini("Extrahiere NUR das Inhaltsverzeichnis aus diesem PDF. Antworte als JSON: {'toc': '...'}", pdf_data=pdf_bytes)
    data_toc = extract_json_safely(res_toc) or {"toc": "Nicht gefunden"}

    # Schritt 2: Bibliography
    res_bib = call_gemini("Extrahiere NUR das Literaturverzeichnis am Ende des Dokuments. Antworte als JSON: {'bibliography': '...'}", pdf_data=pdf_bytes)
    data_bib = extract_json_safely(res_bib) or {"bibliography": "Nicht gefunden"}

    # Schritt 3: Draft Text (Einleitung)
    res_text = call_gemini("Extrahiere die ersten 2-3 Seiten des Hauptteils (Einleitung). Antworte als JSON: {'draft_text': '...'}", pdf_data=pdf_bytes)
    data_text = extract_json_safely(res_text) or {"draft_text": "Nicht gefunden"}

    # Zusammenführen
    final_data = {
        "toc": data_toc.get("toc"),
        "bibliography": data_bib.get("bibliography"),
        "draft_text": data_text.get("draft_text")
    }
    
    return jsonify(final_data), 200

@app.route('/initialize', methods=['POST'])
def initialize_work():
    data = request.json
    toc, bib, draft = data.get('toc',''), data.get('bibliography',''), data.get('draft_text','')
    
    prompt_bib = (
        "Prüfe dieses Literaturverzeichnis auf Korrektheit. Antworte als JSON-Liste.\n"
        "Format: {'entries': [{'status': 'OK/FLAG', 'id': 1, 'text': '...', 'reason': '...'}]}\n\n"
        f"Quellen:\n{bib}"
    )
    res_bib = call_gemini(prompt_bib)
    bib_data = extract_json_safely(res_bib)

    prompt_struct = f"Analysiere kurz die wissenschaftliche Struktur:\nInhalt: {toc}\nText: {draft}"
    analysis = call_gemini(prompt_struct)

    return jsonify({
        "status": "success",
        "bibliography_check": bib_data.get('entries', []) if bib_data else [],
        "structural_analysis": analysis,
        "full_context": f"STRUKTUR:\n{analysis}\n\nLITERATUR:\n{bib}"
    }), 200

@app.route('/evaluate', methods=['POST'])
def evaluate():
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
        f"Lektorat: {res_a}\nFachprüfung: {res_b}\nOriginal: {paragraph}\n\n"
        "Format: {\"gesamtnote_tendenz\": \"...\", \"kritikpunkte\": [{\"kategorie\": \"...\", \"original_zitat\": \"...\", \"kritikpunkt\": \"...\"}], \"ueberarbeiteter_absatz\": \"...\"}\n"
        "WICHTIG: Sprache des Originals beibehalten!"
    )
    
    raw_eval = call_gemini(prompt_c)
    eval_data = extract_json_safely(raw_eval)

    if eval_data:
        return jsonify(eval_data), 200
    else:
        return jsonify({"error": "Gutachten konnte nicht erstellt werden."}), 500

if __name__ == '__main__':
    app.run(debug=True)
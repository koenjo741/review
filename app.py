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

def call_gemini_raw(prompt: str, pdf_data: bytes = None) -> str:
    """Direkter REST-Aufruf an Gemini 1.5 Flash (stabilste Methode)."""
    # Wir nutzen den stabilen v1 Endpunkt
    url = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={GOOGLE_API_KEY}"
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
            return response.json()["candidates"][0]["content"]["parts"][0]["text"]
        else:
            return f"ERROR_API_{response.status_code}: {response.text}"
    except Exception as e:
        return f"ERROR_CONN: {str(e)}"

def clean_json_response(raw_text: str):
    """Extrahiert JSON aus einer Antwort, auch wenn Markdown-Tags enthalten sind."""
    try:
        # Suche nach Inhalten zwischen ```json und ```
        json_match = re.search(r'```json\s*(.*?)\s*```', raw_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(1))
        # Suche nach Inhalten zwischen einfachen ``` und ```
        json_match = re.search(r'```\s*(.*?)\s*```', raw_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(1))
        # Versuche es direkt
        return json.loads(raw_text.strip())
    except Exception as e:
        raise Exception(f"JSON-Parsing fehlgeschlagen: {str(e)} | Original: {raw_text[:200]}")

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
        return jsonify({"error": "Keine Datei"}), 400
    
    file = request.files['file']
    pdf_bytes = file.read()

    prompt = (
        "Analysiere dieses PDF einer Masterarbeit. Extrahiere folgende Teile und gib sie als JSON zurück:\n"
        "1. 'toc': Das Inhaltsverzeichnis.\n"
        "2. 'bibliography': Das Literaturverzeichnis.\n"
        "3. 'draft_text': Ein langer Ausschnitt des Hauptteils (Einleitung bis Methoden).\n\n"
        "Antworte AUSSCHLIESSLICH im JSON-Format: {'toc': '...', 'bibliography': '...', 'draft_text': '...'}"
    )

    try:
        raw_res = call_gemini_raw(prompt, pdf_data=pdf_bytes)
        if "ERROR" in raw_res: return jsonify({"error": raw_res}), 500
        data = clean_json_response(raw_res)
        return jsonify(data), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/initialize', methods=['POST'])
def initialize_work():
    try:
        data = request.json
        toc = data.get('toc', '')
        bib = data.get('bibliography', '')
        draft = data.get('draft_text', '')

        prompt = (
            f"Prüfe dieses Literaturverzeichnis auf Korrektheit. Gib eine JSON-Liste zurück.\n"
            f"Format: {{'entries': [{{'status': 'OK/FLAG', 'id': 1, 'text': '...', 'reason': '...'}}]}}\n\n"
            f"Quellen:\n{bib}"
        )
        raw_bib = call_gemini_raw(prompt)
        bib_data = clean_json_response(raw_bib)

        struct_prompt = f"Analysiere kurz die wissenschaftliche Struktur dieser Arbeit:\nInhalt: {toc}\nText: {draft}"
        analysis = call_gemini_raw(struct_prompt)

        return jsonify({
            "status": "success",
            "bibliography_check": bib_data.get('entries', []),
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

        # RAG Suche
        kw_res = call_gemini_raw(f"Extrahiere 3 medizinische Suchbegriffe für: {paragraph}")
        evidence = call_semantic_scholar(kw_res)
        evidence_text = "\n".join([f"- {p['title']} ({p['year']}): {p.get('abstract','')[:200]}" for p in evidence])

        # Agenten
        res_a = call_gemini_raw(f"Akademisches Lektorat (Stil, Logik): {paragraph}")
        res_b = call_gemini_raw(f"Fachprüfung. Evidenz:\n{evidence_text}\n\nText:\n{paragraph}")

        prompt_c = (
            f"Erstelle ein finales Gutachten als JSON.\n"
            f"Lektorat: {res_a}\nFachprüfung: {res_b}\nOriginal: {paragraph}\n\n"
            "Format: {\"gesamtnote_tendenz\": \"...\", \"kritikpunkte\": [{\"kategorie\": \"...\", \"original_zitat\": \"...\", \"kritikpunkt\": \"...\", \"evidenz_nachweis\": \"...\"}], \"ueberarbeiteter_absatz\": \"...\"}\n"
            "WICHTIG: Sprache des Originals beibehalten!"
        )
        
        raw_eval = call_gemini_raw(prompt_c)
        eval_data = clean_json_response(raw_eval)

        return jsonify(eval_data), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
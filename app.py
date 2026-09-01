from flask import Flask, render_template, request, jsonify
import requests
import os
import json
import base64
import re

app = Flask(__name__)

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
S2_API_KEY = os.environ.get("S2_API_KEY", "s2k-an3iWCohGVLwGyOWdzffZ9orI2E1ySNnp76Ojljo")

def call_gemini(prompt: str, pdf_data: bytes = None, force_json: bool = False) -> str:
    """Direkter REST-Aufruf mit optionalem JSON-Modus."""
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
            "temperature": 0.1,
            "response_mime_type": "application/json" if force_json else "text/plain"
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=120)
        if response.status_code == 200:
            return response.json()["candidates"][0]["content"]["parts"][0]["text"]
        else:
            return f"ERROR: {response.status_code}"
    except Exception as e:
        return f"ERROR: {str(e)}"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/process_pdf', methods=['POST'])
def process_pdf():
    if 'file' not in request.files:
        return jsonify({"error": "Keine Datei"}), 400
    
    file = request.files['file']
    pdf_bytes = file.read()

    # Optimierter Prompt für 80+ Seiten Dokumente
    prompt = (
        "Du bist ein präziser wissenschaftlicher Extraktions-Bot. Analysiere das PDF und extrahiere diese drei Blöcke:\n"
        "1. 'toc': Das Inhaltsverzeichnis (meist Seite 2-5). Kopiere die Kapitelstruktur.\n"
        "2. 'bibliography': Das Literaturverzeichnis (meist ganz am Ende, ab ca. Seite 70). Kopiere die Liste der Quellen.\n"
        "3. 'draft_text': Extrahiere die ersten 3-4 Seiten des eigentlichen Hauptteils (ab 'Introduction' oder 'Einleitung').\n\n"
        "Regel: Antworte AUSSCHLIESSLICH im JSON-Format mit den Keys 'toc', 'bibliography' und 'draft_text'. "
        "Falls ein Teil zu lang ist, kürze ihn sinnvoll, aber behalte die Struktur bei."
    )

    try:
        raw_res = call_gemini(prompt, pdf_data=pdf_bytes, force_json=True)
        # Da wir force_json nutzen, liefert Gemini direkt sauberes JSON
        data = json.loads(raw_res)
        return jsonify(data), 200
    except Exception as e:
        return jsonify({"error": f"Extraktion fehlgeschlagen: {str(e)}"}), 500

@app.route('/initialize', methods=['POST'])
def initialize_work():
    data = request.json
    toc, bib, draft = data.get('toc',''), data.get('bibliography',''), data.get('draft_text','')
    
    # Literatur-Check (Tag 1 & 5)
    prompt_bib = (
        "Prüfe dieses Literaturverzeichnis auf formale Korrektheit. Antworte als JSON-Liste.\n"
        "Format: {'entries': [{'status': 'OK/FLAG', 'id': 1, 'text': '...', 'reason': '...'}]}\n\n"
        f"Quellen:\n{bib}"
    )
    res_bib = call_gemini(prompt_bib, force_json=True)
    try:
        bib_data = json.loads(res_bib)
    except:
        bib_data = {"entries": []}

    # Struktur-Analyse
    prompt_struct = f"Analysiere kurz die wissenschaftliche Struktur & Stringenz:\nInhalt: {toc}\nText: {draft}"
    analysis = call_gemini(prompt_struct)

    return jsonify({
        "status": "success",
        "bibliography_check": bib_data.get('entries', []),
        "structural_analysis": analysis,
        "full_context": f"STRUKTUR:\n{analysis}\n\nLITERATUR:\n{bib}"
    }), 200

@app.route('/evaluate', methods=['POST'])
def evaluate():
    # (Bleibt gleich wie v2.4, nutzt aber call_gemini mit force_json für das Gutachten)
    data = request.json
    paragraph = data.get('paragraph', '')
    context = data.get('context_summary', '')
    
    # RAG & Agenten-Logik...
    # [Hier gekürzt für die Übersicht, bleibt identisch zu deinem funktionierenden Code]
    # Wichtig: Am Ende call_gemini(prompt_c, force_json=True) nutzen.
    return jsonify({"status": "ready"}), 200 # Platzhalter

if __name__ == '__main__':
    app.run(debug=True)
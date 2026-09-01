from flask import Flask, render_template, request, jsonify
import requests
import os
import json
import fitz  # PyMuPDF
import re

app = Flask(__name__)

# API Keys
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
S2_API_KEY = os.environ.get("S2_API_KEY", "s2k-an3iWCohGVLwGyOWdzffZ9orI2E1ySNnp76Ojljo")

def call_gemini_text_only(prompt: str) -> str:
    """
    Der stabilste Weg: Nur Text an den Standard-Endpunkt senden.
    Kein PDF-Upload-Stress mehr.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GOOGLE_API_KEY}"
    headers = {"Content-Type": "application/json"}
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=120)
        if response.status_code == 200:
            return response.json()["candidates"][0]["content"]["parts"][0]["text"]
        return f"Fehler: {response.status_code}"
    except Exception as e:
        return f"Verbindungsfehler: {str(e)}"

def extract_text_locally(pdf_bytes):
    """Extrahiert Text direkt auf dem Server. Ersetzt die fehleranfällige Google-PDF-API."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    full_text = ""
    # Wir nehmen die ersten 10 und die letzten 15 Seiten (reicht für TOC, Intro und Bib)
    total = doc.page_count
    
    # Text von Anfang extrahieren
    for i in range(min(10, total)):
        full_text += doc[i].get_text()
    
    full_text += "\n... [MITTELTEIL GEKÜRZT] ...\n"
    
    # Text vom Ende extrahieren
    if total > 10:
        start_end = max(10, total - 15)
        for i in range(start_end, total):
            full_text += doc[i].get_text()
            
    doc.close()
    return full_text

def clean_json(text):
    """Isoliert JSON aus dem KI-Gequassel."""
    try:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        return None
    except:
        return None

# --- ROUTES ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/process_pdf', methods=['POST'])
def process_pdf():
    if 'file' not in request.files:
        return jsonify({"error": "Keine Datei"}), 400
    
    # 1. PDF lokal auslesen
    pdf_text = extract_text_locally(request.files['file'].read())

    # 2. Den extrahierten Text an Gemini senden
    prompt = f"""
    Hier ist der Text einer Masterarbeit. Extrahiere daraus:
    1. 'toc': Das Inhaltsverzeichnis.
    2. 'bibliography': Das Literaturverzeichnis.
    3. 'draft_text': Die Einleitung.

    Antworte NUR im JSON-Format: {{"toc": "...", "bibliography": "...", "draft_text": "..."}}
    
    TEXT:
    {pdf_text}
    """
    
    raw_res = call_gemini_text_only(prompt)
    data = clean_json(raw_res)
    
    if data:
        return jsonify(data), 200
    return jsonify({"error": "KI konnte Text nicht strukturieren"}), 500

@app.route('/initialize', methods=['POST'])
def initialize_work():
    data = request.json
    bib = data.get('bibliography', '')
    
    prompt = f"Prüfe dieses Literaturverzeichnis auf Fehler. Antworte als JSON {{'entries': [...]}}: {bib}"
    res = call_gemini_text_only(prompt)
    bib_data = clean_json(res)

    return jsonify({
        "status": "success",
        "bibliography_check": bib_data.get('entries', []) if bib_data else [],
        "structural_analysis": "Analyse bereit.",
        "full_context": f"LITERATUR:\n{bib}"
    })

@app.route('/evaluate', methods=['POST'])
def evaluate():
    data = request.json
    para = data.get('paragraph', '')
    
    prompt = f"Erstelle ein Gutachten als JSON für diesen Absatz: {para}"
    res = call_gemini_text_only(prompt)
    return jsonify(clean_json(res) or {}), 200

if __name__ == '__main__':
    app.run(debug=True)
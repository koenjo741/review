from flask import Flask, render_template, request, jsonify
import requests
import os
import json
import base64
import re
import time

app = Flask(__name__)

# API Keys
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
S2_API_KEY = os.environ.get("S2_API_KEY", "s2k-an3iWCohGVLwGyOWdzffZ9orI2E1ySNnp76Ojljo")

def call_gemini(prompt: str, pdf_data: bytes = None, is_json: bool = False) -> dict:
    """
    Ruft Gemini 1.5 Flash auf. 
    Nutzt den v1beta Endpunkt für stabilen JSON-Modus und PDF-Support.
    """
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
            "topP": 0.95,
            "maxOutputTokens": 8192 # Erhöhtes Limit für die Antwort
        }
    }
    
    if is_json:
        payload["generationConfig"]["response_mime_type"] = "application/json"

    # Retry-Logik (max 2 Versuche)
    for attempt in range(2):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=180)
            if response.status_code == 200:
                res_data = response.json()
                text_content = res_data["candidates"][0]["content"]["parts"][0]["text"]
                if is_json:
                    return json.loads(text_content)
                return {"text": text_content}
            else:
                print(f"API Fehler Versuch {attempt+1}: {response.status_code} - {response.text}")
                time.sleep(2)
        except Exception as e:
            print(f"Verbindungsfehler Versuch {attempt+1}: {str(e)}")
            time.sleep(2)
            
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
    if 'file' not in request.files:
        return jsonify({"error": "Keine Datei"}), 400
    
    file = request.files['file']
    pdf_bytes = file.read()

    prompt = """
    Analysiere dieses PDF einer Masterarbeit und extrahiere die folgenden drei Bestandteile.
    Suche gezielt nach den typischen Überschriften (Inhaltsverzeichnis, Literatur, Einleitung).

    1. **toc**: Das vollständige Inhaltsverzeichnis (Kapitelüberschriften und Seitenzahlen).
    2. **bibliography**: Das gesamte Literaturverzeichnis am Ende. Falls es mehr als 50 Einträge sind, extrahiere nur die ersten 50, um die Antwortlänge zu begrenzen.
    3. **draft_text**: Die ersten 2-3 Seiten des eigentlichen Haupttextes (beginnend ab dem Kapitel 'Einleitung' oder 'Introduction').

    Antworte AUSSCHLIESSLICH im JSON-Format mit den Schlüsseln: "toc", "bibliography", "draft_text".
    """

    data = call_gemini(prompt, pdf_data=pdf_bytes, is_json=True)
    
    if data:
        return jsonify(data), 200
    else:
        return jsonify({"error": "Die KI konnte das Dokument nicht stabil extrahieren. Bitte versuche es erneut oder kopiere die Texte manuell."}), 500

@app.route('/initialize', methods=['POST'])
def initialize_work():
    data = request.json
    toc, bib, draft = data.get('toc',''), data.get('bibliography',''), data.get('draft_text','')
    
    prompt_bib = (
        "Überprüfe dieses Literaturverzeichnis auf formale Korrektheit. Antworte als JSON-Objekt mit einer Liste 'entries'.\n"
        "Format: {'entries': [{'status': 'OK/FLAG', 'id': 1, 'text': '...', 'reason': '...'}]}\n\n"
        f"Quellen:\n{bib}"
    )
    bib_data = call_gemini(prompt_bib, is_json=True)

    prompt_struct = f"Analysiere kurz die wissenschaftliche Struktur & Stringenz:\nInhalt: {toc}\nText: {draft}"
    struct_res = call_gemini(prompt_struct)
    analysis = struct_res.get("text", "Analyse fehlgeschlagen") if struct_res else "Analyse fehlgeschlagen"

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

    # RAG Suche
    kw_res = call_gemini(f"Extrahiere 3 medizinische Suchbegriffe für: {paragraph}")
    keywords = kw_res.get("text", paragraph[:50]) if kw_res else paragraph[:50]
    
    evidence = call_semantic_scholar(keywords)
    evidence_text = "\n".join([f"- {p['title']} ({p['year']}): {p.get('abstract','')[:200]}" for p in evidence])

    res_a = call_gemini(f"Akademisches Lektorat (Stil, Logik): {paragraph}")
    res_b = call_gemini(f"Fachprüfung. Evidenz:\n{evidence_text}\n\nText:\n{paragraph}")

    prompt_c = (
        f"Erstelle ein finales Gutachten als JSON.\n"
        f"Lektorat: {res_a}\nFachprüfung: {res_b}\nOriginal: {paragraph}\n\n"
        "Format: {\"gesamtnote_tendenz\": \"...\", \"kritikpunkte\": [{\"kategorie\": \"...\", \"original_zitat\": \"...\", \"kritikpunkt\": \"...\"}], \"ueberarbeiteter_absatz\": \"...\"}\n"
        "WICHTIG: Sprache des Originals beibehalten!"
    )
    
    eval_data = call_gemini(prompt_c, is_json=True)

    if eval_data:
        return jsonify(eval_data), 200
    else:
        return jsonify({"error": "Gutachten konnte nicht erstellt werden."}), 500

if __name__ == '__main__':
    app.run(debug=True)
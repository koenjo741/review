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
    """
    Diese Funktion nutzt exakt den Weg, der bei dir für die Literatur funktioniert hat:
    Direkter POST-Request an den Google-Endpunkt.
    """
    # Wir nutzen das stabilste Modell: gemini-1.5-flash
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GOOGLE_API_KEY}"
    headers = {"Content-Type": "application/json"}
    
    parts = [{"text": prompt}]
    
    # Falls ein PDF vorhanden ist, hängen wir es als inline_data an (Tag 8)
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
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            return f"API-Fehler: {response.status_code} - {response.text}"
    except Exception as e:
        return f"Verbindungsfehler: {str(e)}"

def extract_json(text: str):
    """Hilfsfunktion, um JSON aus dem KI-Text zu isolieren."""
    try:
        # Sucht nach Inhalten zwischen ```json und ```
        match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        # Falls keine Backticks da sind, versuche das ganze Dokument
        return json.loads(text.strip())
    except:
        # Letzter Versuch: Suche nach den äußersten geschweiften Klammern
        try:
            start = text.find('{')
            end = text.rfind('}') + 1
            return json.loads(text[start:end])
        except:
            return None

def call_semantic_scholar(query: str):
    """Suche bei Semantic Scholar (Tag 9)."""
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
        "Antworte NUR im JSON-Format: {'toc': '...', 'bibliography': '...', 'draft_text': '...'}"
    )

    raw_res = call_gemini(prompt, pdf_data=pdf_bytes)
    data = extract_json(raw_res)
    
    if data:
        return jsonify(data), 200
    else:
        return jsonify({"error": f"KI-Antwort konnte nicht als JSON gelesen werden: {raw_res[:200]}"}), 500

@app.route('/initialize', methods=['POST'])
def initialize_work():
    data = request.json
    toc = data.get('toc', '')
    bib = data.get('bibliography', '')
    draft = data.get('draft_text', '')

    # Literatur-Check
    prompt_bib = (
        "Überprüfe dieses Literaturverzeichnis auf Korrektheit. Antworte als JSON-Liste.\n"
        "Format: {'entries': [{'status': 'OK/FLAG', 'id': 1, 'text': '...', 'reason': '...'}]}\n\n"
        f"Quellen:\n{bib}"
    )
    res_bib = call_gemini(prompt_bib)
    bib_data = extract_json(res_bib)

    # Struktur-Analyse
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

    # RAG Suche
    kw_res = call_gemini(f"Extrahiere 3 medizinische Suchbegriffe für: {paragraph}")
    evidence = call_semantic_scholar(kw_res)
    evidence_text = "\n".join([f"- {p['title']} ({p['year']}): {p.get('abstract','')[:200]}" for p in evidence])

    # Agenten
    res_a = call_gemini(f"Akademisches Lektorat (Stil, Logik): {paragraph}")
    res_b = call_gemini(f"Fachprüfung. Evidenz:\n{evidence_text}\n\nText:\n{paragraph}")

    prompt_c = (
        f"Erstelle ein finales Gutachten als JSON.\n"
        f"Lektorat: {res_a}\nFachprüfung: {res_b}\nOriginal: {paragraph}\n\n"
        "Format: {\"gesamtnote_tendenz\": \"...\", \"kritikpunkte\": [{\"kategorie\": \"...\", \"original_zitat\": \"...\", \"kritikpunkt\": \"...\"}], \"ueberarbeiteter_absatz\": \"...\"}\n"
        "WICHTIG: Sprache des Originals beibehalten!"
    )
    
    raw_eval = call_gemini(prompt_c)
    eval_data = extract_json(raw_eval)

    if eval_data:
        return jsonify(eval_data), 200
    else:
        return jsonify({"error": "Gutachten-JSON konnte nicht erstellt werden."}), 500

if __name__ == '__main__':
    app.run(debug=True)
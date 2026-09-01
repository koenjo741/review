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

def call_gemini_smart(prompt: str, pdf_data: bytes = None, is_json: bool = False) -> str:
    """
    Tag 12: Self-Healing API Call. 
    Probiert verschiedene Endpunkte und Modelle, falls einer einen 404 liefert.
    """
    # Liste der stabilsten Modell-IDs für PDF-Analyse
    models_to_try = ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-1.5-flash-latest"]
    
    last_error = ""
    
    for model_id in models_to_try:
        # Wir nutzen v1beta, da dies für PDF (inline_data) am stabilsten ist
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={GOOGLE_API_KEY}"
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
                last_error = f"Modell {model_id} meldet {response.status_code}: {response.text}"
                continue # Nächstes Modell versuchen
        except Exception as e:
            last_error = str(e)
            continue

    raise Exception(f"Alle KI-Modelle sind fehlgeschlagen. Letzter Fehler: {last_error}")

def clean_json_response(raw_text: str):
    """Extrahiert JSON aus der Antwort, falls die KI Text drumherum baut."""
    try:
        # Entferne Markdown-Code-Blöcke
        clean = re.sub(r'```json\s*|\s*```', '', raw_text, flags=re.DOTALL).strip()
        return json.loads(clean)
    except Exception as e:
        # Zweiter Versuch: Suche nach der ersten { und letzten }
        try:
            start = raw_text.find('{')
            end = raw_text.rfind('}') + 1
            return json.loads(raw_text[start:end])
        except:
            raise Exception(f"JSON-Fehler: {str(e)} | Roh-Text: {raw_text[:100]}")

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
        "3. 'draft_text': Ein langer Ausschnitt des Hauptteils.\n\n"
        "Antworte NUR im JSON-Format: {'toc': '...', 'bibliography': '...', 'draft_text': '...'}"
    )

    try:
        raw_res = call_gemini_smart(prompt, pdf_data=pdf_bytes, is_json=True)
        data = clean_json_response(raw_res)
        return jsonify(data), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/initialize', methods=['POST'])
def initialize_work():
    try:
        data = request.json
        toc, bib, draft = data.get('toc',''), data.get('bibliography',''), data.get('draft_text','')

        prompt = (
            f"Prüfe dieses Literaturverzeichnis auf Korrektheit. Gib JSON zurück.\n"
            f"Format: {{'entries': [{{'status': 'OK/FLAG', 'id': 1, 'text': '...', 'reason': '...'}}]}}\n\n"
            f"Quellen:\n{bib}"
        )
        raw_bib = call_gemini_smart(prompt, is_json=True)
        bib_data = clean_json_response(raw_bib)

        struct_prompt = f"Analysiere kurz die wissenschaftliche Struktur:\nInhalt: {toc}\nText: {draft}"
        analysis = call_gemini_smart(struct_prompt)

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
        
        # RAG Suche
        kw_res = call_gemini_smart(f"Extrahiere 3 medizinische Suchbegriffe für: {paragraph}")
        evidence = call_semantic_scholar(kw_res)
        evidence_text = "\n".join([f"- {p['title']} ({p['year']}): {p.get('abstract','')[:200]}" for p in evidence])

        # Agenten
        res_a = call_gemini_smart(f"Akademisches Lektorat (Stil, Logik): {paragraph}")
        res_b = call_gemini_smart(f"Fachprüfung. Evidenz:\n{evidence_text}\n\nText:\n{paragraph}")

        prompt_c = (
            f"Erstelle ein finales Gutachten als JSON.\n"
            f"Lektorat: {res_a}\nFachprüfung: {res_b}\nOriginal: {paragraph}\n\n"
            "Format: {\"gesamtnote_tendenz\": \"...\", \"kritikpunkte\": [{\"kategorie\": \"...\", \"original_zitat\": \"...\", \"kritikpunkt\": \"...\", \"evidenz_nachweis\": \"...\"}], \"ueberarbeiteter_absatz\": \"...\"}\n"
            "WICHTIG: Sprache des Originals beibehalten!"
        )
        
        raw_eval = call_gemini_smart(prompt_c, is_json=True)
        eval_data = clean_json_response(raw_eval)

        return jsonify(eval_data), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
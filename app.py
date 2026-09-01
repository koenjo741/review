from flask import Flask, render_template, request, jsonify
import requests
import os
import json
import base64
import fitz  # PyMuPDF
import re

app = Flask(__name__)

# API Keys
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
S2_API_KEY = os.environ.get("S2_API_KEY", "s2k-an3iWCohGVLwGyOWdzffZ9orI2E1ySNnp76Ojljo")

def get_pdf_segment(pdf_bytes, start_page, end_page):
    """Extrahiert Teilstücke des PDFs, um das Token-Limit zu schonen."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total = doc.page_count
    new_doc = fitz.open()
    # Seitenbereich sicherstellen
    start = max(0, start_page)
    end = min(end_page, total - 1)
    new_doc.insert_pdf(doc, from_page=start, to_page=end)
    segment_bytes = new_doc.write()
    new_doc.close()
    doc.close()
    return segment_bytes

def call_gemini_direct(prompt, pdf_data=None):
    """
    Nutzt exakt den Weg aus deinem ersten funktionierenden Skript.
    """
    # Wir nutzen gemini-1.5-flash (das stabilste Modell)
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
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            return f"Fehler: {response.status_code}. {response.text}"
    except Exception as e:
        return f"Verbindungsfehler: {str(e)}"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/process_pdf', methods=['POST'])
def process_pdf():
    if 'file' not in request.files:
        return jsonify({"error": "Keine Datei"}), 400
    
    file = request.files['file']
    pdf_bytes = file.read()
    
    # Seitenanzahl ermitteln
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total_pages = doc.page_count
    doc.close()

    # 1. TOC extrahieren (Seiten 1-10)
    toc_pdf = get_pdf_segment(pdf_bytes, 0, 10)
    toc_text = call_gemini_direct("Extrahiere das Inhaltsverzeichnis aus diesem PDF-Ausschnitt.", toc_pdf)

    # 2. Literatur extrahieren (Letzte 15 Seiten)
    bib_pdf = get_pdf_segment(pdf_bytes, total_pages - 15, total_pages)
    bib_text = call_gemini_direct("Extrahiere das Literaturverzeichnis aus diesem PDF-Ausschnitt.", bib_pdf)

    # 3. Einleitung extrahieren (Seiten 1-15)
    intro_pdf = get_pdf_segment(pdf_bytes, 0, 15)
    intro_text = call_gemini_direct("Suche das Kapitel 'Einleitung' oder 'Introduction' und kopiere die ersten 3 Seiten Text.", intro_pdf)

    return jsonify({
        "toc": toc_text,
        "bibliography": bib_text,
        "draft_text": intro_text
    }), 200

@app.route('/initialize', methods=['POST'])
def initialize_work():
    data = request.json
    bib = data.get('bibliography', '')
    toc = data.get('toc', '')
    draft = data.get('draft_text', '')

    # Literatur-Check (wie in deinem ersten Tool)
    prompt_bib = (
        "Du bist Lektor. Überprüfe das Literaturverzeichnis auf Fehler.\n"
        "Antworte zeilenweise: STATUS (OK/FLAG), Nummer, Zitat - Begründung.\n\n"
        f"{bib}"
    )
    res_bib = call_gemini_direct(prompt_bib)
    
    # Struktur-Analyse
    prompt_struct = f"Analysiere die Struktur der Arbeit:\nInhalt: {toc}\nText: {draft}"
    analysis = call_gemini_direct(prompt_struct)

    # Wir bauen die Liste für das Frontend manuell zusammen
    checked_sources = []
    for line in res_bib.strip().split('\n'):
        if ',' in line:
            parts = line.split(',', 2)
            checked_sources.append({
                "status": "valide" if "OK" in parts[0].upper() else "warning",
                "id": parts[1].strip() if len(parts) > 1 else "?",
                "text": parts[2].strip() if len(parts) > 2 else line,
                "reason": "Verifiziert" if "OK" in parts[0].upper() else "Prüfen!"
            })

    return jsonify({
        "status": "success",
        "bibliography_check": checked_sources,
        "structural_analysis": analysis,
        "full_context": f"STRUKTUR:\n{analysis}\n\nLITERATUR:\n{bib}"
    })

@app.route('/evaluate', methods=['POST'])
def evaluate():
    data = request.json
    paragraph = data.get('paragraph', '')
    context = data.get('context_summary', '')

    # Agenten-Logik (wie in deinem ersten Tool)
    res_a = call_gemini_direct(f"Akademisches Lektorat (Stil, Logik): {paragraph}")
    res_b = call_gemini_direct(f"Fachprüfung im Kontext der Arbeit:\n{context}\n\nAbsatz: {paragraph}")

    # Synthese zu JSON
    prompt_c = (
        f"Erstelle ein Gutachten als JSON.\nLektorat: {res_a}\nFachprüfung: {res_b}\n"
        "Format: {\"gesamtnote_tendenz\": \"...\", \"kritikpunkte\": [{\"kategorie\": \"...\", \"original_zitat\": \"...\", \"kritikpunkt\": \"...\"}], \"ueberarbeiteter_absatz\": \"...\"}"
    )
    raw_eval = call_gemini_direct(prompt_c)
    
    # Robustes JSON-Parsing
    try:
        start = raw_eval.find('{')
        end = raw_eval.rfind('}') + 1
        return jsonify(json.loads(raw_eval[start:end])), 200
    except:
        return jsonify({"error": "JSON Fehler", "raw": raw_eval}), 500

if __name__ == '__main__':
    app.run(debug=True)
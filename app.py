from flask import Flask, render_template, request, jsonify
import os
import json
import io
import fitz  # PyMuPDF
from google import genai
from google.genai import types
from pydantic import BaseModel

app = Flask(__name__)

# API Konfiguration
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
client = genai.Client(api_key=GOOGLE_API_KEY)

# Pydantic Schema für strukturierte Extraktion
class ExtractionResult(BaseModel):
    content: str

def get_pdf_segment(pdf_bytes, start_page=None, end_page=None):
    """Extrahiert bestimmte Seitenbereiche als neues PDF-Byte-Objekt."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total_pages = doc.page_count
    
    # Standardwerte setzen
    if start_page is None: start_page = 0
    if end_page is None: end_page = total_pages
    
    new_doc = fitz.open()
    new_doc.insert_pdf(doc, from_page=start_page, to_page=min(end_page, total_pages-1))
    
    output_bytes = new_doc.write()
    new_doc.close()
    doc.close()
    return output_bytes

def call_gemini_sdk(prompt, pdf_segment):
    """Ruft Gemini über das offizielle SDK mit einem PDF-Teilstück auf."""
    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=[
                types.Part.from_bytes(data=pdf_segment, mime_type="application/pdf"),
                prompt
            ],
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
                response_schema=ExtractionResult
            )
        )
        # SDK gibt direkt das Pydantic-validierte Objekt zurück
        res_data = json.loads(response.text)
        return res_data.get("content", "Nicht gefunden")
    except Exception as e:
        return f"Fehler: {str(e)}"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/process_pdf', methods=['POST'])
def process_pdf():
    if 'file' not in request.files:
        return jsonify({"error": "Keine Datei"}), 400
    
    file = request.files['file']
    pdf_bytes = file.read()
    
    # Wir nutzen PyMuPDF um die Gesamtzahl der Seiten zu ermitteln
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total_pages = doc.page_count
    doc.close()

    # SCHRITT 1: Inhaltsverzeichnis (Seiten 1-10)
    toc_segment = get_pdf_segment(pdf_bytes, 0, 10)
    toc_text = call_gemini_sdk(
        "Extrahiere das vollständige Inhaltsverzeichnis. Antworte im JSON-Format {'content': '...'}", 
        toc_segment
    )

    # SCHRITT 2: Literaturverzeichnis (Letzte 15 Seiten)
    bib_segment = get_pdf_segment(pdf_bytes, max(0, total_pages - 15), total_pages)
    bib_text = call_gemini_sdk(
        "Extrahiere das vollständige Literaturverzeichnis. Antworte im JSON-Format {'content': '...'}", 
        bib_segment
    )

    # SCHRITT 3: Einleitung (Seiten 1-15, suche den Haupttext)
    intro_segment = get_pdf_segment(pdf_bytes, 0, 15)
    draft_text = call_gemini_sdk(
        "Suche das erste Kapitel (Einleitung/Introduction) und extrahiere die ersten 3-4 Seiten Text. Antworte im JSON-Format {'content': '...'}", 
        intro_segment
    )

    return jsonify({
        "toc": toc_text,
        "bibliography": bib_text,
        "draft_text": draft_text
    }), 200

@app.route('/initialize', methods=['POST'])
def initialize_work():
    # (Hier nutzen wir die bestehende Logik für den Literatur-Check)
    data = request.json
    bib = data.get('bibliography', '')
    
    # Einfacher Prompt für den Check
    response = client.models.generate_content(
        model="gemini-1.5-flash",
        contents=[f"Prüfe diese Literatur auf Korrektheit. Gib eine Liste 'entries' mit status, id, text, reason zurück: {bib}"],
        config=types.GenerateContentConfig(response_mime_type="application/json")
    )
    
    return jsonify({
        "status": "success",
        "bibliography_check": json.loads(response.text).get("entries", []),
        "structural_analysis": "Analyse abgeschlossen.",
        "full_context": f"LITERATUR:\n{bib}"
    })

@app.route('/evaluate', methods=['POST'])
def evaluate():
    data = request.json
    paragraph = data.get('paragraph', '')
    
    # Finales Gutachten via SDK
    prompt = f"Erstelle ein wissenschaftliches Gutachten für diesen Absatz: {paragraph}. Antworte als JSON mit gesamtnote_tendenz, kritikpunkte (Liste), ueberarbeiteter_absatz."
    
    response = client.models.generate_content(
        model="gemini-1.5-flash",
        contents=[prompt],
        config=types.GenerateContentConfig(response_mime_type="application/json")
    )
    
    return jsonify(json.loads(response.text)), 200

if __name__ == '__main__':
    app.run(debug=True)
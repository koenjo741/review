from flask import Flask, render_template, request, jsonify
from Bio import Entrez
import requests
import xml.etree.ElementTree as ET
import os
import json
import re

app = Flask(__name__)

PUBMED_EMAIL = "josef_koenig@hotmail.com"
PUBMED_API_KEY = "2d6671c4cc19fcc9bf7c972e504abf763b09"
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")

def call_gemini(prompt: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GOOGLE_API_KEY}"
    headers = {"Content-Type": "application/json"}
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    response = requests.post(url, headers=headers, json=payload, timeout=60)
    if response.status_code == 200:
        try:
            return response.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception:
            return "Fehler beim Parsen."
    return f"API-Fehler: {response.status_code}"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/initialize', methods=['POST'])
def initialize_work():
    data = request.json
    toc = data.get('toc', '')
    bibliography = data.get('bibliography', '')
    draft_text = data.get('draft_text', '')

    if not bibliography:
        return jsonify({"error": "Literaturverzeichnis fehlt."}), 400

    # 1. LLM-basierter Literatur-Parser (Exakt nach deiner erfolgreichen Strategie)
    parsing_prompt = (
        "Du bist Lektor einer wissenschaftlichen Zeitschrift.\n"
        "Überprüfe das folgende Literaturverzeichnis auf Korrektheit, Vollständigkeit und formale Fehler.\n\n"
        "Antworte AUSSCHLIESSLICH zeilenweise im folgenden Format (ohne Markdown-Blocks):\n"
        "STATUS (OK oder FLAG), Nummer des Zitates, gefolgt von den ersten 50 Zeichen des Zitates - Begründung (falls FLAG, ansonsten 'Valide').\n\n"
        "Beispiel:\n"
        "OK, 1, Rojas-Carabali W, Agrawal R - Valide\n"
        "FLAG, 105, Regulation (EU) 2024/1689 - Tippfehler im Wort 'Parliment'\n\n"
        f"Hier ist das Literaturverzeichnis:\n{bibliography}"
    )
    
    parsed_bib_response = call_gemini(parsing_prompt)

    # Verarbeite die Zeilen für das Frontend
    checked_sources = []
    for line in parsed_bib_response.strip().split('\n'):
        if not line.strip():
            continue
        parts = line.split(',', 2)
        if len(parts) >= 2:
            status = parts[0].strip().upper()
            num = parts[1].strip()
            rest = parts[2].strip() if len(parts) > 2 else ""
            
            is_valide = "OK" in status
            checked_sources.append({
                "id": num,
                "status": "valide" if is_valide else "warning",
                "text": rest,
                "reason": rest if not is_valide else "Verifiziert und formal korrekt."
            })

    # 2. Struktur-Analyse des Inhaltsverzeichnisses & Ist-Standes
    prompt_init = (
        f"Du bist ein wissenschaftlicher Prüfungsausschuss. Analysiere das Inhaltsverzeichnis und den bisherigen Textstand.\n\n"
        f"Inhaltsverzeichnis:\n{toc}\n\n"
        f"Bisheriger Ist-Stand (Volltext-Ausschnitt):\n{draft_text}\n\n"
        f"Gleiche das Inhaltsverzeichnis mit dem Ist-Stand ab und definiere präzise, welche Kapitel bereits geschrieben sind und welche noch fehlen."
    )
    analysis = call_gemini(prompt_init)
    full_context = f"--- STRUKTUR & IST-STAND ---\n{analysis}\n\n--- VOLLSTÄNDIGES LITERATURVERZEICHNIS DER ARBEIT ---\n{bibliography}"

    return jsonify({
        "status": "success",
        "bibliography_check": checked_sources,
        "structural_analysis": analysis,
        "full_context": full_context
    }), 200

@app.route('/evaluate', methods=['POST'])
def evaluate():
    data = request.json
    paragraph = data.get('paragraph', '')
    context_summary = data.get('context_summary', '')
    
    if not paragraph:
        return jsonify({"error": "Kein Absatz übergeben"}), 400

    try:
        prompt_a = f"Akademischer Lektor. Reviewe den Absatz auf Grammatik, Stil und Logik:\n{paragraph}"
        res_a = call_gemini(prompt_a)

        prompt_b = (
            f"Wissenschaftlicher Reviewer. Prüfe den Faktengehalt des Absatzes im Licht der Gesamtarbeit und des Literaturverzeichnisses.\n\n"
            f"Gesamtkontext & Literatur:\n{context_summary}\n\n"
            f"Aktueller Absatz:\n{paragraph}"
        )
        res_b = call_gemini(prompt_b)

        prompt_c = (
            f"Prüfungsvorsitzender. Erstelle das finale Gutachten als reines JSON:\n"
            f"Absatz: {paragraph}\n\nLektorat: {res_a}\n\nFachprüfung: {res_b}\n\n"
            f"STRIKTE SPRACHREGEL: Erkenne die Sprache des Originalabsatzes. "
            f"Der 'ueberarbeiteter_absatz' MUSS ZWINGEND IN EXAKT DERSELBEN SPRACHE BLEIBEN (Englischer Text bleibt auf Englisch, deutscher Text auf Deutsch)! Keine automatische Übersetzung!\n\n"
            f"Markiere korrigierte oder optimierte Textstellen im 'ueberarbeiteter_absatz' ausschließlich mit HTML-Leuchtstift-Tags: <span class=\"highlight\">optimierter Text</span>.\n\n"
            "Antworte AUSSCHLIESSLICH im Format:\n"
            "{\n"
            '  "gesamtnote_tendenz": "string",\n'
            '  "kritikpunkte": [\n'
            "    {\n"
            '      \"kategorie\": \"Stil/Logik oder Fachliche Evidenz\",\n'
            '      \"original_zitat\": \"string\",\n'
            '      \"kritikpunkt\": \"string\",\n'
            '      \"evidenz_nachweis\": \"string\"\n'
            "    }\n"
            "  ],\n"
            '  "ueberarbeiteter_absatz": "string"\n'
            "}"
        )
        
        raw_res = call_gemini(prompt_c).strip()
        if raw_res.startswith("```"):
            raw_res = raw_res.split("```")[1]
            if raw_res.startswith("json"): raw_res = raw_res[4:]
        raw_res = raw_res.strip()

        return jsonify(json.loads(raw_res)), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
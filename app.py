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

def search_pubmed(query: str) -> str:
    Entrez.email = PUBMED_EMAIL
    Entrez.api_key = PUBMED_API_KEY
    try:
        handle = Entrez.esearch(db="pubmed", term=f"{query} AND (review[pt] OR guideline[pt])", retmax=2)
        record = Entrez.read(handle)
        handle.close()
        id_list = record["IdList"]
        if not id_list: return "Nicht gefunden."
        fetch_handle = Entrez.efetch(db="pubmed", id=id_list, rettype="abstract", retmode="xml")
        articles = Entrez.read(fetch_handle)
        fetch_handle.close()
        res = [art['MedlineCitation']['Article'].get('ArticleTitle', '') for art in articles.get('PubmedArticle', [])]
        return "Gefunden in PubMed: " + " ; ".join(res)
    except Exception:
        return "Nicht in PubMed verifiziert."

def search_semanticscholar(query: str) -> str:
    url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={requests.utils.quote(query)}&limit=2&fields=title,year"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            papers = response.json().get("data", [])
            if not papers: return "Nicht gefunden."
            res = [f"{p.get('title')} ({p.get('year', 'k.A.')})" for p in papers]
            return "Gefunden in Semantic Scholar: " + " ; ".join(res)
    except Exception:
        pass
    return "Nicht in Semantic Scholar verifiziert."

def search_arxiv(query: str) -> str:
    url = f"http://export.arxiv.org/api/query?search_query=all:{requests.utils.quote(query)}&max_results=2"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            ns = {'atom': 'http://www.w3.org/2005/Atom'}
            entries = root.findall('atom:entry', ns)
            if not entries: return "Nicht gefunden."
            res = [e.find('atom:title', ns).text.strip().replace('\n', ' ') for e in entries if e.find('atom:title', ns) is not None]
            return "Gefunden auf arXiv: " + " ; ".join(res)
    except Exception:
        pass
    return "Nicht auf arXiv verifiziert."

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

    raw_entries = re.split(r'\n\s*\n|(?=\n\s*(?:\[\d+\]|\d+\.))', bibliography)
    bib_entries = [e.strip().replace('\n', ' ') for e in raw_entries if len(e.strip()) > 15]
    if len(bib_entries) <= 1:
        bib_entries = [line.strip() for line in bibliography.split('\n') if len(line.strip()) > 15]

    checked_sources = []
    for idx, entry in enumerate(bib_entries, start=1):
        clean_query = entry[:80]
        pm = search_pubmed(clean_query)
        s2 = search_semanticscholar(clean_query)
        arxiv_res = search_arxiv(clean_query)
        
        if "Nicht gefunden" not in pm or "Nicht gefunden" not in s2 or "Nicht gefunden" not in arxiv_res:
            checked_sources.append({"id": idx, "status": "valide", "text": entry})
        else:
            checked_sources.append({
                "id": idx, 
                "status": "warning", 
                "text": entry, 
                "reason": "In keiner akademischen Datenbank (PubMed, Semantic Scholar, arXiv) eindeutig verifiziert. Mögliche Fake-Quelle oder Tippfehler."
            })

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
        search_query = paragraph[:80]
        pubmed_res = search_pubmed(search_query)
        s2_res = search_semanticscholar(search_query)
        arxiv_res = search_arxiv(search_query)

        prompt_a = f"Akademischer Lektor. Reviewe den Absatz auf Grammatik, Stil und Logik:\n{paragraph}"
        res_a = call_gemini(prompt_a)

        prompt_b = (
            f"Wissenschaftlicher Reviewer. Prüfe den Faktengehalt des Absatzes im Licht der Gesamtarbeit und des Literaturverzeichnisses.\n\n"
            f"Gesamtkontext & Literatur:\n{context_summary}\n\n"
            f"Aktueller Absatz:\n{paragraph}\n\n"
            f"Live-Datenbank Evidenz:\n{pubmed_res}\n{s2_res}\n{arxiv_res}"
        )
        res_b = call_gemini(prompt_b)

        prompt_c = (
            f"Prüfungsvorsitzender. Erstelle das finale Gutachten als reines JSON:\n"
            f"Absatz: {paragraph}\n\nLektorat: {res_a}\n\nFachprüfung: {res_b}\n\n"
            f"WICHTIG SPRACHREGEL: Erkenne die Sprache des Originalabsatzes ({paragraph[:40]}...). "
            f"Der 'ueberarbeiteter_absatz' MUSS AUSNAHMSLOS IN DERSELBEN SPRACHLICHEN URSPRUNGSSPRACHE bleiben (Deutsch bleibt Deutsch, Englisch bleibt Englisch)! "
            f"Keine automatische Übersetzung in eine andere Sprache!\n\n"
            f"Markiere korrigierte oder optimierte Textstellen im 'ueberarbeiteter_absatz' unbedingt mit HTML-Leuchtstift-Tags wie <span class=\"highlight\">optimierter Text</span>.\n\n"
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
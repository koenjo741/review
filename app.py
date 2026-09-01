from flask import Flask, render_template, request, jsonify
import requests
import os
import json
import re

app = Flask(__name__)

# API Keys - Werden bevorzugt aus der Render-Umgebung (os.environ) geladen
PUBMED_EMAIL = os.environ.get("PUBMED_EMAIL", "josef_koenig@hotmail.com")
PUBMED_API_KEY = os.environ.get("PUBMED_API_KEY", "2d6671c4cc19fcc9bf7c972e504abf763b09")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
S2_API_KEY = os.environ.get("S2_API_KEY", "s2k-an3iWCohGVLwGyOWdzffZ9orI2E1ySNnp76Ojljo")

def call_gemini(prompt: str) -> str:
    """Ruft die Gemini API auf (Modell 1.5-flash für Schnelligkeit und Stabilität)."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GOOGLE_API_KEY}"
    headers = {"Content-Type": "application/json"}
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=120)
        if response.status_code == 200:
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            return f"API-Fehler: {response.status_code} - {response.text}"
    except Exception as e:
        return f"Verbindungsfehler zu Gemini: {str(e)}"

def call_semantic_scholar(query: str, limit: int = 3):
    """Sucht nach wissenschaftlicher Literatur via Semantic Scholar API (Tag 9: RAG)."""
    endpoint = "https://api.semanticscholar.org/graph/v1/paper/search"
    headers = {"x-api-key": S2_API_KEY}
    params = {
        "query": query,
        "limit": limit,
        "fields": "title,authors,year,abstract,url,citationCount"
    }
    try:
        response = requests.get(endpoint, headers=headers, params=params, timeout=15)
        if response.status_code == 200:
            return response.json().get("data", [])
        return []
    except Exception:
        return []

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/initialize', methods=['POST'])
def initialize_work():
    """Phase 1: Onboarding, Literatur-Check und Struktur-Analyse."""
    try:
        data = request.json
        toc = data.get('toc', '')
        bibliography = data.get('bibliography', '')
        draft_text = data.get('draft_text', '')

        if not bibliography:
            return jsonify({"error": "Literaturverzeichnis fehlt."}), 400

        # Literatur-Parsing in Chunks (Tag 1: Token-Management)
        bib_lines = [line for line in bibliography.split('\n') if line.strip()]
        chunk_size = 80
        chunks = [bib_lines[i:i + chunk_size] for i in range(0, len(bib_lines), chunk_size)]

        checked_sources = []
        global_id_counter = 1

        for chunk in chunks:
            chunk_text = "\n".join(chunk)
            parsing_prompt = (
                "Du bist Lektor einer wissenschaftlichen Zeitschrift.\n"
                "Überprüfe das folgende Teilstück eines Literaturverzeichnisses auf Korrektheit.\n"
                "Antworte AUSSCHLIESSLICH zeilenweise im Format:\n"
                "STATUS (OK oder FLAG), Nummer, Zitat-Anfang - Begründung.\n\n"
                f"Hier ist das Teilstück:\n{chunk_text}"
            )
            parsed_response = call_gemini(parsing_prompt)

            for line in parsed_response.strip().split('\n'):
                if not line.strip(): continue
                parts = line.split(',', 2)
                if len(parts) >= 2:
                    status = parts[0].strip().upper()
                    rest = parts[2].strip() if len(parts) > 2 else ""
                    is_valide = "OK" in status
                    checked_sources.append({
                        "id": global_id_counter,
                        "status": "valide" if is_valide else "warning",
                        "text": rest,
                        "reason": rest if not is_valide else "Verifiziert."
                    })
                    global_id_counter += 1

        # Struktur-Analyse
        prompt_init = (
            f"Analysiere das Inhaltsverzeichnis und den Ist-Stand der Masterarbeit.\n"
            f"Inhaltsverzeichnis:\n{toc}\n\n"
            f"Bisheriger Text:\n{draft_text}\n\n"
            "Prüfe: 1. Fehlende Kapitel, 2. Formale Bestandteile, 3. Stringenz, 4. State-of-the-Art."
        )
        analysis = call_gemini(prompt_init)
        full_context = f"--- STRUKTUR ---\n{analysis}\n\n--- LITERATUR ---\n{bibliography}"

        return jsonify({
            "status": "success",
            "bibliography_check": checked_sources,
            "structural_analysis": analysis,
            "full_context": full_context
        }), 200

    except Exception as e:
        return jsonify({"error": f"Server-Fehler: {str(e)}"}), 500

@app.route('/evaluate', methods=['POST'])
def evaluate():
    """Phase 2: Agiles 3-Agenten-Lektorat mit Semantic Scholar RAG."""
    try:
        data = request.json
        paragraph = data.get('paragraph', '')
        context_summary = data.get('context_summary', '')
        
        if not paragraph:
            return jsonify({"error": "Kein Absatz übergeben"}), 400

        # SCHRITT 1: Keyword-Extraktion für RAG (Tag 9)
        keyword_prompt = f"Extrahiere die 3 wichtigsten wissenschaftlichen Suchbegriffe aus diesem Absatz für eine Literaturrecherche: {paragraph}"
        keywords = call_gemini(keyword_prompt)
        
        # SCHRITT 2: Externe Evidenz einholen (Semantic Scholar)
        evidence_data = call_semantic_scholar(keywords)
        evidence_text = "\n".join([
            f"- {p['title']} ({p['year']}): {p.get('abstract', '')[:300]}..." 
            for p in evidence_data
        ]) if evidence_data else "Keine direkte externe Evidenz gefunden."

        # AGENT A: Sprachlich-logisches Lektorat
        prompt_a = f"Akademischer Lektor. Reviewe Stil, Grammatik und Logik:\n{paragraph}"
        res_a = call_gemini(prompt_a)

        # AGENT B: Fachliche Evidenzprüfung (mit RAG-Daten)
        prompt_b = (
            f"Wissenschaftlicher Reviewer. Prüfe den Faktengehalt.\n"
            f"Gesamtkontext der Arbeit:\n{context_summary}\n\n"
            f"Gefundene externe Literatur-Evidenz:\n{evidence_text}\n\n"
            f"Zu prüfender Absatz:\n{paragraph}"
        )
        res_b = call_gemini(prompt_b)

        # AGENT C: Synthesizer (Erstellt das finale JSON - Tag 5: Constrained Generation)
        prompt_c = (
            f"Prüfungsvorsitzender. Erstelle ein finales Gutachten als JSON.\n"
            f"Lektorat: {res_a}\n\nFachprüfung: {res_b}\n\n"
            f"STRIKTE REGEL: Sprache des Originals beibehalten. HTML-Highlights im Text nutzen.\n"
            "Format:\n"
            "{\n"
            '  "gesamtnote_tendenz": "string",\n'
            '  "kritikpunkte": [{"kategorie": "...", "original_zitat": "...", "kritikpunkt": "...", "evidenz_nachweis": "..."}],\n'
            '  "ueberarbeiteter_absatz": "string"\n'
            "}"
        )
        
        raw_res = call_gemini(prompt_c).strip()
        
        # JSON-Bereinigung (falls Markdown-Tags geliefert werden)
        if "```json" in raw_res:
            raw_res = raw_res.split("```json")[1].split("```")[0]
        elif "```" in raw_res:
            raw_res = raw_res.split("```")[1].split("```")[0]
        
        return jsonify(json.loads(raw_res.strip())), 200

    except Exception as e:
        return jsonify({"error": f"Server-Fehler bei der Evaluierung: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(debug=True)
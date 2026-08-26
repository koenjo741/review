@app.route('/initialize', methods=['POST'])
def initialize_work():
    data = request.json
    toc = data.get('toc', '')
    bibliography = data.get('bibliography', '')
    draft_text = data.get('draft_text', '')

    if not bibliography:
        return jsonify({"error": "Literaturverzeichnis fehlt."}), 400

    # 1. Bereinige PDF-Artefakte (Kopf-/Fusszeilen wie Seitenzahlen und Datumsangaben)
    cleaned_bib = re.sub(r'July\s+\d+,\s+\d{4}.*?BSc\..*?\d+/\d+', '', bibliography)
    cleaned_bib = re.sub(r'\b[A-Za-z\s]+\b,\s+BSc\..*?\d+/\d+', '', cleaned_bib)
    cleaned_bib = re.sub(r'\d+/\d+\s*$', '', cleaned_bib, flags=re.MULTILINE)

    # 2. Intelligentes Splitting: Trennt zuverlässig bei Autorenwechseln oder Jahreszahlen im Text, 
    # damit zusammengeführte Literaturklumpen in Einzelquellen aufgelöst werden.
    # Wir suchen nach Mustern wie "Nachname A, Nachname B. (Jahr)" oder "Name et al. Jahr."
    pattern = r'(?=(?:[A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)*|\w+)\s+(?:et al\.|[A-ZÄÖÜ][a-zäöüß]+)\.\s+[A-Z].*?\b(?:19|20)\d{2}\b)'
    
    potential_entries = re.split(pattern, cleaned_bib)
    bib_entries = []
    
    for entry in potential_entries:
        cleaned_entry = entry.replace('\n', ' ').strip()
        # Entferne führende alte Ziffern/Nummern im Rohtext, damit wir sie sauber neu durchnummerieren können
        cleaned_entry = re.sub(r'^[\d\.\s\[\]]+', '', cleaned_entry).strip()
        if len(cleaned_entry) > 15:  # Nur echte Literaturstellen aufnehmen
            bib_entries.append(cleaned_entry)

    # Falls der Regex-Split bei bestimmten Formatierungen greift, Fallback auf Zeilenbasis
    if len(bib_entries) < 3:
        bib_entries = [re.sub(r'^[\d\.\s\[\]]+', '', line.replace('\n', ' ')).strip() for line in bibliography.split('\n') if len(line.strip()) > 15]

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
                "reason": "In keiner akademischen Datenbank (PubMed, Semantic Scholar, arXiv) verifiziert. Bitte prüfen (mögliche Fake-Quelle oder abweichende Schreibweise)."
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
@app.route('/initialize', methods=['POST'])
def initialize_work():
    data = request.json
    toc = data.get('toc', '')
    bibliography = data.get('bibliography', '')
    draft_text = data.get('draft_text', '')

    if not bibliography:
        return jsonify({"error": "Literaturverzeichnis fehlt."}), 400

    # Intelligentes Trennen von Literaturangaben (anhand von Leerzeilen oder Doppelumbrüchen)
    bib_entries = [entry.strip() for entry in bibliography.split('\n\n') if len(entry.strip()) > 10]
    if len(bib_entries) <= 1:
        # Falls keine Doppelumbrüche genutzt wurden, nehmen wir einzelne Zeilen, filtern aber kurze Fragmente weg
        bib_entries = [line.strip() for line in bibliography.split('\n') if len(line.strip()) > 15]

    checked_sources = []
    for entry in bib_entries:  # JETZT WERDEN ALLE QUELLEN GEPRÜFT
        # Bereinige den Suchstring für die API (nutze die ersten 80 Zeichen des Eintrags)
        clean_query = entry.replace('\n', ' ')[:80]
        pm = search_pubmed(clean_query)
        s2 = search_semanticscholar(clean_query)
        arxiv_res = search_arxiv(clean_query)
        
        if "Nicht gefunden" not in pm or "Nicht gefunden" not in s2 or "Nicht gefunden" not in arxiv_res:
            checked_sources.append(f"✓ Valide: {entry.replace(chr(10), ' ')}")
        else:
            checked_sources.append(f"⚠ Potenziell unbestätigt/Fake: {entry.replace(chr(10), ' ')}")

    prompt_init = (
        f"Du bist ein wissenschaftlicher Prüfungsausschuss. Analysiere das Inhaltsverzeichnis und den bisherigen Textstand.\n\n"
        f"Inhaltsverzeichnis:\n{toc}\n\n"
        f"Bisheriger Ist-Stand (Volltext-Ausschnitt):\n{draft_text}\n\n"
        f"Gleiche das Inhaltsverzeichnis mit dem Ist-Stand ab und definiere präzise, welche Kapitel bereits geschrieben sind und welche noch fehlen."
    )
    analysis = call_gemini(prompt_init)

    return jsonify({
        "status": "success",
        "bibliography_check": checked_sources,
        "structural_analysis": analysis
    }), 200
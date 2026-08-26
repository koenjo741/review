from flask import Flask, render_template, request, jsonify
from Bio import Entrez
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from typing import List
import os

app = Flask(__name__)

# Konfiguration
PUBMED_EMAIL = "josef_koenig@hotmail.com"
PUBMED_API_KEY = "2d6671c4cc19fcc9bf7c972e504abf763b09"

# Zentraler Client (verhindert Mehrfach-Instanziierung und spart RAM)
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
client = genai.Client(api_key=GOOGLE_API_KEY)

def search_pubmed(query: str) -> str:
    """Sucht in PubMed nach medizinischer Evidenz."""
    Entrez.email = PUBMED_EMAIL
    Entrez.api_key = PUBMED_API_KEY
    try:
        handle = Entrez.esearch(db="pubmed", term=f"{query} AND (review[pt] OR guideline[pt])", retmax=3)
        record = Entrez.read(handle)
        handle.close()
        id_list = record["IdList"]
        if not id_list: 
            return "Keine PubMed-Ergebnisse gefunden."
        fetch_handle = Entrez.efetch(db="pubmed", id=id_list, rettype="abstract", retmode="xml")
        articles = Entrez.read(fetch_handle)
        fetch_handle.close()
        res = []
        for art in articles['PubmedArticle']:
            title = art['MedlineCitation']['Article'].get('ArticleTitle', 'Kein Titel')
            res.append(title)
        return "PubMed Treffer: " + " ; ".join(res)
    except Exception as e: 
        return f"PubMed Fehler: {str(e)}"

class FeedbackItem(BaseModel):
    kategorie: str = Field(description="'Stil/Logik' oder 'Fachliche Evidenz'")
    original_zitat: str = Field(description="Die beanstandete Passage")
    kritikpunkt: str = Field(description="Präzise Begründung des Mangels")
    evidenz_nachweis: str = Field(default="", description="Quelle/DOI bei fachlichen Fehlern")

class MasterarbeitReview(BaseModel):
    gesamtnote_tendenz: str = Field(description="z.B. 'Sehr gut', 'Überarbeitungsbedürftig'")
    kritikpunkte: List[FeedbackItem]
    ueberarbeiteter_absatz: str = Field(description="Vorschlag für den fertig formulierten Absatz")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/evaluate', methods=['POST'])
def evaluate():
    data = request.json
    text = data.get('text', '')
    
    if not text:
        return jsonify({"error": "Kein Text übergeben"}), 400

    try:
        # Agent A: Lektorat (Schnellmodell)
        prompt_a = f"Du bist ein akademischer Lektor. Reviewe den Text auf Grammatik, Stil und Logik: {text}"
        res_a = client.models.generate_content(model="gemini-2.5-flash", contents=prompt_a)

        # Agent B: Fachprüfung mit PubMed-Tool (Pro-Modell)
        prompt_b = f"Du bist ein medizinischer Reviewer und Informatiker. Prüfe die Fakten im Text: {text}. Nutze search_pubmed bei Bedarf."
        chat = client.chats.create(
            model="gemini-2.5-pro", 
            config=types.GenerateContentConfig(
                tools=[search_pubmed]
            )
        )
        res_b = chat.send_message(prompt_b)

        # Agent C: Prüfungsvorsitz & JSON-Synthese
        prompt_c = f"Du bist der Prüfungsvorsitzende. Original: {text}\n\nLektorat: {res_a.text}\n\nFachprüfung: {res_b.text}\n\nErstelle das finale Gutachten als JSON."
        res_c = client.models.generate_content(
            model="gemini-2.5-pro", 
            contents=prompt_c, 
            config=types.GenerateContentConfig(
                response_mime_type="application/json", 
                response_schema=MasterarbeitReview
            )
        )
        
        # Direkte Rückgabe des JSON-Strings an das Frontend
        return res_c.text, 200, {'Content-Type': 'application/json'}

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
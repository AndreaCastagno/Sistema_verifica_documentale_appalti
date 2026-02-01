#attestati
#back

from fastapi import APIRouter, UploadFile, File
#APIRouter, permette di creare  un gruppo di enpoit separati dal file principale
#UploadFile, file caricato dall’utente tramite HTTP
#File def. i parametri del file negli endpoint

from ocr.ocr_engine import extract_text     #Importa la funzione extract_text dal programma ocr_engine.py
from datetime import date, timedelta        #Importa il tipo date per la gestione delle scadenze
from typing import List                     #mporta List, che serve per dire a FastAPI che i miei valori sono liste di oggetti
import re                                      
'''Importa il modulo delle espressioni regolari. Serve per
riconoscere pattern come date/ricerca parole chiave: Regex
'''
import smtplib                              #SMTP per invio mail
from email.mime.text import MIMEText        #Serve per crea il corpo del messaggio email in Txt.

router = APIRouter()

# 0) CONFIGURAZIONE EMAIL

# Gmail SMTP, creaz. costanti per l'invio di mail (in futuro dovranno essere dei campi di unput per il login)
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587                             #porta ufficiale standard internazionale per il protocollo SMTP 
SMTP_USER = "******@gmail.com"     #Mail partenza 
SMTP_PASS = "******"              #Password per app di google, censurata per privacy

TO_EMAIL = "******@gmail.com"      #Mail fornitore


"""Invia una email di testo semplice via SMTP.
    definisce una funzione con destinatario, oggetto , testo"""
def send_email_sync(to_email: str, subject: str, body: str):   

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = to_email

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server: #Si connette con SMTP verso il server indicato
        server.starttls()   #Avvia server
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
    #Costrutto with chiude connessione in automatico

def format_attestato_block(result: dict) -> str:
    """Crea il blocco di testo per ogni file, tutto nella stessa mail
    Prende un result (dizionario con i dati di un attestato) e 
    restituisce una stringa formattata
    Smplicemente prende il risultato di un attestato alla volta e 
    costruisce una stringa formattata"""
    #Estrae due sotto-dizionari da result:
    course_info = result.get("course_info", {})
    validity = result.get("validity", {})
    
    #Estrazione dei singoli campi
    course_type = course_info.get("course_type")
    course_date = validity.get("course_date")
    expiry_date = validity.get("expiry_date")
    is_expired = validity.get("is_expired")
    days_to_expiry = validity.get("days_to_expiry")

    # stato leggibile
    if is_expired is True:
        stato = "SCADUTO"
    elif is_expired is False:
        stato = "VALIDO"
    else:
        stato = "NON DETERMINABILE" #Per None

    giorni_str = "n/d" if days_to_expiry is None else str(days_to_expiry) #altrimenti converte il numero in stringa.

    #Costruisce una stringa multilinea
    block = f"""Esito verifica attestato di formazione

File: {result.get('filename')}
Tipo corso riconosciuto: {course_type}

Data corso: {course_date}
Scadenza: {expiry_date}

Stato: {stato}
Giorni alla scadenza (se positivi) / da quando è scaduto (se negativi): {giorni_str}
"""
    return block


def send_attestati_result_email(results: List[dict]):  #La funzione attende una lista di dizionari
    """
    Invia UNA SOLA mail con un blocco per ogni attestato analizzato.
    """
    if not results:
        return #Se results è vuota la funzione esce subito senza inviare mail

    blocks = [format_attestato_block(r) for r in results] #ottiene una lista di righe per ogni attestato
    body = "\n\n------------------------------\n\n".join(blocks) #unisce tutti i blocchi un un unica strinza e divide in paragrafi
    subject = f"Esito verifica attestati ({len(results)} documenti)"

    send_email_sync(TO_EMAIL, subject, body)

# 1) PULIZIA DEL TESTO PRIMA DELLA RICERCA DELLE PAROLE CHIAVE

def normalize(text: str) -> str:
    t = text.lower()
    t = t.replace("\n", " ")
    t = re.sub(r"\s+", " ", t)
    return t.strip()

# 2) RICONOSCIMENTO TIPO DI CORSO TRAMITE KEYWORDS

COURSE_KEYWORDS = {
    "preposto": [
        "corso per preposto", "formazione preposti", "preposto alla sicurezza"
    ],
    "rspp": [
        "rspp", "responsabile del servizio di prevenzione e protezione"
    ],
    "antincendio": [
        "corso antincendio", "addetto antincendio", "antincendio", "formazione antincendio"
    ],
    "primo_soccorso": [
        "corso di primo soccorso", "soccorso", "addetto al primo soccorso", "formazione primo soccorso"
    ],
    "generale": [
        "formazione generale", "corso di formazione della durata", "formazione lavoratori"
    ],
}
    #DIZIONARIO DI LISTE  DI PAROLE CHIAVE    

    #anni di validità per ciascun tipo di corso
COURSE_VALIDITY_YEARS = {
    "generale": 5,
    "preposto": 2,
    "rspp": 5,
    "antincendio": 3,
    "primo_soccorso": 3,
}
DEFAULT_VALIDITY_YEARS = 5      #fallback se non riconosciuto
    

def detect_course_type(text: str) -> dict:
    """Riconosce UN solo tipo di corso (oppure 'sconosciuto')."""
    norm = normalize(text)     #usa funzione normalize in punto 1

    '''Per ogni tipo di corso e relative parole chiave, verifica se almeno una keyword
    è presente nel testo normalizzato `norm`. Se sì, aggiunge il tipo di corso
    trovato a `matched_types` e la keyword corrispondente a `matched_keywords`,
    evitando duplicati per lo stesso tipo (grazie al break).'''
    for course_type, patterns in COURSE_KEYWORDS.items():
        for kw in patterns:
            if kw in norm:
                # appena trovo una keyword, ritorno SUBITO
                return {
                    "course_type": course_type,
                    "matched_types": [course_type],
                    "matched_keywords": [kw],
                }

    # se nessuna parola chiave è stata trovata:
    return {
        "course_type": "sconosciuto",
        "matched_types": [],
        "matched_keywords": [],
    }


# 3) RILEVAZIONE DATE CORSO E SCADENZA

#Rileva date con due cifre separate da carattere speciale, separate da /, - o . oppure date con mese testuale
NUMERIC_DATE = r"(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{2,4})"
TEXTUAL_DATE = r"(\d{1,2})\s+(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre|gen|feb|mar|apr|mag|giu|lug|ago|set|ott|nov|dic)\s+(\d{4})"

IT_MONTHS = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6,
    "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
    "gen": 1, "feb": 2, "mar": 3, "apr": 4, "mag": 5, "giu": 6, "lug": 7, "ago": 8,
    "set": 9, "ott": 10, "nov": 11, "dic": 12,
}

#Pattern generico: o numerica o testuale per indicare sempre le date
DATE_ANY_REGEX = (
    r"\d{1,2}[\/\-.]\d{1,2}[\/\-.]\d{2,4}"
    r"|\d{1,2}\s+(?:gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre|gen|feb|mar|apr|mag|giu|lug|ago|set|ott|nov|dic)\s+\d{4}"
)               #^^^ ?: = “raggruppa, ma NON creare un gruppo catturante”


def parse_it_date(fragment: str):
    """legge la stringa e le trasforma (parse) in date italiane sia numeriche che testuali."""
    s = fragment.strip().lower()

    #Prova prima a leggere una data numerica; tipo: 19/01/2021
    m = re.search(NUMERIC_DATE, s)     
    if m:
        d = int(m.group(1))
        mth = int(m.group(2))
        y = int(m.group(3))
        if y < 100:             #visto che anno può essere di 2 cifre
            y = 2000 + y
        try:
            return date(y, mth, d)
        except ValueError:
            return None

    #Prova quella testuale; 15 novembre 2012
    m = re.search(TEXTUAL_DATE, s)
    if m:
        d = int(m.group(1))
        mname = m.group(2)
        y = int(m.group(3))
        mth = IT_MONTHS.get(mname)
        if not mth:
            return None
        try:
            return date(y, mth, d)
        except ValueError:
            return None

    return None


def add_years(d: date, years: int) -> date:
    """Aggiunge anni in base alla scadenza; gestisce anche il 29/02."""
    try:
        return date(d.year + years, d.month, d.day)
    except ValueError:
        if d.month == 2 and d.day == 29:
            return date(d.year + years, 2, 28)
        raise


def extract_course_date(text: str) -> dict:
    """
    Cerca la data di svolgimento/fine corso.
    Priorità:
    1) "dal DATA al DATA2" (numerica o testuale) → usa DATA2
    2) etichette tipo 'svoltosi il', 'effettuato il', 'rilasciato il' + DATA
    3) ultima data che NON è vicino a 'nato/nata'
    """
    norm = normalize(text)

    # 1) cerca range "dal ... al ..."
    m_range = re.search(
        r"dal\s+(" + DATE_ANY_REGEX + r")\s+al\s+(" + DATE_ANY_REGEX + r")",
        norm
    )
    if m_range:
        end_fragment = m_range.group(2)
        course_date = parse_it_date(end_fragment)
        if course_date:
            return {
                "course_date": course_date,
                "evidence": m_range.group(0)
            }

    # 2) frasi tipo "svoltosi il DATA", "effettuato il DATA", ...
    for label in ["svoltosi il", "svolto il", "effettuato il", "effettuata il", "rilasciato il", "rilasciata il"]:
        m = re.search(label + r"\s+(.{0,35})", norm)
        if m:
            fragment = m.group(1)
            parsed = parse_it_date(fragment)
            if parsed:
                return {
                    "course_date": parsed,
                    "evidence": label + " " + fragment
                }

    # 3) fallback: ultima data NON vicina a "nato/nata/nascit"
    last_date = None
    last_evidence = None
    for m in re.finditer(DATE_ANY_REGEX, norm):
        fragment = m.group(0)
        parsed = parse_it_date(fragment)
        if not parsed:
            continue

        # contesto prima della data (per evitare la data di nascita)
        start = max(0, m.start() - 30)
        context = norm[start:m.start()]
        if "nato" in context or "nata" in context or "nascit" in context:
            continue  # se il contesto è quello della data di nascita lo salta

        last_date = parsed
        last_evidence = fragment

    if last_date:
        return {
            "course_date": last_date,
            "evidence": last_evidence
        }

    return {
        "course_date": None,
        "evidence": None
    }


def compute_course_validity(course_date: date | None, course_info: dict) -> dict:
    """
    Calcola la scadenza in base al tipo di corso.
    Assume che ci sia al massimo UN tipo di corso.
    """
    if not course_date:
        return {
            "course_date": None,
            "expiry_date": None,
            "is_expired": None,
            "days_to_expiry": None,
            "validity_years": None,
        }

    course_type = course_info.get("course_type")

    if course_type and course_type != "sconosciuto":
        validity_years = COURSE_VALIDITY_YEARS.get(course_type, DEFAULT_VALIDITY_YEARS)
    else:
        # se non riconosciuto, usa durata di default
        validity_years = DEFAULT_VALIDITY_YEARS

    expiry = add_years(course_date, validity_years)
    today = date.today()
    is_expired = expiry < today
    days_to_expiry = (expiry - today).days

    return {
        "course_date": course_date.isoformat(),
        "expiry_date": expiry.isoformat(),              #ISO ovvero aaaa/mm/gg
        "is_expired": is_expired,
        "days_to_expiry": days_to_expiry,
        "validity_years": validity_years,
    }

# 4) ENDPOINT FASTAPI - MULTIPLI

@router.post("/check-multiple", summary="Analisi multipla attestati di formazione")
async def check_attestati_multipli(files: List[UploadFile] = File(...)):
    #async... è una funzione seguita quando qualcuno fa una richiesta POST a quell’URL
    #List[UploadFile] indica che si possono mandare più file
    #File(...) è un parametro obbligatorio, preso dal body della richiesta (form-data)
    """
    - Riceve più file (PDF/immagini) nello stesso request
    - Per ogni file:
        - OCR
        - riconoscimento tipo corso
        - data corso
        - scadenza in base al ruolo
    - Restituisce una lista di risultati
    - Invia UNA mail con il riepilogo di tutti i documenti
    """
    results = []

    for f in files:
        #Scorre tutti i file caricati dal cliente
        #Legge in memoria i byte del file f (PDF o immagine).
        #Passa i byte all’OCR
        content = await f.read()
        text = extract_text(content)

        course_info = detect_course_type(text)      #analizza testo e capisce il tipo corso + restituisce dict.
        date_info = extract_course_date(text)       #individua data 
        validity = compute_course_validity(date_info["course_date"], course_info) #calcola data scadenza, conta giorni a scadenza ecc.

        results.append({
            "filename": f.filename,
            "document": "attestato_formazione",
            "course_info": course_info,
            "validity": {
                **validity,
                "evidence": date_info["evidence"],
            },
            "preview_text": text[:500],
        })

    # invia mail con TUTTI i risultati nella stessa mail (vedi blocco precedente)
    try:
        send_attestati_result_email(results)
    except Exception as e:
        print(f"[ATTESTATI][EMAIL] Errore invio mail (multipli): {e}")

    return {
        "count": len(results),
        "results": results,
    }

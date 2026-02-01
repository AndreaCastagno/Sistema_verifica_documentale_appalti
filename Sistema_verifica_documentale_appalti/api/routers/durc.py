#DURC
#I comandi comuni con il programma attestati.py non verranno spiegati nuovamente
from fastapi import APIRouter, UploadFile, File
from ocr.ocr_engine import extract_text
from datetime import date, timedelta
import smtplib
from email.mime.text import MIMEText
import re

router = APIRouter()

# 1) PULIZIA TESTO

# Vedi spiegazione di attestati
def normalize(text: str) -> str:
    t = text.lower()
    t = t.replace("\n", " ")
    t = re.sub(r"\s+", " ", t)
    return t.strip()


# 2) RICONOSCIMENTO DOCUMENTO DURC

DURC_KEYWORDS = [
    "durc",
    "durc on-line",
    "durc on line",
    "risulta regolare",
    "inps",
    "inail",
]

#prende in input la stringa generata dall'ocr e restituisce un dizionario
def is_durc_document(text: str) -> dict:
    norm = normalize(text)
    found = [kw for kw in DURC_KEYWORDS if kw in norm] 
    #ogni parola nel testo normalizzato viene aggiunta alla lista found
    # euristica: almeno 4 parole chiave devono essere riconosciute nel documento per considerarlo DURC
    return {
        "is_durc": len(found) >= 4,
        "keywords_found": found,
    }


# 3) ESTRAZIONE DATE
# Vedi spiegazione di attestati
DATE_REGEX = r"(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})"


def parse_numeric_date(fragment: str):
    """legge stringa e trasforma in una data numerica (parse) dd/mm/yyyy o dd-mm-yyyy, 
    non sono presenti mesi scritti in forma letterale come
    nel programma precedente"""
    m = re.search(DATE_REGEX, fragment)
    if not m:
        return None
    d = int(m.group(1))
    mth = int(m.group(2))
    y = int(m.group(3))
    try:
        return date(y, mth, d)
    except ValueError:
        return None


def find_labeled_date(norm_text: str, labels: list[str]) -> tuple[date | None, str | None]:
    #ritorna una tupla tipo (data trovata oppure None, stringa oppure None)
    """
    Carca una data numerica subito dopo una delle etichette
    Restituisce (data, evidenza_testuale)
    """
    for label in labels:
        idx = norm_text.find(label) #restituisce l’indice della stringa in cui la parola appare
        if idx == -1:
            continue
        window = norm_text[idx: idx + 30]  # 30 caratteri dopo l’etichetta
        #^^^ serve per evitare di cercare date in tutto il documento ma solo in una finestra
        m = re.search(DATE_REGEX, window)
        if m:
            frag = m.group(0)               #frag sta per fragment ed è il pezzo di stringa trovata
            parsed = parse_numeric_date(frag)
            if parsed:
                evidence = window.strip()
                return parsed, evidence
    return None, None


def extract_durc_dates(text: str) -> dict:
    """
    Estrae la 'scadenza validità' riportata sul DURC
    Determina se il documento è valido confrontando la scadenza stampata con la data odierna
    """
    norm = normalize(text)

    # 1) Scadenza validità stampata sul DURc
    printed_labels = [
        "scadenza validità",
    ]   #Etichetta che precede la scadenza
    printed_expiry, printed_evidence = find_labeled_date(norm, printed_labels)
    #^^ Restituisce una tupla destrutturata 
    
    # 2) Stato rispetto alla data odierna
    today = date.today()
    is_expired = None
    days_to_expiry = None

    if printed_expiry:
        is_expired = printed_expiry < today
        days_to_expiry = (printed_expiry - today).days

    return {
        "printed_expiry_date": printed_expiry.isoformat() if printed_expiry else None,
        "printed_expiry_evidence": printed_evidence,
        "is_expired": is_expired,
        "days_to_expiry": days_to_expiry,
    }

   

# 4) CONFIGURAZIONE EMAIL

# Gmail SMTP
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "******.com"     #Mail partenza 
SMTP_PASS = "******"  

TO_EMAIL = "******.com"      #Mail forniotre


def send_email_sync(to_email: str, subject: str, body: str):
    """Invia una email di testo semplice via SMTP."""
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = to_email

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)


def send_durc_result_email(result: dict):
    """
    Costruisce il testo della mail a partire dal risultato dell'analisi DURC
    e la invia. La validità è valutata SOLO in base alla scadenza riportata sul DURC.
    """
    #Estrae due sotto-dizionari da result:
    detected = result.get("detected", {})
    info = result.get("durc_info", {})

    is_durc = detected.get("is_durc")
    printed_expiry_date = info.get("printed_expiry_date")
    is_expired = info.get("is_expired")
    days_to_expiry = info.get("days_to_expiry")

    # stato leggibile
    if is_expired is True:
        stato = "SCADUTO"
    elif is_expired is False:
        stato = "VALIDO"
    else:
        stato = "NON DETERMINABILE"

    # giorni per la scadenza
    if days_to_expiry is None:
        giorni_str = "n/d"
    else:
        giorni_str = str(days_to_expiry)

    subject = f"Esito verifica DURC - {stato}"

    body = f"""Esito verifica documento DURC

File: {result.get('filename')}
Riconosciuto come DURC: {is_durc}

Scadenza riportata sul DURC: {printed_expiry_date}

Stato (in base alla scadenza riportata): {stato}
Giorni alla scadenza (se positivi) / da quando è scaduto (se negativi): {giorni_str}

"""

    send_email_sync(TO_EMAIL, subject, body)

#Il programma è analogo a attestati.py ma non contiene la possibilità di mandare il report di 2 verifiche contemporaneee"""''





# 5) ENDPOINT FASTAPI

@router.post("/check", summary="Analisi DURC")
async def check_durc(file: UploadFile = File(...)):
    """
    - OCR del documento
    - euristica per capire se è un DURC
    - estrazione data scadenza stampata
    - verifica se è ancora valido oggi
    - invio mail con esito istantaneo
    """
    content = await file.read()     #Legge i byte del file caricato via API
    text = extract_text(content)    #Legge i byte del file caricato via API
    
    durc_flag = is_durc_document(text)      #Identifica se il documento è effettivamente un DURC
    dates_info = extract_durc_dates(text)   #Estrae la data di scadenza

    result = {
        "filename": file.filename,
        "document": "durc",
        "detected": durc_flag,
        "durc_info": dates_info,
        "preview_text": text[:500],
    }   # Risultato mostrato su FastAPI

    # Invio mail senza bloccare l’API se qualcosa è errato
    try:
        send_durc_result_email(result)
    except Exception as e:
         # Se l’invio fallisce mostra in console terminale/visualstudio
        print(f"[DURC][EMAIL] Errore invio mail: {e}")

    return result

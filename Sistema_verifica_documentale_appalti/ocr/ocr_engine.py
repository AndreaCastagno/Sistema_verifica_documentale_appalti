#ocr_engine.py


import pytesseract                          #Collegamento tesseract, per restituire testo da immagine
from pdf2image import convert_from_bytes    #Libr. per conversine PDF in lista di immagini
from PIL import Image                       #Libr. per aprire Img.    
from io import BytesIO                      #Libr. per aprire Img. dai suoi byte

def extract_text(file_bytes):               #file_bytes è il file caricato su FastAPI, vedi Routers
    try:                                    #Prova a convertire PDF in Img.  
        pages = convert_from_bytes(file_bytes)
    except:
        pages = [Image.open(BytesIO(file_bytes))] #Se try non ha successo converte Img. in byte

    text = ""                               #Inizializza una stringa vuota
    for page in pages:                      #Per ogni Pg. esegue OCR su immagine (in italiano)
        text += pytesseract.image_to_string(page, lang="ita")

    return text


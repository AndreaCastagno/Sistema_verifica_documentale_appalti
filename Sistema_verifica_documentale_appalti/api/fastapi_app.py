#fastapi_app

#Aggiunge i router alla pagina principale di FastAPI

from fastapi import FastAPI
from api.routers import durc, attestati 
#Importa i moduli durc e attestati dal package api.routers

app = FastAPI(title="Sistema di pre-verifica documentale per ditte appaltatrici")
#Crea app e inserisce un titolo all'interfaccia creata 

#Associa i router ad app
app.include_router(durc.router, prefix="/durc", tags=["DURC"])
app.include_router(attestati.router, prefix="/attestati", tags=["Attestati"])


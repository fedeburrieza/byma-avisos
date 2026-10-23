"""
Avisos de Hecho Relevante de BYMA -> Telegram

Uso:
    python byma_alertas.py            # una pasada (para cron / GitHub Actions)
    python byma_alertas.py --loop     # revisa cada 3 minutos (para probar en tu PC)

Variables de entorno (NO poner el token en el codigo):
    TELEGRAM_TOKEN     token del bot
    TELEGRAM_CHAT_ID   tu chat_id
    TICKERS            (opcional) lista separada por coma, ej: GGAL,YPFD,PAMP
                       Si esta vacio, avisa de todos los emisores.
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

URL = "https://open.bymadata.com.ar/vanoms-be-core/rest/api/bymadata/free/bnown/relevant-facts"
PAGINA = "https://open.bymadata.com.ar/#/issuers-negociable-securities-information"
TZ = ZoneInfo("America/Argentina/Buenos_Aires")
STATE_FILE = Path(__file__).with_name("seen.json")
DIAS_ATRAS = 3          # ventana de consulta
INTERVALO_LOOP = 180    # segundos (solo con --loop)
FALLOS_PARA_ALERTAR = 5

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
TICKERS = {t.strip().upper() for t in os.environ.get("TICKERS", "").split(",") if t.strip()}

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://open.bymadata.com.ar",
    "Referer": "https://open.bymadata.com.ar/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
}


def cargar_estado():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"seen": [], "fallos": 0, "inicializado": False}


def guardar_estado(estado):
    estado["seen"] = estado["seen"][-3000:]  # no crece para siempre
    STATE_FILE.write_text(json.dumps(estado), encoding="utf-8")


def telegram(texto):
    r = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": texto, "disable_web_page_preview": True},
        timeout=20,
    )
    r.raise_for_status()


def traer_avisos():
    hoy = datetime.now(TZ).date()
    payload = {
        "filter": True,
        "publishDate": (hoy - timedelta(days=DIAS_ATRAS)).isoformat(),
        "publishToDate": hoy.isoformat(),
        "dateEntryFrom": None,
        "dateEntryTo": None,
    }
    r = requests.post(URL, json=payload, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json().get("data", [])


def es_hecho_relevante(aviso):
    ref = aviso.get("referencia", "").strip().lower()
    if ref.startswith("hecho relevante de cedear"):
        return False  # los hechos de cedears no interesan
    return ref.startswith("hecho relevante")


def pasa_filtro_ticker(aviso):
    if not TICKERS:
        return True
    return aviso.get("especie", "").upper() in TICKERS


def formatear(aviso):
    ticker = aviso.get("especie") or "-"
    return (
        f"📢 HECHO RELEVANTE\n"
        f"{aviso.get('emisor', '')} ({ticker})\n\n"
        f"{aviso.get('referencia', '')}\n\n"
        f"🕒 {aviso.get('fecha', '')[:16]}\n"
        f"{PAGINA}"
    )


def pasada():
    estado = cargar_estado()
    try:
        avisos = traer_avisos()
        estado["fallos"] = 0
    except Exception as e:
        estado["fallos"] += 1
        print(f"Error consultando BYMA ({estado['fallos']}): {e}")
        if estado["fallos"] == FALLOS_PARA_ALERTAR:
            telegram(f"⚠️ El bot no puede consultar BYMA hace {FALLOS_PARA_ALERTAR} intentos: {e}")
        guardar_estado(estado)
        return

    vistos = set(estado["seen"])
    nuevos = []
    for a in avisos:
        id_ = a.get("descarga")
        if id_ is None or id_ in vistos:
            continue
        vistos.add(id_)
        estado["seen"].append(id_)
        if es_hecho_relevante(a) and pasa_filtro_ticker(a):
            nuevos.append(a)

    if not estado["inicializado"]:
        # Primera corrida: se marcan como vistos sin enviar, para no inundarte.
        estado["inicializado"] = True
        print(f"Primera corrida: {len(avisos)} avisos marcados como vistos, no se envia nada.")
    else:
        nuevos.sort(key=lambda a: a.get("fecha", ""))
        for a in nuevos:
            telegram(formatear(a))
            print("Enviado:", a.get("emisor"), "-", a.get("referencia"))
        if not nuevos:
            print("Sin hechos relevantes nuevos.")

    guardar_estado(estado)


if __name__ == "__main__":
    if not TOKEN or not CHAT_ID:
        sys.exit("Faltan las variables de entorno TELEGRAM_TOKEN y TELEGRAM_CHAT_ID.")
    if "--loop" in sys.argv:
        while True:
            pasada()
            time.sleep(INTERVALO_LOOP)
    else:
        pasada()

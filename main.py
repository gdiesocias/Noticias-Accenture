import os
import smtplib
import re
import time
import random
from difflib import SequenceMatcher
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, make_msgid
from gnews import GNews
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urlparse
from functools import lru_cache

import requests

# =========================
# 1) CONFIGURACIÓN (ENV)
# =========================
EMAIL_USER = os.environ.get("EMAIL_USER", "").strip()
EMAIL_PASS = os.environ.get("EMAIL_PASS", "").strip()
EMAIL_TO_RAW = os.environ.get("EMAIL_TO", "").strip()  # puede ser "a@a.com,b@b.com; c@c.com"

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587").strip() or 587)
SMTP_TIMEOUT = int(os.environ.get("SMTP_TIMEOUT", "20").strip() or 20)

# DEBUG (ponlo a 1 si quieres ver por consola por qué se acepta/rechaza una noticia)
DEBUG_SOURCES = os.environ.get("DEBUG_SOURCES", "0").strip() == "1"

# =========================
# 2) CLIENTES
# =========================
CLIENTES = [
    "Banco Sabadell", "BBVA", "CaixaBank", "Iberdrola", "Airbus",
    "Repsol", "Banco Santander", "Amadeus", "EDP", "Masorange",
    "El Corte Inglés", "Endesa", "Mapfre", "Telefónica"
]

# =========================
# 3) PALABRAS CLAVE
# =========================
KEYWORDS_EXACTAS = ["IA", "ESG", "CX", "BPM", "GenAI", "IoT", "PwC", "EY", "KPMG", "BCG", "IBM", "CEO", "OPA", "CIO", "CTO"]

KEYWORDS_GENERALES = [
    "inteligencia artificial", "big data", "alianza", "ecosistema",
    "estrategia", "organización", "organigrama", "talento", "transformación",
    "digitalización", "innovación", "automatización", "eficiencia",
    "machine learning", "cloud", "ciberseguridad", "blockchain",
    "fintech", "insurtech", "renovables", "sostenibilidad",
    "regulación", "compliance", "transición energética",
    "reskilling", "híbrido", "futuro del trabajo", "resultados", "beneficio"
]

# =========================
# 4) PALABRAS PROHIBIDAS
# =========================
PALABRAS_PROHIBIDAS = [
    "fútbol", "futbol", "liga", "champions", "gol", "partido", "alineación",
    "fichaje", "entrenador", "baloncesto", "tenis", "nadal", "alonso",
    "sucesos", "accidente", "lotería"
]

# =========================
# 5) LISTA BLANCA DE MEDIOS (PRO)
# - Se filtra por DOMINIO REAL (resolviendo redirects de Google News)
# - Puedes añadir/quitar dominios aquí
# =========================
ALLOWED_DOMAINS = {
   # Generalistas
    "elpais.com",
    "elmundo.es",
    "abc.es",
    "20minutos.es",
    "eldiario.es",
    "elespanol.com",
    "larazon.es",
    "lavanguardia.com",
    "madridiario.es",
    "levante-emv.com",
    "diariodesevilla.es",
    "elcorreo.com",
    "elnortedecastilla.es",
    "heraldo.es",
    

    # Económicos / empresa
    "expansion.com",
    "cincodias.elpais.com",
    "cincodias.com",
    "eleconomista.es",
    "invertia.com",
    "elconfidencial.com",
    "vozpopuli.com",
    "capitalmadrid.com",
    "laverdad.es",
    "diariodemallorca.es",
    "canarias7.es",
    "diariodenavarra.es",
    "diariomontanes.es",

    
    # Internacionales
    "reuters.com",
    "bloomberg.com",
    "ft.com",
    "wsj.com",
}

# Opcional: lista negra por si hay dominios que se cuelan por redirects raros
BLOCKED_DOMAINS = {
    # "facebook.com", "youtube.com"
}

EMAIL_REGEX = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)

# HTTP session (reutilizable)
_HTTP = requests.Session()
_HTTP.headers.update({"User-Agent": "Mozilla/5.0"})

# =========================
# Helpers PRO: dominio + resolución + caché + logging
# =========================
def _netloc(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ""

def _looks_like_google_redirect(url: str) -> bool:
    host = _netloc(url)
    if not host:
        return False
    # gnews suele devolver news.google.com o enlaces google intermedios
    return any(x in host for x in ("news.google.com", "news.googleusercontent.com", "google.com"))

@lru_cache(maxsize=5000)
def resolve_final_url(url: str) -> str:
    """
    Resuelve redirects SOLO cuando parece enlace intermedio de Google.
    Cacheado para no penalizar rendimiento.
    """
    try:
        if not _looks_like_google_redirect(url):
            return url
        r = _HTTP.get(url, allow_redirects=True, timeout=10)
        return r.url or url
    except Exception:
        return url

def allowed_by_domain(url: str) -> Tuple[bool, str, str]:
    """
    Devuelve (allowed, domain, final_url)
    """
    final_url = resolve_final_url(url)
    dom = _netloc(final_url)

    if not dom:
        return False, "", final_url

    if any(dom == b or dom.endswith("." + b) for b in BLOCKED_DOMAINS):
        return False, dom, final_url

    allowed = any(dom == a or dom.endswith("." + a) for a in ALLOWED_DOMAINS)
    return allowed, dom, final_url

def debug_log(msg: str) -> None:
    if DEBUG_SOURCES:
        print(msg)

# =========================
# Parsing / Validaciones
# =========================
def parse_recipients(raw: str) -> List[str]:
    """
    Acepta una cadena con emails separados por coma o punto y coma.
    Devuelve una lista de emails limpios y validados.
    """
    if not raw:
        return []
    parts = re.split(r"[;,]", raw)
    emails = []
    for p in parts:
        e = p.strip()
        if not e:
            continue
        if EMAIL_REGEX.match(e):
            emails.append(e)
        else:
            print(f"⚠️ EMAIL_TO contiene un email inválido y se ignora: {e}")
    # dedup conservando orden
    seen = set()
    unique = []
    for e in emails:
        if e not in seen:
            unique.append(e)
            seen.add(e)
    return unique

def validate_env(recipients: List[str]) -> None:
    if not EMAIL_USER:
        raise RuntimeError("Falta la variable de entorno EMAIL_USER.")
    if not EMAIL_PASS:
        raise RuntimeError("Falta la variable de entorno EMAIL_PASS.")
    if not recipients:
        raise RuntimeError("Falta EMAIL_TO o no hay destinatarios válidos (separa por comas o ;).")

def contiene_palabra_prohibida(texto: str) -> bool:
    for prohibida in PALABRAS_PROHIBIDAS:
        if re.search(r"\b" + re.escape(prohibida) + r"\b", texto):
            return True
    return False

def es_similar(a: str, b: str) -> bool:
    return SequenceMatcher(None, a, b).ratio() > 0.65

def get_article_url(articulo: Dict[str, Any]) -> str:
    """
    PRO: gnews puede devolver url en 'url' o 'link' según versión/feed.
    """
    return (articulo.get("url") or articulo.get("link") or "").strip()

# =========================
# BÚSQUEDA + FILTRO (PRO)
# =========================
def buscar_y_filtrar() -> List[Dict[str, Any]]:
    print(f"🚀 AGENTE NUBE (PRO): {datetime.now().strftime('%H:%M:%S')}")
    google_news = GNews(language="es", country="ES", period="1d", max_results=100)

    noticias_relevantes: List[Dict[str, Any]] = []
    titulos_vistos: List[str] = []

    for i, cliente in enumerate(CLIENTES):
        try:
            # Throttle para evitar rate-limits
            time.sleep(random.uniform(1.0, 2.0))

            print(f"[{i+1}/{len(CLIENTES)}] 🔹 {cliente}...", end="")
            resultados = google_news.get_news(cliente)
            print(f" {len(resultados)} analizadas.")

            for articulo in resultados:
                titulo = (articulo.get("title") or "").strip()
                url = (articulo.get("url") or articulo.get("link") or "").strip()
                descripcion = articulo.get("description") or ""

                if not titulo or not url:
                    continue

                # 1) Filtro por medios (dominio real)
                allowed, dom, final_url = allowed_by_domain(url)
                if not allowed:
                    debug_log(f"    ⛔ RECHAZADA (medio) dom={dom} url={final_url[:120]}")
                    continue
                debug_log(f"    ✅ OK (medio) dom={dom}")

                # 2) Texto a analizar
                texto_analizar = (titulo + " " + descripcion).lower()

                # 3) Palabras prohibidas
                if contiene_palabra_prohibida(texto_analizar):
                    debug_log(f"    ⛔ RECHAZADA (prohibidas) '{titulo[:80]}'")
                    continue

                # 4) Dedupe por similitud de título
                if any(es_similar(titulo.lower(), t.lower()) for t in titulos_vistos):
                    debug_log(f"    ⛔ RECHAZADA (duplicada) '{titulo[:80]}'")
                    continue

                # 5) Keywords
                temas_encontrados = []

                for kw in KEYWORDS_GENERALES:
                    if kw.lower() in texto_analizar:
                        temas_encontrados.append(kw)

                for kw in KEYWORDS_EXACTAS:
                    patron = r"\b" + re.escape(kw.lower()) + r"\b"
                    if re.search(patron, texto_analizar):
                        temas_encontrados.append(kw)

                if not temas_encontrados:
                    debug_log(f"    ⛔ RECHAZADA (sin keywords) '{titulo[:80]}'")
                    continue

                titulos_vistos.append(titulo)
                temas_str = ", ".join(sorted(set(temas_encontrados), key=str.lower)).upper()

                noticias_relevantes.append({
                    "cliente": cliente,
                    "temas": temas_str,
                    "titulo": titulo,
                    "url": final_url,  # usamos URL final del medio
                    "fecha": articulo.get("published date", "N/D"),
                    "fuente": (articulo.get("publisher") or {}).get("title", dom or "Google News"),
                    "dominio": dom,
                })

        except Exception as e:
            print(f"⚠️ Error {cliente}: {e}")

    return noticias_relevantes

# =========================
# EMAIL
# =========================
def construir_html(noticias: List[Dict[str, Any]]) -> str:
    noticias.sort(key=lambda x: x["cliente"])

    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 20px;">
        <div style="max-width: 680px; margin: 0 auto; background-color: #ffffff; padding: 20px; border-radius: 8px;">
            <h2 style="color: #2c3e50;">📊 Reporte Diario (Nube) - PRO</h2>
            <p>Se han detectado <strong>{len(noticias)}</strong> noticias relevantes hoy.</p>
            <hr>
    """

    current_client = ""
    for n in noticias:
        if n["cliente"] != current_client:
            html += f"<h3 style='background-color: #eee; color: #333; padding: 8px; margin-top: 20px;'>{n['cliente']}</h3>"
            current_client = n["cliente"]

        titulo = n["titulo"]
        url = n["url"]
        fuente = n.get("fuente", "Google News")
        fecha = n.get("fecha", "N/D")
        temas = n.get("temas", "")
        dom = n.get("dominio", "")

        html += f"""
        <div style="margin-bottom: 15px; border-left: 3px solid #2980b9; padding-left: 10px;">
            <div style="font-size: 10px; color: #e67e22; font-weight: bold;">{temas}</div>
            <a href="{url}" style="font-size: 14px; font-weight: bold; color: #333; text-decoration: none;">{titulo}</a>
            <div style="font-size: 11px; color: #888;">{fuente} ({dom}) - {fecha}</div>
        </div>
        """

    html += "</div></body></html>"
    return html

def enviar_correo(noticias: List[Dict[str, Any]], recipients: List[str]) -> None:
    if not noticias:
        print("\n📭 Informe vacío.")
        return

    html = construir_html(noticias)

    msg = MIMEMultipart()
    msg["From"] = EMAIL_USER

    # Para privacidad: ponemos un To "neutro" (tú mismo) y el envío real va por BCC (recipients)
    msg["To"] = EMAIL_USER
    msg["Subject"] = f"🚀 Reporte Cloud (PRO): {len(noticias)} noticias"
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=None)

    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(EMAIL_USER, EMAIL_PASS)

            # Envío REAL a la lista de destinatarios (varios correos)
            server.sendmail(EMAIL_USER, recipients, msg.as_string())

        print(f"✅ Correo enviado a {len(recipients)} destinatario(s): {', '.join(recipients)}")
    except Exception as e:
        print(f"❌ Error enviando correo: {e}")

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    recipients = parse_recipients(EMAIL_TO_RAW)
    validate_env(recipients)

    datos = buscar_y_filtrar()
    enviar_correo(datos, recipients)




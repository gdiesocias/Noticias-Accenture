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
from typing import List, Dict, Any, Tuple
from urllib.parse import urlparse
from functools import lru_cache

import requests

# =========================
# 1) CONFIGURACIÓN (ENV)
# =========================
EMAIL_USER = os.environ.get("EMAIL_USER", "").strip()
EMAIL_PASS = os.environ.get("EMAIL_PASS", "").strip()
EMAIL_TO_RAW = os.environ.get("EMAIL_TO", "").strip()

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587").strip() or 587)
SMTP_TIMEOUT = int(os.environ.get("SMTP_TIMEOUT", "20").strip() or 20)

# DEBUG
DEBUG_SOURCES = True  # pon False cuando ya funcione

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
# 5) WHITELISTS (SEPARADAS)
# =========================
# SOLO DOMINIOS AQUÍ
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
    "laverdad.es",
    "diariodemallorca.es",
    "canarias7.es",
    "diariodenavarra.es",
    "diariomontanes.es",
    "RTVE.es",
    "heraldo.es",
    "ElPlural.com",
    "Finanzas.com",
    "eldiariocantabria.es",

    # Económicos / empresa
    "expansion.com",
    "cincodias.elpais.com",
    "cincodias.com",
    "eleconomista.es",
    "invertia.com",
    "elconfidencial.com",
    "vozpopuli.com",
    "capitalmadrid.com",

    # Internacionales
    "reuters.com",
    "bloomberg.com",
    "ft.com",
    "wsj.com",
}

# SOLO NOMBRES DE MEDIO AQUÍ (publisher.title)
ALLOWED_PUBLISHERS = {
    "El País", "EL PAÍS",
    "El Mundo", "EL MUNDO",
    "ABC",
    "20minutos",
    "elDiario.es",
    "EL ESPAÑOL", "El Español",
    "La Razón",
    "La Vanguardia",
    "Expansión",
    "Cinco Días",
    "elEconomista.es", "El Economista", "elEconomista",
    "El Confidencial",
    "Vozpópuli", "Vozpopuli",
    "Capital Madrid",
    "Diario de Sevilla",
    "Heraldo de Aragón", "Heraldo",
    "El Norte de Castilla",
    "El Correo",
    "La Verdad",
    "Diario de Mallorca",
    "Canarias7", "Canarias 7",
    "Diario de Navarra",
    "El Diario Montañés",
    "El Periódico",
    "Bolsamania",
    "Cadena SER",
    "COPE",
    "Faro de Vigo",
    "Europa Press",
    "La Voz de Galicia",
    "RTVE.es",
    "heraldo.es",
    "ElPlural.com",
    "Finanzas.com",
    "eldiariocantabria.es",
    "Infodefensa",
}

BLOCKED_DOMAINS = set()

def debug_log(msg: str) -> None:
    if DEBUG_SOURCES:
        print(msg)

def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())

ALLOWED_PUBLISHERS_NORM = {norm(x) for x in ALLOWED_PUBLISHERS}

EMAIL_REGEX = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)

_HTTP = requests.Session()
_HTTP.headers.update({"User-Agent": "Mozilla/5.0"})

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
    return any(x in host for x in ("news.google.com", "news.googleusercontent.com", "google.com"))

@lru_cache(maxsize=5000)
def resolve_final_url(url: str) -> str:
    """
    OJO: los enlaces /rss/articles/ NO siempre redirigen a la web final.
    Aun así, intentamos; si no, devolvemos el propio link.
    """
    try:
        if not _looks_like_google_redirect(url):
            return url
        r = _HTTP.get(url, allow_redirects=True, timeout=10)
        return r.url or url
    except Exception:
        return url

def allowed_source(articulo: Dict[str, Any]) -> Tuple[bool, str, str, str]:
    """
    Decide si aceptar por:
    - Si dom == news.google.com => usar publisher (porque no se puede resolver a dominio real)
    - Si dom != news.google.com => usar dominios
    Devuelve: (allowed, dom, final_url, publisher_raw)
    """
    url = (articulo.get("url") or articulo.get("link") or "").strip()
    publisher_raw = ((articulo.get("publisher") or {}).get("title") or "").strip()

    final_url = resolve_final_url(url)
    dom = _netloc(final_url)

    # Bloqueos por dominio
    if dom and any(dom == b or dom.endswith("." + b) for b in BLOCKED_DOMAINS):
        return False, dom, final_url, publisher_raw

    # Caso RSS wrapper
    if dom == "news.google.com":
        pub_ok = norm(publisher_raw) in ALLOWED_PUBLISHERS_NORM
        return pub_ok, dom, final_url, publisher_raw

    # Caso normal: dominio final
    dom_ok = any(dom == a or dom.endswith("." + a) for a in ALLOWED_DOMAINS)
    return dom_ok, dom, final_url, publisher_raw

def parse_recipients(raw: str) -> List[str]:
    if not raw:
        return []
    parts = re.split(r"[;,]", raw)
    emails = []
    for p in parts:
        e = p.strip()
        if e and EMAIL_REGEX.match(e):
            emails.append(e)
    # dedup
    seen = set()
    out = []
    for e in emails:
        if e not in seen:
            out.append(e)
            seen.add(e)
    return out

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

def buscar_y_filtrar() -> List[Dict[str, Any]]:
    print(f"🚀 AGENTE NUBE (PRO): {datetime.now().strftime('%H:%M:%S')}")
    google_news = GNews(language="es", country="ES", period="1d", max_results=100)

    noticias_relevantes: List[Dict[str, Any]] = []
    titulos_vistos: List[str] = []

    for i, cliente in enumerate(CLIENTES):
        try:
            time.sleep(random.uniform(1.0, 2.0))
            print(f"[{i+1}/{len(CLIENTES)}] 🔹 {cliente}...", end="")
            resultados = google_news.get_news(cliente)
            print(f" {len(resultados)} analizadas.")

            for articulo in resultados:
                titulo = (articulo.get("title") or "").strip()
                descripcion = articulo.get("description") or ""
                if not titulo:
                    continue

                url = (articulo.get("url") or articulo.get("link") or "").strip()
                if not url:
                    continue

                allowed, dom, final_url, publisher = allowed_source(articulo)
                if not allowed:
                    debug_log(f"    ⛔ RECHAZADA (medio) dom={dom} publisher='{publisher}' url={final_url[:120]}")
                    continue
                debug_log(f"    ✅ OK (medio) dom={dom} publisher='{publisher}'")

                texto_analizar = (titulo + " " + descripcion).lower()

                if contiene_palabra_prohibida(texto_analizar):
                    debug_log(f"    ⛔ RECHAZADA (prohibidas) '{titulo[:80]}'")
                    continue

                if any(es_similar(titulo.lower(), t.lower()) for t in titulos_vistos):
                    debug_log(f"    ⛔ RECHAZADA (duplicada) '{titulo[:80]}'")
                    continue

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
                    "url": final_url,  # si es news.google.com, será wrapper; al menos se abre en Google News
                    "fecha": articulo.get("published date", "N/D"),
                    "fuente": publisher or dom or "Google News",
                    "dominio": dom,
                })

        except Exception as e:
            print(f"⚠️ Error {cliente}: {e}")

    return noticias_relevantes

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

    if not noticias:
        html += "<p style='color:#888;'>No se han encontrado noticias relevantes con los filtros actuales.</p>"

    current_client = ""
    for n in noticias:
        if n["cliente"] != current_client:
            html += f"<h3 style='background-color: #eee; color: #333; padding: 8px; margin-top: 20px;'>{n['cliente']}</h3>"
            current_client = n["cliente"]

        html += f"""
        <div style="margin-bottom: 15px; border-left: 3px solid #2980b9; padding-left: 10px;">
            <div style="font-size: 10px; color: #e67e22; font-weight: bold;">{n.get("temas","")}</div>
            <a href="{n.get("url","")}" style="font-size: 14px; font-weight: bold; color: #333; text-decoration: none;">{n.get("titulo","")}</a>
            <div style="font-size: 11px; color: #888;">{n.get("fuente","")} - {n.get("fecha","N/D")}</div>
        </div>
        """

    html += "</div></body></html>"
    return html

def enviar_correo(noticias: List[Dict[str, Any]], recipients: List[str]) -> None:
    # Enviar incluso si está vacío (para saber que el job corrió)
    if not noticias:
        print("\n📭 Informe vacío (se enviará correo igualmente).")

    html = construir_html(noticias)

    msg = MIMEMultipart()
    msg["From"] = EMAIL_USER
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
            server.sendmail(EMAIL_USER, recipients, msg.as_string())

        print(f"✅ Correo enviado a {len(recipients)} destinatario(s): {', '.join(recipients)}")
    except Exception as e:
        print(f"❌ Error enviando correo: {e}")

if __name__ == "__main__":
    recipients = parse_recipients(EMAIL_TO_RAW)
    validate_env(recipients)

    datos = buscar_y_filtrar()
    enviar_correo(datos, recipients)




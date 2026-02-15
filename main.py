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
# 2) CLIENTES, COMPETIDORES Y PARTNERS
# =========================
CLIENTES = [
    "Banco Sabadell", "BBVA", "CaixaBank", "Iberdrola", "Airbus",
    "Repsol", "Banco Santander", "Amadeus", "EDP", "Masorange",
    "El Corte Inglés", "Endesa", "Mapfre", "Telefónica", "Vodafone",
    "Moeve", "Ibercaja", "Naturgy", "Bankinter", "Red Eléctrica", "Redeia",
    "Antonio Puig", "Inditex", "Gestamp", "Mutua Madrileña", "Ferrovial", 
    "Unicaja", "Antolin", "Mahou", "Kutxabank", "Grupo Planeta", "Altice",
    "Acciona", "Galp", "Navantia",
]

COMPETIDORES = [
    "NTT Data", "Deloitte", "Capgemini", "Inetum", "Telefónica",
    "Kyndryl", "EY", "DXC", "Indra", "Minsait", "KPMG", "PWC", "WPP", "BCG", "Mckinsey", 
]

PARTNERS = [
    "Microsoft",
    "Google",
    "AWS",
    "Salesforce",
    "SAP",
    "ServiceNow",
    "Oracle",
    "IBM",
    "Databricks",
    "Workday",
]

# =========================
# 3) PALABRAS CLAVE
# =========================
KEYWORDS_EXACTAS = [
    # Cargos clave (movimiento de poder)
    "CEO",
    "CIO",
    "CTO",

    # Tecnología core estratégica
    "ERP",
    "SAP",
    "RPA",
    "IPO",
    "OPA"
]

KEYWORDS_GENERALES = [

    # --- Inversión / Oportunidad ---
    "inversión",
    "invertirá",
    "invertirá en",
    "destina",
    "destinará",
    "licita",
    "licitación",
    "adjudica",
    "adjudicación",
    "adjudicatario",
    "contrato",
    "renovación de contrato",
    "extensión de contrato",
    "acuerdo marco",
    "acuerdo plurianual",
    "concurso público",
    "pliego",
    "rfp",
    "rfi",
    "tender",
    "solicitud de ofertas",
    "proceso competitivo",
    "convocatoria",
    "plan",
    "plan estratégico",
    "plan de transformación",
    "programa estratégico",
    "programa de eficiencia",
    "plan de reducción de costes",
    "plan de ahorro",
    "presupuesto",
    "capex",
    "opex",
    "roadmap",
    "revisión estratégica",
    "spin-off",
    "escisión",
    "carve-out",
    "integración tras adquisición",

    # --- Verbos de acción frecuentes en prensa ---
    "lanza",
    "lanza plan",
    "impulsa",
    "impulsará",
    "pone en marcha",
    "activa",
    "aprueba",
    "autoriza",
    "moderniza",
    "renueva",
    "renovará",
    "actualiza",
    "digitaliza",
    "digitalización",
    "transformación digital",
    "nuevo sistema",
    "nueva plataforma",
    "nuevo modelo operativo",
    "externaliza",
    "subcontrata",
    "implementa",
    "implementará",
    "implantará",
    "despliega",
    "desarrollará",

    # --- Tecnología core Accenture ---
    "inteligencia artificial",
    "ia generativa",
    "inteligencia generativa",
    "genai",
    "machine learning",
    "big data",
    "analytics",
    "analítica avanzada",
    "data platform",
    "data governance",
    "gobierno del dato",
    "modernización tecnológica",
    "core bancario",
    "erp",
    "sap",
    "s/4hana",
    "salesforce",
    "servicenow",
    "oracle",
    "migración",
    "migración a la nube",
    "cloud",
    "cloud híbrido",
    "nube híbrida",
    "multi-cloud",
    "infraestructura cloud",
    "infraestructura tecnológica",
    "infraestructura digital",
    "data center",
    "centro de datos",
    "automatización",
    "automatización inteligente",
    "automatización de procesos",
    "rpa",
    "hyperautomation",
    "low code",
    "plataforma digital",
    "plataforma tecnológica",
    "software corporativo",
    "ciberseguridad",
    "ciberresiliencia",
    "zero trust",
    "identidad digital",
    "blockchain",

    # --- Organización / Movimiento ejecutivo ---
    "nuevo ceo",
    "nuevo cio",
    "nuevo cto",
    "nuevo ciso",
    "nombramiento",
    "relevo",
    "cese",
    "reestructuración",
    "cambio organizativo",
    "dirección digital",
    "dirección de tecnología",
    "transformación organizativa",

    # --- ESG / Regulación ---
    "esg",
    "csrd",
    "taxonomía europea",
    "reporting esg",
    "descarbonización",
    "huella de carbono",
    "eficiencia energética",
    "hidrógeno",
    "movilidad eléctrica",
    "regulación",
    "normativa",
    "cumplimiento normativo",
    "compliance",
    "supervisión",
    "requerimientos regulatorios",
    "resiliencia operativa",
    "dora",
    "basel iii",
    "regulatory framework",

    # --- Incidentes / Riesgo ---
    "fallo tecnológico",
    "colapso del sistema",
    "interrupción del servicio",
    "caída del sistema",
    "problemas informáticos",
    "brecha de seguridad",
    "ataque informático",
    "ciberataque",
    "ransomware",
    "filtración de datos",
    "data breach",
    "cyber attack",
    "ransomware attack",
    "it outage",
    "system failure",

    # --- Alianzas ---
    "alianza estratégica",
    "joint venture",
    "colaboración",
    "partnership",
    "acuerdo tecnológico",
    "selecciona a",
    "elige a",
    "partners with",
    "awards contract",
    "awarded contract",

    # --- Modelo operativo ---
    "outsourcing",
    "bpo",
    "managed services",
    "centro de excelencia",
    "coe",
    "hub tecnológico",
    "digital factory",

    # --- English expansion ---
    "investment",
    "to invest",
    "launches",
    "rolls out",
    "deploys",
    "implements",
    "selects",
    "appoints",
    "transformation program",
    "digital transformation",
    "modernization",
    "cloud migration",
    "core system upgrade",
    "erp implementation",
    "technology upgrade",
    "cost reduction plan",
    "efficiency program",
    "it overhaul"
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
    "ElPlural.com",
    "Finanzas.com",
    "eldiariocantabria.es",

    # Económicos / empresa
    "expansion.com",
    "cincodias.elpais.com",
    "cincodias.com",
    "eleconomista.es",
    "elconfidencial.com",
    "capitalmadrid.com",

    # Internacionales
    "reuters.com",
    "bloomberg.com",
    "ft.com",
    "wsj.com",
}

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
    "Cadena SER",
    "COPE",
    "Faro de Vigo",
    "Europa Press",
    "La Voz de Galicia",
    "RTVE.es",
    "ElPlural.com",
    "Finanzas.com",
    "eldiariocantabria.es",
    "Infodefensa",
}

BLOCKED_DOMAINS = set()

# ✅ MUST CHANGE #1: Normalizar dominios a minúsculas
ALLOWED_DOMAINS = {d.strip().lower() for d in ALLOWED_DOMAINS}
BLOCKED_DOMAINS = {d.strip().lower() for d in BLOCKED_DOMAINS}

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
    try:
        if not _looks_like_google_redirect(url):
            return url
        r = _HTTP.get(url, allow_redirects=True, timeout=10)
        return r.url or url
    except Exception:
        return url

def allowed_source(articulo: Dict[str, Any]) -> Tuple[bool, str, str, str]:
    url = (articulo.get("url") or articulo.get("link") or "").strip()
    publisher_raw = ((articulo.get("publisher") or {}).get("title") or "").strip()

    final_url = resolve_final_url(url)
    dom = _netloc(final_url)

    if dom and any(dom == b or dom.endswith("." + b) for b in BLOCKED_DOMAINS):
        return False, dom, final_url, publisher_raw

    if dom == "news.google.com":
        pub_ok = norm(publisher_raw) in ALLOWED_PUBLISHERS_NORM
        return pub_ok, dom, final_url, publisher_raw

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

# ✅ MUST CHANGE #3: published date robusto
def get_published(articulo: Dict[str, Any]) -> str:
    return (
        articulo.get("published date")
        or articulo.get("published_date")
        or articulo.get("pubDate")
        or articulo.get("published")
        or "N/D"
    )

def buscar_y_filtrar_entidades(entidades: List[str], tipo: str) -> List[Dict[str, Any]]:
    google_news = GNews(language="es", country="ES", period="1d", max_results=100)

    noticias_relevantes: List[Dict[str, Any]] = []
    titulos_vistos: List[str] = []

    for i, entidad in enumerate(entidades):
        try:
            time.sleep(random.uniform(1.0, 2.0))
            print(f"[{i+1}/{len(entidades)}] 🔹 {entidad} ({tipo})...", end="")
            resultados = google_news.get_news(entidad)
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
                    "tipo": tipo,
                    "entidad": entidad,
                    "temas": temas_str,
                    "titulo": titulo,
                    "url": final_url,
                    "fecha": get_published(articulo),
                    "fuente": publisher or dom or "Google News",
                    "dominio": dom,
                })

        except Exception as e:
            print(f"⚠️ Error {entidad} ({tipo}): {e}")

    return noticias_relevantes

def construir_html(
    noticias_clientes: List[Dict[str, Any]],
    noticias_competidores: List[Dict[str, Any]],
    noticias_partners: List[Dict[str, Any]],
) -> str:
    noticias_clientes.sort(key=lambda x: x["entidad"])
    noticias_competidores.sort(key=lambda x: x["entidad"])
    noticias_partners.sort(key=lambda x: x["entidad"])

    total_clientes = len(noticias_clientes)
    total_competidores = len(noticias_competidores)
    total_partners = len(noticias_partners)
    total = total_clientes + total_competidores + total_partners

    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 20px;">
        <div style="max-width: 680px; margin: 0 auto; background-color: #ffffff; padding: 20px; border-radius: 8px;">
            <h2 style="color: #2c3e50;">📊 Reporte Diario Noticias Accenture</h2>
            <p>
                Se han detectado <strong>{total}</strong> noticias relevantes hoy
                (<strong>Clientes:</strong> {total_clientes} |
                 <strong>Competidores:</strong> {total_competidores} |
                 <strong>Partners:</strong> {total_partners}).
            </p>
            <hr>
    """

    # -------- BLOQUE CLIENTES --------
    html += f"""
        <h2 style="color:#2c3e50; margin-top: 10px;">🧩 Noticias de Clientes</h2>
        <p style="color:#666; font-size:12px;">Total: <strong>{total_clientes}</strong></p>
        <hr>
    """

    if not noticias_clientes:
        html += "<p style='color:#888;'>No se han encontrado noticias de clientes con los filtros actuales.</p>"
    else:
        current = ""
        for n in noticias_clientes:
            if n["entidad"] != current:
                html += f"<h3 style='background-color: #eee; color: #333; padding: 8px; margin-top: 20px;'>{n['entidad']}</h3>"
                current = n["entidad"]

            html += f"""
            <div style="margin-bottom: 15px; border-left: 3px solid #2980b9; padding-left: 10px;">
                <div style="font-size: 10px; color: #e67e22; font-weight: bold;">{n.get("temas","")}</div>
                <a href="{n.get("url","")}" style="font-size: 14px; font-weight: bold; color: #333; text-decoration: none;">{n.get("titulo","")}</a>
                <div style="font-size: 11px; color: #888;">{n.get("fuente","")} - {n.get("fecha","N/D")}</div>
            </div>
            """

    # -------- BLOQUE COMPETIDORES --------
    html += f"""
        <hr style="margin-top: 25px;">
        <h2 style="color:#2c3e50;">🥊 Noticias de Competidores</h2>
        <p style="color:#666; font-size:12px;">Total: <strong>{total_competidores}</strong></p>
        <hr>
    """

    if not noticias_competidores:
        html += "<p style='color:#888;'>No se han encontrado noticias de competidores con los filtros actuales.</p>"
    else:
        current = ""
        for n in noticias_competidores:
            if n["entidad"] != current:
                html += f"<h3 style='background-color: #eee; color: #333; padding: 8px; margin-top: 20px;'>{n['entidad']}</h3>"
                current = n["entidad"]

            html += f"""
            <div style="margin-bottom: 15px; border-left: 3px solid #8e44ad; padding-left: 10px;">
                <div style="font-size: 10px; color: #e67e22; font-weight: bold;">{n.get("temas","")}</div>
                <a href="{n.get("url","")}" style="font-size: 14px; font-weight: bold; color: #333; text-decoration: none;">{n.get("titulo","")}</a>
                <div style="font-size: 11px; color: #888;">{n.get("fuente","")} - {n.get("fecha","N/D")}</div>
            </div>
            """

    # -------- BLOQUE PARTNERS --------
    html += f"""
        <hr style="margin-top: 25px;">
        <h2 style="color:#2c3e50;">🤝 Noticias de Partners</h2>
        <p style="color:#666; font-size:12px;">Total: <strong>{total_partners}</strong></p>
        <hr>
    """

    if not noticias_partners:
        html += "<p style='color:#888;'>No se han encontrado noticias de partners con los filtros actuales.</p>"
    else:
        current = ""
        for n in noticias_partners:
            if n["entidad"] != current:
                html += f"<h3 style='background-color: #eee; color: #333; padding: 8px; margin-top: 20px;'>{n['entidad']}</h3>"
                current = n["entidad"]

            html += f"""
            <div style="margin-bottom: 15px; border-left: 3px solid #16a085; padding-left: 10px;">
                <div style="font-size: 10px; color: #e67e22; font-weight: bold;">{n.get("temas","")}</div>
                <a href="{n.get("url","")}" style="font-size: 14px; font-weight: bold; color: #333; text-decoration: none;">{n.get("titulo","")}</a>
                <div style="font-size: 11px; color: #888;">{n.get("fuente","")} - {n.get("fecha","N/D")}</div>
            </div>
            """

    html += "</div></body></html>"
    return html

def enviar_correo(
    noticias_clientes: List[Dict[str, Any]],
    noticias_competidores: List[Dict[str, Any]],
    noticias_partners: List[Dict[str, Any]],
    recipients: List[str]
) -> None:
    if not noticias_clientes and not noticias_competidores and not noticias_partners:
        print("\n📭 Informe vacío (se enviará correo igualmente).")

    html = construir_html(noticias_clientes, noticias_competidores, noticias_partners)

    msg = MIMEMultipart()
    msg["From"] = EMAIL_USER
    # ✅ MUST CHANGE #2: cabecera To correcta
    msg["To"] = ", ".join(recipients)

    total = len(noticias_clientes) + len(noticias_competidores) + len(noticias_partners)
    msg["Subject"] = (
        f"🚀 Reporte Diario: {total} noticias "
        f"(Clientes {len(noticias_clientes)} | "
        f"Competidores {len(noticias_competidores)} | "
        f"Partners {len(noticias_partners)})"
    )
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
    print(f"🚀 AGENTE NUBE (PRO): {datetime.now().strftime('%H:%M:%S')}")
    recipients = parse_recipients(EMAIL_TO_RAW)
    validate_env(recipients)

    noticias_clientes = buscar_y_filtrar_entidades(CLIENTES, "cliente")
    noticias_competidores = buscar_y_filtrar_entidades(COMPETIDORES, "competidor")
    noticias_partners = buscar_y_filtrar_entidades(PARTNERS, "partner")

    enviar_correo(noticias_clientes, noticias_competidores, noticias_partners, recipients)


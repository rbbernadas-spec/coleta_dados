# db.py
import os
import socket
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from sqlmodel import SQLModel, create_engine, Session
from dotenv import load_dotenv

load_dotenv()

def _get_database_url_and_source():
    src = "none"
    secret_url = ""
    env_url = ""

    # 1) PRIORIDADE: st.secrets (no Streamlit Cloud)
    try:
        import streamlit as st
        secret_url = (st.secrets.get("DATABASE_URL", "") or "").strip()
        if secret_url:
            src = "secrets"
    except Exception:
        pass

    # 2) fallback: variável de ambiente
    if not secret_url:
        env_url = (os.getenv("DATABASE_URL", "") or "").strip()
        if env_url:
            src = "env"

    url = secret_url or env_url
    if not url or "postgresql" not in url:
        raise RuntimeError(
            "DATABASE_URL ausente/ inválida. Configure em Secrets (Streamlit Cloud) "
            "ex.: postgresql+psycopg://usuario:senha@<pooler-host>:6543/postgres?sslmode=require"
        )

    # garante sslmode=require na URL (idempotente)
    parsed = urlparse(url)
    q = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if "sslmode" not in q:
        q["sslmode"] = "require"
    new_query = urlencode(q)
    url = urlunparse(parsed._replace(query=new_query))
    return url, src

DATABASE_URL, DB_SRC = _get_database_url_and_source()

# ------------ Forçar IPv4 via connect_args ------------
# Mantemos o host original na URL (para TLS/SNI),
# e passamos 'hostaddr' (IPv4) diretamente ao driver via connect_args.
def _resolve_ipv4(hostname: str) -> str | None:
    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_INET, 0, socket.IPPROTO_TCP)
        if infos:
            return infos[0][4][0]
    except Exception:
        return None
    return None

_parsed = urlparse(DATABASE_URL)
_TARGET_HOST = _parsed.hostname or ""
_TARGET_PORT = _parsed.port
_IPV4 = _resolve_ipv4(_TARGET_HOST)

CONNECT_ARGS = {"sslmode": "require"}
if _IPV4:
    CONNECT_ARGS["hostaddr"] = _IPV4

# Cria engine com connect_args (psycopg respeita isso)
engine = create_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    connect_args=CONNECT_ARGS,
)

def conn_info():
    """Retorna (host, porta, origem_da_url, extras) para debug na UI (sem vazar senha)."""
    extras = []
    if _IPV4:
        extras.append(f"hostaddr={_IPV4}")
    extras.append("sslmode=require")
    extras_str = " & ".join(extras) if extras else "-"
    return (_TARGET_HOST, _TARGET_PORT or "(sem porta)", DB_SRC, extras_str)

def test_connection():
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("select 1;")
        return True, "Conexão OK."
    except Exception as e:
        return False, f"Falha na conexão: {e}"

def init_db():
    import models  # registra as tabelas
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session




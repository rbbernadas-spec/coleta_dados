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

    # 1) PRIORIDADE: st.secrets
    try:
        import streamlit as st
        secret_url = (st.secrets.get("DATABASE_URL", "") or "").strip()
        if secret_url:
            src = "secrets"
    except Exception:
        pass

    # 2) fallback: env var
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

    # Garante sslmode=require
    parsed = urlparse(url)
    q = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if "sslmode" not in q:
        q["sslmode"] = "require"

    # Força IPv4: resolve A record e injeta hostaddr=<IPv4>
    # Mantemos 'host' original para SNI/certificado TLS.
    try:
        # Apenas se ainda não há hostaddr
        if "hostaddr" not in q and parsed.hostname:
            # AF_INET = IPv4 only
            infos = socket.getaddrinfo(parsed.hostname, None, socket.AF_INET, 0, socket.IPPROTO_TCP)
            if infos:
                ipv4 = infos[0][4][0]
                q["hostaddr"] = ipv4
    except Exception:
        # Se der erro na resolução IPv4, seguimos sem hostaddr (fica como está)
        pass

    new_query = urlencode(q)
    parsed = parsed._replace(query=new_query)
    final_url = urlunparse(parsed)
    return final_url, src

DATABASE_URL, DB_SRC = _get_database_url_and_source()
engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)

def conn_info():
    """Retorna (host, porta, origem_da_url, query) para debug na UI (sem vazar senha)."""
    p = urlparse(DATABASE_URL)
    host = p.hostname or ""
    port = p.port or "(sem porta)"
    q = dict(parse_qsl(p.query, keep_blank_values=True))
    # mostramos se há hostaddr e sslmode
    extras = []
    if "hostaddr" in q:
        extras.append(f"hostaddr={q['hostaddr']}")
    if "sslmode" in q:
        extras.append(f"sslmode={q['sslmode']}")
    extras_str = " & ".join(extras) if extras else "-"
    return host, port, DB_SRC, extras_str

def test_connection():
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("select 1;")
        return True, "Conexão OK."
    except Exception as e:
        return False, f"Falha na conexão: {e}"

def init_db():
    import models  # registra tabelas
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session



# db.py (psycopg2 + IPv4)
import os
import socket
from urllib.parse import urlparse, parse_qsl
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
            "ex.: postgresql+psycopg2://usuario:senha@<pooler-host>:6543/postgres?sslmode=require"
        )
    return url, src

DATABASE_URL, DB_SRC = _get_database_url_and_source()

# -------- Força IPv4 resolvendo A record e passando via connect_args --------
def _resolve_ipv4(hostname: str) -> str | None:
    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_INET, 0, socket.IPPROTO_TCP)
        if infos:
            return infos[0][4][0]
    except Exception:
        return None
    return None

parsed = urlparse(DATABASE_URL)
TARGET_HOST = parsed.hostname or ""
TARGET_PORT = parsed.port or 6543
HOSTADDR = _resolve_ipv4(TARGET_HOST)

# psycopg2 lê connect_args; forçamos ssl e ip v4
connect_args = {"sslmode": "require"}
if HOSTADDR:
    connect_args["hostaddr"] = HOSTADDR

engine = create_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    connect_args=connect_args,
)

def conn_info():
    extras = []
    if HOSTADDR:
        extras.append(f"hostaddr={HOSTADDR}")
    extras.append("sslmode=require")
    extras_str = " & ".join(extras)
    return TARGET_HOST, TARGET_PORT, DB_SRC, extras_str

def test_connection():
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("select 1;")
        return True, "Conexão OK."
    except Exception as e:
        return False, f"Falha na conexão: {e}"

def init_db():
    import models
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session


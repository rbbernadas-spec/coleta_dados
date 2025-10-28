# db.py
import os
from urllib.parse import urlparse
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
            "ex.: postgresql+psycopg://usuario:senha@host:6543/postgres?sslmode=require"
        )
    # Garante ssl
    if "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url, src

DATABASE_URL, DB_SRC = _get_database_url_and_source()
engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)

def conn_info():
    """Retorna (host, porta, origem_da_url) para debug na UI."""
    p = urlparse(DATABASE_URL)
    host = p.hostname or ""
    port = p.port or "(sem porta)"
    return host, port, DB_SRC

def test_connection():
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("select 1")
        return True, "Conexão OK."
    except Exception as e:
        return False, f"Falha na conexão: {e}"

def init_db():
    import models
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session



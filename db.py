# db.py
import os
from urllib.parse import urlparse
from sqlmodel import SQLModel, create_engine, Session
from dotenv import load_dotenv

# Carrega .env local (não afeta o Cloud, mas não atrapalha)
load_dotenv()

def _get_database_url():
    # 1) Streamlit Secrets tem prioridade
    try:
        import streamlit as st
        secret_url = st.secrets.get("DATABASE_URL", "").strip()
    except Exception:
        secret_url = ""

    # 2) Se não houver nos secrets, tenta variável de ambiente
    env_url = os.getenv("DATABASE_URL", "").strip()

    url = secret_url or env_url
    if not url or "postgresql" not in url:
        raise RuntimeError(
            "DATABASE_URL ausente/ inválida. Configure em Secrets (Streamlit Cloud) "
            "ex.: postgresql+psycopg://usuario:senha@host:6543/postgres?sslmode=require"
        )
    # Garante sslmode=require
    if "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url

DATABASE_URL = _get_database_url()

# Cria engine
engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)

def conn_info():
    """Retorna host/porta só para debug na UI (sem vazar senha)."""
    parsed = urlparse(DATABASE_URL)
    host = parsed.hostname or ""
    port = parsed.port or "(sem porta)"
    return host, port

def test_connection():
    """Testa a conexão e retorna (ok, mensagem)."""
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


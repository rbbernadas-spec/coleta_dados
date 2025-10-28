# db.py
import os
from sqlmodel import SQLModel, create_engine, Session
from dotenv import load_dotenv

load_dotenv()

# Tenta pegar do ambiente
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Tenta pegar dos secrets do Streamlit (no Cloud)
try:
    import streamlit as st
    if not DATABASE_URL:
        DATABASE_URL = st.secrets.get("DATABASE_URL", "")
except Exception:
    st = None  # streamlit não disponível localmente

if not DATABASE_URL or "postgresql" not in DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL ausente/ inválida. Configure em Secrets (Streamlit Cloud) "
        "ex.: postgresql+psycopg://usuario:senha@host:5432/postgres?sslmode=require"
    )

# Garante sslmode=require
if "sslmode=" not in DATABASE_URL:
    DATABASE_URL += ("&" if "?" in DATABASE_URL else "?") + "sslmode=require"

engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)

def test_connection():
    # Testa conexão e retorna (ok, mensagem)
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

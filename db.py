# db.py
import os
from sqlmodel import SQLModel, create_engine, Session
from dotenv import load_dotenv

# Tenta carregar .env (não usado no Cloud, mas não atrapalha)
load_dotenv()

# >>> NOVO: tenta buscar no st.secrets quando em Cloud
DATABASE_URL = os.getenv("DATABASE_URL", "")
try:
    import streamlit as st  # disponível no Cloud
    if not DATABASE_URL:
        DATABASE_URL = st.secrets.get("DATABASE_URL", "")
except Exception:
    pass

if not DATABASE_URL or "postgresql" not in DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL ausente/ inválida. Configure-a em Secrets (Streamlit Cloud) "
        'como: postgresql+psycopg://usuario:senha@host:6543/postgres?sslmode=require'
    )

# Garante sslmode=require (idempotente)
if "sslmode=" not in DATABASE_URL:
    DATABASE_URL += ("&" if "?" in DATABASE_URL else "?") + "sslmode=require"

engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)

def init_db():
    import models  # registra tabelas
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session


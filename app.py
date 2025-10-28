# app.py (trecho do topo)
import streamlit as st
from sqlmodel import Session, select
from db import init_db, engine, test_connection, conn_info
from models import Empresa, Lancamento
import pandas as pd

st.set_page_config(page_title="Sistema de Coleta de Dados", layout="wide")

def to_dict(m):
    return m.model_dump() if hasattr(m, "model_dump") else m.dict()

with st.sidebar:
    st.header("Menu")
    host, port, src = conn_info()
    st.caption(f"📡 Conectando a: `{host}:{port}`  •  fonte: **{src}**")
    menu = st.radio("Selecione uma opção:", ["Início", "Lançamentos", "DRE (Competência)"])

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("Testar conexão"):
            ok, msg = test_connection()
            (st.success if ok else st.error)(msg)
    with col_b:
        if st.button("Inicializar Banco de Dados"):
            try:
                init_db()
                st.success("Banco inicializado no Postgres (nuvem).")
            except Exception as e:
                st.error(f"Falha ao inicializar: {e}")

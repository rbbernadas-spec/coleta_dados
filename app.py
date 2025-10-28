# app.py
import streamlit as st
from sqlmodel import Session, select
from db import init_db, engine
from db import test_connection  # ADICIONE ISSO
with st.sidebar:
    st.header("Menu")
    menu = st.radio("Selecione uma opção:", ["Início", "Lançamentos", "DRE (Competência)"])
    if st.button("Testar conexão"):
        ok, msg = test_connection()
        st.write(msg)
    if st.button("Inicializar Banco de Dados"):
        init_db()
        st.success("Banco inicializado no Postgres (nuvem).")
from models import Empresa, Lancamento
import pandas as pd

st.set_page_config(page_title="Sistema de Coleta de Dados", layout="wide")

with st.sidebar:
    st.header("Menu")
    menu = st.radio("Selecione uma opção:", ["Início", "Lançamentos", "DRE (Competência)"])
    if st.button("Inicializar Banco de Dados"):
        init_db()
        st.success("Banco inicializado no Postgres (nuvem).")

if menu == "Início":
    st.title("📊 Sistema de Coleta de Dados - Consultoria (Nuvem)")
    st.write("Conectado a Postgres (Supabase). Use o menu para cadastrar lançamentos e visualizar a DRE por competência.")
    st.info("Antes de lançar valores, cadastre uma **Empresa** em Lançamentos caso ainda não exista.")

elif menu == "Lançamentos":
    st.header("🧾 Cadastro de Lançamentos")
    with Session(engine) as session:
        empresas = session.exec(select(Empresa)).all()
        if not empresas:
            st.warning("Cadastre uma empresa para começar.")
            col1, col2 = st.columns([2,1])
            with col1:
                nome = st.text_input("Nome da Empresa")
            with col2:
                cnpj = st.text_input("CNPJ (opcional)")
            if st.button("Salvar Empresa"):
                if not nome:
                    st.error("Informe o nome da empresa.")
                else:
                    e = Empresa(nome=nome, cnpj=cnpj or None)
                    session.add(e)
                    session.commit()
                    st.success("Empresa cadastrada! Você já pode lançar movimentações.")
        else:
            empresa = empresas[0]
            st.info(f"Empresa ativa: **{empresa.nome}**")

            data_comp = st.date_input("Data de Competência")
            historico = st.text_input("Histórico")
            tipo = st.selectbox("Tipo", ["RECEITA", "DESPESA", "CUSTO"])
            valor = st.number_input("Valor (R$)", min_value=0.0, step=0.01, format="%.2f")

            if st.button("Salvar Lançamento"):
                if not historico or valor <= 0:
                    st.error("Preencha histórico e valor > 0.")
                else:
                    novo = Lancamento(
                        empresa_id=empresa.id,
                        data_competencia=data_comp,
                        historico=historico.strip(),
                        valor=float(valor),
                        tipo=tipo,
                    )
                    session.add(novo)
                    session.commit()
                    st.success("Lançamento salvo!")

            st.divider()
            st.subheader("📋 Lançamentos Cadastrados")
            lancs = session.exec(select(Lancamento).where(Lancamento.empresa_id == empresa.id)).all()
            if lancs:
                df = pd.DataFrame([l.model_dump() for l in lancs])
                st.dataframe(df, use_container_width=True)
            else:
                st.caption("Nenhum lançamento ainda.")

elif menu == "DRE (Competência)":
    st.header("📈 DRE (Competência)")
    with Session(engine) as session:
        empresas = session.exec(select(Empresa)).all()
        if not empresas:
            st.warning("Cadastre uma empresa em Lançamentos primeiro.")
        else:
            empresa = empresas[0]
            lancs = session.exec(
                select(Lancamento).where(Lancamento.empresa_id == empresa.id)
            ).all()
            if not lancs:
                st.warning("Nenhum lançamento cadastrado.")
            else:
                df = pd.DataFrame([l.model_dump() for l in lancs])
                dre = df.groupby("tipo", dropna=False)["valor"].sum().reset_index()
                col1, col2 = st.columns([2,1])
                with col1:
                    st.dataframe(dre, use_container_width=True)
                with col2:
                    st.metric("Total Lançado", f"R$ {df['valor'].sum():,.2f}")


# app.py
import streamlit as st
from sqlmodel import Session, select
from db import init_db, engine, test_connection, conn_info
from models import (
    Empresa, Cliente, Fornecedor, Produto, PlanoContasDRE, Estoque,
    Lancamento, ContaReceber, ContaPagar,
    Documento, Parcela, DocumentoItem
)
import pandas as pd
from datetime import date, timedelta
from typing import List, Tuple

st.set_page_config(page_title="Sistema de Coleta de Dados", layout="wide")

# --- Helpers ---
def to_dict(m):
    return m.model_dump() if hasattr(m, "model_dump") else m.dict()

def parse_condicao_pagamento(texto: str) -> List[int]:
    """
    Converte "30/60/90" -> [30, 60, 90]
    "0" -> [0] (à vista)
    vazio -> [0]
    """
    if not texto:
        return [0]
    dias = []
    for parte in texto.replace(" ", "").split("/"):
        if parte == "":
            continue
        try:
            dias.append(int(parte))
        except ValueError:
            # ignora entradas inválidas silenciosamente
            pass
    return dias or [0]

def gerar_parcelas(valor_total: float, offsets: List[int], base: date) -> List[Tuple[date, float]]:
    """
    Distribui valor_total igualmente pelas parcelas, ajustando centavos na última.
    """
    n = max(1, len(offsets))
    base_parc = round(valor_total / n, 2)
    valores = [base_parc] * n
    ajuste = round(valor_total - sum(valores), 2)
    valores[-1] = round(valores[-1] + ajuste, 2)
    datas = [base + timedelta(days=d) for d in offsets]
    return list(zip(datas, valores))

def gerar_cr_cp_e_lancamentos(
    session: Session,
    doc: Documento,
    parcelas: List[Parcela],
    classif_dre_compra: str = "DESPESA"  # para COMPRA: DESPESA ou CUSTO
):
    """
    - Para VENDA/SERVICO: cria CR a partir das parcelas + Lancamento(RECEITA)
    - Para COMPRA: cria CP a partir das parcelas + Lancamento(DESPESA/CUSTO)
    """
    # Vincula a parceiro_id corretamente em CR/CP e lançamento
    if doc.natureza in ("VENDA", "SERVICO"):
        # CR + RECEITA
        for p in parcelas:
            cr = ContaReceber(
                empresa_id=doc.empresa_id,
                cliente_id=doc.parceiro_id if doc.parceiro_tipo == "CLIENTE" else None,
                titulo=f"{doc.tipo_doc} {doc.numero or ''}".strip(),
                data_emissao=doc.data_emissao,
                data_vencto=p.data_vencto,
                valor=p.valor,
                saldo=p.valor,
                status="ABERTO",
            )
            session.add(cr)

        lan = Lancamento(
            empresa_id=doc.empresa_id,
            data_competencia=doc.data_competencia,
            data_movimento=doc.data_emissao,
            historico=f"{doc.tipo_doc} {doc.numero or ''} - {doc.parceiro_tipo} {doc.parceiro_id}",
            valor=doc.valor_total,
            tipo="RECEITA",
            origem="DOCUMENTO",
            doc_ref=str(doc.id),
            cliente_id=doc.parceiro_id if doc.parceiro_tipo == "CLIENTE" else None,
        )
        session.add(lan)

    elif doc.natureza == "COMPRA":
        # CP + DESPESA/CUSTO
        for p in parcelas:
            cp = ContaPagar(
                empresa_id=doc.empresa_id,
                fornecedor_id=doc.parceiro_id if doc.parceiro_tipo == "FORNECEDOR" else None,
                titulo=f"{doc.tipo_doc} {doc.numero or ''}".strip(),
                data_emissao=doc.data_emissao,
                data_vencto=p.data_vencto,
                valor=p.valor,
                saldo=p.valor,
                status="ABERTO",
            )
            session.add(cp)

        lan = Lancamento(
            empresa_id=doc.empresa_id,
            data_competencia=doc.data_competencia,
            data_movimento=doc.data_emissao,
            historico=f"{doc.tipo_doc} {doc.numero or ''} - {doc.parceiro_tipo} {doc.parceiro_id}",
            valor=doc.valor_total,
            tipo=classif_dre_compra,  # 'DESPESA' ou 'CUSTO'
            origem="DOCUMENTO",
            doc_ref=str(doc.id),
            fornecedor_id=doc.parceiro_id if doc.parceiro_tipo == "FORNECEDOR" else None,
        )
        session.add(lan)

# ---------------- Sidebar ----------------
with st.sidebar:
    st.header("Menu")
    host, port, src, extras = conn_info()
    st.caption(f"📡 Conectando a: `{host}:{port}` • fonte: **{src}** • {extras or '-'}")
    menu = st.radio("Selecione uma opção:", ["Início", "Documentos", "Lançamentos (consulta)", "DRE (Competência)"])

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

# ---------------- Páginas ----------------
if menu == "Início":
    st.title("📊 Sistema de Coleta de Dados - Consultoria (Nuvem)")
    st.write(
        "Agora seus lançamentos passam a ser via **Documentos** (cabeçalho/parcelas/itens). "
        "O sistema gera automaticamente **Contas a Receber/Pagar** e **Lançamentos (DRE)**."
    )
    st.info("Sugestão: cadastre ao menos um **Cliente** e/ou **Fornecedor** antes de lançar um Documento.")

elif menu == "Documentos":
    st.header("📄 Documentos (Completo: cabeçalho + parcelas + itens)")

    with Session(engine) as session:
        # Empresa única (MVP)
        empresas = session.exec(select(Empresa)).all()
        if not empresas:
            st.warning("Cadastre uma empresa para começar.")
            col1, col2 = st.columns([2, 1])
            with col1:
                nome = st.text_input("Nome da Empresa")
            with col2:
                cnpj = st.text_input("CNPJ (opcional)")
            if st.button("Salvar Empresa"):
                if not nome.strip():
                    st.error("Informe o nome da empresa.")
                else:
                    e = Empresa(nome=nome.strip(), cnpj=(cnpj.strip() or None))
                    session.add(e)
                    session.commit()
                    st.success("Empresa cadastrada! Recarregue a página.")
        else:
            empresa = empresas[0]
            st.success(f"Empresa ativa: **{empresa.nome}**")

            # --- Cabeçalho do Documento ---
            st.subheader("Cabeçalho")
            col1, col2, col3 = st.columns([1, 1, 1])
            with col1:
                natureza = st.selectbox("Natureza", ["VENDA", "COMPRA", "SERVICO"])
                tipo_doc = st.selectbox("Tipo de Documento", ["NFe", "NFSe", "Recibo", "Contrato", "Outro"])
            with col2:
                numero = st.text_input("Número")
                serie = st.text_input("Série (opcional)")
            with col3:
                chave = st.text_input("Chave (opcional)")

            # Parceiro
            st.subheader("Parceiro")
            if natureza in ("VENDA", "SERVICO"):
                parceiro_tipo = "CLIENTE"
                lista = session.exec(select(Cliente).where(Cliente.empresa_id == empresa.id)).all()
                nomes = ["[+] Cadastrar novo cliente"] + [f"{c.id} - {c.nome}" for c in lista]
                escolha = st.selectbox("Cliente", nomes)
                if escolha == "[+] Cadastrar novo cliente":
                    novo_nome = st.text_input("Nome do novo cliente")
                    novo_doc = st.text_input("Documento (opcional)")
                    if st.button("Salvar Cliente"):
                        if not novo_nome.strip():
                            st.error("Informe o nome.")
                        else:
                            c = Cliente(empresa_id=empresa.id, nome=novo_nome.strip(), doc=(novo_doc.strip() or None))
                            session.add(c)
                            session.commit()
                            st.success("Cliente cadastrado. Recarregue a página para selecioná-lo.")
                            st.stop()
                else:
                    parceiro_id = int(escolha.split(" - ")[0])
            else:
                parceiro_tipo = "FORNECEDOR"
                lista = session.exec(select(Fornecedor).where(Fornecedor.empresa_id == empresa.id)).all()
                nomes = ["[+] Cadastrar novo fornecedor"] + [f"{f.id} - {f.nome}" for f in lista]
                escolha = st.selectbox("Fornecedor", nomes)
                if escolha == "[+] Cadastrar novo fornecedor":
                    novo_nome = st.text_input("Nome do novo fornecedor")
                    novo_doc = st.text_input("Documento (opcional)")
                    if st.button("Salvar Fornecedor"):
                        if not novo_nome.strip():
                            st.error("Informe o nome.")
                        else:
                            f = Fornecedor(empresa_id=empresa.id, nome=novo_nome.strip(), doc=(novo_doc.strip() or None))
                            session.add(f)
                            session.commit()
                            st.success("Fornecedor cadastrado. Recarregue a página para selecioná-lo.")
                            st.stop()
                else:
                    parceiro_id = int(escolha.split(" - ")[0])

            # Datas e valor
            st.subheader("Datas e Valor")
            col1, col2, col3 = st.columns([1, 1, 1])
            with col1:
                data_emissao = st.date_input("Data de Emissão", value=date.today())
            with col2:
                data_competencia = st.date_input("Data de Competência", value=date.today())
            with col3:
                valor_total = st.number_input("Valor Total (R$)", min_value=0.0, step=0.01, format="%.2f")

            # Pagamento / Parcelas
            st.subheader("Pagamento / Parcelas")
            colp1, colp2 = st.columns([1, 2])
            with colp1:
                cond_str = st.text_input("Condição de Pagamento (ex.: 0 ou 30/60/90)", value="0")
            with colp2:
                offs = parse_condicao_pagamento(cond_str)
                preview = gerar_parcelas(valor_total or 0.0, offs, data_emissao)
                df_prev = pd.DataFrame([{"Parcela": i+1, "Vencimento": d, "Valor": v} for i,(d,v) in enumerate(preview)])
                st.dataframe(df_prev, use_container_width=True)

            # Itens (opcional)
            st.subheader("Itens (opcional)")
            st.caption("Preencha itens para detalhar produtos/serviços. Deixe vazio se não precisar.")
            if "itens_df" not in st.session_state:
                st.session_state["itens_df"] = pd.DataFrame(
                    [{"descricao": "", "quantidade": 1.0, "unidade": "un", "preco_unit": 0.0, "valor_total": 0.0}]
                )
            itens_df = st.data_editor(
                st.session_state["itens_df"],
                num_rows="dynamic",
                use_container_width=True,
                key="itens_editor",
            )
            # Atualiza total do item automaticamente na visualização (não impede edição manual)
            if not itens_df.empty:
                itens_df["valor_total"] = (itens_df["quantidade"].astype(float) * itens_df["preco_unit"].astype(float)).round(2)

            # Classificação DRE (para COMPRA)
            classif_dre_compra = "DESPESA"
            if natureza == "COMPRA":
                classif_dre_compra = st.selectbox("Classificar COMPRA no DRE como:", ["DESPESA", "CUSTO"])

            observacoes = st.text_area("Observações (opcional)")

            st.divider()
            if st.button("✅ Salvar Documento e Gerar CR/CP + Lançamentos"):
                # Validação básica
                erros = []
                if valor_total <= 0:
                    erros.append("Valor Total deve ser > 0.")
                if not parceiro_id:
                    erros.append("Selecione um parceiro válido.")
                if erros:
                    for e in erros:
                        st.error(e)
                    st.stop()

                # Cria Documento
                doc = Documento(
                    empresa_id=empresa.id,
                    natureza=natureza,
                    tipo_doc=tipo_doc,
                    numero=numero.strip() or None,
                    serie=serie.strip() or None,
                    chave=chave.strip() or None,
                    parceiro_tipo=parceiro_tipo,
                    parceiro_id=parceiro_id,
                    data_emissao=data_emissao,
                    data_competencia=data_competencia,
                    valor_total=float(valor_total),
                    observacoes=observacoes.strip() or None,
                )
                session.add(doc)
                session.commit()
                session.refresh(doc)

                # Itens (se houver)
                itens_salvos = []
                if not itens_df.empty:
                    for _, row in itens_df.iterrows():
                        desc = str(row.get("descricao", "")).strip()
                        if not desc:
                            continue
                        qtd = float(row.get("quantidade", 0) or 0)
                        und = str(row.get("unidade", "un")).strip() or "un"
                        pu = float(row.get("preco_unit", 0) or 0)
                        vt = float(row.get("valor_total", 0) or 0)
                        item = DocumentoItem(
                            documento_id=doc.id,
                            produto_id=None,  # MVP: sem vínculo direto ao cadastro de produto
                            descricao=desc,
                            quantidade=qtd,
                            unidade=und,
                            preco_unit=pu,
                            valor_total=vt,
                            conta_dre_id=None,
                        )
                        session.add(item)
                        itens_salvos.append(item)
                    session.commit()

                # Gera Parcelas a partir da condição
                parcels = []
                for i, (venc, val) in enumerate(preview, start=1):
                    destino = "CR" if natureza in ("VENDA", "SERVICO") else "CP"
                    p = Parcela(
                        documento_id=doc.id,
                        destino=destino,
                        data_vencto=venc,
                        valor=float(val),
                    )
                    session.add(p)
                    parcels.append(p)
                session.commit()

                # CR/CP + Lançamentos (DRE)
                gerar_cr_cp_e_lancamentos(session, doc, parcels, classif_dre_compra=classif_dre_compra)
                session.commit()

                st.success(f"Documento #{doc.id} salvo, parcelas geradas e DRE lançada!")
                st.experimental_rerun()

            # Lista últimos documentos
            st.subheader("📚 Documentos Recentes")
            docs = session.exec(
                select(Documento).where(Documento.empresa_id == empresa.id).order_by(Documento.id.desc())
            ).all()
            if docs:
                df_docs = pd.DataFrame([to_dict(d) for d in docs])
                st.dataframe(df_docs, use_container_width=True)
            else:
                st.caption("Nenhum documento ainda.")

elif menu == "Lançamentos (consulta)":
    st.header("🧾 Lançamentos (somente consulta)")
    with Session(engine) as session:
        empresas = session.exec(select(Empresa)).all()
        if not empresas:
            st.warning("Cadastre uma empresa em Documentos.")
        else:
            empresa = empresas[0]
            lancs = session.exec(
                select(Lancamento).where(Lancamento.empresa_id == empresa.id)
            ).all()
            if lancs:
                df = pd.DataFrame([to_dict(l) for l in lancs])
                st.dataframe(df, use_container_width=True)
            else:
                st.caption("Nenhum lançamento ainda.")

elif menu == "DRE (Competência)":
    st.header("📈 DRE (Competência)")
    with Session(engine) as session:
        empresas = session.exec(select(Empresa)).all()
        if not empresas:
            st.warning("Cadastre uma empresa em Documentos primeiro.")
        else:
            empresa = empresas[0]
            lancs = session.exec(
                select(Lancamento).where(Lancamento.empresa_id == empresa.id)
            ).all()
            if not lancs:
                st.warning("Nenhum lançamento cadastrado.")
            else:
                df = pd.DataFrame([to_dict(l) for l in lancs])
                dre = df.groupby("tipo", dropna=False)["valor"].sum().reset_index()

                col1, col2 = st.columns([2, 1])
                with col1:
                    st.dataframe(dre, use_container_width=True)
                with col2:
                    st.metric("Total Lançado", f"R$ {df['valor'].sum():,.2f}")

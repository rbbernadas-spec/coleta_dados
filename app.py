# app.py
import streamlit as st
from sqlmodel import Session, select, delete
from sqlalchemy.exc import ProgrammingError
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

# ---------------- Schema bootstrap (auto) ----------------
# Garante que as tabelas existam após mudanças de modelos
if "schema_ready" not in st.session_state:
    try:
        init_db()
        st.session_state["schema_ready"] = True
    except Exception:
        # Se falhar aqui, o botão "Inicializar Banco" ainda permitirá criar
        st.session_state["schema_ready"] = False

# ---------------- Helpers ----------------
def to_dict(m):
    return m.model_dump() if hasattr(m, "model_dump") else m.dict()

def parse_condicao_pagamento(texto: str) -> List[int]:
    """Converte '30/60/90' -> [30, 60, 90]; '0' -> [0]; vazio -> [0]."""
    if not texto:
        return [0]
    dias = []
    for parte in texto.replace(" ", "").split("/"):
        if parte == "":
            continue
        try:
            dias.append(int(parte))
        except ValueError:
            pass
    return dias or [0]

def gerar_parcelas(valor_total: float, offsets: List[int], base: date) -> List[Tuple[date, float]]:
    """Distribui valor_total igualmente; acerta centavos na última."""
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
    - VENDA/SERVICO: cria CR a partir das parcelas + Lancamento(RECEITA)
    - COMPRA: cria CP a partir das parcelas + Lancamento(DESPESA/CUSTO)
    Todos com referência ao Documento (titulo 'DOC#<id> ...', doc_ref=<id>).
    """
    titulo_base = f"DOC#{doc.id} {doc.tipo_doc} {doc.numero or ''}".strip()

    if doc.natureza in ("VENDA", "SERVICO"):
        # CR + RECEITA
        for p in parcelas:
            cr = ContaReceber(
                empresa_id=doc.empresa_id,
                cliente_id=doc.parceiro_id if doc.parceiro_tipo == "CLIENTE" else None,
                titulo=titulo_base,
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
                titulo=titulo_base,
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

def apagar_dependentes_do_documento(session: Session, doc_id: int):
    """
    Deleta: Itens, Parcelas, CR/CP (pelo prefixo DOC#<id>), Lançamentos (doc_ref=<id>).
    Usa LIKE em vez de startswith (melhor compatibilidade SQL).
    """
    # 1) Itens
    session.exec(delete(DocumentoItem).where(DocumentoItem.documento_id == doc_id))
    # 2) Parcelas
    session.exec(delete(Parcela).where(Parcela.documento_id == doc_id))
    # 3) CR/CP pelo título prefixado
    titulo_like = f"DOC#{doc_id}%"
    session.exec(delete(ContaReceber).where(ContaReceber.titulo.like(titulo_like)))
    session.exec(delete(ContaPagar).where(ContaPagar.titulo.like(titulo_like)))
    # 4) Lançamentos pela referência doc_ref
    session.exec(delete(Lancamento).where(Lancamento.doc_ref == str(doc_id)))
    session.commit()

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
                st.session_state["schema_ready"] = True
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
        try:
            empresas = session.exec(select(Empresa)).all()
        except ProgrammingError:
            # Se a tabela não existir (schema mudou), cria e recarrega
            init_db()
            st.rerun()

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

            # Modo de edição
            st.session_state.setdefault("editing_doc_id", None)
            colm1, colm2 = st.columns([1, 1])
            with colm1:
                if st.session_state["editing_doc_id"]:
                    st.info(f"Editando Documento #{st.session_state['editing_doc_id']}")
                else:
                    st.caption("Criar novo documento")
            with colm2:
                if st.session_state["editing_doc_id"] and st.button("Cancelar edição"):
                    st.session_state["editing_doc_id"] = None
                    st.rerun()

            # Se estiver editando, carregar doc
            editing_doc = None
            if st.session_state["editing_doc_id"]:
                editing_doc = session.get(Documento, st.session_state["editing_doc_id"])

            # --- Cabeçalho do Documento ---
            st.subheader("Cabeçalho")
            col1, col2, col3 = st.columns([1, 1, 1])
            with col1:
                natureza = st.selectbox(
                    "Natureza", ["VENDA", "COMPRA", "SERVICO"],
                    index=(["VENDA","COMPRA","SERVICO"].index(editing_doc.natureza) if editing_doc else 0)
                )
                tipo_doc = st.selectbox(
                    "Tipo de Documento", ["NFe", "NFSe", "Recibo", "Contrato", "Outro"],
                    index=(["NFe","NFSe","Recibo","Contrato","Outro"].index(editing_doc.tipo_doc) if editing_doc else 0)
                )
            with col2:
                numero = st.text_input("Número", value=(editing_doc.numero or "") if editing_doc else "")
                serie = st.text_input("Série (opcional)", value=(editing_doc.serie or "") if editing_doc else "")
            with col3:
                chave = st.text_input("Chave (opcional)", value=(editing_doc.chave or "") if editing_doc else "")

            # Parceiro
            st.subheader("Parceiro")
            parceiro_id = None  # evita NameError
            if natureza in ("VENDA", "SERVICO"):
                parceiro_tipo = "CLIENTE"
                lista = session.exec(select(Cliente).where(Cliente.empresa_id == empresa.id)).all()
                nomes = [f"{c.id} - {c.nome}" for c in lista]
                nomes_combo = ["[+] Cadastrar novo cliente"] + nomes
                default_idx = 0
                if editing_doc and editing_doc.parceiro_tipo == "CLIENTE":
                    try:
                        default_idx = 1 + next(i for i,x in enumerate(nomes) if x.startswith(f"{editing_doc.parceiro_id} - "))
                    except StopIteration:
                        default_idx = 0
                escolha = st.selectbox("Cliente", nomes_combo, index=default_idx)
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
                nomes = [f"{f.id} - {f.nome}" for f in lista]
                nomes_combo = ["[+] Cadastrar novo fornecedor"] + nomes
                default_idx = 0
                if editing_doc and editing_doc.parceiro_tipo == "FORNECEDOR":
                    try:
                        default_idx = 1 + next(i for i,x in enumerate(nomes) if x.startswith(f"{editing_doc.parceiro_id} - "))
                    except StopIteration:
                        default_idx = 0
                escolha = st.selectbox("Fornecedor", nomes_combo, index=default_idx)
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
                data_emissao = st.date_input("Data de Emissão", value=(editing_doc.data_emissao if editing_doc else date.today()))
            with col2:
                data_competencia = st.date_input("Data de Competência", value=(editing_doc.data_competencia if editing_doc else date.today()))
            with col3:
                valor_total = st.number_input("Valor Total (R$)", min_value=0.0, step=0.01, format="%.2f", value=float(editing_doc.valor_total) if editing_doc else 0.0)

            # Pagamento / Parcelas
            st.subheader("Pagamento / Parcelas")
            colp1, colp2 = st.columns([1, 2])
            with colp1:
                cond_default = "0"
                if editing_doc:
                    # inferir offsets das parcelas existentes
                    offs = []
                    for p in session.exec(select(Parcela).where(Parcela.documento_id == editing_doc.id)).all():
                        offs.append((p.data_vencto - editing_doc.data_emissao).days)
                    offs.sort()
                    if offs:
                        cond_default = "/".join(str(d) for d in offs)
                cond_str = st.text_input("Condição de Pagamento (ex.: 0 ou 30/60/90)", value=cond_default)
            with colp2:
                offs = parse_condicao_pagamento(cond_str)
                preview = gerar_parcelas(valor_total or 0.0, offs, data_emissao)
                df_prev = pd.DataFrame([{"Parcela": i+1, "Vencimento": d, "Valor": v} for i,(d,v) in enumerate(preview)])
                st.dataframe(df_prev, use_container_width=True)

            # Itens (opcional)
            st.subheader("Itens (opcional)")
            st.caption("Preencha itens para detalhar produtos/serviços. Deixe vazio se não precisar.")
            if "itens_df" not in st.session_state or st.session_state.get("editing_doc_snapshot") != st.session_state.get("editing_doc_id"):
                # carrega itens do doc em edição ou inicia vazio
                if editing_doc:
                    itens = session.exec(select(DocumentoItem).where(DocumentoItem.documento_id == editing_doc.id)).all()
                    if itens:
                        st.session_state["itens_df"] = pd.DataFrame([
                            {
                                "descricao": it.descricao,
                                "quantidade": it.quantidade,
                                "unidade": it.unidade,
                                "preco_unit": it.preco_unit,
                                "valor_total": it.valor_total,
                            }
                            for it in itens
                        ])
                    else:
                        st.session_state["itens_df"] = pd.DataFrame(
                            [{"descricao": "", "quantidade": 1.0, "unidade": "un", "preco_unit": 0.0, "valor_total": 0.0}]
                        )
                else:
                    st.session_state["itens_df"] = pd.DataFrame(
                        [{"descricao": "", "quantidade": 1.0, "unidade": "un", "preco_unit": 0.0, "valor_total": 0.0}]
                    )
                st.session_state["editing_doc_snapshot"] = st.session_state.get("editing_doc_id")

            itens_df = st.data_editor(
                st.session_state["itens_df"],
                num_rows="dynamic",
                use_container_width=True,
                key="itens_editor",
            )
            if not itens_df.empty:
                itens_df["valor_total"] = (itens_df["quantidade"].astype(float) * itens_df["preco_unit"].astype(float)).round(2)

            # Classificação DRE (para COMPRA)
            classif_dre_compra = "DESPESA"
            if natureza == "COMPRA":
                classif_dre_compra = st.selectbox(
                    "Classificar COMPRA no DRE como:",
                    ["DESPESA", "CUSTO"],
                    index=(["DESPESA","CUSTO"].index("DESPESA") if not editing_doc else ["DESPESA","CUSTO"].index("DESPESA"))
                )

            observacoes = st.text_area("Observações (opcional)", value=(editing_doc.observacoes or "") if editing_doc else "")

            st.divider()
            acao_label = "💾 Salvar Alterações" if editing_doc else "✅ Salvar Documento e Gerar CR/CP + Lançamentos"
            if st.button(acao_label):
                # Validação
                erros = []
                if valor_total <= 0:
                    erros.append("Valor Total deve ser > 0.")
                if not parceiro_id:
                    erros.append("Selecione um parceiro válido (ou cadastre um).")
                if erros:
                    for e in erros:
                        st.error(e)
                    st.stop()

                if editing_doc:
                    # Atualiza documento e refaz tudo
                    doc = editing_doc
                    doc.natureza = natureza
                    doc.tipo_doc = tipo_doc
                    doc.numero = numero.strip() or None
                    doc.serie = serie.strip() or None
                    doc.chave = chave.strip() or None
                    doc.parceiro_tipo = parceiro_tipo
                    doc.parceiro_id = parceiro_id
                    doc.data_emissao = data_emissao
                    doc.data_competencia = data_competencia
                    doc.valor_total = float(valor_total)
                    doc.observacoes = observacoes.strip() or None
                    session.add(doc)
                    session.commit()

                    # Apaga dependentes antigos e recria
                    apagar_dependentes_do_documento(session, doc.id)

                else:
                    # Cria novo documento
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

                # Itens
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
                            produto_id=None,
                            descricao=desc,
                            quantidade=qtd,
                            unidade=und,
                            preco_unit=pu,
                            valor_total=vt,
                            conta_dre_id=None,
                        )
                        session.add(item)
                    session.commit()

                # Parcelas
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

                # CR/CP + Lançamentos
                gerar_cr_cp_e_lancamentos(session, doc, parcels, classif_dre_compra=classif_dre_compra)
                session.commit()

                if editing_doc:
                    st.success(f"Documento #{doc.id} atualizado com sucesso!")
                    st.session_state["editing_doc_id"] = None
                else:
                    st.success(f"Documento #{doc.id} salvo, parcelas geradas e DRE lançada!")
                st.rerun()

            # Lista e ações
            st.subheader("📚 Documentos Recentes")
            try:
                docs = session.exec(
                    select(Documento).where(Documento.empresa_id == empresa.id).order_by(Documento.id.desc())
                ).all()
            except ProgrammingError:
                init_db()
                st.rerun()

            if docs:
                df_docs = pd.DataFrame([to_dict(d) for d in docs])
                st.dataframe(df_docs, use_container_width=True)

                # Ações por ID
                st.write("### Ações")
                doc_ids = [d.id for d in docs]
                escolha_id = st.selectbox("Documento", doc_ids, format_func=lambda x: f"#{x}")
                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button("✏️ Editar selecionado"):
                        st.session_state["editing_doc_id"] = int(escolha_id)
                        st.rerun()
                with col_b:
                    if st.button("🗑️ Excluir selecionado"):
                        apagar_dependentes_do_documento(session, int(escolha_id))
                        session.exec(delete(Documento).where(Documento.id == int(escolha_id)))
                        session.commit()
                        st.success(f"Documento #{int(escolha_id)} excluído.")
                        st.rerun()
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




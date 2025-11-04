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
from typing import List, Tuple, Optional, Dict

st.set_page_config(page_title="Sistema de Coleta de Dados", layout="wide")

# ---------------- Schema bootstrap (auto) ----------------
if "schema_ready" not in st.session_state:
    try:
        init_db()
        st.session_state["schema_ready"] = True
    except Exception:
        st.session_state["schema_ready"] = False

# =============== DRE Plano (pré-definido) ===============
DRE_PRESETS = [
    # 1) RECEITAS
    "RECEITA: Vendas de produtos",
    "RECEITA: Prestação de serviços",
    "RECEITA: Recebimento de juros",   # <- entra como Receita Bruta
    "RECEITA: Royalties",
    "RECEITA: Dividendos",
    "RECEITA: Deduções e abatimentos",   # entra negativa no DRE

    # 2) GASTOS COM FOLHA
    "GASTOS COM FOLHA: Salários e ordenados",
    "GASTOS COM FOLHA: Horas extras e adicionais",
    "GASTOS COM FOLHA: Férias e 13º (provisão e despesa)",
    "GASTOS COM FOLHA: Encargos sociais - INSS (patronal)",
    "GASTOS COM FOLHA: Encargos sociais - FGTS",
    "GASTOS COM FOLHA: Encargos sociais - Outros",
    "GASTOS COM FOLHA: Benefícios",

    # 3) CPV/CMV (custos de venda)
    "CPV/CMV: Matéria-prima",
    "CPV/CMV: Distribuição",
    "CPV/CMV: Logística",

    # 4) DESPESAS FIXAS
    "DESPESAS FIXAS: Aluguel",
    "DESPESAS FIXAS: Água",
    "DESPESAS FIXAS: Energia",

    # 5) DESPESAS ADMINISTRATIVAS
    "DESPESAS ADMINISTRATIVAS: Manutenção",
    "DESPESAS ADMINISTRATIVAS: Telefone em escritórios",
    "DESPESAS ADMINISTRATIVAS: Outros",

    # 6) DESPESAS COM VENDAS
    "DESPESAS COM VENDAS",

    # 7) DESPESAS FINANCEIRAS
    "DESPESAS FINANCEIRAS",

    # Provisões
    "PROVISÕES: IRPJ e CSLL",
]

# app.py — SUBSTITUIR seed_plano_contas_if_needed por esta versão
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError, InternalError
from sqlmodel import SQLModel

def seed_plano_contas_if_needed(session: Session, empresa_id: int):
    """
    Garante a existência de PlanoContasDRE e insere presets.
    Compatível com Transaction Pooler: DDL roda em AUTOCOMMIT.
    """
    try:
        # tenta listar contas
        existentes = session.exec(
            select(PlanoContasDRE).where(PlanoContasDRE.empresa_id == empresa_id)
        ).all()
    except (ProgrammingError, InternalError, Exception):
        # 1) tenta criar via metadata (ainda pode falhar no pooler)
        try:
            SQLModel.metadata.create_all(session.get_bind())
            session.commit()
        except Exception:
            pass

        # 2) cria com AUTOCOMMIT (compatível com pooler)
        from db import engine
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.exec_driver_sql("""
                CREATE TABLE IF NOT EXISTS planocontasdre (
                    id SERIAL PRIMARY KEY,
                    empresa_id INTEGER NOT NULL,
                    nome TEXT NOT NULL
                )
            """)
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_planocontasdre_empresa_id ON planocontasdre (empresa_id)")
        session.commit()

        existentes = session.exec(
            select(PlanoContasDRE).where(PlanoContasDRE.empresa_id == empresa_id)
        ).all()

    nomes_exist = {c.nome for c in existentes}
    criou = False
    for nome in DRE_PRESETS:
        if nome not in nomes_exist:
            session.add(PlanoContasDRE(empresa_id=empresa_id, nome=nome))
            criou = True
    if criou:
        session.commit()



def carregar_mapa_contas(session: Session, empresa_id: int) -> Dict[str, int]:
    contas = session.exec(
        select(PlanoContasDRE).where(PlanoContasDRE.empresa_id == empresa_id)
    ).all()
    return {c.nome: c.id for c in contas}

# --------------- Utilidades genéricas -------------------
def to_dict(m):
    return m.model_dump() if hasattr(m, "model_dump") else m.dict()

def parse_condicao_pagamento(texto: str) -> List[int]:
    if not texto:
        return [0]
    dias = []
    for parte in texto.replace(" ", "").split("/"):
        if not parte:
            continue
        try:
            dias.append(int(parte))
        except ValueError:
            pass
    return dias or [0]

def gerar_parcelas(valor_total: float, offsets: List[int], base: date) -> List[Tuple[date, float]]:
    n = max(1, len(offsets))
    base_parc = round(valor_total / n, 2)
    valores = [base_parc] * n
    ajuste = round(valor_total - sum(valores), 2)
    valores[-1] = round(valores[-1] + ajuste, 2)
    datas = [base + timedelta(days=d) for d in offsets]
    return list(zip(datas, valores))

def natureza_eff_for(doc: Documento, servico_modo: Optional[str]) -> str:
    if doc.natureza == "SERVICO":
        return servico_modo or "VENDA"
    return "VENDA" if doc.natureza == "VENDA" else "COMPRA"

def gerar_cr_cp_e_lancamentos(
    session: Session,
    doc: Documento,
    parcelas: List[Parcela],
    classif_dre_compra: str = "DESPESA",
    servico_modo: Optional[str] = None,
):
    natureza_eff = natureza_eff_for(doc, servico_modo)
    titulo_base = f"DOC#{doc.id} {doc.tipo_doc} {doc.numero or ''}".strip()

    if natureza_eff == "VENDA":
        for p in parcelas:
            session.add(ContaReceber(
                empresa_id=doc.empresa_id,
                cliente_id=doc.parceiro_id if doc.parceiro_tipo == "CLIENTE" else None,
                titulo=titulo_base,
                data_emissao=doc.data_emissao,
                data_vencto=p.data_vencto,
                valor=p.valor,
                saldo=p.valor,
                status="ABERTO",
            ))
        session.add(Lancamento(
            empresa_id=doc.empresa_id,
            data_competencia=doc.data_competencia,
            data_movimento=doc.data_emissao,
            historico=f"{doc.tipo_doc} {doc.numero or ''} - {doc.parceiro_tipo} {doc.parceiro_id}",
            valor=doc.valor_total,
            tipo="RECEITA",
            origem="DOCUMENTO",
            doc_ref=str(doc.id),
            cliente_id=doc.parceiro_id if doc.parceiro_tipo == "CLIENTE" else None,
        ))
    else:  # COMPRA
        for p in parcelas:
            session.add(ContaPagar(
                empresa_id=doc.empresa_id,
                fornecedor_id=doc.parceiro_id if doc.parceiro_tipo == "FORNECEDOR" else None,
                titulo=titulo_base,
                data_emissao=doc.data_emissao,
                data_vencto=p.data_vencto,
                valor=p.valor,
                saldo=p.valor,
                status="ABERTO",
            ))
        session.add(Lancamento(
            empresa_id=doc.empresa_id,
            data_competencia=doc.data_competencia,
            data_movimento=doc.data_emissao,
            historico=f"{doc.tipo_doc} {doc.numero or ''} - {doc.parceiro_tipo} {doc.parceiro_id}",
            valor=doc.valor_total,
            tipo=classif_dre_compra,  # 'DESPESA' ou 'CUSTO'
            origem="DOCUMENTO",
            doc_ref=str(doc.id),
            fornecedor_id=doc.parceiro_id if doc.parceiro_tipo == "FORNECEDOR" else None,
        ))

def apagar_dependentes_do_documento(session: Session, doc_id: int):
    session.exec(delete(DocumentoItem).where(DocumentoItem.documento_id == doc_id))
    session.exec(delete(Parcela).where(Parcela.documento_id == doc_id))
    titulo_like = f"DOC#{doc_id}%"
    session.exec(delete(ContaReceber).where(ContaReceber.titulo.like(titulo_like)))
    session.exec(delete(ContaPagar).where(ContaPagar.titulo.like(titulo_like)))
    session.exec(delete(Lancamento).where(Lancamento.doc_ref == str(doc_id)))
    session.commit()

def pick_parceiro(session: Session, empresa_id: int, natureza_eff: str, editing_doc: Optional[Documento]) -> Tuple[str, Optional[int]]:
    st.subheader("Parceiro")
    parceiro_id = None
    if natureza_eff == "VENDA":
        parceiro_tipo = "CLIENTE"
        lista = session.exec(select(Cliente).where(Cliente.empresa_id == empresa_id)).all()
        nomes = [f"{c.id} - {c.nome}" for c in lista]
        nomes_combo = ["[+] Cadastrar novo cliente"] + nomes
        default_idx = 0
        if editing_doc and editing_doc.parceiro_tipo == "CLIENTE":
            try:
                default_idx = 1 + next(i for i, x in enumerate(nomes) if x.startswith(f"{editing_doc.parceiro_id} - "))
            except StopIteration:
                default_idx = 0
        escolha = st.selectbox("Cliente", nomes_combo, index=default_idx, key="sb_cliente")
        if escolha == "[+] Cadastrar novo cliente":
            with st.expander("Cadastrar Cliente", expanded=True):
                novo_nome = st.text_input("Nome do novo cliente", key="novo_cli_nome")
                novo_doc = st.text_input("Documento (opcional)", key="novo_cli_doc")
                if st.button("Salvar Cliente", key="btn_salvar_cli"):
                    if not novo_nome.strip():
                        st.error("Informe o nome.")
                    else:
                        session.add(Cliente(empresa_id=empresa_id, nome=novo_nome.strip(), doc=(novo_doc.strip() or None)))
                        session.commit()
                        st.success("Cliente cadastrado. Recarregue a página.")
                        st.rerun()
        else:
            parceiro_id = int(escolha.split(" - ")[0])
    else:
        parceiro_tipo = "FORNECEDOR"
        lista = session.exec(select(Fornecedor).where(Fornecedor.empresa_id == empresa_id)).all()
        nomes = [f"{f.id} - {f.nome}" for f in lista]
        nomes_combo = ["[+] Cadastrar novo fornecedor"] + nomes
        default_idx = 0
        if editing_doc and editing_doc.parceiro_tipo == "FORNECEDOR":
            try:
                default_idx = 1 + next(i for i, x in enumerate(nomes) if x.startswith(f"{editing_doc.parceiro_id} - "))
            except StopIteration:
                default_idx = 0
        escolha = st.selectbox("Fornecedor", nomes_combo, index=default_idx, key="sb_fornecedor")
        if escolha == "[+] Cadastrar novo fornecedor":
            with st.expander("Cadastrar Fornecedor", expanded=True):
                novo_nome = st.text_input("Nome do novo fornecedor", key="novo_forn_nome")
                novo_doc = st.text_input("Documento (opcional)", key="novo_forn_doc")
                if st.button("Salvar Fornecedor", key="btn_salvar_forn"):
                    if not novo_nome.strip():
                        st.error("Informe o nome.")
                    else:
                        session.add(Fornecedor(empresa_id=empresa_id, nome=novo_nome.strip(), doc=(novo_doc.strip() or None)))
                        session.commit()
                        st.success("Fornecedor cadastrado. Recarregue a página.")
                        st.rerun()
        else:
            parceiro_id = int(escolha.split(" - ")[0])
    return parceiro_tipo, parceiro_id

# ---------------- Sidebar ----------------
with st.sidebar:
    st.header("Menu")
    host, port, src, extras = conn_info()
    st.caption(f"📡 Conectando a: `{host}:{port}` • fonte: **{src}** • {extras or '-'}")
    menu = st.radio(
        "Selecione uma opção:",
        ["Início", "Documentos", "Contas a Receber", "Contas a Pagar", "Lançamentos (consulta)", "DRE (Competência)"]
    )

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
    st.write("Lance **Documentos** (cabeçalho/parcelas/itens) e classifique cada item em **Conta DRE** (pré-definida).")
    st.info("Se não houver itens, crie 1 item com o valor total e escolha a Conta DRE.")

elif menu == "Documentos":
    st.header("📄 Documentos (Itens com Conta DRE pré-definida)")

    with Session(engine) as session:
        # Empresa única (MVP)
        try:
            empresas = session.exec(select(Empresa)).all()
        except ProgrammingError:
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
                    session.add(Empresa(nome=nome.strip(), cnpj=(cnpj.strip() or None)))
                    session.commit()
                    st.success("Empresa cadastrada! Recarregue a página.")
        else:
            empresa = empresas[0]
            st.success(f"Empresa ativa: **{empresa.nome}**")

            # Seed do plano de contas com os presets
            seed_plano_contas_if_needed(session, empresa.id)
            mapa_contas = carregar_mapa_contas(session, empresa.id)
            contas_opcoes = [n for n in DRE_PRESETS if n in mapa_contas]

            # Edição
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

            editing_doc = session.get(Documento, st.session_state["editing_doc_id"]) if st.session_state["editing_doc_id"] else None

            # Cabeçalho
            st.subheader("Cabeçalho")
            col1, col2, col3 = st.columns([1, 1, 1])
            with col1:
                natureza = st.selectbox(
                    "Natureza", ["VENDA", "COMPRA", "SERVICO"],
                    index=(["VENDA","COMPRA","SERVICO"].index(editing_doc.natureza) if editing_doc else 0),
                    key="sb_natureza"
                )
                tipo_doc = st.selectbox(
                    "Tipo de Documento", ["NFe", "NFSe", "Recibo", "Contrato", "Outro"],
                    index=(["NFe","NFSe","Recibo","Contrato","Outro"].index(editing_doc.tipo_doc) if editing_doc else 0),
                    key="sb_tipodoc"
                )
            with col2:
                numero = st.text_input("Número", value=(editing_doc.numero or "") if editing_doc else "")
                serie = st.text_input("Série (opcional)", value=(editing_doc.serie or "") if editing_doc else "")
            with col3:
                chave = st.text_input("Chave (opcional)", value=(editing_doc.chave or "") if editing_doc else "")

            # SERVIÇO → VENDA/COMPRA
            servico_modo = None
            if natureza == "SERVICO":
                sv = st.radio("Este serviço é:", ["VENDA (vou receber)", "COMPRA (vou pagar)"], horizontal=True)
                servico_modo = "VENDA" if sv.startswith("VENDA") else "COMPRA"
            natureza_eff = natureza if natureza != "SERVICO" else (servico_modo or "VENDA")

            # Parceiro
            parceiro_tipo, parceiro_id = pick_parceiro(session, empresa.id, natureza_eff, editing_doc)

            # Datas e valor total
            st.subheader("Datas e Valor")
            col1, col2, col3 = st.columns([1, 1, 1])
            with col1:
                data_emissao = st.date_input("Data de Emissão", value=(editing_doc.data_emissao if editing_doc else date.today()))
            with col2:
                data_competencia = st.date_input("Data de Competência", value=(editing_doc.data_competencia if editing_doc else date.today()))
            with col3:
                valor_total = st.number_input("Valor Total (R$)", min_value=0.0, step=0.01, format="%.2f", value=float(editing_doc.valor_total) if editing_doc else 0.0)

            # Parcelas
            st.subheader("Pagamento / Parcelas")
            colp1, colp2 = st.columns([1, 2])
            with colp1:
                cond_default = "0"
                if editing_doc:
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
                st.dataframe(pd.DataFrame([{"Parcela": i+1, "Vencimento": d, "Valor": v} for i,(d,v) in enumerate(preview)]), use_container_width=True)

            # Itens (com Conta DRE)
            st.subheader("Itens (Conta DRE pré-definida)")
            if "itens_df" not in st.session_state or st.session_state.get("editing_doc_snapshot") != st.session_state.get("editing_doc_id"):
                if editing_doc:
                    itens = session.exec(select(DocumentoItem).where(DocumentoItem.documento_id == editing_doc.id)).all()
                    if itens:
                        id_to_nome = {v: k for k, v in mapa_contas.items()}
                        st.session_state["itens_df"] = pd.DataFrame([
                            {
                                "descricao": it.descricao,
                                "quantidade": float(it.quantidade or 0),
                                "unidade": it.unidade,
                                "preco_unit": float(it.preco_unit or 0),
                                "valor_total": float(it.valor_total or 0),
                                "Conta DRE": id_to_nome.get(it.conta_dre_id, ""),
                            }
                            for it in itens
                        ])
                    else:
                        st.session_state["itens_df"] = pd.DataFrame(
                            [{"descricao": "", "quantidade": 1.0, "unidade": "un",
                              "preco_unit": 0.0, "valor_total": 0.0, "Conta DRE": ""}]
                        )
                else:
                    st.session_state["itens_df"] = pd.DataFrame(
                        [{"descricao": "", "quantidade": 1.0, "unidade": "un",
                          "preco_unit": 0.0, "valor_total": 0.0, "Conta DRE": ""}]
                    )
                st.session_state["editing_doc_snapshot"] = st.session_state.get("editing_doc_id")

            col_cfg = {
                "descricao": st.column_config.TextColumn("Descrição"),
                "quantidade": st.column_config.NumberColumn("Qtd", step=0.01),
                "unidade": st.column_config.TextColumn("Un."),
                "preco_unit": st.column_config.NumberColumn("Preço Unit.", step=0.01),
                "valor_total": st.column_config.NumberColumn("Valor Total", step=0.01, disabled=True),
                "Conta DRE": st.column_config.SelectboxColumn("Conta DRE", options=[""] + contas_opcoes),
            }
            itens_df = st.data_editor(
                st.session_state["itens_df"],
                column_config=col_cfg,
                num_rows="dynamic",
                use_container_width=True,
                key="itens_editor",
            )
            if not itens_df.empty:
                itens_df["valor_total"] = (itens_df["quantidade"].astype(float) * itens_df["preco_unit"].astype(float)).round(2)

            # Fallback para COMPRA sem itens
            classif_dre_compra = "DESPESA"
            if natureza_eff == "COMPRA":
                classif_dre_compra = st.selectbox("Classificar COMPRA (fallback) como:", ["DESPESA", "CUSTO"])

            observacoes = st.text_area("Observações (opcional)", value=(editing_doc.observacoes or "") if editing_doc else "")

            st.divider()
            acao_label = "💾 Salvar Alterações" if editing_doc else "✅ Salvar Documento (gera CR/CP + Lançamentos)"
            if st.button(acao_label):
                erros = []
                if valor_total <= 0:
                    erros.append("Valor Total deve ser > 0.")
                if not parceiro_id:
                    erros.append("Selecione um parceiro válido (ou cadastre um).")
                if natureza == "SERVICO" and servico_modo not in ("VENDA", "COMPRA"):
                    erros.append("Defina se o serviço é VENDA (vou receber) ou COMPRA (vou pagar).")
                if itens_df.empty:
                    erros.append("Inclua ao menos um item e escolha a Conta DRE.")
                if erros:
                    for e in erros:
                        st.error(e)
                    st.stop()

                # cria/atualiza cabeçalho
                if editing_doc:
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
                    apagar_dependentes_do_documento(session, doc.id)
                else:
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

                # salva itens
                total_itens = 0.0
                for _, row in itens_df.iterrows():
                    desc = str(row.get("descricao", "")).strip() or "Item"
                    qtd = float(row.get("quantidade", 0) or 0)
                    und = str(row.get("unidade", "un")).strip() or "un"
                    pu = float(row.get("preco_unit", 0) or 0)
                    vt = float(row.get("valor_total", 0) or 0)
                    conta_nome = str(row.get("Conta DRE", "")).strip()
                    if vt == 0 and not desc:
                        continue
                    conta_id = mapa_contas.get(conta_nome) if conta_nome else None
                    session.add(DocumentoItem(
                        documento_id=doc.id, produto_id=None, descricao=desc,
                        quantidade=qtd, unidade=und, preco_unit=pu, valor_total=vt,
                        conta_dre_id=conta_id,
                    ))
                    total_itens += vt
                session.commit()

                if round(total_itens, 2) != round(float(valor_total or 0), 2):
                    st.warning(f"A soma dos itens (R$ {total_itens:,.2f}) difere do Valor Total (R$ {valor_total:,.2f}).")

                # parcelas
                parcels = []
                for i, (venc, val) in enumerate(preview, start=1):
                    destino = "CR" if natureza_eff == "VENDA" else "CP"
                    p = Parcela(documento_id=doc.id, destino=destino, data_vencto=venc, valor=float(val))
                    session.add(p)
                    parcels.append(p)
                session.commit()

                # CR/CP + Lançamentos (fallback)
                gerar_cr_cp_e_lancamentos(
                    session, doc, parcels,
                    classif_dre_compra=classif_dre_compra,
                    servico_modo=(servico_modo if natureza == "SERVICO" else None)
                )
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
                st.dataframe(pd.DataFrame([to_dict(d) for d in docs]), use_container_width=True)
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

elif menu == "Contas a Receber":
    st.header("💰 Contas a Receber")
    with Session(engine) as session:
        empresas = session.exec(select(Empresa)).all()
        if not empresas:
            st.warning("Cadastre uma empresa em Documentos.")
        else:
            empresa = empresas[0]
            colf1, colf2, colf3 = st.columns([1.2, 1.2, 1])
            with colf1:
                dt_ini = st.date_input("Vencimento de", value=date.today() - timedelta(days=30))
            with colf2:
                dt_fim = st.date_input("Vencimento até", value=date.today() + timedelta(days=60))
            with colf3:
                status_opts = ["ABERTO", "PARCIAL", "QUITADO"]
                status_sel = st.multiselect("Status", status_opts, default=["ABERTO", "PARCIAL"])

            clientes = session.exec(select(Cliente).where(Cliente.empresa_id == empresa.id)).all()
            mapa_cli = {0: "Todos"} | {c.id: c.nome for c in clientes}
            cli_id = st.selectbox("Cliente", list(mapa_cli.keys()), format_func=lambda x: mapa_cli[x])

            q = select(ContaReceber).where(ContaReceber.empresa_id == empresa.id)
            q = q.where(ContaReceber.data_vencto >= dt_ini).where(ContaReceber.data_vencto <= dt_fim)
            if status_sel:
                q = q.where(ContaReceber.status.in_(status_sel))
            if cli_id != 0:
                q = q.where(ContaReceber.cliente_id == cli_id)
            titulos = session.exec(q.order_by(ContaReceber.data_vencto, ContaReceber.id)).all()

            if titulos:
                st.dataframe(pd.DataFrame([to_dict(t) for t in titulos]), use_container_width=True)
                ids = [t.id for t in titulos]
                sel_id = st.selectbox("Título", ids, format_func=lambda x: f"CR#{x}")
                t = session.get(ContaReceber, sel_id)

                st.subheader("Ações")
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.write("🔻 Baixa (parcial/total)")
                    val_baixa = st.number_input("Valor da baixa", min_value=0.0, step=0.01, format="%.2f", key="cr_baixa_val")
                    if st.button("Registrar baixa", key="cr_baixar"):
                        if val_baixa <= 0:
                            st.error("Informe um valor > 0.")
                        elif t.status == "QUITADO":
                            st.warning("Título já quitado.")
                        else:
                            novo_saldo = round(max(0.0, (t.saldo or 0.0) - val_baixa), 2)
                            t.saldo = novo_saldo
                            t.status = "QUITADO" if novo_saldo == 0 else "PARCIAL"
                            session.add(t)
                            session.commit()
                            st.success("Baixa registrada.")
                            st.rerun()
                with col2:
                    st.write("✏️ Editar título")
                    novo_titulo = st.text_input("Título", value=t.titulo, key="cr_edit_tit")
                    novo_vencto = st.date_input("Vencimento", value=t.data_vencto, key="cr_edit_venc")
                    novo_valor = st.number_input("Valor", min_value=0.0, value=float(t.valor), step=0.01, format="%.2f", key="cr_edit_val")
                    if st.button("Salvar edição", key="cr_salvar_edit"):
                        t.titulo = novo_titulo.strip() or t.titulo
                        t.data_vencto = novo_vencto
                        t.valor = novo_valor
                        if t.saldo > t.valor:
                            t.saldo = t.valor
                        session.add(t)
                        session.commit()
                        st.success("Título atualizado.")
                        st.rerun()
                with col3:
                    st.write("🗑️ Excluir")
                    if st.button("Excluir título", key="cr_excluir"):
                        session.exec(delete(ContaReceber).where(ContaReceber.id == t.id))
                        session.commit()
                        st.success("Título excluído.")
                        st.rerun()
            else:
                st.caption("Nenhum título encontrado com os filtros aplicados.")

elif menu == "Contas a Pagar":
    st.header("📤 Contas a Pagar")
    with Session(engine) as session:
        empresas = session.exec(select(Empresa)).all()
        if not empresas:
            st.warning("Cadastre uma empresa em Documentos.")
        else:
            empresa = empresas[0]
            colf1, colf2, colf3 = st.columns([1.2, 1.2, 1])
            with colf1:
                dt_ini = st.date_input("Vencimento de", value=date.today() - timedelta(days=30), key="cp_di")
            with colf2:
                dt_fim = st.date_input("Vencimento até", value=date.today() + timedelta(days=60), key="cp_df")
            with colf3:
                status_opts = ["ABERTO", "PARCIAL", "QUITADO"]
                status_sel = st.multiselect("Status", status_opts, default=["ABERTO", "PARCIAL"], key="cp_st")

            fornecedores = session.exec(select(Fornecedor).where(Fornecedor.empresa_id == empresa.id)).all()
            mapa_forn = {0: "Todos"} | {f.id: f.nome for f in fornecedores}
            forn_id = st.selectbox("Fornecedor", list(mapa_forn.keys()), format_func=lambda x: mapa_forn[x], key="cp_forn")

            q = select(ContaPagar).where(ContaPagar.empresa_id == empresa.id)
            q = q.where(ContaPagar.data_vencto >= dt_ini).where(ContaPagar.data_vencto <= dt_fim)
            if status_sel:
                q = q.where(ContaPagar.status.in_(status_sel))
            if forn_id != 0:
                q = q.where(ContaPagar.fornecedor_id == forn_id)
            titulos = session.exec(q.order_by(ContaPagar.data_vencto, ContaPagar.id)).all()

            if titulos:
                st.dataframe(pd.DataFrame([to_dict(t) for t in titulos]), use_container_width=True)
                ids = [t.id for t in titulos]
                sel_id = st.selectbox("Título", ids, format_func=lambda x: f"CP#{x}", key="cp_sel")
                t = session.get(ContaPagar, sel_id)

                st.subheader("Ações")
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.write("🔻 Baixa (parcial/total)")
                    val_baixa = st.number_input("Valor da baixa", min_value=0.0, step=0.01, format="%.2f", key="cp_baixa_val")
                    if st.button("Registrar baixa", key="cp_baixar"):
                        if val_baixa <= 0:
                            st.error("Informe um valor > 0.")
                        elif t.status == "QUITADO":
                            st.warning("Título já quitado.")
                        else:
                            novo_saldo = round(max(0.0, (t.saldo or 0.0) - val_baixa), 2)
                            t.saldo = novo_saldo
                            t.status = "QUITADO" if novo_saldo == 0 else "PARCIAL"
                            session.add(t)
                            session.commit()
                            st.success("Baixa registrada.")
                            st.rerun()
                with col2:
                    st.write("✏️ Editar título")
                    novo_titulo = st.text_input("Título", value=t.titulo, key="cp_edit_tit")
                    novo_vencto = st.date_input("Vencimento", value=t.data_vencto, key="cp_edit_venc")
                    novo_valor = st.number_input("Valor", min_value=0.0, value=float(t.valor), step=0.01, format="%.2f", key="cp_edit_val")
                    if st.button("Salvar edição", key="cp_salvar_edit"):
                        t.titulo = novo_titulo.strip() or t.titulo
                        t.data_vencto = novo_vencto
                        t.valor = novo_valor
                        if t.saldo > t.valor:
                            t.saldo = t.valor
                        session.add(t)
                        session.commit()
                        st.success("Título atualizado.")
                        st.rerun()
                with col3:
                    st.write("🗑️ Excluir")
                    if st.button("Excluir título", key="cp_excluir"):
                        session.exec(delete(ContaPagar).where(ContaPagar.id == t.id))
                        session.commit()
                        st.success("Título excluído.")
                        st.rerun()
            else:
                st.caption("Nenhum título encontrado com os filtros aplicados.")

elif menu == "Lançamentos (consulta)":
    st.header("🧾 Lançamentos (somente consulta)")
    with Session(engine) as session:
        empresas = session.exec(select(Empresa)).all()
        if not empresas:
            st.warning("Cadastre uma empresa em Documentos.")
        else:
            empresa = empresas[0]
            lancs = session.exec(select(Lancamento).where(Lancamento.empresa_id == empresa.id)).all()
            st.dataframe(pd.DataFrame([to_dict(l) for l in lancs]) if lancs else pd.DataFrame(), use_container_width=True)

elif menu == "DRE (Competência)":
    st.header("📈 DRE (Competência) — Estrutura solicitada")
    with Session(engine) as session:
        empresas = session.exec(select(Empresa)).all()
        if not empresas:
            st.warning("Cadastre uma empresa em Documentos primeiro.")
        else:
            empresa = empresas[0]
            seed_plano_contas_if_needed(session, empresa.id)
            planos = session.exec(select(PlanoContasDRE).where(PlanoContasDRE.empresa_id == empresa.id)).all()
            plano_by_id = {p.id: p.nome for p in planos}

            itens = session.exec(select(DocumentoItem)).all()

            # Mapa de bucket do DRE final (ajustado: juros agora é Receita Bruta)
            bucket_map = {
                # RECEITAS (todas como Receita Bruta, exceto deduções)
                "RECEITA: Vendas de produtos": "RECEITA_BRUTA",
                "RECEITA: Prestação de serviços": "RECEITA_BRUTA",
                "RECEITA: Royalties": "RECEITA_BRUTA",
                "RECEITA: Dividendos": "RECEITA_BRUTA",
                "RECEITA: Recebimento de juros": "RECEITA_BRUTA",
                "RECEITA: Deduções e abatimentos": "DEDUCOES",  # NEGATIVO

                # FOLHA
                "GASTOS COM FOLHA: Salários e ordenados": "FOLHA",
                "GASTOS COM FOLHA: Horas extras e adicionais": "FOLHA",
                "GASTOS COM FOLHA: Férias e 13º (provisão e despesa)": "FOLHA",
                "GASTOS COM FOLHA: Encargos sociais - INSS (patronal)": "FOLHA",
                "GASTOS COM FOLHA: Encargos sociais - FGTS": "FOLHA",
                "GASTOS COM FOLHA: Encargos sociais - Outros": "FOLHA",
                "GASTOS COM FOLHA: Benefícios": "FOLHA",

                # CPV/CMV
                "CPV/CMV: Matéria-prima": "CPV",
                "CPV/CMV: Distribuição": "CPV",
                "CPV/CMV: Logística": "CPV",

                # Despesas fixas
                "DESPESAS FIXAS: Aluguel": "DESPESAS_FIXAS",
                "DESPESAS FIXAS: Água": "DESPESAS_FIXAS",
                "DESPESAS FIXAS: Energia": "DESPESAS_FIXAS",

                # Despesas administrativas
                "DESPESAS ADMINISTRATIVAS: Manutenção": "DESPESAS_ADMIN",
                "DESPESAS ADMINISTRATIVAS: Telefone em escritórios": "DESPESAS_ADMIN",
                "DESPESAS ADMINISTRATIVAS: Outros": "DESPESAS_ADMIN",

                # Despesas com vendas
                "DESPESAS COM VENDAS": "DESPESAS_VENDAS",

                # Despesas financeiras
                "DESPESAS FINANCEIRAS": "DESPESAS_FIN",

                # Provisões
                "PROVISÕES: IRPJ e CSLL": "PROV_IRPJ_CSLL",
            }

            # Acumula valores por bucket
            acc = {
                "RECEITA_BRUTA": 0.0,
                "DEDUCOES": 0.0,
                "FOLHA": 0.0,
                "CPV": 0.0,
                "DESPESAS_FIXAS": 0.0,
                "DESPESAS_ADMIN": 0.0,
                "DESPESAS_VENDAS": 0.0,
                "DESPESAS_FIN": 0.0,
                "PROV_IRPJ_CSLL": 0.0,
            }

            for it in itens:
                val = float(it.valor_total or 0.0)
                if val == 0:
                    continue
                nome = plano_by_id.get(it.conta_dre_id, "")
                bucket = bucket_map.get(nome)
                if not bucket:
                    continue
                # Sinal: receitas +; deduções/folha/cpv/despesas/provisões -
                if bucket == "RECEITA_BRUTA":
                    acc[bucket] += val
                elif bucket == "DEDUCOES":
                    acc[bucket] -= abs(val)
                else:
                    acc[bucket] -= abs(val)

            # -------- Cálculo na ORDEM solicitada --------
            receita_bruta = acc["RECEITA_BRUTA"]
            deducoes = acc["DEDUCOES"]
            receita_liquida = receita_bruta + deducoes

            gastos_folha = acc["FOLHA"]              # negativo
            cpv = acc["CPV"]                         # negativo
            lucro_bruto = receita_liquida + cpv      # cpv negativo reduz

            desp_fixas = acc["DESPESAS_FIXAS"]       # negativo
            desp_admin = acc["DESPESAS_ADMIN"]       # negativo
            desp_vendas = acc["DESPESAS_VENDAS"]     # negativo
            desp_fin = acc["DESPESAS_FIN"]           # negativo

            resultado_antes_ir = (
                lucro_bruto + desp_fixas + desp_admin + desp_vendas + desp_fin
            )
            provisoes = acc["PROV_IRPJ_CSLL"]        # negativo
            resultado_liquido = resultado_antes_ir + provisoes

            # Exibição em tabela na ORDEM pedida
            linhas = [
                {"Conta": "Receita Bruta", "Valor (R$)": round(receita_bruta, 2)},
                {"Conta": "(-) Deduções e abatimentos", "Valor (R$)": round(deducoes, 2)},
                {"Conta": "(=) Receita Líquida", "Valor (R$)": round(receita_liquida, 2)},
                {"Conta": "(-) Gastos com Folha", "Valor (R$)": round(gastos_folha, 2)},
                {"Conta": "(-) CPV/CMV", "Valor (R$)": round(cpv, 2)},
                {"Conta": "(=) Lucro Bruto", "Valor (R$)": round(lucro_bruto, 2)},
                {"Conta": "(-) Despesas Fixas", "Valor (R$)": round(desp_fixas, 2)},
                {"Conta": "(-) Despesas Administrativas", "Valor (R$)": round(desp_admin, 2)},
                {"Conta": "(-) Despesas com Vendas", "Valor (R$)": round(desp_vendas, 2)},
                {"Conta": "(-) Despesas Financeiras", "Valor (R$)": round(desp_fin, 2)},
                {"Conta": "(=) Resultado Antes IRPJ/CSLL", "Valor (R$)": round(resultado_antes_ir, 2)},
                {"Conta": "(-) Provisões IRPJ e CSLL", "Valor (R$)": round(provisoes, 2)},
                {"Conta": "(=) Resultado Líquido", "Valor (R$)": round(resultado_liquido, 2)},
            ]
            st.dataframe(pd.DataFrame(linhas), use_container_width=True)

            col1, col2, col3 = st.columns(3)
            col1.metric("Receita Líquida", f"R$ {receita_liquida:,.2f}")
            col2.metric("Lucro Bruto", f"R$ {lucro_bruto:,.2f}")
            col3.metric("Resultado Líquido", f"R$ {resultado_liquido:,.2f}")






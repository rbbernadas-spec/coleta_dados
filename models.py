# models.py
from __future__ import annotations
from typing import Optional
from datetime import date
from sqlmodel import SQLModel, Field


# ----------------- Tabelas base -----------------
class Empresa(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nome: str
    cnpj: Optional[str] = None


class Cliente(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    empresa_id: int = Field(foreign_key="empresa.id", index=True)
    nome: str
    doc: Optional[str] = None


class Fornecedor(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    empresa_id: int = Field(foreign_key="empresa.id", index=True)
    nome: str
    doc: Optional[str] = None


class Produto(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    empresa_id: int = Field(foreign_key="empresa.id", index=True)
    nome: str
    sku: Optional[str] = None
    preco_venda: Optional[float] = Field(default=0.0)
    unidade: Optional[str] = Field(default="un")


class Estoque(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    produto_id: int = Field(foreign_key="produto.id", index=True)
    quantidade: float = Field(default=0.0)
    custo_medio: float = Field(default=0.0)


# ------------- Plano de Contas DRE --------------
class PlanoContasDRE(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    empresa_id: int = Field(foreign_key="empresa.id", index=True)
    nome: str  # Ex.: "RECEITA: Vendas de produtos", "DESPESAS FIXAS: Aluguel", etc.


# ---------------- Documentos --------------------
class Documento(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    empresa_id: int = Field(foreign_key="empresa.id", index=True)

    natureza: str  # "VENDA" | "COMPRA" | "SERVICO"
    tipo_doc: str  # "NFe" | "NFSe" | "Recibo" | "Contrato" | "Outro"
    numero: Optional[str] = None
    serie: Optional[str] = None
    chave: Optional[str] = None

    parceiro_tipo: str  # "CLIENTE" | "FORNECEDOR"
    parceiro_id: int    # id do Cliente/Fornecedor escolhido

    data_emissao: date
    data_competencia: date
    valor_total: float = 0.0

    observacoes: Optional[str] = None


class DocumentoItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    documento_id: int = Field(foreign_key="documento.id", index=True)
    produto_id: Optional[int] = Field(default=None, foreign_key="produto.id")

    descricao: str
    quantidade: float = 0.0
    unidade: str = "un"
    preco_unit: float = 0.0
    valor_total: float = 0.0

    conta_dre_id: Optional[int] = Field(default=None, foreign_key="planocontasdre.id", index=True)


class Parcela(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    documento_id: int = Field(foreign_key="documento.id", index=True)
    destino: str  # "CR" | "CP"
    data_vencto: date
    valor: float = 0.0


# ----------- Contas a Receber / Pagar -----------
class ContaReceber(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    empresa_id: int = Field(foreign_key="empresa.id", index=True)
    cliente_id: Optional[int] = Field(default=None, foreign_key="cliente.id", index=True)

    titulo: str
    data_emissao: date
    data_vencto: date
    valor: float = 0.0
    saldo: float = 0.0
    status: str = "ABERTO"  # "ABERTO" | "PARCIAL" | "QUITADO"


class ContaPagar(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    empresa_id: int = Field(foreign_key="empresa.id", index=True)
    fornecedor_id: Optional[int] = Field(default=None, foreign_key="fornecedor.id", index=True)

    titulo: str
    data_emissao: date
    data_vencto: date
    valor: float = 0.0
    saldo: float = 0.0
    status: str = "ABERTO"  # "ABERTO" | "PARCIAL" | "QUITADO"


# ----------------- Lançamentos -------------------
class Lancamento(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    empresa_id: int = Field(foreign_key="empresa.id", index=True)

    data_competencia: date
    data_movimento: date
    historico: Optional[str] = None
    valor: float = 0.0

    # "RECEITA", "DESPESA", "CUSTO" (fallback de documentos)
    tipo: str

    origem: Optional[str] = None     # "DOCUMENTO", etc.
    doc_ref: Optional[str] = None    # id do documento como string

    cliente_id: Optional[int] = Field(default=None, foreign_key="cliente.id")
    fornecedor_id: Optional[int] = Field(default=None, foreign_key="fornecedor.id")





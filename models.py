# models.py
from typing import Optional
from sqlmodel import SQLModel, Field
from datetime import date

# --- ENTIDADES BÁSICAS ---

class Empresa(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nome: str
    cnpj: Optional[str] = None

class PlanoContasDRE(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str
    nome: str
    parent_id: Optional[int] = Field(default=None, foreign_key="planocontasdre.id")
    nivel: int = 1

class Cliente(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    empresa_id: int = Field(foreign_key="empresa.id")
    nome: str
    doc: Optional[str] = None

class Fornecedor(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    empresa_id: int = Field(foreign_key="empresa.id")
    nome: str
    doc: Optional[str] = None

# --- PRODUTOS / ESTOQUE ---

class Produto(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    empresa_id: int = Field(foreign_key="empresa.id")
    sku: str
    nome: str
    unidade: str
    tipo: str  # 'produto', 'servico', 'mp'
    conta_dre_receita_id: Optional[int] = Field(default=None, foreign_key="planocontasdre.id")

class Estoque(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    empresa_id: int = Field(foreign_key="empresa.id")
    produto_id: int = Field(foreign_key="produto.id")
    qty_atual: float = 0
    custo_medio_atual: float = 0

# --- LANCAMENTOS / FINANCEIRO ---

class Lancamento(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    empresa_id: int = Field(foreign_key="empresa.id")
    data_competencia: date
    data_movimento: Optional[date] = None
    historico: str
    planocontas_id: Optional[int] = Field(default=None, foreign_key="planocontasdre.id")
    cliente_id: Optional[int] = Field(default=None, foreign_key="cliente.id")
    fornecedor_id: Optional[int] = Field(default=None, foreign_key="fornecedor.id")
    valor: float
    tipo: str  # 'RECEITA', 'DESPESA', 'CUSTO'
    origem: Optional[str] = None
    doc_ref: Optional[str] = None

class ContaReceber(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    empresa_id: int = Field(foreign_key="empresa.id")
    cliente_id: Optional[int] = Field(default=None, foreign_key="cliente.id")
    titulo: str
    data_emissao: date
    data_vencto: date
    valor: float
    saldo: float
    status: str = "ABERTO"

class ContaPagar(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    empresa_id: int = Field(foreign_key="empresa.id")
    fornecedor_id: Optional[int] = Field(default=None, foreign_key="fornecedor.id")
    titulo: str
    data_emissao: date
    data_vencto: date
    valor: float
    saldo: float
    status: str = "ABERTO"

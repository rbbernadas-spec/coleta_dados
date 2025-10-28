# db.py
import os
from sqlmodel import SQLModel, create_engine, Session
from dotenv import load_dotenv

# Carrega variáveis do .env
load_dotenv()

# Lê a URL do banco do Supabase
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL or "postgresql+psycopg://" not in DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL ausente ou inválida. Verifique seu arquivo .env com a URL completa do Supabase."
    )

# Cria engine (Postgres na nuvem)
engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)

# Inicializa o banco (cria tabelas se não existirem)
def init_db():
    import models  # importa os modelos para registrar as tabelas
    SQLModel.metadata.create_all(engine)

# Fornece sessão de conexão
def get_session():
    with Session(engine) as session:
        yield session
# db.py
import os
from sqlmodel import SQLModel, create_engine, Session
from dotenv import load_dotenv

# Carrega variáveis do .env
load_dotenv()

# Lê a URL do banco do Supabase
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL or "postgresql+psycopg://" not in DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL ausente ou inválida. Verifique seu arquivo .env com a URL completa do Supabase."
    )

# Cria engine (Postgres na nuvem)
engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)

# Inicializa o banco (cria tabelas se não existirem)
def init_db():
    import models  # importa os modelos para registrar as tabelas
    SQLModel.metadata.create_all(engine)

# Fornece sessão de conexão
def get_session():
    with Session(engine) as session:
        yield session

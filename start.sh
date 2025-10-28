#!/usr/bin/env bash
set -e

echo "[1/3] Verificando Python..."
python --version || python3 --version

echo "[2/3] Instalando dependências..."
pip install --upgrade pip
pip install -r requirements.txt

echo "[3/3] Inicializando app Streamlit..."
# Porta padrão do Streamlit: 8501
# Plataformas de nuvem normalmente definem a variável $PORT
PORT_ARG=""
if [ -n "$PORT" ]; then
  PORT_ARG="--server.port=${PORT} --server.address=0.0.0.0"
fi

streamlit run app.py $PORT_ARG

FROM python:3.9-slim

# Instalar dependências do sistema (ffmpeg é essencial para o yt-dlp manipulação de áudio)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiar apenas o requirements.txt primeiro para aproveitar o cache do Docker
COPY requirements.txt .

# Instalar dependências Python
RUN pip install --no-cache-dir -r requirements.txt
# Instalar gunicorn para servidor de produção
RUN pip install gunicorn

# Copiar o restante do código
COPY . .

# Expor a porta 8888
EXPOSE 8888

# Comando para iniciar a aplicação usando Gunicorn
# Timeout aumentado para 120s para permitir processamentos mais longos (transcrições/downloads)
CMD ["gunicorn", "--bind", "0.0.0.0:8888", "app:app", "--workers", "3", "--timeout", "120"]

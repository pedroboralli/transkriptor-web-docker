FROM python:3.9-slim

# Instalar dependências do sistema
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiar requirements e instalar dependências
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instalar yt-dlp mais recente
RUN pip install --no-cache-dir --upgrade yt-dlp

# Copiar aplicação
COPY . .

# Criar diretório de downloads
RUN mkdir -p /app/downloads

# Expor porta
EXPOSE 8888

# Usar Flask dev server (mais simples para debug)
CMD ["python", "app.py"]

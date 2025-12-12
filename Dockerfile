FROM python:3.9-slim

# Instalar dependências do sistema (ffmpeg é essencial para o yt-dlp)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiar apenas o requirements.txt primeiro para aproveitar o cache do Docker
COPY requirements.txt .

# Instalar dependências Python
RUN pip install --no-cache-dir -r requirements.txt

# Forçar atualização do yt-dlp para a versão mais recente do master
RUN pip install --no-cache-dir --force-reinstall https://github.com/yt-dlp/yt-dlp/archive/master.zip

# Instalar gunicorn para servidor de produção
RUN pip install --no-cache-dir gunicorn

# Copiar o restante do código
COPY . .

# Criar diretório para downloads
RUN mkdir -p /app/downloads

# Expor a porta 8888
EXPOSE 8888

# Comando para iniciar a aplicação usando Gunicorn
# Configurações otimizadas para Easypanel
CMD ["gunicorn", "--bind", "0.0.0.0:8888", "app:app", "--workers", "2", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", "--log-level", "info"]

# Deploy no Easypanel - Guia Rápido

## 📦 Estrutura de Arquivos

Todos os arquivos Docker necessários já estão prontos:
- ✅ `Dockerfile` - Configuração da imagem
- ✅ `docker-compose.yml` - Orquestração (opcional no Easypanel)
- ✅ `.dockerignore` - Otimização
- ✅ `app.py` - Aplicação principal
- ✅ `requirements.txt` - Dependências

## 🚀 Deploy no Easypanel

### Método 1: Deploy via GitHub (Recomendado)

1. **Fazer push do código para GitHub**
   ```bash
   cd transkriptor-web-docker
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin seu-repositorio.git
   git push -u origin main
   ```

2. **No Easypanel:**
   - Criar novo projeto → "App"
   - Escolher "GitHub" como source
   - Selecionar repositório e branch
   - Easypanel detectará automaticamente o `Dockerfile`

3. **Configurar:**
   - Port: `8888` (já está no Dockerfile)
   - Environment Variables:
     - `OPENAI_API_KEY` = sua chave
   - Domain: adicionar seu domínio (SSL automático)

4. **Deploy:**
   - Clicar em "Deploy"
   - Easypanel vai fazer build e subir aplicação

### Método 2: Deploy Manual (Upload de Arquivos)

1. **No Easypanel:**
   - Criar novo projeto → "App"
   - Escolher "Dockerfile" como source

2. **Upload:**
   - Fazer zip da pasta `transkriptor-web-docker`
   - Fazer upload no Easypanel
   - Ou usar Git local

3. **Configurar:**
   - Port: `8888`
   - Environment: `OPENAI_API_KEY`
   - Domain: seu domínio

## ⚙️ Configurações Importantes no Easypanel

### Port Mapping
- Container Port: `8888`
- Easypanel vai expor automaticamente

### Environment Variables
```
OPENAI_API_KEY=sua_chave_aqui
PYTHONUNBUFFERED=1
```

### Volume (Opcional)
Se quiser persistir downloads:
- Mount Path: `/app/downloads`
- Host Path: deixar Easypanel criar automaticamente

### Resources
- Memory: 512MB-1GB (recomendado)
- CPU: 0.5-1 core

## � Atualizar Aplicação

### Se usar GitHub:
1. Fazer push das mudanças
2. No Easypanel: clicar em "Rebuild"

### Se usar upload manual:
1. Fazer novo upload
2. Rebuild automático

## 🔍 Monitoramento

No painel do Easypanel você pode:
- Ver logs em tempo real
- Reiniciar aplicação
- Ver uso de recursos
- Configurar SSL/domínio

## ✅ Checklist Deploy

- [ ] Código no GitHub ou pronto para upload
- [ ] OPENAI_API_KEY configurada
- [ ] Port 8888 configurado
- [ ] Domínio adicionado (opcional mas recomendado)
- [ ] SSL ativado (automático no Easypanel)
- [ ] Build concluído com sucesso
- [ ] Aplicação acessível

## 🎯 URL de Acesso

Após deploy:
- Com domínio: `https://seu-dominio.com`
- Default Easypanel: URL gerada automaticamente pelo painel

## 💡 Dicas

1. **SSL Automático**: Easypanel configura SSL automaticamente quando você adiciona um domínio
2. **Auto-Deploy**: Configure webhook do GitHub para deploy automático em cada push
3. **Logs**: Use a aba "Logs" no Easypanel para debug
4. **Rebuild**: Se algo der errado, clique em "Rebuild" para reconstruir do zero

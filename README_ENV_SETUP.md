# 🔐 Configuração de Segurança - Variáveis de Ambiente

## ⚡ **Setup Rápido**

### 1. **Primeiro uso:**
```bash
# Copie o arquivo de exemplo
copy .env.example .env

# Edite o .env com suas credenciais reais
notepad .env
```

### 2. **Preencha o arquivo .env:**
```bash
# CONFIGURAÇÕES DO KEYCLOAK
KEYCLOAK_AUTH_URL=https://lus.rr.sebrae.com.br/realms/sebrae-corporate/protocol/openid-connect/token
KEYCLOAK_CLIENT_ID=seu_client_id_real
KEYCLOAK_CLIENT_SECRET=seu_client_secret_real

# CONFIGURAÇÕES DAS APIS DO RM
RM_FINANCEIRO_BASE_URL=https://api.rm.sebrae.com/financeiro
RM_RH_BASE_URL=https://api.rm.sebrae.com/rh
RM_API_TIMEOUT=30
```

### 3. **Execute a aplicação:**
```bash
python app.py
```

## 🔒 **Segurança**

### ✅ **O que está protegido:**
- **Credenciais KeyCloak**: client_id, client_secret
- **URLs das APIs**: Configuráveis por ambiente
- **Timeouts**: Personalizáveis

### ⚠️ **IMPORTANTE:**
- ❌ **NUNCA** commite o arquivo `.env`
- ✅ **SEMPRE** use o `.env.example` como modelo
- ✅ **Mantenha** `.env` no `.gitignore`

## 👥 **Para Colaboradores**

### **Novo desenvolvedor:**
1. Clone o repositório
2. Copie `.env.example` para `.env`
3. Peça as credenciais para um colega
4. Preencha o arquivo `.env`
5. Execute `python app.py`

### **Mudanças em configuração:**
1. Atualize `.env.example` (se necessário)
2. Comunique aos colegas sobre novas variáveis
3. Nunca commite credenciais reais

## 🚀 **Deploy em Produção**

### **Servidor:**
```bash
# Definir variáveis no servidor
export KEYCLOAK_CLIENT_ID="valor_producao"
export KEYCLOAK_CLIENT_SECRET="valor_producao"
# ... outras variáveis

# Ou usar arquivo .env no servidor
cp .env.production .env
```

### **Docker:**
```dockerfile
# No Dockerfile
ENV KEYCLOAK_CLIENT_ID=valor
ENV KEYCLOAK_CLIENT_SECRET=valor
```

## 🔧 **Troubleshooting**

### **Erro: "Variável não encontrada"**
1. Verifique se o arquivo `.env` existe
2. Confirme se a variável está definida no `.env`
3. Reinicie a aplicação após alterar o `.env`

### **Teste manual das variáveis:**
```bash
# Testar carregamento do .env
python -c "from dotenv import load_dotenv; import os; load_dotenv(); print('KeyCloak URL:', os.getenv('KEYCLOAK_AUTH_URL'))"

# Testar inicialização do app
python -c "from app import app; print('✅ App carregado com sucesso!')"
```

### **Erro: "Token inválido"**
1. Verifique as credenciais no `.env`
2. Confirme se o client_secret está correto
3. Teste manualmente com curl

### **Erro: "SSL Certificate Error"**
- A aplicação tem fallback automático para `verify=False`
- Logs mostrarão: "Aviso: SSL verification desabilitado"

## 📝 **Variáveis Disponíveis**

| Variável | Descrição | Exemplo |
|----------|-----------|---------|
| `KEYCLOAK_AUTH_URL` | URL do endpoint de token | `https://...` |
| `KEYCLOAK_CLIENT_ID` | ID do cliente KeyCloak | `hubcount` |
| `KEYCLOAK_CLIENT_SECRET` | Secret do cliente | `abc123...` |
| `RM_FINANCEIRO_BASE_URL` | Base URL da API financeira | `https://api.rm...` |
| `RM_RH_BASE_URL` | Base URL da API de RH | `https://api.rm...` |
| `RM_API_TIMEOUT` | Timeout das APIs (segundos) | `30` |
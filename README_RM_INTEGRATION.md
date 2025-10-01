# HubCount - Integração com APIs do RM via KeyCloak

Sistema de BI integrado que suporta tanto bancos de dados SQL quanto APIs do RM (Royal Management) autenticadas via KeyCloak.

## 🚀 Funcionalidades Implementadas

### ✅ Autenticação KeyCloak
- Gerenciamento automático de tokens de acesso
- Renovação automática antes do vencimento
- Cache de tokens em memória
- Tratamento de erros SSL/TLS

### ✅ Suporte a Múltiplas APIs do RM
- Framework extensível para diferentes APIs
- Configuração via YAML
- Queries flexíveis (GET, POST, parâmetros)
- Normalização automática de respostas

### ✅ Datasources Híbridos
- Bancos SQL tradicionais (SQLite, PostgreSQL, MySQL)
- APIs do RM como datasources
- Interface unificada para métricas

## 📋 Pré-requisitos

```bash
pip install -r requirements.txt
```

## ⚙️ Configuração

### 1. KeyCloak (hubcount_config.yml)

```yaml
keycloak:
  auth_url: "https://lus.rr.sebrae.com.br/realms/sebrae-corporate/protocol/openid-connect/token"
  client_id: "hubcount"
  client_secret: "7nI3Ttz2v4TFdN4d5xujB8pPYUMXVTSw"
```

### 2. APIs do RM

```yaml
rm_apis:
  rm_financeiro:
    name: "rm_financeiro"
    type: "rm-api"
    base_url: "https://api.rm.com/financeiro"
    timeout: 30
    description: "API do RM para dados financeiros"
  
  rm_rh:
    name: "rm_rh"
    type: "rm-api" 
    base_url: "https://api.rm.com/rh"
    timeout: 30
    description: "API do RM para dados de RH"
```

### 3. Métricas de API

```yaml
metrics:
  rm_total_receitas:
    title: "Total de Receitas (RM)"
    source: rm_financeiro
    type: single
    desc: "Total de receitas obtido via API do RM"
    api_query: "/receitas/total"

  rm_despesas_por_categoria:
    title: "Despesas por Categoria (RM)"
    source: rm_financeiro  
    type: bar
    desc: "Despesas agrupadas por categoria via API do RM"
    api_query: "/despesas/por-categoria"
```

## 🔧 Tipos de Queries API

### Query Simples (GET)
```yaml
api_query: "/usuarios"
api_query: "/dados?filtro=ativo"
```

### Query Complexa (JSON)
```yaml
api_query: '{
  "method": "POST",
  "endpoint": "/search",
  "data": {"filtro": "ativo", "limite": 100},
  "params": {"formato": "json"}
}'
```

## 🚀 Execução

```bash
# Iniciar aplicação
python app.py

# Testar autenticação KeyCloak
python test_keycloak.py

# Acessar dashboard
http://127.0.0.1:5000
```

## 📊 Endpoints da API

- `GET /api/health` - Status da aplicação
- `GET /api/datasources` - Lista datasources disponíveis
- `GET /api/metrics` - Executa métricas
- `GET /api/metrics?source=rm_financeiro` - Métricas específicas
- `GET /api/keycloak/test` - Testa autenticação KeyCloak
- `POST /api/refresh-config` - Recarrega configuração

## 🔍 Estrutura de Resposta das APIs RM

O sistema normaliza automaticamente respostas das APIs para o formato esperado:

### Para métricas `single`:
```json
{"value": 12345}
// ou diretamente o valor numérico
```

### Para métricas `bar`/`line`/`pie`:
```json
[
  {"label": "Categoria A", "value": 100},
  {"label": "Categoria B", "value": 200}
]
```

### Para métricas `table`:
```json
[
  {"coluna1": "valor1", "coluna2": "valor2"},
  {"coluna1": "valor3", "coluna2": "valor4"}
]
```

## 🛠️ Desenvolvimento

### Estrutura dos Arquivos
- `app.py` - Aplicação principal Flask
- `keycloak_auth.py` - Módulo de autenticação KeyCloak
- `rm_apis.py` - Classes base para APIs do RM
- `hubcount_config.yml` - Configuração do sistema
- `test_keycloak.py` - Scripts de teste

### Adicionando Nova API RM

1. Adicione configuração no YAML:
```yaml
rm_apis:
  nova_api:
    name: "nova_api"
    type: "rm-api"
    base_url: "https://api.rm.com/nova"
    timeout: 30
```

2. Crie métricas usando a nova API:
```yaml
metrics:
  nova_metrica:
    title: "Nova Métrica"
    source: nova_api
    type: single
    api_query: "/dados/total"
```

## ⚠️ Tratamento de Erros

O sistema trata automaticamente:
- **Tokens expirados**: Renovação automática
- **Erros SSL**: Fallback para desenvolvimento
- **APIs indisponíveis**: Logs detalhados
- **Respostas inválidas**: Normalização flexível

## 🔐 Segurança

- Tokens são mantidos apenas em memória
- Logs não expõem dados sensíveis
- Configurações podem usar variáveis de ambiente
- Suporte a SSL/TLS configurável

## 📝 Logs

O sistema gera logs detalhados para:
- Autenticação KeyCloak
- Chamadas de API
- Erros e exceções
- Performance de consultas

## 🎯 Próximos Passos

Para usar com APIs reais do RM:

1. **Ajuste as URLs** no `hubcount_config.yml`
2. **Configure os endpoints** corretos nas métricas
3. **Teste conectividade** com `python test_keycloak.py`
4. **Valide retornos** das APIs no dashboard
5. **Ajuste normalização** se necessário no `rm_apis.py`
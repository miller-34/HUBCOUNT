# app.py
"""
HubCount BI Studio – Flask (single-file)
- UI com cards + Chart.js (single/line/bar/pie/table)
- YAML de configuração (datasources + métricas)
- Filtro por banco: /api/metrics?source=<nome_do_banco>
- Seed de bancos SQLite de demonstração
"""

from __future__ import annotations
import os, time, yaml, logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, List, Union
from flask import Flask, jsonify, request, Response, render_template_string
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from dotenv import load_dotenv

# Carrega variáveis de ambiente do arquivo .env
load_dotenv()

# Importações dos módulos de APIs do RM
from keycloak_auth import initialize_keycloak_auth
from rm_apis import get_rm_api, clear_api_cache

APP_TITLE = "Análise de Dados Sebrae-RR"
DEFAULT_CONFIG_PATH = os.environ.get("HUBCOUNT_CONFIG", "hubcount_config.yml")

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ------------------------- Tipos/Config -------------------------

def expand_env_vars(data):
    """Expande variáveis de ambiente nos valores da configuração"""
    if isinstance(data, dict):
        return {k: expand_env_vars(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [expand_env_vars(item) for item in data]
    elif isinstance(data, str) and data.startswith("${") and data.endswith("}"):
        # Extrai o nome da variável: ${VAR_NAME} -> VAR_NAME
        var_name = data[2:-1]
        return os.getenv(var_name, data)  # Retorna o valor da env var ou o valor original
    else:
        return data

@dataclass
class DataSource:
    name: str
    uri: str
    ds_type: str = "sql"  # "sql" ou "api"

@dataclass
class Metric:
    key: str
    title: str
    source: str
    mtype: str               # single | bar | line | pie | table
    sql: Optional[str] = None
    api_query: Optional[str] = None
    value_col: Optional[str] = None
    label_col: Optional[str] = None
    desc: Optional[str] = None

class Config:
    def __init__(self, datasources: Dict[str, DataSource], metrics: Dict[str, Metric], 
                 keycloak_config: Optional[Dict[str, str]] = None, 
                 rm_apis_config: Optional[Dict[str, Dict[str, Any]]] = None):
        self.datasources = datasources
        self.metrics = metrics
        self.keycloak_config = keycloak_config
        self.rm_apis_config = rm_apis_config or {}

    @staticmethod
    def from_yaml(path: str) -> "Config":
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(DEFAULT_YAML_EXAMPLE.strip() + "\n")
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        
        # Expande variáveis de ambiente
        raw = expand_env_vars(raw)
        
        # Datasources SQL
        dss: Dict[str, DataSource] = {}
        for name, d in (raw.get("datasources") or {}).items():
            dss[name] = DataSource(name=name, uri=d["uri"], ds_type="sql")
        
        # APIs do RM como datasources
        rm_apis_config = raw.get("rm_apis") or {}
        for name, api_config in rm_apis_config.items():
            api_config["name"] = name
            dss[name] = DataSource(name=name, uri="", ds_type="api")
        
        # Métricas
        mets: Dict[str, Metric] = {}
        for key, m in (raw.get("metrics") or {}).items():
            mets[key] = Metric(
                key=key,
                title=m.get("title", key),
                source=m["source"],
                sql=m.get("sql"),
                api_query=m.get("api_query"),
                mtype=m.get("type", "single"),
                value_col=m.get("value_col", "value"),
                label_col=m.get("label_col", "label"),
                desc=m.get("desc"),
            )
        
        # Configuração do KeyCloak
        keycloak_config = raw.get("keycloak")
        
        return Config(
            datasources=dss, 
            metrics=mets, 
            keycloak_config=keycloak_config,
            rm_apis_config=rm_apis_config
        )

# ------------------------- Engines cache -------------------------
_engine_cache: Dict[str, Engine] = {}
def get_engine(uri: str) -> Engine:
    if uri not in _engine_cache:
        _engine_cache[uri] = create_engine(uri, pool_pre_ping=True)
    return _engine_cache[uri]

# ------------------------- Execução de métricas -------------------------
def run_metric(conf: Config, metric_key: str) -> Dict[str, Any]:
    if metric_key not in conf.metrics:
        raise KeyError(f"Métrica '{metric_key}' não encontrada.")
    m = conf.metrics[metric_key]
    ds = conf.datasources.get(m.source)
    if not ds:
        raise KeyError(f"DataSource '{m.source}' não encontrado para a métrica '{metric_key}'.")

    t0 = time.time()
    
    if ds.ds_type == "sql":
        # Execução SQL tradicional
        if not m.sql:
            raise ValueError(f"Métrica '{metric_key}' do tipo SQL deve ter campo 'sql'.")
        
        eng = get_engine(ds.uri)
        with eng.connect() as conn:
            result = conn.execute(text(m.sql))
            rows = [dict(r._mapping) for r in result]
    
    elif ds.ds_type == "api":
        # Execução via API do RM
        if not m.api_query:
            raise ValueError(f"Métrica '{metric_key}' do tipo API deve ter campo 'api_query'.")
        
        api_config = conf.rm_apis_config.get(m.source)
        if not api_config:
            raise KeyError(f"Configuração da API '{m.source}' não encontrada.")
        
        api = get_rm_api(m.source, api_config)
        rows = api.execute_query(m.api_query)
        
    else:
        raise ValueError(f"Tipo de datasource não suportado: {ds.ds_type}")
    
    elapsed_ms = int((time.time() - t0) * 1000)

    if m.mtype == "single":
        val_col = m.value_col or "value"
        value = rows[0][val_col] if rows and val_col in rows[0] else (rows[0] if rows else None)
        if isinstance(value, dict):
            # Se o valor é um dict, tenta pegar o primeiro valor numérico
            for v in value.values():
                if isinstance(v, (int, float)):
                    value = v
                    break
        payload = {"type": "single", "value": value, "elapsed_ms": elapsed_ms}
    elif m.mtype in ("bar", "line", "pie"):
        val_col = m.value_col or "value"
        lab_col = m.label_col or "label"
        labels = [str(r.get(lab_col, f"Item {i+1}")) for i, r in enumerate(rows)]
        values = []
        for r in rows:
            val = r.get(val_col, 0)
            if val is not None:
                try:
                    values.append(float(val))
                except (ValueError, TypeError):
                    values.append(0)
            else:
                values.append(0)
        payload = {"type": m.mtype, "labels": labels, "values": values, "elapsed_ms": elapsed_ms}
    elif m.mtype == "table":
        payload = {"type": "table", "rows": rows, "elapsed_ms": elapsed_ms}
    else:
        raise ValueError(f"Tipo de métrica não suportado: {m.mtype}")

    return {"key": m.key, "title": m.title, "desc": m.desc, "source": m.source, "data": payload}

# ------------------------- Carrega config -------------------------
config: Config = Config.from_yaml(DEFAULT_CONFIG_PATH)

# Inicializa KeyCloak se configurado
if config.keycloak_config:
    try:
        initialize_keycloak_auth(
            config.keycloak_config["auth_url"],
            config.keycloak_config["client_id"],
            config.keycloak_config["client_secret"]
        )
        logger.info("KeyCloak inicializado com sucesso")
    except Exception as e:
        logger.error(f"Erro ao inicializar KeyCloak: {e}")
else:
    logger.warning("Configuração do KeyCloak não encontrada")

# ------------------------- APIs -------------------------
@app.get("/api/health")
def api_health() -> Response:
    return jsonify({"ok": True, "app": APP_TITLE})

@app.get("/api/datasources")
def api_datasources() -> Response:
    datasources_info = {}
    for name, ds in config.datasources.items():
        datasources_info[name] = {
            "name": name,
            "type": ds.ds_type
        }
    return jsonify({"datasources": list(config.datasources.keys()), "datasources_info": datasources_info})

@app.get("/api/keycloak/test")
def api_keycloak_test() -> Response:
    """Testa a conectividade com o KeyCloak"""
    if not config.keycloak_config:
        return jsonify({"ok": False, "error": "KeyCloak não configurado"}), 400
    
    try:
        from keycloak_auth import get_keycloak_auth
        auth = get_keycloak_auth()
        token = auth.get_access_token()
        return jsonify({
            "ok": True, 
            "message": "Token obtido com sucesso",
            "token_length": len(token),
            "has_token": bool(token)
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.get("/api/metrics")
def api_metrics() -> Response:
    """
    Retorna métricas.
      ?keys=a,b,c    -> apenas essas chaves
      ?source=hotel  -> apenas métricas cujo 'source' seja 'hotel'
    """
    keys_param = request.args.get("keys")
    source_param = request.args.get("source")

    if keys_param:
        wanted = [k.strip() for k in keys_param.split(",") if k.strip()]
    else:
        wanted = list(config.metrics.keys())

    if source_param:
        wanted = [k for k in wanted if config.metrics.get(k) and config.metrics[k].source == source_param]

    out: List[Dict[str, Any]] = []
    errors: Dict[str, str] = {}
    for k in wanted:
        try:
            out.append(run_metric(config, k))
        except Exception as e:
            errors[k] = str(e)
    return jsonify({"metrics": out, "errors": errors})

@app.post("/api/refresh-config")
def api_refresh_config() -> Response:
    global config
    try:
        config = Config.from_yaml(DEFAULT_CONFIG_PATH)
        
        # Reinicializa KeyCloak se necessário
        if config.keycloak_config:
            try:
                initialize_keycloak_auth(
                    config.keycloak_config["auth_url"],
                    config.keycloak_config["client_id"],
                    config.keycloak_config["client_secret"]
                )
                logger.info("KeyCloak reinicializado com sucesso")
            except Exception as e:
                logger.error(f"Erro ao reinicializar KeyCloak: {e}")
        
        # Limpa cache de APIs
        clear_api_cache()
        
        return jsonify({
            "ok": True, 
            "metrics": list(config.metrics.keys()), 
            "datasources": list(config.datasources.keys()),
            "keycloak_configured": bool(config.keycloak_config),
            "rm_apis": list(config.rm_apis_config.keys())
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

# ------------------------- UI -------------------------
HTML = """
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{title}}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet"/>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <style>
    body{ background:#f5f6fa; color:#2c3e50 }
    .card{ background:#ffffff; border-color:#dcdde1 }
    .metric-value{ font-size: clamp(28px, 5vw, 42px); font-weight: 800 }
    .metric-desc{ color:#555 }
    .page-title{ font-weight:800; letter-spacing:.5px; color:#004a80 }
    .footer{ color:#666; font-size:.9rem }
    .loader{ width:36px; height:36px; border-radius:50%; border:4px solid #ccc; border-top-color:#0077c2; animation:spin 1s linear infinite; }
    @keyframes spin {to{ transform: rotate(360deg) }}
  </style>
</head>
<body>
  <div class="container py-4">
    <div class="d-flex align-items-center gap-3 mb-4">
      <div class="loader" id="loader" hidden></div>
      <h1 class="page-title m-0">{{title}}</h1>

      <!-- Seletor de banco -->
      <div class="d-flex align-items-center gap-2 ms-auto">
        <label for="ds-select" class="form-label m-0" style="font-size:.9rem;">Banco:</label>
        <select id="ds-select" class="form-select form-select-sm" style="width:auto; min-width: 220px;">
          <option value="">Todos os bancos</option>
        </select>
        <button class="btn btn-sm btn-outline-dark" id="btn-refresh">Recarregar config</button>
      </div>
    </div>

    <div id="errors" class="mb-3"></div>
    <div class="row" id="cards"></div>
    <div class="footer mt-5">Sistema de BI integrado com APIs do RM via KeyCloak • Edite <code>hubcount_config.yml</code> para configurar suas métricas.</div>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
  <script>
  const el = (sel, root=document) => root.querySelector(sel);

  async function fetchJSON(url, opts={}){
    const r = await fetch(url, opts);
    if(!r.ok) throw new Error(await r.text());
    return r.json();
  }
  function showLoader(show){ el('#loader').hidden = !show }
  function fmtNumber(n){
    if(n === null || n === undefined) return '—';
    try{ return new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 2 }).format(n); }
    catch(_){ return String(n); }
  }

  // ---------- Cards ----------
  function chartCard(metric){
    const id = `chart_${metric.key}`;
    const card = document.createElement('div');
    card.className = 'col-12 col-md-6 col-xl-4 mb-4';
    card.innerHTML = `
      <div class="card h-100 shadow-sm">
        <div class="card-body d-flex flex-column">
          <div class="d-flex align-items-start mb-2">
            <h5 class="card-title me-2">${metric.title}</h5>
            <span class="badge bg-secondary">${metric.source}</span>
          </div>
          ${metric.desc ? `<div class="metric-desc mb-2">${metric.desc}</div>` : ''}
          <div class="mt-auto"><canvas id="${id}" height="200"></canvas></div>
          <div class="text-end text-muted mt-2" style="font-size:.85rem">${metric.data.elapsed_ms} ms</div>
        </div>
      </div>`;
    setTimeout(()=>{
      const ctx = el('#'+id).getContext('2d');
      const type = metric.data.type === 'pie' ? 'pie' : (metric.data.type === 'line' ? 'line' : 'bar');
      new Chart(ctx, {
        type,
        data: { labels: metric.data.labels, datasets: [{ label: metric.title, data: metric.data.values }] },
        options: {
          responsive:true,
          plugins: { legend: { display: metric.data.type==='pie' } },
          scales: (metric.data.type==='pie') ? {} : { y: { beginAtZero:true } }
        }
      });
    },0);
    return card;
  }

  function singleCard(metric){
    const card = document.createElement('div');
    card.className = 'col-12 col-sm-6 col-lg-4 col-xxl-3 mb-4';
    card.innerHTML = `
      <div class="card h-100 shadow-sm">
        <div class="card-body">
          <div class="d-flex align-items-start mb-2">
            <h5 class="card-title me-2">${metric.title}</h5>
            <span class="badge bg-secondary">${metric.source}</span>
          </div>
          ${metric.desc ? `<div class="metric-desc mb-2">${metric.desc}</div>` : ''}
          <div class="metric-value">${fmtNumber(metric.data.value)}</div>
          <div class="text-end text-muted mt-2" style="font-size:.85rem">${metric.data.elapsed_ms} ms</div>
        </div>
      </div>`;
    return card;
  }

  function tableCard(metric){
    const card = document.createElement('div');
    card.className = 'col-12 mb-4';
    const rows = metric.data.rows || [];
    const headers = rows.length ? Object.keys(rows[0]) : [];
    const thead = headers.map(h=>`<th>${h}</th>`).join('');
    const tbody = rows.map(r=>`<tr>${headers.map(h=>`<td>${r[h] ?? ''}</td>`).join('')}</tr>`).join('');
    card.innerHTML = `
      <div class="card h-100 shadow-sm">
        <div class="card-body">
          <div class="d-flex align-items-start mb-2">
            <h5 class="card-title me-2">${metric.title}</h5>
            <span class="badge bg-secondary">${metric.source}</span>
          </div>
          ${metric.desc ? `<div class="metric-desc mb-2">${metric.desc}</div>` : ''}
          <div class="table-responsive">
            <table class="table table-striped table-bordered align-middle">
              <thead><tr>${thead}</tr></thead>
              <tbody>${tbody}</tbody>
            </table>
          </div>
          <div class="text-end text-muted mt-2" style="font-size:.85rem">${metric.data.elapsed_ms} ms</div>
        </div>
      </div>`;
    return card;
  }

  // ---------- Carregamento ----------
  async function loadDatasources(){
    try{
      const data = await fetchJSON('/api/datasources');
      const sel = el('#ds-select');
      sel.innerHTML = '<option value="">Todos os bancos</option>';
      (data.datasources || []).forEach(ds=>{
        const opt = document.createElement('option');
        opt.value = ds; opt.textContent = ds; sel.appendChild(opt);
      });
    }catch(e){ /* opcional: exibir erro */ }
  }

  async function loadMetrics(source=""){
    showLoader(true);
    el('#cards').innerHTML = ''; el('#errors').innerHTML = '';
    try{
      const qs = source ? `?source=${encodeURIComponent(source)}` : '';
      const data = await fetchJSON('/api/metrics'+qs);

      if(Object.keys(data.errors||{}).length){
        const list = Object.entries(data.errors).map(([k,v])=>`<li><code>${k}</code>: ${v}</li>`).join('');
        el('#errors').innerHTML = `<div class="alert alert-warning">
          Erros ao carregar algumas métricas:<ul class="m-0 ps-4">${list}</ul></div>`;
      }
      for(const metric of (data.metrics||[])){
        let card; const t = metric.data?.type;
        if(t === 'single') card = singleCard(metric);
        else if(t === 'table') card = tableCard(metric);
        else card = chartCard(metric);
        el('#cards').appendChild(card);
      }
      if((data.metrics||[]).length === 0){
        el('#errors').innerHTML = `<div class="alert alert-info">Nenhuma métrica para ${source || 'todas as fontes'}.</div>`;
      }
    }catch(e){
      el('#errors').innerHTML = `<div class="alert alert-danger">Falha ao carregar métricas: ${e.message}</div>`;
    }finally{
      showLoader(false);
    }
  }

  // Troca de banco
  el('#ds-select').addEventListener('change', ()=> loadMetrics(el('#ds-select').value));

  // Recarregar YAML
  el('#btn-refresh').addEventListener('click', async ()=>{
    showLoader(true);
    try{ await fetchJSON('/api/refresh-config', { method:'POST' }); }
    finally{ showLoader(false); await loadDatasources(); loadMetrics(el('#ds-select').value); }
  });

  // Inicializa
  loadDatasources().then(()=> loadMetrics(""));
  </script>
</body>
</html>
"""

@app.get("/")
def home():
    return render_template_string(HTML, title=APP_TITLE)

# ------------------------- YAML exemplo -------------------------
DEFAULT_YAML_EXAMPLE = r"""
# hubcount_config.yml

# IMPORTANTE: Credenciais agora vêm do arquivo .env
# 1. Copie .env.example para .env
# 2. Preencha os valores reais no .env
# 3. NUNCA commite o arquivo .env!

# Configuração do KeyCloak para autenticação das APIs do RM
keycloak:
  auth_url: "${KEYCLOAK_AUTH_URL}"
  client_id: "${KEYCLOAK_CLIENT_ID}"
  client_secret: "${KEYCLOAK_CLIENT_SECRET}"

# APIs do RM
rm_apis:
  rm_financeiro:
    name: "rm_financeiro"
    type: "rm-api"
    base_url: "${RM_FINANCEIRO_BASE_URL}"
    timeout: "${RM_API_TIMEOUT}"
    description: "API do RM para dados financeiros"
  
  rm_rh:
    name: "rm_rh"
    type: "rm-api" 
    base_url: "${RM_RH_BASE_URL}"
    timeout: "${RM_API_TIMEOUT}"
    description: "API do RM para dados de RH"

# Datasources SQL (se necessário)
datasources:
  # Exemplo para PostgreSQL:
  # producao:
  #   uri: postgresql+psycopg2://usuario:senha@servidor:5432/banco
  
  # Exemplo para MySQL:
  # mysql_db:
  #   uri: mysql+pymysql://usuario:senha@servidor:3306/banco

# Métricas das APIs do RM
metrics:
  # --- RM FINANCEIRO ---
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

  # --- RM RH ---
  rm_total_funcionarios:
    title: "Total de Funcionários (RM)"
    source: rm_rh
    type: single
    desc: "Número total de funcionários via API do RM"
    api_query: "/funcionarios/count"

  rm_funcionarios_por_departamento:
    title: "Funcionários por Departamento (RM)"
    source: rm_rh
    type: pie
    desc: "Distribuição de funcionários por departamento via API do RM"
    api_query: "/funcionarios/por-departamento"
"""



if __name__ == "__main__":
    app.run(debug=True)

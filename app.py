# app.py
from __future__ import annotations

import os, time, json, yaml
from dataclasses import dataclass
from typing import Any, Dict, Optional, List

import requests
from flask import Flask, jsonify, request, Response, render_template_string
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

APP_TITLE = "Análise de Dados Sebrae-RR"
DEFAULT_CONFIG_PATH = os.environ.get("HUBCOUNT_CONFIG", "hubcount_config.yml")

app = Flask(__name__)

# ========================= Modelos =========================
@dataclass
class DataSource:
    name: str
    uri: str
    type: str = "db"                        # "db" (default) ou "http"
    headers: Optional[Dict[str, str]] = None
    auth: Optional[Dict[str, Any]] = None   # {token_url, client_id, client_secret, grant_type}

@dataclass
class Metric:
    key: str
    title: str
    source: str
    sql: Optional[str]             # para DB (SQL) ou JSON ({"path": "..."}) para HTTP
    mtype: str                     # single | bar | line | pie | table
    value_col: Optional[str] = None
    label_col: Optional[str] = None
    desc: Optional[str] = None
    http: Optional[Dict[str, Any]] = None   # (opcional) sobrescritas por métrica

class Config:
    def __init__(self, datasources: Dict[str, DataSource], metrics: Dict[str, Metric]):
        self.datasources = datasources
        self.metrics = metrics

    @staticmethod
    def from_yaml(path: str) -> "Config":
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(DEFAULT_YAML_EXAMPLE.strip() + "\n")
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        dss: Dict[str, DataSource] = {}
        for name, d in (raw.get("datasources") or {}).items():
            dss[name] = DataSource(
                name=name,
                uri=d["uri"],
                type=d.get("type", "db"),
                headers=d.get("headers"),
                auth=d.get("auth"),
            )

        mets: Dict[str, Metric] = {}
        for key, m in (raw.get("metrics") or {}).items():
            mets[key] = Metric(
                key=key,
                title=m.get("title", key),
                source=m["source"],
                sql=m.get("sql"),
                mtype=m.get("type", "single"),
                value_col=m.get("value_col", "value"),
                label_col=m.get("label_col", "label"),
                desc=m.get("desc"),
                http=m.get("http"),
            )
        return Config(datasources=dss, metrics=mets)

# ========================= Utils =========================
_engine_cache: Dict[str, Engine] = {}
def get_engine(uri: str) -> Engine:
    eng = _engine_cache.get(uri)
    if eng is None:
        eng = create_engine(uri, pool_pre_ping=True)
        _engine_cache[uri] = eng
    return eng

# cache simples de tokens por datasource
_token_cache: Dict[str, Dict[str, Any]] = {}  # { ds_name: {"token": str, "exp": epoch_seconds} }

def _get_bearer_for_ds(ds: DataSource) -> Optional[str]:
    """Obtém (e cacheia) um token bearer via client_credentials, se ds.auth existir."""
    if not ds.auth:
        return None

    cached = _token_cache.get(ds.name)
    now = time.time()
    if cached and cached.get("exp", 0) - 30 > now:
        return cached["token"]

    auth = ds.auth
    data = {
        "grant_type": auth.get("grant_type", "client_credentials"),
        "client_id": auth["client_id"],
        "client_secret": auth["client_secret"],
    }
    resp = requests.post(auth["token_url"], data=data, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    token = payload.get("access_token")
    ttl = int(payload.get("expires_in", 1800))
    _token_cache[ds.name] = {"token": token, "exp": now + ttl}
    return token

def _jget(data: Any, path: Optional[str]):
    """
    Extrai de 'data' um caminho simples "a.b.c".
    Suporta lista com '[]' no fim do segmento: ex. "items[].value".
    """
    if not path:
        return data
    parts = path.split(".")
    cur = data
    i = 0
    while i < len(parts):
        seg = parts[i]
        is_list = seg.endswith("[]")
        key = seg[:-2] if is_list else seg

        if isinstance(cur, dict):
            cur = cur.get(key)
        else:
            return None

        if is_list:
            rest = ".".join(parts[i+1:]) or None
            if not isinstance(cur, list):
                return []
            return [_jget(item, rest) for item in cur]
        i += 1
    return cur

def _parse_sql_json(sql_field: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Se a métrica para HTTP usa `sql: | {"path": "..."}` devolve dict, senão None.
    """
    if not sql_field:
        return None
    s = sql_field.strip()
    if s.startswith("{") and s.endswith("}"):
        try:
            return json.loads(s)
        except Exception:
            return None
    return None

# ========================= Execução de métricas =========================
def run_metric(conf: Config, metric_key: str) -> Dict[str, Any]:
    if metric_key not in conf.metrics:
        raise KeyError(f"Métrica '{metric_key}' não encontrada.")
    m = conf.metrics[metric_key]
    ds = conf.datasources.get(m.source)
    if not ds:
        raise KeyError(f"DataSource '{m.source}' não encontrado para a métrica '{metric_key}'.")

    # ---------- Datasource HTTP ----------
    if ds.type == "http" or ds.uri.startswith("http"):
        t0 = time.time()

        # Monta URL final
        base_url = ds.uri.rstrip("/")
        # Se a métrica quiser sobrepor URL/params/headers:
        http_cfg = m.http or {}
        rel_url = (http_cfg.get("url") or "").strip("/")
        url = f"{base_url}/{rel_url}" if rel_url else base_url

        # Headers
        headers = {}
        if ds.headers:
            headers.update(ds.headers)
        # OAuth2 client_credentials
        bearer = _get_bearer_for_ds(ds)
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        # Headers na métrica (sobrescrevem)
        if http_cfg.get("headers"):
            headers.update(http_cfg["headers"])

        method = (http_cfg.get("method") or "GET").upper()
        params = http_cfg.get("params") or {}
        body = http_cfg.get("json") or None

        resp = requests.request(method, url, params=params, json=body, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        elapsed_ms = int((time.time() - t0) * 1000)

        # O campo sql pode conter {"path":"..."} para single,
        # ou http.rows_path para tabelas/gráficos.
        sql_json = _parse_sql_json(m.sql)
        rows_path = (http_cfg.get("rows_path") or (sql_json or {}).get("rows_path"))
        value_path = (http_cfg.get("value_path") or (sql_json or {}).get("path"))
        label_path = (http_cfg.get("label_path") or (sql_json or {}).get("label_path"))

        if m.mtype == "single":
            val = _jget(data, value_path)
            if isinstance(val, list) and len(val) == 1:
                val = val[0]
            payload = {"type": "single", "value": val, "elapsed_ms": elapsed_ms}

        elif m.mtype in ("bar", "line", "pie"):
            rows = _jget(data, rows_path)
            if not isinstance(rows, list):
                rows = []
            lab = m.label_col or "label"
            val = m.value_col or "value"
            # se quiser pegar label/value por caminhos separados:
            if label_path or value_path:
                labels = _jget(data, label_path) or []
                values = _jget(data, value_path) or []
            else:
                labels = [str(r.get(lab)) for r in rows]
                values = [float(r.get(val) or 0) for r in rows]
            payload = {"type": m.mtype, "labels": labels, "values": values, "elapsed_ms": elapsed_ms}

        elif m.mtype == "table":
            rows = _jget(data, rows_path)
            if not isinstance(rows, list):
                rows = []
            payload = {"type": "table", "rows": rows, "elapsed_ms": elapsed_ms}

        else:
            raise ValueError(f"Tipo de métrica HTTP não suportado: {m.mtype}")

        return {"key": m.key, "title": m.title, "desc": m.desc, "source": m.source, "data": payload}

    # ---------- Datasource DB (SQLAlchemy) ----------
    eng = get_engine(ds.uri)
    t0 = time.time()
    with eng.connect() as conn:
        result = conn.execute(text(m.sql or ""))
        rows = [dict(r._mapping) for r in result]
    elapsed_ms = int((time.time() - t0) * 1000)

    if m.mtype == "single":
        col = m.value_col or "value"
        value = rows[0][col] if rows else None
        payload = {"type": "single", "value": value, "elapsed_ms": elapsed_ms}
    elif m.mtype in ("bar", "line", "pie"):
        v = m.value_col or "value"; l = m.label_col or "label"
        labels = [str(r[l]) for r in rows]
        values = [float(r[v]) if r.get(v) is not None else 0 for r in rows]
        payload = {"type": m.mtype, "labels": labels, "values": values, "elapsed_ms": elapsed_ms}
    elif m.mtype == "table":
        payload = {"type": "table", "rows": rows, "elapsed_ms": elapsed_ms}
    else:
        raise ValueError(f"Tipo de métrica não suportado: {m.mtype}")

    return {"key": m.key, "title": m.title, "desc": m.desc, "source": m.source, "data": payload}

# ========================= Config global =========================
config: Config = Config.from_yaml(DEFAULT_CONFIG_PATH)

# ========================= APIs =========================
@app.get("/api/health")
def api_health() -> Response:
    return jsonify({"ok": True, "app": APP_TITLE})

@app.get("/api/datasources")
def api_datasources() -> Response:
    return jsonify({"datasources": list(config.datasources.keys())})

@app.get("/api/metrics")
def api_metrics() -> Response:
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
    config = Config.from_yaml(DEFAULT_CONFIG_PATH)
    # opcional: limpar cache de tokens quando recarregar
    _token_cache.clear()
    return jsonify({"ok": True, "metrics": list(config.metrics.keys()), "datasources": list(config.datasources.keys())})

# ========================= UI =========================
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
    <div class="footer mt-5">Feito com Flask + SQLAlchemy + Chart.js • Edite <code>hubcount_config.yml</code>.</div>
  </div>

  <script>
  const el = (s,r=document)=>r.querySelector(s);

  async function fetchJSON(url, opts={}){
    const r = await fetch(url, opts);
    if(!r.ok) throw new Error(await r.text());
    return r.json();
  }
  function showLoader(show){ el('#loader').hidden = !show }

  function singleCard(m){
    const c = document.createElement('div');
    c.className='col-12 col-sm-6 col-lg-4 col-xxl-3 mb-4';
    c.innerHTML=`<div class="card h-100 shadow-sm"><div class="card-body">
      <div class="d-flex align-items-start mb-2">
        <h5 class="card-title me-2">${m.title}</h5>
        <span class="badge bg-secondary">${m.source}</span>
      </div>
      ${m.desc?`<div class="text-muted mb-2">${m.desc}</div>`:''}
      <div class="metric-value">${new Intl.NumberFormat('pt-BR',{maximumFractionDigits:2}).format(m.data.value ?? 0)}</div>
      <div class="text-end text-muted mt-2" style="font-size:.85rem">${m.data.elapsed_ms} ms</div>
    </div></div>`;
    return c;
  }
  function chartCard(m){
    const id='c_'+m.key, c=document.createElement('div'); c.className='col-12 col-md-6 col-xl-4 mb-4';
    c.innerHTML=`<div class="card h-100 shadow-sm"><div class="card-body d-flex flex-column">
      <div class="d-flex align-items-start mb-2">
        <h5 class="card-title me-2">${m.title}</h5>
        <span class="badge bg-secondary">${m.source}</span>
      </div>
      ${m.desc?`<div class="text-muted mb-2">${m.desc}</div>`:''}
      <div class="mt-auto"><canvas id="${id}" height="200"></canvas></div>
      <div class="text-end text-muted mt-2" style="font-size:.85rem">${m.data.elapsed_ms} ms</div>
    </div></div>`;
    setTimeout(()=>{
      new Chart(document.getElementById(id),{
        type: m.data.type==='pie'?'pie':(m.data.type==='line'?'line':'bar'),
        data:{labels:m.data.labels, datasets:[{label:m.title, data:m.data.values}]},
        options:{responsive:true, plugins:{legend:{display:m.data.type==='pie'}}, scales:(m.data.type==='pie')?{}:{y:{beginAtZero:true}}}
      });
    },0);
    return c;
  }
  function tableCard(m){
    const rows=m.data.rows||[], keys=rows.length?Object.keys(rows[0]):[];
    const c=document.createElement('div'); c.className='col-12 mb-4';
    c.innerHTML=`<div class="card h-100 shadow-sm"><div class="card-body">
      <div class="d-flex align-items-start mb-2">
        <h5 class="card-title me-2">${m.title}</h5>
        <span class="badge bg-secondary">${m.source}</span>
      </div>
      <div class="table-responsive"><table class="table table-striped table-bordered">
        <thead><tr>${keys.map(k=>`<th>${k}</th>`).join('')}</tr></thead>
        <tbody>${rows.map(r=>`<tr>${keys.map(k=>`<td>${r[k]??''}</td>`).join('')}</tr>`).join('')}</tbody>
      </table></div>
      <div class="text-end text-muted mt-2" style="font-size:.85rem">${m.data.elapsed_ms} ms</div>
    </div></div>`;
    return c;
  }

  async function loadDatasources(){
    const data = await fetchJSON('/api/datasources');
    const sel = el('#ds-select'); sel.innerHTML = '<option value="">Todos os bancos</option>';
    (data.datasources||[]).forEach(ds=>{
      const o=document.createElement('option'); o.value=ds; o.textContent=ds; sel.appendChild(o);
    });
  }
  async function loadMetrics(source=""){
    showLoader(true); el('#cards').innerHTML=''; el('#errors').innerHTML='';
    try{
      const qs = source?`?source=${encodeURIComponent(source)}`:'';
      const data = await fetchJSON('/api/metrics'+qs);
      if(Object.keys(data.errors||{}).length){
        const list = Object.entries(data.errors).map(([k,v])=>`<li><code>${k}</code>: ${v}</li>`).join('');
        el('#errors').innerHTML = `<div class="alert alert-warning">Erros:<ul class="m-0 ps-4">${list}</ul></div>`;
      }
      for(const m of (data.metrics||[])){
        const t=m.data?.type;
        el('#cards').appendChild(t==='single'?singleCard(m):t==='table'?tableCard(m):chartCard(m));
      }
      if((data.metrics||[]).length===0){
        el('#errors').innerHTML = `<div class="alert alert-info">Nenhuma métrica para ${source||'todas as fontes'}.</div>`;
      }
    }finally{ showLoader(false); }
  }
  el('#ds-select').addEventListener('change', ()=>loadMetrics(el('#ds-select').value));
  el('#btn-refresh').addEventListener('click', async ()=>{
    await fetchJSON('/api/refresh-config',{method:'POST'}); await loadDatasources(); loadMetrics(el('#ds-select').value);
  });
  loadDatasources().then(()=>loadMetrics(""));
  </script>
</body>
</html>
"""

@app.get("/")
def home():
    return render_template_string(HTML, title=APP_TITLE)

# YAML exemplo (apenas para primeira execução, se arquivo não existir)
DEFAULT_YAML_EXAMPLE = r"""
datasources:
  helpdesk:
    uri: sqlite:///helpdesk_demo.db
  finance:
    uri: sqlite:///finance_demo.db
  # hotel:
  #   uri: postgresql+psycopg2://usuario:senha@127.0.0.1:5432/hotel
  # api_financeiro:
  #   type: http
  #   uri: https://api.exemplo.com/v1/financeiro
  #   auth:
  #     token_url: https://auth.exemplo.com/realms/xxx/protocol/openid-connect/token
  #     client_id: hubcount
  #     client_secret: SEU_CLIENT_SECRET
  #     grant_type: client_credentials

metrics:
  tickets_open:
    title: "Chamados abertos"
    source: helpdesk
    type: single
    sql: |
      SELECT COUNT(*) AS value FROM tickets WHERE status IN ('open','pending');
"""

if __name__ == "__main__":
    app.run(debug=True)

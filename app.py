# app.py
"""
HubCount BI Studio – Flask (single-file)
- UI com cards + Chart.js (single/line/bar/pie/table)
- YAML de configuração (datasources + métricas)
- Filtro por banco: /api/metrics?source=<nome_do_banco>
- Seed de bancos SQLite de demonstração
"""

from __future__ import annotations
import os, time, yaml
from dataclasses import dataclass
from typing import Any, Dict, Optional, List
from flask import Flask, jsonify, request, Response, render_template_string
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

APP_TITLE = "Análise de Dados Sebrae-RR"
DEFAULT_CONFIG_PATH = os.environ.get("HUBCOUNT_CONFIG", "hubcount_config.yml")

app = Flask(__name__)

# ------------------------- Tipos/Config -------------------------
@dataclass
class DataSource:
    name: str
    uri: str

@dataclass
class Metric:
    key: str
    title: str
    source: str
    sql: str
    mtype: str               # single | bar | line | pie | table
    value_col: Optional[str] = None
    label_col: Optional[str] = None
    desc: Optional[str] = None

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
            dss[name] = DataSource(name=name, uri=d["uri"])
        mets: Dict[str, Metric] = {}
        for key, m in (raw.get("metrics") or {}).items():
            mets[key] = Metric(
                key=key,
                title=m.get("title", key),
                source=m["source"],
                sql=m["sql"],
                mtype=m.get("type", "single"),
                value_col=m.get("value_col", "value"),
                label_col=m.get("label_col", "label"),
                desc=m.get("desc"),
            )
        return Config(datasources=dss, metrics=mets)

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

    eng = get_engine(ds.uri)
    t0 = time.time()
    with eng.connect() as conn:
        result = conn.execute(text(m.sql))
        rows = [dict(r._mapping) for r in result]
    elapsed_ms = int((time.time() - t0) * 1000)

    if m.mtype == "single":
        val_col = m.value_col or "value"
        value = rows[0][val_col] if rows else None
        payload = {"type": "single", "value": value, "elapsed_ms": elapsed_ms}
    elif m.mtype in ("bar", "line", "pie"):
        val_col = m.value_col or "value"
        lab_col = m.label_col or "label"
        labels = [str(r[lab_col]) for r in rows]
        values = [float(r[val_col]) if r.get(val_col) is not None else 0 for r in rows]
        payload = {"type": m.mtype, "labels": labels, "values": values, "elapsed_ms": elapsed_ms}
    elif m.mtype == "table":
        payload = {"type": "table", "rows": rows, "elapsed_ms": elapsed_ms}
    else:
        raise ValueError(f"Tipo de métrica não suportado: {m.mtype}")

    return {"key": m.key, "title": m.title, "desc": m.desc, "source": m.source, "data": payload}

# ------------------------- Carrega config -------------------------
config: Config = Config.from_yaml(DEFAULT_CONFIG_PATH)

# ------------------------- APIs -------------------------
@app.get("/api/health")
def api_health() -> Response:
    return jsonify({"ok": True, "app": APP_TITLE})

@app.get("/api/datasources")
def api_datasources() -> Response:
    return jsonify({"datasources": list(config.datasources.keys())})

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
        return jsonify({"ok": True, "metrics": list(config.metrics.keys()), "datasources": list(config.datasources.keys())})
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
    <div class="footer mt-5">Feito com Flask + SQLAlchemy + Chart.js • Edite <code>hubcount_config.yml</code> para adicionar bancos e métricas.</div>
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
# hubcount_config.yml (exemplo)
datasources:
  helpdesk:
    uri: sqlite:///helpdesk_demo.db
  finance:
    uri: sqlite:///finance_demo.db
  # Exemplo Postgres (ajuste credenciais/host):
  # hotel:
  #   uri: postgresql+psycopg2://usuario:senha@127.0.0.1:5432/hotel

metrics:
  # --- HELP DESK (demo) ---
  tickets_open:
    title: "Chamados abertos"
    source: helpdesk
    type: single
    sql: |
      SELECT COUNT(*) AS value
      FROM tickets
      WHERE status IN ('open','pending');

  # --- FINANCEIRO (demo) ---
  revenue_paid_month:
    title: "Receita paga por mês"
    source: finance
    type: line
    label_col: label
    value_col: value
    sql: |
      SELECT strftime('%Y-%m', paid_at) AS label, SUM(amount) AS value
      FROM invoices
      WHERE status = 'paid'
      GROUP BY 1
      ORDER BY 1;
"""

# ------------------------- Seed demo (SQLite) -------------------------
@app.post("/api/seed-demo")
def seed_demo():
    """Cria/zera bancos demo SQLite (helpdesk_demo.db e finance_demo.db)."""
    import sqlite3
    # Helpdesk
    hd = sqlite3.connect("helpdesk_demo.db")
    hd.executescript("""
      CREATE TABLE IF NOT EXISTS tickets(
        id INTEGER PRIMARY KEY,
        subject TEXT, status TEXT, agent TEXT, created_at TEXT
      );
      DELETE FROM tickets;
      INSERT INTO tickets(subject,status,agent,created_at) VALUES
        ('Erro no login','open','Alice','2025-09-01'),
        ('Falha no boleto','pending','Bob','2025-09-02'),
        ('Dúvida de uso','closed','Alice','2025-09-03'),
        ('Integração API','open','Carol','2025-09-04'),
        ('Bug UI','open','Bob','2025-09-05'),
        ('Lentidão','pending','Alice','2025-09-06');
    """)
    hd.commit(); hd.close()

    # Finance
    fn = sqlite3.connect("finance_demo.db")
    fn.executescript("""
      CREATE TABLE IF NOT EXISTS invoices(
        id INTEGER PRIMARY KEY,
        client_name TEXT, amount REAL, status TEXT, paid_at TEXT
      );
      DELETE FROM invoices;
      INSERT INTO invoices(client_name,amount,status,paid_at) VALUES
        ('ACME', 1200.00, 'paid',   '2025-06-10'),
        ('ACME',  850.00, 'paid',   '2025-07-01'),
        ('Globex', 300.00, 'unpaid','2025-07-15'),
        ('Inova',  990.00, 'paid',   '2025-08-02'),
        ('Inova', 1300.00, 'paid',   '2025-09-05'),
        ('SoluTI', 450.00, 'paid',   '2025-09-20');
    """)
    fn.commit(); fn.close()
    return jsonify({"ok": True, "msg": "Bancos demo criados/atualizados."})

if __name__ == "__main__":
    app.run(debug=True)

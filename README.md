# HubCount BI Studio - Flask

Mini plataforma BI estilo HubCount, feita em Flask + Chart.js.

## Estrutura

- `app.py` - aplicação principal Flask (contém rotas, API e frontend)
- `hubcount_config.yml` - configuração de bancos e métricas
- `requirements.txt` - dependências Python
- `templates/` - (vazio, caso queira customizar HTML)
- `static/` - (vazio, para CSS/JS próprios)

## Como rodar

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
flask --app app.py run --debug
```

Abra http://127.0.0.1:5000

import os
import json
import requests
from fastapi import FastAPI, Form, Query, Header
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from dotenv import load_dotenv

# Carrega variáveis do arquivo .env (local).
# No Render, ele usa as variáveis de ambiente configuradas no painel.
load_dotenv()

app = FastAPI()

BIN_ID = os.getenv("JSONBIN_BIN_ID")
MASTER_KEY = os.getenv("JSONBIN_MASTER_KEY")
REPAIR_TOKEN = os.getenv("REPAIR_TOKEN")  # <- token de proteção da rota /repair

if not BIN_ID or not MASTER_KEY:
    raise RuntimeError(
        "Defina JSONBIN_BIN_ID e JSONBIN_MASTER_KEY no arquivo .env "
        "ou nas variáveis de ambiente da hospedagem."
    )

# JSONBin v3:
# - Leitura recomendada: /latest
# - Update: PUT no endpoint do bin (sem /latest)
JSONBIN_URL = f"https://api.jsonbin.io/v3/b/{BIN_ID}"
JSONBIN_READ_URL = f"https://api.jsonbin.io/v3/b/{BIN_ID}/latest"


def unwrap_record(data):
    """
    Descasca "record.record.record..." até chegar no dicionário real de clientes.
    Ex.: {"record": {"record": {"cliente1": {...}}}} -> {"cliente1": {...}}
    """
    while isinstance(data, dict) and set(data.keys()) == {"record"}:
        data = data["record"]
    return data


def get_bin():
    """Lê o JSON atual do JSONBin e devolve SOMENTE o dicionário de licenças."""
    r = requests.get(
        JSONBIN_READ_URL,
        headers={"X-Master-Key": MASTER_KEY},
        timeout=15,
    )
    r.raise_for_status()
    root = r.json()

    data = root.get("record", {})
    data = unwrap_record(data)

    if not isinstance(data, dict):
        data = {}

    return data


def save_bin(data: dict):
    """
    Salva o dicionário de licenças de volta no JSONBin.
    IMPORTANTE: no JSONBin v3, o PUT deve receber o JSON puro,
    e não {"record": ...}.
    """
    if not isinstance(data, dict):
        data = {}

    r = requests.put(
        JSONBIN_URL,
        headers={
            "X-Master-Key": MASTER_KEY,
            "Content-Type": "application/json",
        },
        json=data,  # ✅ JSON puro
        timeout=15,
    )
    r.raise_for_status()


@app.get("/", response_class=HTMLResponse)
def home():
    licencas = get_bin()

    rows = ""
    for cliente, info in licencas.items():
        # proteção extra caso algum item não seja dict
        if not isinstance(info, dict):
            continue

        expira = info.get("expira", "")
        hwid = info.get("hwid", "")
        ativo = info.get("ativo", True)
        status = "Ativo" if ativo else "Inativo"

        rows += f"""
        <tr>
          <td>{cliente}</td>
          <td>{expira}</td>
          <td>{hwid}</td>
          <td>{status}</td>
          <td>
            <form method="post" action="/editar" style="display:inline">
              <input type="hidden" name="cliente" value="{cliente}">
              <input type="date" name="expira" value="{expira}">
              <select name="ativo">
                <option value="true" {"selected" if ativo else ""}>Ativo</option>
                <option value="false" {"selected" if not ativo else ""}>Inativo</option>
              </select>
              <button type="submit">Salvar</button>
            </form>
          </td>
        </tr>
        """

    html = f"""
    <html>
    <head>
      <meta charset="utf-8">
      <title>Painel de Licenças</title>
      <style>
        body {{
          font-family: Arial, sans-serif;
          padding: 20px;
        }}
        table {{
          border-collapse: collapse;
          margin-top: 20px;
          min-width: 650px;
        }}
        th, td {{
          border: 1px solid #ccc;
          padding: 6px 10px;
          text-align: left;
        }}
        th {{
          background: #eee;
        }}
        h1, h2 {{ margin-bottom: 10px; }}
        form {{ margin: 0; }}
        .hint {{
          font-size: 12px;
          color: #666;
          margin-top: 8px;
        }}
      </style>
    </head>
    <body>
      <h1>Painel de Licenças</h1>

      <h2>Criar nova licença</h2>
      <form method="post" action="/criar">
        Cliente:
        <input name="cliente" required>
        Expira:
        <input type="date" name="expira" required>
        <button type="submit">Criar / Atualizar</button>
      </form>

      <div class="hint">
        Dica: a rota <b>/repair</b> limpa o JSONBin (precisa de token).
      </div>

      <h2>Licenças cadastradas</h2>
      <table>
        <tr>
          <th>Cliente</th>
          <th>Expira</th>
          <th>HWID</th>
          <th>Status</th>
          <th>Ações</th>
        </tr>
        {rows}
      </table>
    </body>
    </html>
    """
    return html


@app.post("/criar")
def criar(
    cliente: str = Form(...),
    expira: str = Form(...),
):
    data = get_bin()

    cliente = cliente.strip()

    # Se já existir, atualiza expiração e reativa
    if cliente in data and isinstance(data.get(cliente), dict):
        data[cliente]["expira"] = expira
        data[cliente]["ativo"] = True
        # mantém hwid se existir
        data[cliente].setdefault("hwid", "")
    else:
        data[cliente] = {
            "expira": expira,
            "hwid": "",
            "ativo": True,
        }

    save_bin(data)
    return RedirectResponse(url="/", status_code=302)


@app.post("/editar")
def editar(
    cliente: str = Form(...),
    expira: str = Form(...),
    ativo: str = Form(...),
):
    data = get_bin()
    cliente = cliente.strip()

    if cliente not in data or not isinstance(data.get(cliente), dict):
        return RedirectResponse(url="/", status_code=302)

    data[cliente]["expira"] = expira
    data[cliente]["ativo"] = (ativo == "true")
    data[cliente].setdefault("hwid", "")

    save_bin(data)
    return RedirectResponse(url="/", status_code=302)


# ===========================
#  ROTA DE REPARO DO JSONBIN
# ===========================
@app.get("/repair")
def repair(
    token: str = Query(default="", description="Token de reparo"),
    x_repair_token: str = Header(default="", alias="X-Repair-Token"),
):
    """
    Limpa a estrutura do bin caso ele tenha virado record.record.record...
    Protegido por token via:
      - query param ?token=...
      - OU header X-Repair-Token: ...
    """
    if not REPAIR_TOKEN:
        return JSONResponse(
            {"ok": False, "error": "REPAIR_TOKEN não configurado no ambiente."},
            status_code=403,
        )

    provided = token or x_repair_token
    if provided != REPAIR_TOKEN:
        return JSONResponse(
            {"ok": False, "error": "Token inválido."},
            status_code=403,
        )

    # lê, desembrulha automaticamente (get_bin já faz isso),
    # e salva “flat” (save_bin salva sem wrapper)
    data = get_bin()
    save_bin(data)

    return {"ok": True, "clientes": len(data), "mensagem": "Bin reparado e normalizado com sucesso."}

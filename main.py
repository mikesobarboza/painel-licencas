import os
import json
import requests
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from dotenv import load_dotenv

# Carrega variáveis do arquivo .env (local).
# No Render, ele usa as variáveis de ambiente configuradas no painel.
load_dotenv()

app = FastAPI()

BIN_ID = os.getenv("JSONBIN_BIN_ID")
MASTER_KEY = os.getenv("JSONBIN_MASTER_KEY")

if not BIN_ID or not MASTER_KEY:
    raise RuntimeError(
        "Defina JSONBIN_BIN_ID e JSONBIN_MASTER_KEY no arquivo .env "
        "ou nas variáveis de ambiente da hospedagem."
    )

JSONBIN_URL = f"https://api.jsonbin.io/v3/b/{BIN_ID}"


def get_bin():
    """Lê o JSON atual do JSONBin e devolve o dicionário de licenças."""
    r = requests.get(JSONBIN_URL, headers={"X-Master-Key": MASTER_KEY})
    r.raise_for_status()
    root = r.json()

    # Pegamos o "record" externo
    data = root.get("record", {})
    if not isinstance(data, dict):
        data = {}

    # Se dentro dele existir outro "record" que também é um dict,
    # e esse "record interno" parece ser a tabela de clientes,
    # usamos ele como base.
    if "record" in data and isinstance(data["record"], dict):
        inner = data["record"]
        if all(isinstance(v, dict) for v in inner.values()):
            data = inner

    return data


def save_bin(data: dict):
    """Salva o dicionário de licenças de volta no JSONBin, mantendo o mesmo formato."""
    # Envolve o dicionário em um único "record"
    wrapper = {"record": data}
    r = requests.put(
        JSONBIN_URL,
        headers={
            "X-Master-Key": MASTER_KEY,
            "Content-Type": "application/json",
        },
        data=json.dumps(wrapper),
    )
    r.raise_for_status()


@app.get("/", response_class=HTMLResponse)
def home():
    licencas = get_bin()

    rows = ""
    for cliente, info in licencas.items():
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

    # Se já existir, atualiza expiração e reativa
    if cliente in data:
        data[cliente]["expira"] = expira
        data[cliente]["ativo"] = True
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
    if cliente not in data:
        return RedirectResponse(url="/", status_code=302)

    data[cliente]["expira"] = expira
    data[cliente]["ativo"] = (ativo == "true")
    save_bin(data)
    return RedirectResponse(url="/", status_code=302)

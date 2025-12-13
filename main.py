import os
import requests
from fastapi import FastAPI, Form, Query, Header
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

BIN_ID = os.getenv("JSONBIN_BIN_ID")
MASTER_KEY = os.getenv("JSONBIN_MASTER_KEY")
REPAIR_TOKEN = os.getenv("REPAIR_TOKEN")

if not BIN_ID or not MASTER_KEY:
    raise RuntimeError(
        "Defina JSONBIN_BIN_ID e JSONBIN_MASTER_KEY no .env "
        "ou nas variáveis de ambiente do Render."
    )

JSONBIN_URL = f"https://api.jsonbin.io/v3/b/{BIN_ID}"
JSONBIN_READ_URL = f"https://api.jsonbin.io/v3/b/{BIN_ID}/latest"


def normalize_licenses(obj):
    """
    Normaliza qualquer bagunça do tipo:
    - record.record.record...
    - metadata em qualquer nível
    - mistura de {"record": {...}, "clienteX": {...}} etc.

    Resultado final: dict plano {cliente: {expira, hwid, ativo}}
    """
    if not isinstance(obj, dict):
        return {}

    result = {}

    rec = obj.get("record")
    if isinstance(rec, dict):
        result.update(normalize_licenses(rec))

    for k, v in obj.items():
        if k in ("record", "metadata"):
            continue

        # caso seja cliente real
        if isinstance(v, dict) and any(key in v for key in ("expira", "hwid", "ativo")):
            result[k] = v
            continue

        # caso seja wrapper/bagunça
        if isinstance(v, dict) and ("record" in v or "metadata" in v):
            extracted = normalize_licenses(v)
            if extracted:
                result.update(extracted)

    cleaned = {}
    for cliente, info in result.items():
        if isinstance(info, dict):
            cleaned[cliente] = {
                "expira": info.get("expira", ""),
                "hwid": info.get("hwid", ""),
                "ativo": info.get("ativo", True),
            }

    return cleaned


def get_bin():
    r = requests.get(
        JSONBIN_READ_URL,
        headers={"X-Master-Key": MASTER_KEY},
        timeout=20,
    )
    r.raise_for_status()
    root = r.json()

    data = root.get("record", {})
    return normalize_licenses(data)


def save_bin(data: dict):
    # JSONBin v3: PUT recebe o JSON puro (sem wrapper {"record": ...})
    if not isinstance(data, dict):
        data = {}

    r = requests.put(
        JSONBIN_URL,
        headers={
            "X-Master-Key": MASTER_KEY,
            "Content-Type": "application/json",
        },
        json=data,
        timeout=20,
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
            <form method="post" action="/editar" style="display:inline; margin-right:6px;">
              <input type="hidden" name="cliente" value="{cliente}">
              <input type="date" name="expira" value="{expira}">
              <select name="ativo">
                <option value="true" {"selected" if ativo else ""}>Ativo</option>
                <option value="false" {"selected" if not ativo else ""}>Inativo</option>
              </select>
              <button type="submit">Salvar</button>
            </form>

            <form method="post" action="/limpar_hwid" style="display:inline; margin-right:6px;">
              <input type="hidden" name="cliente" value="{cliente}">
              <button type="submit" title="Zera o HWID desse cliente">Limpar HWID</button>
            </form>

            <form method="post" action="/excluir" style="display:inline;"
                  onsubmit="return confirm('Excluir o cliente: {cliente}? Essa ação não tem Ctrl+Z 😅');">
              <input type="hidden" name="cliente" value="{cliente}">
              <button type="submit" style="background:#b00020; color:white; border:none; padding:6px 10px; cursor:pointer;">
                Excluir
              </button>
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
          min-width: 780px;
        }}
        th, td {{
          border: 1px solid #ccc;
          padding: 6px 10px;
          text-align: left;
          vertical-align: top;
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
        button {{
          padding: 6px 10px;
        }}
        input[type="date"] {{
          padding: 4px 6px;
        }}
        select {{
          padding: 4px 6px;
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
        Dica: rode <b>/repair</b> uma vez pra normalizar o JSONBin.
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
def criar(cliente: str = Form(...), expira: str = Form(...)):
    data = get_bin()
    cliente = cliente.strip()

    if cliente in data:
        data[cliente]["expira"] = expira
        data[cliente]["ativo"] = True
        data[cliente].setdefault("hwid", "")
    else:
        data[cliente] = {"expira": expira, "hwid": "", "ativo": True}

    save_bin(data)
    return RedirectResponse(url="/", status_code=302)


@app.post("/editar")
def editar(cliente: str = Form(...), expira: str = Form(...), ativo: str = Form(...)):
    data = get_bin()
    cliente = cliente.strip()

    if cliente not in data:
        return RedirectResponse(url="/", status_code=302)

    data[cliente]["expira"] = expira
    data[cliente]["ativo"] = (ativo == "true")
    data[cliente].setdefault("hwid", "")

    save_bin(data)
    return RedirectResponse(url="/", status_code=302)


@app.post("/limpar_hwid")
def limpar_hwid(cliente: str = Form(...)):
    data = get_bin()
    cliente = cliente.strip()

    if cliente in data:
        data[cliente]["hwid"] = ""
        save_bin(data)

    return RedirectResponse(url="/", status_code=302)


@app.post("/excluir")
def excluir(cliente: str = Form(...)):
    data = get_bin()
    cliente = cliente.strip()

    if cliente in data:
        del data[cliente]
        save_bin(data)

    return RedirectResponse(url="/", status_code=302)


@app.get("/repair")
def repair(
    token: str = Query(default="", description="Token de reparo"),
    x_repair_token: str = Header(default="", alias="X-Repair-Token"),
):
    """
    Normaliza o bin e salva no formato correto (plano).
    Proteção por token via:
      - /repair?token=...
      - Header X-Repair-Token: ...
    """
    if not REPAIR_TOKEN:
        return JSONResponse(
            {"ok": False, "error": "REPAIR_TOKEN não configurado no ambiente."},
            status_code=403,
        )

    provided = token or x_repair_token
    if provided != REPAIR_TOKEN:
        return JSONResponse({"ok": False, "error": "Token inválido."}, status_code=403)

    data = get_bin()
    save_bin(data)

    return {"ok": True, "clientes": len(data), "mensagem": "Bin normalizado e salvo (sem record/metadata)."}

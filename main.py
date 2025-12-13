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
    - presença de metadata em qualquer nível
    - mistura de {"record": {...}, "clienteX": {...}} (seu caso do cliente002)

    Resultado final: dict plano {cliente: {expira, hwid, ativo}}
    """
    if not isinstance(obj, dict):
        return {}

    result = {}

    # 1) Se existe "record" e é dict, normaliza ele e mescla no resultado
    rec = obj.get("record")
    if isinstance(rec, dict):
        result.update(normalize_licenses(rec))

    # 2) Mescla chaves do nível atual, ignorando wrappers
    for k, v in obj.items():
        if k in ("record", "metadata"):
            continue

        # Se por acaso aparecer outro wrapper no meio, normaliza
        if isinstance(v, dict) and ("record" in v or "metadata" in v):
            # cuidado: só trata como wrapper se ele tiver cara de wrapper,
            # mas aqui a gente pode ser pragmático e normalizar mesmo assim.
            # Se v for um cliente real {expira, hwid, ativo}, normalize_licenses(v) daria {}
            # então a gente testa o formato de cliente antes.
            if any(key in v for key in ("expira", "hwid", "ativo")):
                result[k] = v
            else:
                # tenta extrair algo útil
                extracted = normalize_licenses(v)
                if extracted:
                    # se extraiu clientes, mescla
                    result.update(extracted)
                else:
                    # se não extraiu, ignora
                    pass
        else:
            # Mantém o valor bruto (normalmente é dict de cliente)
            result[k] = v

    # 3) Por garantia: só mantém entradas que parecem cliente (dict)
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
    # JSONBin v3: PUT recebe o JSON PURO (sem wrapper {"record": ...})
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

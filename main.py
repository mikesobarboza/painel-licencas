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

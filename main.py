import os
import html
import secrets
from datetime import datetime
from string import Template
from typing import Any, Dict, List

import requests
from fastapi import Cookie, Form, Header, Query, Response
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

BIN_ID = os.getenv("JSONBIN_BIN_ID")
MASTER_KEY = os.getenv("JSONBIN_MASTER_KEY")
REPAIR_TOKEN = os.getenv("REPAIR_TOKEN")
PAINEL_PASSWORD = os.getenv("PAINEL_PASSWORD", "admin123")

SITES_BIN_ID = os.getenv("SITES_BIN_ID")
SITES_MASTER_KEY = os.getenv("SITES_MASTER_KEY")
SITES_CONFIGURED = bool(SITES_BIN_ID and SITES_MASTER_KEY)

if not BIN_ID or not MASTER_KEY:
    raise RuntimeError("Configure JSONBIN_BIN_ID e JSONBIN_MASTER_KEY no ambiente.")

active_sessions: Dict[str, bool] = {}

SERVICOS: Dict[str, Dict[str, str]] = {
    "Principal": {
        "nome": "Principal",
        "bin_id": BIN_ID,
        "master_key": MASTER_KEY,
        "icone": "[P]",
    }
}


def check_auth(session_token: str | None) -> bool:
    return bool(session_token and session_token in active_sessions)


def normalize_licenses(obj: Any) -> Dict[str, Dict[str, Any]]:
    if not isinstance(obj, dict):
        return {}

    result: Dict[str, Dict[str, Any]] = {}

    rec = obj.get("record")
    if isinstance(rec, dict):
        result.update(normalize_licenses(rec))

    licenses = obj.get("licenses")
    if isinstance(licenses, dict):
        result.update(normalize_licenses(licenses))

    for key, value in obj.items():
        if key in ("record", "metadata", "licenses"):
            continue
        if isinstance(value, dict) and any(k in value for k in ("key", "status", "expiresAt", "periodDays")):
            result[key] = value
            continue
        if isinstance(value, dict) and ("record" in value or "metadata" in value or "licenses" in value):
            nested = normalize_licenses(value)
            if nested:
                result.update(nested)

    cleaned: Dict[str, Dict[str, Any]] = {}
    for license_key, info in result.items():
        if isinstance(info, dict):
            cleaned[license_key] = {
                "key": info.get("key", license_key),
                "status": info.get("status", "active"),
                "hardwareId": info.get("hardwareId"),
                "expiresAt": info.get("expiresAt", ""),
                "periodDays": info.get("periodDays", 30),
                "allowedProviders": info.get("allowedProviders", []),
                "createdAt": info.get("createdAt", ""),
            }

    return cleaned


def get_bin(servico_config: Dict[str, str] | None = None) -> Dict[str, Dict[str, Any]]:
    if servico_config is None:
        servico_config = SERVICOS["Principal"]

    read_url = f"https://api.jsonbin.io/v3/b/{servico_config['bin_id']}/latest"
    resp = requests.get(read_url, headers={"X-Master-Key": servico_config["master_key"]}, timeout=20)
    resp.raise_for_status()
    root = resp.json()
    return normalize_licenses(root.get("record", {}))


def save_bin(data: Dict[str, Dict[str, Any]], servico_config: Dict[str, str] | None = None) -> None:
    if servico_config is None:
        servico_config = SERVICOS["Principal"]
    if not isinstance(data, dict):
        data = {}

    update_url = f"https://api.jsonbin.io/v3/b/{servico_config['bin_id']}"
    resp = requests.put(
        update_url,
        headers={"X-Master-Key": servico_config["master_key"], "Content-Type": "application/json"},
        json=data,
        timeout=20,
    )
    resp.raise_for_status()


def get_sites() -> Dict[str, Dict[str, Any]]:
    if not SITES_CONFIGURED:
        return {}
    read_url = f"https://api.jsonbin.io/v3/b/{SITES_BIN_ID}/latest"
    try:
        resp = requests.get(read_url, headers={"X-Master-Key": SITES_MASTER_KEY}, timeout=20)
        resp.raise_for_status()
        data = resp.json().get("record", {})
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_sites(data: Dict[str, Dict[str, Any]]) -> bool:
    if not SITES_CONFIGURED:
        return False
    if not isinstance(data, dict):
        data = {}
    update_url = f"https://api.jsonbin.io/v3/b/{SITES_BIN_ID}"
    try:
        resp = requests.put(
            update_url,
            headers={"X-Master-Key": SITES_MASTER_KEY, "Content-Type": "application/json"},
            json=data,
            timeout=20,
        )
        resp.raise_for_status()
        return True
    except Exception:
        return False


def generate_license_key(expires_at: str) -> str:
    try:
        dt = datetime.fromisoformat(expires_at)
    except Exception:
        dt = datetime.utcnow()
    formatted = dt.strftime("%Y%m%d%H%M")
    return f"MK-30D-{formatted}-{secrets.token_hex(6).upper()}"


def escape_attr(value: str) -> str:
    return html.escape(value, quote=True)


@app.get("/", response_class=HTMLResponse)
def home(session_token: str = Cookie(None)):
    if not check_auth(session_token):
        return RedirectResponse(url="/login", status_code=302)
    servico = "Principal"

    servico_config = SERVICOS[servico]
    licencas = get_bin(servico_config)

    rows: List[str] = []
    for license_key, info in licencas.items():
                key = info.get("key", license_key)
                status = info.get("status", "active")
                hardware_id = info.get("hardwareId")
                expires_at = info.get("expiresAt", "")
                period_days = info.get("periodDays", 30)
                allowed_providers = info.get("allowedProviders", [])
                created_at = info.get("createdAt", "")

                status_label = "Ativo" if status == "active" else "Inativo"
                status_class = "badge-ok" if status == "active" else "badge-bad"
                hardware_display = hardware_id or "Nao vinculado"
                providers_display = ", ".join(allowed_providers) if allowed_providers else "Nenhum"

                rows.append(
                        f"""
                        <tr class="license-row">
                            <td class="td-key">
                                <div class="key">{escape_attr(key)}</div>
                                <div class="meta">Criada em: {escape_attr(created_at)}</div>
                            </td>
                            <td class="td-expira">
                                <div class="strong">{escape_attr(expires_at)}</div>
                                <div class="meta">Periodo: {period_days} dias</div>
                            </td>
                            <td class="td-hwid">{escape_attr(hardware_display)}</td>
                            <td class="td-providers">{escape_attr(providers_display)}</td>
                            <td class="td-status"><span class="badge {status_class}">{status_label}</span></td>
                            <td class="td-actions">
                                <div class="action-buttons">
                                    <button type="button" class="btn btn-renew" data-license="{escape_attr(license_key)}" data-expires="{escape_attr(expires_at)}" onclick="openRenew(this)">Renovar</button>
                                    <button type="button" class="btn btn-edit" data-license="{escape_attr(license_key)}" data-providers="{escape_attr(providers_display)}" onclick="editProviders(this)">Editar</button>
                                    <form method="post" action="/limpar_hwid" class="inline-form" onsubmit="return confirm('Limpar HWID da licenca: {escape_attr(key)}?');">
                                        <input type="hidden" name="license_key" value="{escape_attr(license_key)}">
                                        <button type="submit" class="btn btn-clear">Limpar HWID</button>
                                    </form>
                                    <form method="post" action="/excluir" class="inline-form" onsubmit="return confirm('Excluir a licenca: {escape_attr(key)}? Esta acao nao pode ser desfeita.');">
                                        <input type="hidden" name="license_key" value="{escape_attr(license_key)}">
                                        <button type="submit" class="btn btn-delete">Excluir</button>
                                    </form>
                                </div>
                            </td>
                        </tr>
                        """
                )

    rows_html = "\n".join(rows) if rows else "<tr><td colspan=\"6\" style=\"text-align:center; color:#666;\">Nenhuma licenca cadastrada</td></tr>"

    bin_id_short = servico_config["bin_id"][:12] + "..."
    total_licencas = len(licencas)

    page_template = """
    <html>
    <head>
      <meta charset=\"utf-8\">\n      <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n      <title>Painel de Licencas - $servico</title>
      <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: Arial, sans-serif; background: #f4f5fb; padding: 24px; }
        .container { max-width: 1400px; margin: 0 auto; background: #fff; padding: 32px; border-radius: 12px; box-shadow: 0 12px 40px rgba(0,0,0,0.12); }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
        h1 { font-size: 26px; color: #1f2933; }
        .logout { background: #c0392b; color: #fff; text-decoration: none; padding: 10px 16px; border-radius: 6px; font-weight: 700; }
        .tabs { display: flex; gap: 8px; margin: 18px 0; flex-wrap: wrap; }
        .service-tab { padding: 10px 16px; border-radius: 6px; border: 1px solid #e1e7ef; text-decoration: none; color: #1f2933; background: #fff; font-weight: 600; }
        .service-tab.active { background: #2f6fed; color: #fff; border-color: #2f6fed; }
        .service-info { display: flex; gap: 16px; flex-wrap: wrap; margin: 16px 0; color: #1f2933; }
        .service-info .pill { background: #eef2f7; padding: 8px 12px; border-radius: 8px; border: 1px solid #e1e7ef; }
        .create-section { background: #f7f9fc; border: 1px solid #e1e7ef; border-radius: 10px; padding: 20px; margin: 18px 0; }
        .form-grid { display: grid; grid-template-columns: 1fr 1fr auto; gap: 14px; align-items: end; }
        .form-group { display: flex; flex-direction: column; gap: 6px; }
        .form-group label { font-weight: 600; color: #374151; }
        .form-group input { padding: 12px; border: 1px solid #cbd5e1; border-radius: 8px; font-size: 14px; }
        .license-preview { padding: 12px; border: 1px dashed #cbd5e1; border-radius: 8px; min-height: 42px; background: #fff; font-family: monospace; color: #111827; }
        .btn-create { padding: 12px 22px; background: #2f6fed; color: #fff; border: none; border-radius: 8px; font-weight: 700; cursor: pointer; }
        .table-container { margin-top: 16px; overflow-x: auto; }
        table { width: 100%; border-collapse: collapse; }
        th { text-align: left; padding: 12px; background: #1f2933; color: #fff; font-size: 13px; }
        td { padding: 12px; border-bottom: 1px solid #e5e7eb; vertical-align: top; }
        .license-row:hover { background: #f9fafb; }
        .key { font-weight: 700; color: #111827; }
        .meta { color: #6b7280; font-size: 12px; margin-top: 4px; }
        .td-hwid { font-family: monospace; color: #374151; }
        .td-providers { color: #111827; }
        .action-buttons { display: flex; gap: 8px; flex-wrap: wrap; }
        .inline-form { display: inline; }
        .btn { padding: 8px 12px; border: none; border-radius: 6px; font-weight: 700; cursor: pointer; }
        .btn-edit { background: #2563eb; color: #fff; }
        .btn-renew { background: #10b981; color: #fff; }
        .btn-clear { background: #f59e0b; color: #1f2933; }
        .btn-delete { background: #ef4444; color: #fff; }
        .badge { padding: 6px 10px; border-radius: 12px; font-weight: 700; font-size: 12px; }
        .badge-ok { background: #dcfce7; color: #166534; }
        .badge-bad { background: #fee2e2; color: #991b1b; }
        .hint { margin-top: 10px; background: #fff7ed; border: 1px solid #fed7aa; padding: 10px 12px; border-radius: 8px; color: #92400e; }
        @media (max-width: 960px) { .form-grid { grid-template-columns: 1fr; } .action-buttons { flex-direction: column; } }
        .modal { display: none; position: fixed; z-index: 1000; inset: 0; background: rgba(0,0,0,0.55); }
        .modal-content { background: #fff; margin: 8% auto; padding: 22px; border-radius: 10px; max-width: 520px; box-shadow: 0 16px 40px rgba(0,0,0,0.25); }
        .modal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
        .close-modal { cursor: pointer; font-size: 22px; color: #6b7280; }
        .modal-body textarea { width: 100%; min-height: 120px; padding: 10px; border: 1px solid #cbd5e1; border-radius: 8px; font-family: monospace; }
        .modal-body input { width: 100%; padding: 10px; border: 1px solid #cbd5e1; border-radius: 8px; }
        .modal-footer { display: flex; gap: 10px; justify-content: flex-end; margin-top: 12px; }
        .btn-modal-cancel { background: #6b7280; color: #fff; padding: 10px 16px; border: none; border-radius: 8px; font-weight: 700; cursor: pointer; }
        .btn-modal-save { background: #16a34a; color: #fff; padding: 10px 16px; border: none; border-radius: 8px; font-weight: 700; cursor: pointer; }
      </style>
      <script>
        function randomHex(len) {
          const chars = '0123456789ABCDEF';
          let out = '';
          for (let i = 0; i < len; i++) { out += chars[Math.floor(Math.random() * 16)]; }
          return out;
        }

        function generateLicenseFromDate() {
          const expiresInput = document.getElementById('expiresInput');
          const licenseInput = document.getElementById('licenseInput');
          const preview = document.getElementById('licensePreview');
          if (!expiresInput || !licenseInput || !preview) return;
          if (!expiresInput.value) {
            licenseInput.value = '';
            preview.textContent = 'Selecione a data para gerar';
            return;
          }
          const dt = new Date(expiresInput.value);
          if (Number.isNaN(dt.getTime())) {
            preview.textContent = 'Data invalida';
            return;
          }
          const pad = (n) => String(n).padStart(2, '0');
          const formatted = dt.getFullYear().toString() + pad(dt.getMonth() + 1) + pad(dt.getDate()) + pad(dt.getHours()) + pad(dt.getMinutes());
          const key = 'MK-30D-' + formatted + '-' + randomHex(12);
          licenseInput.value = key;
          preview.textContent = key;
        }

        function editProviders(button) {
          const license = button.getAttribute('data-license');
          const providers = button.getAttribute('data-providers') || '';
          document.getElementById('editModal').style.display = 'block';
          document.getElementById('editLicenseKey').value = license;
          document.getElementById('editProviders').value = providers === 'Nenhum' ? '' : providers;
          document.getElementById('modalTitle').textContent = 'Editar provedores: ' + license;
        }

        function openRenew(button) {
          const license = button.getAttribute('data-license');
          const expires = button.getAttribute('data-expires') || '';
          document.getElementById('renewModal').style.display = 'block';
          document.getElementById('renewLicenseKey').value = license;
          document.getElementById('renewTitle').textContent = 'Renovar licenca: ' + license;
          const expiresInput = document.getElementById('renewExpires');
          if (expiresInput) {
            let value = '';
            if (expires) {
              const parsed = new Date(expires);
              if (!Number.isNaN(parsed.getTime())) {
                const pad = (n) => String(n).padStart(2, '0');
                value = parsed.getFullYear() + '-' + pad(parsed.getMonth() + 1) + '-' + pad(parsed.getDate()) + 'T' + pad(parsed.getHours()) + ':' + pad(parsed.getMinutes());
              }
            }
            expiresInput.value = value;
          }
        }

        function closeModal() { document.getElementById('editModal').style.display = 'none'; }
        function closeRenew() { document.getElementById('renewModal').style.display = 'none'; }
        window.onclick = function(event) {
          const editModalEl = document.getElementById('editModal');
          const renewModalEl = document.getElementById('renewModal');
          if (event.target === editModalEl) { closeModal(); }
          if (event.target === renewModalEl) { closeRenew(); }
        };

        window.addEventListener('DOMContentLoaded', () => {
          const expiresInput = document.getElementById('expiresInput');
          const form = document.getElementById('createForm');
          if (expiresInput) { expiresInput.addEventListener('input', generateLicenseFromDate); expiresInput.addEventListener('change', generateLicenseFromDate); }
          if (form) { form.addEventListener('submit', () => { const licenseInput = document.getElementById('licenseInput'); if (licenseInput && !licenseInput.value) generateLicenseFromDate(); }); }
        });
      </script>
    </head>
    <body>
      <div class="container">
        <div class="header">
          <h1>Painel de Licencas</h1>
          <a href="/logout" class="logout">Sair</a>
        </div>

        <div class="tabs">
          <a href="/" class="service-tab active">Licencas</a>
          <a href="/sites" class="service-tab">Sites</a>
        </div>
        <div class="service-info">
          <div class="pill">Bin ID: $bin_id_short</div>
          <div class="pill">Total de licencas: $total_licencas</div>
        </div>

        <div class="create-section">
          <h2>Criar nova licenca</h2>
          <form id="createForm" method="post" action="/criar">
            <input type="hidden" name="license_key" id="licenseInput">
            <div class="form-grid">
              <div class="form-group">
                <label>Data de expiracao</label>
                <input id="expiresInput" type="datetime-local" name="expires_at" required>
              </div>
              <div class="form-group">
                <label>Licenca gerada</label>
                <div id="licensePreview" class="license-preview">Selecione a data para gerar</div>
              </div>
              <button type="submit" class="btn-create">Criar</button>
            </div>
          </form>
        </div>

        <div class="hint">Dica: use /repair?token=seu_token para normalizar dados do bin.</div>

        <h2 style="margin:18px 0 8px 0;">Licencas cadastradas</h2>
        <div class="table-container">
          <table>
            <thead>
              <tr><th>Licenca</th><th>Expira</th><th>HWID</th><th>Provedores</th><th>Status</th><th>Acoes</th></tr>
            </thead>
            <tbody>$rows_html</tbody>
          </table>
        </div>
      </div>

            <div id="renewModal" class="modal">
                <div class="modal-content">
                    <div class="modal-header">
                        <h3 id="renewTitle">Renovar licenca</h3>
                        <span class="close-modal" onclick="closeRenew()">&#10005;</span>
                    </div>
                    <form method="post" action="/editar">
                        <input type="hidden" id="renewLicenseKey" name="license_key">
                        <div class="modal-body">
                            <label for="renewExpires">Nova data de expiracao</label>
                            <input id="renewExpires" type="datetime-local" name="expires_at" required>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn-modal-cancel" onclick="closeRenew()">Cancelar</button>
                            <button type="submit" class="btn-modal-save">Salvar</button>
                        </div>
                    </form>
                </div>
            </div>

      <div id="editModal" class="modal">
        <div class="modal-content">
          <div class="modal-header">
            <h3 id="modalTitle">Editar provedores</h3>
            <span class="close-modal" onclick="closeModal()">&#10005;</span>
          </div>
          <form method="post" action="/editar_provedores">
            <input type="hidden" id="editLicenseKey" name="license_key">
            <div class="modal-body">
              <label for="editProviders">Provedores permitidos (separe por virgula). Deixe vazio para permitir todos.</label>
              <textarea id="editProviders" name="providers" placeholder="ex: provedor1, provedor2"></textarea>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn-modal-cancel" onclick="closeModal()">Cancelar</button>
              <button type="submit" class="btn-modal-save">Salvar</button>
            </div>
          </form>
        </div>
      </div>
    </body>
    </html>
    """

    page = Template(page_template).substitute(
        servico=escape_attr(servico),
        bin_id_short=escape_attr(bin_id_short),
        total_licencas=total_licencas,
        rows_html=rows_html,
    )

    return HTMLResponse(content=page)


@app.post("/criar")
def criar(
    response: Response,
    session_token: str = Cookie(None),
    expires_at: str = Form(...),
    license_key: str | None = Form(None),
):
    if not check_auth(session_token):
        return RedirectResponse(url="/login", status_code=302)
    servico_config = SERVICOS["Principal"]
    data = get_bin(servico_config)

    license_key = (license_key or "").strip()
    if not license_key:
        license_key = generate_license_key(expires_at)
    while license_key in data:
        license_key = generate_license_key(expires_at)

    if license_key not in data:
        data[license_key] = {
            "key": license_key,
            "status": "active",
            "hardwareId": None,
            "expiresAt": expires_at,
            "periodDays": 30,
            "allowedProviders": [],
            "createdAt": datetime.utcnow().isoformat(),
        }
    else:
        data[license_key]["expiresAt"] = expires_at
        data[license_key]["status"] = "active"

    save_bin(data, servico_config)
    redirect_response = RedirectResponse(url="/", status_code=302)
    redirect_response.set_cookie(key="session_token", value=session_token, httponly=True, max_age=86400)
    return redirect_response


@app.post("/editar")
def editar(
    response: Response,
    session_token: str = Cookie(None),
    license_key: str = Form(...),
    expires_at: str = Form(...),
):
    if not check_auth(session_token):
        return RedirectResponse(url="/login", status_code=302)
    servico_config = SERVICOS["Principal"]
    data = get_bin(servico_config)
    license_key = license_key.strip()

    if license_key in data:
        data[license_key]["expiresAt"] = expires_at
        save_bin(data, servico_config)

    redirect_response = RedirectResponse(url="/", status_code=302)
    redirect_response.set_cookie(key="session_token", value=session_token, httponly=True, max_age=86400)
    return redirect_response


@app.post("/editar_provedores")
def editar_provedores(
    response: Response,
    session_token: str = Cookie(None),
    license_key: str = Form(...),
    providers: str = Form(""),
):
    if not check_auth(session_token):
        return RedirectResponse(url="/login", status_code=302)
    servico_config = SERVICOS["Principal"]
    data = get_bin(servico_config)
    license_key = license_key.strip()

    if license_key in data:
        providers_list = [p.strip() for p in providers.split(",") if p.strip()]
        data[license_key]["allowedProviders"] = providers_list
        save_bin(data, servico_config)

    redirect_response = RedirectResponse(url="/", status_code=302)
    redirect_response.set_cookie(key="session_token", value=session_token, httponly=True, max_age=86400)
    return redirect_response


@app.post("/limpar_hwid")
def limpar_hwid(
    response: Response,
    session_token: str = Cookie(None),
    license_key: str = Form(...),
):
    if not check_auth(session_token):
        return RedirectResponse(url="/login", status_code=302)
    servico_config = SERVICOS["Principal"]
    data = get_bin(servico_config)
    license_key = license_key.strip()

    if license_key in data:
        data[license_key]["hardwareId"] = None
        save_bin(data, servico_config)

    redirect_response = RedirectResponse(url="/", status_code=302)
    redirect_response.set_cookie(key="session_token", value=session_token, httponly=True, max_age=86400)
    return redirect_response


@app.post("/excluir")
def excluir(
    response: Response,
    session_token: str = Cookie(None),
    license_key: str = Form(...),
):
    if not check_auth(session_token):
        return RedirectResponse(url="/login", status_code=302)
    servico_config = SERVICOS["Principal"]
    data = get_bin(servico_config)
    license_key = license_key.strip()

    if license_key in data:
        del data[license_key]
        save_bin(data, servico_config)

    redirect_response = RedirectResponse(url="/", status_code=302)
    redirect_response.set_cookie(key="session_token", value=session_token, httponly=True, max_age=86400)
    return redirect_response


@app.get("/login", response_class=HTMLResponse)
def login_page():
    html_page = """
    <html><head><meta charset=\"utf-8\"><title>Login</title>
    <style>
      body { font-family: Arial, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; background: #1f2933; }
      .box { background: #fff; padding: 28px; border-radius: 10px; width: 320px; box-shadow: 0 10px 30px rgba(0,0,0,0.2); }
      h2 { margin: 0 0 12px 0; color: #111827; }
      input { width: 100%; padding: 12px; border: 1px solid #cbd5e1; border-radius: 8px; margin-top: 8px; }
      button { width: 100%; padding: 12px; margin-top: 12px; background: #2563eb; color: #fff; border: none; border-radius: 8px; font-weight: 700; cursor: pointer; }
    </style></head>
    <body><div class=\"box\"><h2>Login</h2><form method=\"post\" action=\"/login\"><input type=\"password\" name=\"password\" placeholder=\"Senha\" required><button type=\"submit\">Entrar</button></form></div></body></html>
    """
    return HTMLResponse(content=html_page)


@app.post("/login")
def do_login(response: Response, password: str = Form(...)):
    if password == PAINEL_PASSWORD:
        session_token = secrets.token_urlsafe(32)
        active_sessions[session_token] = True
        resp = RedirectResponse(url="/", status_code=302)
        resp.set_cookie(key="session_token", value=session_token, httponly=True, max_age=86400)
        return resp
    return HTMLResponse("Senha incorreta", status_code=401)


@app.get("/logout")
def logout(response: Response, session_token: str = Cookie(None)):
    if session_token in active_sessions:
        del active_sessions[session_token]
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie(key="session_token")
    return resp


@app.get("/repair")
def repair(
    token: str = Query(default="", description="Token de reparo"),
    x_repair_token: str = Header(default="", alias="X-Repair-Token"),
):
    if not REPAIR_TOKEN:
        return JSONResponse({"ok": False, "error": "REPAIR_TOKEN nao configurado."}, status_code=403)

    provided = token or x_repair_token
    if provided != REPAIR_TOKEN:
        return JSONResponse({"ok": False, "error": "Token invalido."}, status_code=403)

    servico_config = SERVICOS["Principal"]
    data = get_bin(servico_config)
    save_bin(data, servico_config)
    return {"ok": True, "servico": "Principal", "clientes": len(data)}


@app.get("/api/sites")
def api_get_sites():
    if not SITES_CONFIGURED:
        return {"sites": []}

    sites_data = get_sites()
    active_sites = []
    for site_name, site_info in sites_data.items():
        if isinstance(site_info, dict) and site_info.get("ativo", True):
            active_sites.append(
                {
                    "nome": site_name,
                    "dominio": site_info.get("dominio", ""),
                    "url": site_info.get("url", ""),
                    "seletores": {
                        "valueInput": site_info.get("valueInput", ""),
                        "generateButton": site_info.get("generateButton", ""),
                        "pixCode": site_info.get("pixCode", ""),
                        "copyButton": site_info.get("copyButton", ""),
                        "closeModalButton": site_info.get("closeModalButton", ""),
                        "openFormButton": site_info.get("openFormButton", ""),
                    },
                }
            )
    return {"sites": active_sites}


@app.get("/sites", response_class=HTMLResponse)
def sites_panel(session_token: str = Cookie(None)):
    if not check_auth(session_token):
        return RedirectResponse(url="/login", status_code=302)
    if not SITES_CONFIGURED:
        return HTMLResponse("Sites nao configurados.", status_code=503)

    sites_data = get_sites()
    rows = []
    for site_name, site_info in sites_data.items():
        if not isinstance(site_info, dict):
            continue
        dominio = site_info.get("dominio", "")
        url = site_info.get("url", "")
        ativo = site_info.get("ativo", True)
        status = "Ativo" if ativo else "Inativo"
        rows.append(
            f"<tr><td>{escape_attr(site_name)}</td><td>{escape_attr(dominio)}</td><td>{escape_attr(url)}</td><td>{status}</td>"
            f"<td><form method=\"post\" action=\"/sites/delete\" onsubmit=\"return confirm('Excluir {escape_attr(site_name)}?');\">"
            f"<input type=\"hidden\" name=\"site_name\" value=\"{escape_attr(site_name)}\"><button type=\"submit\">Deletar</button></form></td></tr>"
        )

    rows_html = "".join(rows) if rows else "<tr><td colspan=\"5\">Nenhum site cadastrado</td></tr>"

    page_template = """
    <html><head><meta charset=\"utf-8\"><title>Sites</title>
    <style>
      body { font-family: Arial, sans-serif; background: #f4f5fb; padding: 24px; }
      .container { max-width: 1100px; margin: 0 auto; background: #fff; padding: 28px; border-radius: 12px; box-shadow: 0 12px 40px rgba(0,0,0,0.12); }
      .tabs { display: flex; gap: 8px; margin-bottom: 18px; }
      .tab { padding: 10px 16px; border-radius: 6px; border: 1px solid #e1e7ef; text-decoration: none; color: #1f2933; background: #fff; font-weight: 700; }
      .tab.active { background: #2f6fed; color: #fff; border-color: #2f6fed; }
      .form-grid { display: grid; grid-template-columns: 1fr 1fr auto; gap: 12px; align-items: end; }
      .form-group { display: flex; flex-direction: column; gap: 6px; }
      .form-group input { padding: 10px; border: 1px solid #cbd5e1; border-radius: 8px; }
      .btn { padding: 10px 16px; background: #16a34a; color: #fff; border: none; border-radius: 8px; font-weight: 700; cursor: pointer; }
      table { width: 100%; border-collapse: collapse; margin-top: 18px; }
      th, td { padding: 10px; border-bottom: 1px solid #e5e7eb; text-align: left; }
    </style></head>
    <body>
      <div class=\"container\">
        <div class=\"tabs\"><a class=\"tab\" href=\"/\">Licencas</a><span class=\"tab active\">Sites</span></div>
        <form method=\"post\" action=\"/sites/add\">\n          <div class=\"form-grid\">\n            <div class=\"form-group\"><label>Nome</label><input name=\"site_name\" required></div>\n            <div class=\"form-group\"><label>Dominio</label><input name=\"dominio\"></div>\n            <button class=\"btn\" type=\"submit\">Adicionar</button>\n          </div>\n          <div class=\"form-group\" style=\"margin-top:12px;\"><label>URL padrao</label><input name=\"url\" required></div>\n          <div class=\"form-grid\" style=\"grid-template-columns: 1fr 1fr; margin-top:12px;\">\n            <div class=\"form-group\"><label>valueInput</label><input name=\"valueInput\"></div>\n            <div class=\"form-group\"><label>generateButton</label><input name=\"generateButton\"></div>\n            <div class=\"form-group\"><label>pixCode</label><input name=\"pixCode\"></div>\n            <div class=\"form-group\"><label>copyButton</label><input name=\"copyButton\"></div>\n            <div class=\"form-group\"><label>closeModalButton</label><input name=\"closeModalButton\"></div>\n            <div class=\"form-group\"><label>openFormButton</label><input name=\"openFormButton\"></div>\n          </div>\n        </form>
        <table><thead><tr><th>Nome</th><th>Dominio</th><th>URL</th><th>Status</th><th>Acoes</th></tr></thead><tbody>$rows_html</tbody></table>
      </div>
    </body></html>
    """

    page = Template(page_template).substitute(rows_html=rows_html)
    return HTMLResponse(content=page)


@app.post("/sites/add")
def add_site(
    session_token: str = Cookie(None),
    site_name: str = Form(...),
    dominio: str = Form(""),
    url: str = Form(...),
    valueInput: str = Form(""),
    generateButton: str = Form(""),
    pixCode: str = Form(""),
    copyButton: str = Form(""),
    closeModalButton: str = Form(""),
    openFormButton: str = Form(""),
):
    if not check_auth(session_token):
        return RedirectResponse(url="/login", status_code=302)
    if not SITES_CONFIGURED:
        return RedirectResponse(url="/sites", status_code=302)

    sites_data = get_sites()
    site_name = site_name.strip()
    sites_data[site_name] = {
        "dominio": dominio.strip(),
        "url": url.strip(),
        "valueInput": valueInput.strip(),
        "generateButton": generateButton.strip(),
        "pixCode": pixCode.strip(),
        "copyButton": copyButton.strip(),
        "closeModalButton": closeModalButton.strip(),
        "openFormButton": openFormButton.strip(),
        "ativo": True,
    }
    save_sites(sites_data)
    return RedirectResponse(url="/sites", status_code=302)


@app.post("/sites/delete")
def delete_site(session_token: str = Cookie(None), site_name: str = Form(...)):
    if not check_auth(session_token):
        return RedirectResponse(url="/login", status_code=302)
    if not SITES_CONFIGURED:
        return RedirectResponse(url="/sites", status_code=302)

    sites_data = get_sites()
    site_name = site_name.strip()
    if site_name in sites_data:
        del sites_data[site_name]
        save_sites(sites_data)
    return RedirectResponse(url="/sites", status_code=302)


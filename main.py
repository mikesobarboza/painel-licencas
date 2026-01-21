import os
import secrets
import requests
from fastapi import FastAPI, Form, Query, Header, Cookie, Response
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

BIN_ID = os.getenv("JSONBIN_BIN_ID")
MASTER_KEY = os.getenv("JSONBIN_MASTER_KEY")
REPAIR_TOKEN = os.getenv("REPAIR_TOKEN")
PAINEL_PASSWORD = os.getenv("PAINEL_PASSWORD", "admin123")  # Senha padrão: admin123

# Carregar configuração de Sites (opcional)
SITES_BIN_ID = os.getenv('SITES_BIN_ID')
SITES_MASTER_KEY = os.getenv('SITES_MASTER_KEY')
SITES_CONFIGURED = SITES_BIN_ID and SITES_MASTER_KEY

if not BIN_ID or not MASTER_KEY:
    raise RuntimeError(
        "Defina JSONBIN_BIN_ID e JSONBIN_MASTER_KEY no .env "
        "ou nas variáveis de ambiente do Render."
    )

# Armazena sessões ativas (em produção, use Redis ou DB)
active_sessions = {}

# Sistema de múltiplos serviços
SERVICOS = {}

# Serviço principal/padrão (compatibilidade com setup atual)
SERVICOS["Principal"] = {
    "nome": "Principal",
    "bin_id": BIN_ID,
    "master_key": MASTER_KEY,
    "icone": "🔹"
}

# Carregar serviços adicionais do .env
# Formato: NOMEDOSERVICO_BIN_ID e NOMEDOSERVICO_MASTER_KEY
for key in os.environ:
    if key.endswith("_BIN_ID") and key not in ("JSONBIN_BIN_ID", "SITES_BIN_ID"):
        service_prefix = key[:-7]  # Remove "_BIN_ID"
        master_key_var = f"{service_prefix}_MASTER_KEY"
        master_key = os.getenv(master_key_var)
        
        if master_key:
            # Formatar nome do serviço (STREAMING_PRO -> Streaming Pro)
            service_name = service_prefix.replace("_", " ").title()
            
            # Definir ícone baseado no nome
            icone = "📦"
            if "STREAM" in service_prefix.upper():
                icone = "📺"
            elif "CHAT" in service_prefix.upper() or "BOT" in service_prefix.upper():
                icone = "🤖"
            elif "GAME" in service_prefix.upper():
                icone = "🎮"
            elif "VPN" in service_prefix.upper():
                icone = "🔐"
            
            SERVICOS[service_name] = {
                "nome": service_name,
                "bin_id": os.getenv(key),
                "master_key": master_key,
                "icone": icone
            }

JSONBIN_URL = f"https://api.jsonbin.io/v3/b/{BIN_ID}"
JSONBIN_READ_URL = f"https://api.jsonbin.io/v3/b/{BIN_ID}/latest"


def check_auth(session_token: str = None) -> bool:
    """Verifica se o token de sessão é válido."""
    if not session_token:
        return False
    return session_token in active_sessions


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


def get_bin(servico_config: dict = None):
    """Obtém dados do bin. Se servico_config não fornecido, usa o principal."""
    if servico_config is None:
        servico_config = SERVICOS["Principal"]
    
    bin_id = servico_config["bin_id"]
    master_key = servico_config["master_key"]
    
    read_url = f"https://api.jsonbin.io/v3/b/{bin_id}/latest"
    
    r = requests.get(
        read_url,
        headers={"X-Master-Key": master_key},
        timeout=20,
    )
    r.raise_for_status()
    root = r.json()

    data = root.get("record", {})
    return normalize_licenses(data)


def save_bin(data: dict, servico_config: dict = None):
    """Salva dados no bin. Se servico_config não fornecido, usa o principal."""
    if servico_config is None:
        servico_config = SERVICOS["Principal"]
    
    # JSONBin v3: PUT recebe o JSON puro (sem wrapper {"record": ...})
    if not isinstance(data, dict):
        data = {}
    
    bin_id = servico_config["bin_id"]
    master_key = servico_config["master_key"]
    
    update_url = f"https://api.jsonbin.io/v3/b/{bin_id}"

    r = requests.put(
        update_url,
        headers={
            "X-Master-Key": master_key,
            "Content-Type": "application/json",
        },
        json=data,
        timeout=20,
    )
    r.raise_for_status()


# ============================================
# FUNÇÕES DE SITES
# ============================================

def get_sites():
    """Obtém dados de sites do JSONBin."""
    if not SITES_CONFIGURED:
        return {}
    
    read_url = f"https://api.jsonbin.io/v3/b/{SITES_BIN_ID}/latest"
    
    try:
        r = requests.get(
            read_url,
            headers={"X-Master-Key": SITES_MASTER_KEY},
            timeout=20,
        )
        r.raise_for_status()
        root = r.json()
        data = root.get("record", {})
        
        # Normalizar dados
        if not isinstance(data, dict):
            return {}
        return data
    except Exception as e:
        print(f"Erro ao buscar sites: {e}")
        return {}


def save_sites(data: dict):
    """Salva dados de sites no JSONBin."""
    if not SITES_CONFIGURED:
        return False
    
    if not isinstance(data, dict):
        data = {}
    
    try:
        update_url = f"https://api.jsonbin.io/v3/b/{SITES_BIN_ID}"
        
        r = requests.put(
            update_url,
            headers={
                "X-Master-Key": SITES_MASTER_KEY,
                "Content-Type": "application/json",
            },
            json=data,
            timeout=20,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"Erro ao salvar sites: {e}")
        return False

@app.get("/", response_class=HTMLResponse)
def home(session_token: str = Cookie(None), servico: str = Query("Principal")):
    # Verifica autenticação
    if not check_auth(session_token):
        return RedirectResponse(url="/login", status_code=302)
    
    # Verificar se o serviço existe
    if servico not in SERVICOS:
        servico = "Principal"
    
    servico_config = SERVICOS[servico]
    licencas = get_bin(servico_config)

    rows = ""
    for cliente, info in licencas.items():
        expira = info.get("expira", "")
        hwid = info.get("hwid", "")
        ativo = info.get("ativo", True)
        status_class = "status-active" if ativo else "status-inactive"
        status_icon = "✅" if ativo else "❌"
        status_text = "Ativo" if ativo else "Inativo"
        hwid_display = hwid if hwid else '<span style="color: #999; font-style: italic;">Não vinculado</span>'

        rows += f"""
        <tr class="license-row">
          <td class="td-cliente">
            <div class="cliente-name">👤 {cliente}</div>
          </td>
          <td class="td-expira">
            <input type="date" class="edit-date" data-cliente="{cliente}" value="{expira}" onchange="enableSaveButton('{cliente}')">
          </td>
          <td class="td-hwid" title="{hwid if hwid else 'HWID não vinculado'}">
            <div class="hwid-display">{hwid_display}</div>
          </td>
          <td class="td-status">
            <select class="edit-status" data-cliente="{cliente}" onchange="enableSaveButton('{cliente}')">
              <option value="true" {"selected" if ativo else ""}>✅ Ativo</option>
              <option value="false" {"selected" if not ativo else ""}>❌ Inativo</option>
            </select>
          </td>
          <td class="td-actions">
            <div class="action-buttons">
              <form method="post" action="/editar" class="inline-form" id="form-{cliente}">
                <input type="hidden" name="cliente" value="{cliente}">
                <input type="hidden" name="servico" value="{servico}">
                <input type="hidden" name="expira" class="hidden-expira-{cliente}" value="{expira}">
                <input type="hidden" name="ativo" class="hidden-ativo-{cliente}" value="{"true" if ativo else "false"}">
                <button type="submit" class="btn btn-save" id="save-{cliente}" disabled title="Salvar alterações">
                  💾 Salvar
                </button>
              </form>
              
              <form method="post" action="/limpar_hwid" class="inline-form">
                <input type="hidden" name="cliente" value="{cliente}">
                <input type="hidden" name="servico" value="{servico}">
                <button type="submit" class="btn btn-clear" title="Limpar HWID vinculado">
                  🔓 Limpar HWID
                </button>
              </form>
              
              <form method="post" action="/excluir" class="inline-form"
                    onsubmit="return confirm('⚠️ Excluir o cliente: {cliente}?\\n\\nEssa ação é PERMANENTE e não pode ser desfeita!');">
                <input type="hidden" name="cliente" value="{cliente}">
                <input type="hidden" name="servico" value="{servico}">
                <button type="submit" class="btn btn-delete">
                  🗑️ Excluir
                </button>
              </form>
            </div>
          </td>
        </tr>
        """

    # Criar abas de serviços
    servicos_tabs = ""
    for nome, config in SERVICOS.items():
        is_active = "active" if nome == servico else ""
        servicos_tabs += f"""
        <a href="/?servico={nome}" class="service-tab {is_active}">
          {config['icone']} {nome}
        </a>
        """
    
    # Informações do serviço atual
    bin_id_short = servico_config['bin_id'][:12] + "..."
    total_licencas = len(licencas)
    
    html = f"""
    <html>
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>🔐 Painel de Licenças - {servico}</title>
      <style>
        * {{
          margin: 0;
          padding: 0;
          box-sizing: border-box;
        }}
        
        body {{
          font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
          background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
          padding: 20px;
          min-height: 100vh;
        }}
        
        .container {{
          max-width: 1600px;
          margin: 0 auto;
          background: white;
          padding: 40px;
          border-radius: 15px;
          box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }}
        
        .header {{
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 30px;
          padding-bottom: 20px;
          border-bottom: 3px solid #667eea;
        }}
        
        h1 {{
          margin: 0;
          color: #333;
          font-size: 32px;
          display: flex;
          align-items: center;
          gap: 10px;
        }}
        
        .logout {{
          color: #fff;
          background: #b00020;
          font-weight: bold;
          text-decoration: none;
          padding: 12px 24px;
          border: none;
          border-radius: 8px;
          transition: all 0.3s;
          font-size: 16px;
          box-shadow: 0 4px 6px rgba(176, 0, 32, 0.3);
        }}
        
        .logout:hover {{
          background: #8b0019;
          transform: translateY(-2px);
          box-shadow: 0 6px 12px rgba(176, 0, 32, 0.4);
        }}
        
        .service-selector {{
          display: flex;
          gap: 12px;
          margin: 25px 0;
          flex-wrap: wrap;
          background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
          padding: 20px;
          border-radius: 12px;
          border: 2px solid #dee2e6;
        }}
        
        .service-selector-label {{
          align-self: center;
          font-weight: 600;
          color: #495057;
          margin-right: 10px;
          font-size: 16px;
        }}
        
        .service-tab {{
          padding: 12px 24px;
          background: white;
          border: 2px solid #dee2e6;
          border-radius: 8px;
          text-decoration: none;
          color: #495057;
          font-weight: 600;
          transition: all 0.3s;
          display: inline-block;
          box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        
        .service-tab:hover {{
          border-color: #667eea;
          transform: translateY(-3px);
          box-shadow: 0 6px 12px rgba(102, 126, 234, 0.3);
          color: #667eea;
        }}
        
        .service-tab.active {{
          background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
          color: white;
          border-color: #667eea;
          box-shadow: 0 6px 12px rgba(102, 126, 234, 0.4);
        }}
        
        .service-info {{
          background: linear-gradient(135deg, #e3f2fd 0%, #bbdefb 100%);
          padding: 16px 20px;
          border-radius: 10px;
          margin: 20px 0;
          font-size: 15px;
          color: #0d47a1;
          border-left: 5px solid #1976d2;
          box-shadow: 0 2px 8px rgba(25, 118, 210, 0.2);
          display: flex;
          gap: 20px;
          flex-wrap: wrap;
        }}
        
        .service-info-item {{
          display: flex;
          align-items: center;
          gap: 8px;
        }}
        
        .create-section {{
          background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
          padding: 30px;
          border-radius: 12px;
          margin: 25px 0;
          border: 2px solid #dee2e6;
          box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}
        
        .create-section h2 {{
          margin: 0 0 20px 0;
          color: #333;
          font-size: 24px;
          display: flex;
          align-items: center;
          gap: 10px;
        }}
        
        .form-grid {{
          display: grid;
          grid-template-columns: 1fr 1fr auto;
          gap: 15px;
          align-items: end;
        }}
        
        .form-group {{
          display: flex;
          flex-direction: column;
        }}
        
        .form-group label {{
          font-weight: 600;
          color: #495057;
          margin-bottom: 8px;
          font-size: 14px;
        }}
        
        .form-group input {{
          padding: 12px 16px;
          border: 2px solid #ced4da;
          border-radius: 8px;
          font-size: 15px;
          transition: all 0.3s;
        }}
        
        .form-group input:focus {{
          outline: none;
          border-color: #667eea;
          box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }}
        
        .btn-create {{
          padding: 12px 32px;
          background: linear-gradient(135deg, #28a745 0%, #20c997 100%);
          color: white;
          border: none;
          border-radius: 8px;
          font-size: 16px;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.3s;
          box-shadow: 0 4px 6px rgba(40, 167, 69, 0.3);
        }}
        
        .btn-create:hover {{
          transform: translateY(-2px);
          box-shadow: 0 6px 12px rgba(40, 167, 69, 0.4);
        }}
        
        .table-container {{
          margin-top: 30px;
          overflow-x: auto;
          border-radius: 12px;
          box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}
        
        table {{
          width: 100%;
          border-collapse: separate;
          border-spacing: 0;
          background: white;
        }}
        
        th {{
          background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
          color: white;
          font-weight: 600;
          padding: 16px 12px;
          text-align: left;
          font-size: 14px;
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }}
        
        th:first-child {{
          border-top-left-radius: 12px;
        }}
        
        th:last-child {{
          border-top-right-radius: 12px;
        }}
        
        td {{
          padding: 14px 12px;
          border-bottom: 1px solid #e9ecef;
          font-size: 14px;
        }}
        
        .license-row {{
          transition: all 0.3s;
        }}
        
        .license-row:hover {{
          background: #f8f9fa;
          transform: scale(1.01);
        }}
        
        .cliente-name {{
          font-weight: 600;
          color: #495057;
          font-size: 15px;
        }}
        
        .hwid-display {{
          font-family: 'Courier New', monospace;
          font-size: 13px;
          color: #6c757d;
        }}
        
        .edit-date, .edit-status {{
          padding: 8px 12px;
          border: 2px solid #ced4da;
          border-radius: 6px;
          font-size: 14px;
          transition: all 0.3s;
          width: 100%;
        }}
        
        .edit-date:focus, .edit-status:focus {{
          outline: none;
          border-color: #667eea;
          box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }}
        
        .action-buttons {{
          display: flex;
          gap: 8px;
          flex-wrap: wrap;
        }}
        
        .inline-form {{
          display: inline;
        }}
        
        .btn {{
          padding: 8px 14px;
          border: none;
          border-radius: 6px;
          font-size: 13px;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.3s;
          white-space: nowrap;
        }}
        
        .btn-save {{
          background: linear-gradient(135deg, #007bff 0%, #0056b3 100%);
          color: white;
          box-shadow: 0 2px 4px rgba(0, 123, 255, 0.3);
        }}
        
        .btn-save:hover:not(:disabled) {{
          transform: translateY(-2px);
          box-shadow: 0 4px 8px rgba(0, 123, 255, 0.4);
        }}
        
        .btn-save:disabled {{
          opacity: 0.5;
          cursor: not-allowed;
        }}
        
        .btn-clear {{
          background: linear-gradient(135deg, #ffc107 0%, #ff9800 100%);
          color: #000;
          box-shadow: 0 2px 4px rgba(255, 193, 7, 0.3);
        }}
        
        .btn-clear:hover {{
          transform: translateY(-2px);
          box-shadow: 0 4px 8px rgba(255, 193, 7, 0.4);
        }}
        
        .btn-delete {{
          background: linear-gradient(135deg, #dc3545 0%, #b00020 100%);
          color: white;
          box-shadow: 0 2px 4px rgba(220, 53, 69, 0.3);
        }}
        
        .btn-delete:hover {{
          transform: translateY(-2px);
          box-shadow: 0 4px 8px rgba(220, 53, 69, 0.4);
        }}
        
        .hint {{
          background: #fff3cd;
          color: #856404;
          padding: 12px 16px;
          border-radius: 8px;
          margin: 15px 0;
          border-left: 4px solid #ffc107;
          font-size: 14px;
        }}
        
        .section-title {{
          font-size: 22px;
          font-weight: 600;
          color: #333;
          margin: 30px 0 15px 0;
          display: flex;
          align-items: center;
          gap: 10px;
        }}
        
        @media (max-width: 1200px) {{
          .form-grid {{
            grid-template-columns: 1fr;
          }}
        }}
        
        @media (max-width: 768px) {{
          .container {{
            padding: 20px;
          }}
          
          h1 {{
            font-size: 24px;
          }}
          
          .action-buttons {{
            flex-direction: column;
          }}
        }}
      </style>
      <script>
        function enableSaveButton(cliente) {{
          const saveBtn = document.getElementById('save-' + cliente);
          const dateInput = document.querySelector('.edit-date[data-cliente="' + cliente + '"]');
          const statusSelect = document.querySelector('.edit-status[data-cliente="' + cliente + '"]');
          
          // Atualizar campos hidden
          document.querySelector('.hidden-expira-' + cliente).value = dateInput.value;
          document.querySelector('.hidden-ativo-' + cliente).value = statusSelect.value;
          
          // Habilitar botão
          saveBtn.disabled = false;
          saveBtn.style.opacity = '1';
        }}
      </script>
    </head>
    <body>
      <div class="container">
        <div class="header">
          <h1>🔐 Painel de Licenças</h1>
          <a href="/logout" class="logout">🚪 Sair</a>
        </div>

        <div style="display: flex; gap: 10px; margin: 25px 0; flex-wrap: wrap;">
          <a href="/" style="padding: 12px 24px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: 2px solid #667eea; border-radius: 8px; text-decoration: none; font-weight: 600; cursor: pointer; transition: all 0.3s; display: inline-block;">🔹 Licenças</a>
          <a href="/sites" style="padding: 12px 24px; background: white; border: 2px solid #dee2e6; border-radius: 8px; text-decoration: none; color: #495057; font-weight: 600; cursor: pointer; transition: all 0.3s; display: inline-block;">🌐 Sites</a>
        </div>

        <div class="service-selector">
          <div class="service-selector-label">🎯 Selecionar Serviço:</div>
          {servicos_tabs}
        </div>

        <div class="service-info">
          <div class="service-info-item">
            <strong>📋 Serviço:</strong> {servico_config['icone']} {servico}
          </div>
          <div class="service-info-item">
            <strong>📦 Bin ID:</strong> {bin_id_short}
          </div>
          <div class="service-info-item">
            <strong>📊 Total de Licenças:</strong> {total_licencas}
          </div>
        </div>

        <div class="create-section">
          <h2>➕ Criar Nova Licença</h2>
          <form method="post" action="/criar">
            <input type="hidden" name="servico" value="{servico}">
            <div class="form-grid">
              <div class="form-group">
                <label>👤 Nome do Cliente</label>
                <input name="cliente" required placeholder="Digite o nome do cliente">
              </div>
              <div class="form-group">
                <label>📅 Data de Expiração</label>
                <input type="date" name="expira" required>
              </div>
              <button type="submit" class="btn-create">✨ Criar / Atualizar</button>
            </div>
          </form>
        </div>

        <div class="hint">
          💡 <strong>Dica:</strong> Use <code>/repair?token=seu_token&servico={servico}</code> para normalizar e corrigir dados do bin deste serviço.
        </div>

        <h2 class="section-title">📋 Licenças Cadastradas</h2>
        <div class="table-container">
          <table>
            <thead>
              <tr>
                <th>👤 Cliente</th>
                <th>📅 Data Expiração</th>
                <th>💻 HWID</th>
                <th>⚡ Status</th>
                <th>🔧 Ações</th>
              </tr>
            </thead>
            <tbody>
              {rows}
            </tbody>
          </table>
        </div>
      </div>
    </body>
    </html>
    """
    return html


@app.post("/criar")
def criar(session_token: str = Cookie(None), cliente: str = Form(...), expira: str = Form(...), servico: str = Form("Principal")):
    # Verifica autenticação
    if not check_auth(session_token):
        return RedirectResponse(url="/login", status_code=302)
    
    # Verificar se o serviço existe
    if servico not in SERVICOS:
        servico = "Principal"
    
    servico_config = SERVICOS[servico]
    data = get_bin(servico_config)
    cliente = cliente.strip()

    if cliente in data:
        data[cliente]["expira"] = expira
        data[cliente]["ativo"] = True
        data[cliente].setdefault("hwid", "")
    else:
        data[cliente] = {"expira": expira, "hwid": "", "ativo": True}

    save_bin(data, servico_config)
    return RedirectResponse(url=f"/?servico={servico}", status_code=302)


@app.post("/editar")
def editar(session_token: str = Cookie(None), cliente: str = Form(...), expira: str = Form(...), ativo: str = Form(...), servico: str = Form("Principal")):
    # Verifica autenticação
    if not check_auth(session_token):
        return RedirectResponse(url="/login", status_code=302)
    
    # Verificar se o serviço existe
    if servico not in SERVICOS:
        servico = "Principal"
    
    servico_config = SERVICOS[servico]
    data = get_bin(servico_config)
    cliente = cliente.strip()

    if cliente not in data:
        return RedirectResponse(url=f"/?servico={servico}", status_code=302)

    data[cliente]["expira"] = expira
    data[cliente]["ativo"] = (ativo == "true")
    data[cliente].setdefault("hwid", "")

    save_bin(data, servico_config)
    return RedirectResponse(url=f"/?servico={servico}", status_code=302)


@app.post("/limpar_hwid")
def limpar_hwid(session_token: str = Cookie(None), cliente: str = Form(...), servico: str = Form("Principal")):
    # Verifica autenticação
    if not check_auth(session_token):
        return RedirectResponse(url="/login", status_code=302)
    
    # Verificar se o serviço existe
    if servico not in SERVICOS:
        servico = "Principal"
    
    servico_config = SERVICOS[servico]
    data = get_bin(servico_config)
    cliente = cliente.strip()

    if cliente in data:
        data[cliente]["hwid"] = ""
        save_bin(data, servico_config)

    return RedirectResponse(url=f"/?servico={servico}", status_code=302)


@app.post("/excluir")
def excluir(session_token: str = Cookie(None), cliente: str = Form(...), servico: str = Form("Principal")):
    # Verifica autenticação
    if not check_auth(session_token):
        return RedirectResponse(url="/login", status_code=302)
    
    # Verificar se o serviço existe
    if servico not in SERVICOS:
        servico = "Principal"
    
    servico_config = SERVICOS[servico]
    data = get_bin(servico_config)
    cliente = cliente.strip()

    if cliente in data:
        del data[cliente]
        save_bin(data, servico_config)

    return RedirectResponse(url=f"/?servico={servico}", status_code=302)


@app.get("/login", response_class=HTMLResponse)
def login_page():
    html = """
    <html>
    <head>
      <meta charset="utf-8">
      <title>Login - Painel de Licenças</title>
      <style>
        body {
          font-family: Arial, sans-serif;
          display: flex;
          justify-content: center;
          align-items: center;
          height: 100vh;
          margin: 0;
          background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }
        .login-box {
          background: white;
          padding: 40px;
          border-radius: 10px;
          box-shadow: 0 10px 25px rgba(0,0,0,0.2);
          width: 300px;
        }
        h2 {
          margin-top: 0;
          color: #333;
          text-align: center;
        }
        input {
          width: 100%;
          padding: 12px;
          margin: 10px 0;
          border: 1px solid #ddd;
          border-radius: 5px;
          box-sizing: border-box;
        }
        button {
          width: 100%;
          padding: 12px;
          background: #667eea;
          color: white;
          border: none;
          border-radius: 5px;
          cursor: pointer;
          font-size: 16px;
          margin-top: 10px;
        }
        button:hover {
          background: #5568d3;
        }
      </style>
    </head>
    <body>
      <div class="login-box">
        <h2>🔐 Login</h2>
        <form method="post" action="/login">
          <input type="password" name="password" placeholder="Digite a senha" required autofocus>
          <button type="submit">Entrar</button>
        </form>
      </div>
    </body>
    </html>
    """
    return html


@app.post("/login")
def do_login(response: Response, password: str = Form(...)):
    if password == PAINEL_PASSWORD:
        # Cria token de sessão
        session_token = secrets.token_urlsafe(32)
        active_sessions[session_token] = True
        
        # Define cookie de sessão
        response = RedirectResponse(url="/", status_code=302)
        response.set_cookie(key="session_token", value=session_token, httponly=True, max_age=86400)  # 24h
        return response
    else:
        return HTMLResponse(
            content="""
            <html>
            <head>
              <meta charset="utf-8">
              <meta http-equiv="refresh" content="2;url=/login">
              <style>
                body {
                  font-family: Arial, sans-serif;
                  display: flex;
                  justify-content: center;
                  align-items: center;
                  height: 100vh;
                  margin: 0;
                  background: #f44336;
                  color: white;
                }
              </style>
            </head>
            <body>
              <div style="text-align: center;">
                <h1>❌ Senha incorreta!</h1>
                <p>Redirecionando...</p>
              </div>
            </body>
            </html>
            """,
            status_code=401
        )


@app.get("/logout")
def logout(response: Response, session_token: str = Cookie(None)):
    # Remove sessão
    if session_token in active_sessions:
        del active_sessions[session_token]
    
    # Remove cookie
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(key="session_token")
    return response


@app.get("/repair")
def repair(
    token: str = Query(default="", description="Token de reparo"),
    servico: str = Query(default="Principal", description="Nome do serviço"),
    x_repair_token: str = Header(default="", alias="X-Repair-Token"),
):
    """
    Normaliza o bin e salva no formato correto (plano).
    Proteção por token via:
      - /repair?token=...&servico=...
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

    # Verificar se o serviço existe
    if servico not in SERVICOS:
        return JSONResponse(
            {"ok": False, "error": f"Serviço '{servico}' não encontrado. Serviços disponíveis: {list(SERVICOS.keys())}"},
            status_code=404,
        )
    
    servico_config = SERVICOS[servico]
    data = get_bin(servico_config)
    save_bin(data, servico_config)

    return {
        "ok": True, 
        "servico": servico,
        "clientes": len(data), 
        "mensagem": f"Bin do serviço '{servico}' normalizado e salvo (sem record/metadata)."
    }


@app.get("/api/sites")
def api_get_sites():
    """
    Rota pública para a extensão buscar sites.
    Retorna apenas sites ativos.
    """
    if not SITES_CONFIGURED:
        return {"sites": []}
    
    sites_data = get_sites()
    
    # Filtrar apenas sites ativos
    active_sites = []
    for site_name, site_info in sites_data.items():
        if isinstance(site_info, dict) and site_info.get("ativo", True):
            active_sites.append({
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
                }
            })
    
    return {"sites": active_sites}



@app.get("/sites", response_class=HTMLResponse)
def sites_panel(session_token: str = Cookie(None)):
    """Painel de gerenciamento de sites (requer autenticação)."""
    if not check_auth(session_token):
        return RedirectResponse(url="/login", status_code=302)
    
    if not SITES_CONFIGURED:
        return HTMLResponse(
            content="""
            <html>
            <head>
                <meta charset="utf-8">
                <title>Sites QR Code - Painel de Licenças</title>
                <style>
                    body { font-family: Arial; background: #f5f5f5; padding: 20px; }
                    .container { max-width: 900px; margin: 0 auto; background: white; padding: 40px; border-radius: 10px; box-shadow: 0 0 10px rgba(0,0,0,0.1); }
                    .error { color: #d32f2f; background: #ffebee; padding: 20px; border-radius: 5px; }
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>🌐 Gerenciar Sites</h1>
                    <div class="error">
                        ⚠️ Sites não configurado. Configure SITES_BIN_ID e SITES_MASTER_KEY no Render.
                    </div>
                    <p><a href="/">← Voltar</a></p>
                </div>
            </body>
            </html>
            """,
            status_code=503
        )
    
    sites_data = get_sites()
    
    # Gerar linhas da tabela
    rows = ""
    for site_name, site_info in sites_data.items():
        if not isinstance(site_info, dict):
            continue
        
        dominio = site_info.get("dominio", "")
        url = site_info.get("url", "")
        ativo = site_info.get("ativo", True)
        status_icon = "✅" if ativo else "❌"
        status_text = "Ativo" if ativo else "Inativo"
        
        rows += f"""
        <tr>
            <td>{site_name}</td>
            <td>{dominio}</td>
            <td><code style="background: #f0f0f0; padding: 5px; border-radius: 3px; font-size: 12px;">{url[:40]}...</code></td>
            <td>{status_icon} {status_text}</td>
            <td>
                <form method="post" action="/sites/delete" style="display: inline;" onsubmit="return confirm('Excluir {site_name}?');">
                    <input type="hidden" name="site_name" value="{site_name}">
                    <button type="submit" style="background: #d32f2f; color: white; border: none; padding: 8px 15px; border-radius: 5px; cursor: pointer;">🗑️ Deletar</button>
                </form>
            </td>
        </tr>
        """
    
    html = f"""
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>🌐 Gerenciar Sites - Painel de Licenças</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; min-height: 100vh; }}
            .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 40px; border-radius: 15px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); }}
            
            .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; padding-bottom: 20px; border-bottom: 3px solid #667eea; }}
            h1 {{ margin: 0; color: #333; font-size: 32px; display: flex; align-items: center; gap: 10px; }}
            .logout {{ color: #fff; background: #b00020; font-weight: bold; text-decoration: none; padding: 12px 24px; border: none; border-radius: 8px; transition: all 0.3s; font-size: 16px; box-shadow: 0 4px 6px rgba(176, 0, 32, 0.3); }}
            .logout:hover {{ background: #8b0019; transform: translateY(-2px); }}
            
            .tabs {{ display: flex; gap: 10px; margin-bottom: 30px; }}
            .tab {{ padding: 12px 24px; background: white; border: 2px solid #dee2e6; border-radius: 8px; text-decoration: none; color: #495057; font-weight: 600; cursor: pointer; transition: all 0.3s; }}
            .tab.active {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border-color: #667eea; }}
            .tab:hover {{ border-color: #667eea; color: #667eea; }}
            
            .create-section {{ background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%); padding: 30px; border-radius: 12px; margin: 25px 0; border: 2px solid #dee2e6; }}
            .create-section h2 {{ margin: 0 0 20px 0; color: #333; font-size: 24px; }}
            
            .form-grid {{ display: grid; grid-template-columns: 1fr 1fr auto; gap: 15px; align-items: end; }}
            .form-group {{ display: flex; flex-direction: column; }}
            .form-group label {{ font-weight: 600; color: #495057; margin-bottom: 8px; font-size: 14px; }}
            .form-group input, .form-group textarea {{ padding: 12px 16px; border: 2px solid #ced4da; border-radius: 8px; font-size: 15px; transition: all 0.3s; }}
            .form-group input:focus, .form-group textarea:focus {{ outline: none; border-color: #667eea; box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1); }}
            
            .btn-create {{ padding: 12px 32px; background: linear-gradient(135deg, #28a745 0%, #20c997 100%); color: white; border: none; border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer; transition: all 0.3s; }}
            .btn-create:hover {{ transform: translateY(-2px); }}
            
            .table-container {{ margin-top: 30px; overflow-x: auto; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
            table {{ width: 100%; border-collapse: collapse; background: white; }}
            th {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; font-weight: 600; padding: 16px 12px; text-align: left; font-size: 14px; text-transform: uppercase; }}
            td {{ padding: 14px 12px; border-bottom: 1px solid #e9ecef; font-size: 14px; }}
            tr:hover {{ background: #f8f9fa; }}
            
            .hint {{ background: #fff3cd; color: #856404; padding: 12px 16px; border-radius: 8px; margin: 15px 0; border-left: 4px solid #ffc107; font-size: 14px; }}
            
            @media (max-width: 768px) {{
                .form-grid {{ grid-template-columns: 1fr; }}
                .container {{ padding: 20px; }}
                h1 {{ font-size: 24px; }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🌐 Gerenciar Sites QR Code</h1>
                <a href="/logout" class="logout">🚪 Sair</a>
            </div>
            
            <div class="tabs">
                <a href="/" class="tab">🔹 Licenças</a>
                <a href="/sites" class="tab active">🌐 Sites</a>
            </div>
            
            <div class="hint">
                💡 <strong>Dica:</strong> Use F12 (DevTools) para descobrir os seletores CSS dos elementos. Inspecione: campo de valor, botão gerar, código PIX, botão copiar.
            </div>
            
            <div class="create-section">
                <h2>➕ Adicionar Novo Site</h2>
                <form method="post" action="/sites/add">
                    <div class="form-grid">
                        <div class="form-group">
                            <label>📛 Nome do Site</label>
                            <input name="site_name" required placeholder="Ex: Gerador QR Code PIX">
                        </div>
                        <div class="form-group">
                            <label>🌐 Domínio</label>
                            <input name="dominio" placeholder="Ex: geradorqrcodepix.com.br">
                        </div>
                        <button type="submit" class="btn-create">✨ Adicionar</button>
                    </div>
                    
                    <div style="margin-top: 15px;">
                        <div class="form-group">
                            <label>📍 Padrão URL</label>
                            <input name="url" placeholder="Ex: https://geradorqrcodepix.com.br/*" required>
                        </div>
                    </div>
                    
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-top: 15px;">
                        <div class="form-group">
                            <label>💰 Campo de Valor (opcional)</label>
                            <input name="valueInput" placeholder="Ex: #valor">
                        </div>
                        <div class="form-group">
                            <label>🔘 Botão Gerar (obrigatório)</label>
                            <input name="generateButton" placeholder="Ex: #gerar" required>
                        </div>
                        <div class="form-group">
                            <label>📊 Código PIX (obrigatório)</label>
                            <input name="pixCode" placeholder="Ex: #codigo-pix" required>
                        </div>
                        <div class="form-group">
                            <label>📋 Botão Copiar (opcional)</label>
                            <input name="copyButton" placeholder="Ex: #copiar">
                        </div>
                        <div class="form-group">
                            <label>❌ Fechar Modal (opcional)</label>
                            <input name="closeModalButton" placeholder="Ex: .close">
                        </div>
                        <div class="form-group">
                            <label>📝 Reabrir Formulário (opcional)</label>
                            <input name="openFormButton" placeholder="Ex: #novo-formulario">
                        </div>
                    </div>
                </form>
            </div>
            
            <h2 style="margin-top: 30px; margin-bottom: 15px; color: #333; font-size: 22px; display: flex; align-items: center; gap: 10px;">📋 Sites Cadastrados</h2>
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>📛 Nome</th>
                            <th>🌐 Domínio</th>
                            <th>📍 URL</th>
                            <th>⚡ Status</th>
                            <th>🔧 Ações</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows if rows else '<tr><td colspan="5" style="text-align: center; color: #999;">Nenhum site cadastrado</td></tr>'}
                    </tbody>
                </table>
            </div>
        </div>
    </body>
    </html>
    """
    
    return html


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
    openFormButton: str = Form("")
):
    """Adiciona ou atualiza um site."""
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
        "ativo": True
    }
    
    save_sites(sites_data)
    return RedirectResponse(url="/sites", status_code=302)


@app.post("/sites/delete")
def delete_site(session_token: str = Cookie(None), site_name: str = Form(...)):
    """Deleta um site."""
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


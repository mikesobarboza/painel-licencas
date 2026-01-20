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

if not BIN_ID or not MASTER_KEY:
    raise RuntimeError(
        "Defina JSONBIN_BIN_ID e JSONBIN_MASTER_KEY no .env "
        "ou nas variáveis de ambiente do Render."
    )

# Armazena sessões ativas (em produção, use Redis ou DB)
active_sessions = {}

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
def home(session_token: str = Cookie(None)):
    # Verifica autenticação
    if not check_auth(session_token):
        return RedirectResponse(url="/login", status_code=302)
    
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
      <p><a href="/logout" style="color: red; font-weight: bold;">🚪 Sair</a></p>

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
def criar(session_token: str = Cookie(None), cliente: str = Form(...), expira: str = Form(...)):
    # Verifica autenticação
    if not check_auth(session_token):
        return RedirectResponse(url="/login", status_code=302)
    
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
def editar(session_token: str = Cookie(None), cliente: str = Form(...), expira: str = Form(...), ativo: str = Form(...)):
    # Verifica autenticação
    if not check_auth(session_token):
        return RedirectResponse(url="/login", status_code=302)
    
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
def limpar_hwid(session_token: str = Cookie(None), cliente: str = Form(...)):
    # Verifica autenticação
    if not check_auth(session_token):
        return RedirectResponse(url="/login", status_code=302)
    
    data = get_bin()
    cliente = cliente.strip()

    if cliente in data:
        data[cliente]["hwid"] = ""
        save_bin(data)

    return RedirectResponse(url="/", status_code=302)


@app.post("/excluir")
def excluir(session_token: str = Cookie(None), cliente: str = Form(...)):
    # Verifica autenticação
    if not check_auth(session_token):
        return RedirectResponse(url="/login", status_code=302)
    
    data = get_bin()
    cliente = cliente.strip()

    if cliente in data:
        del data[cliente]
        save_bin(data)

    return RedirectResponse(url="/", status_code=302)


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


@app.get("/debug-senha")
def debug_senha():
    """Rota temporária para debug - REMOVER EM PRODUÇÃO"""
    return {
        "senha_esperada": PAINEL_PASSWORD,
        "tamanho": len(PAINEL_PASSWORD),
        "tipo": type(PAINEL_PASSWORD).__name__
    }


@app.post("/login")
def do_login(response: Response, password: str = Form(...)):
    # Log para debug
    print(f"DEBUG - Senha recebida: '{password}' (len={len(password)})")
    print(f"DEBUG - Senha esperada: '{PAINEL_PASSWORD}' (len={len(PAINEL_PASSWORD)})")
    print(f"DEBUG - São iguais? {password == PAINEL_PASSWORD}")
    
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

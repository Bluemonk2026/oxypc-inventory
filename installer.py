#!/usr/bin/env python3
"""
OxyPC Web Installer
───────────────────
1. Upload this file to your server (or: curl -O https://raw.githubusercontent.com/TheCodeOrbit/oxypc/main/installer.py)
2. Run:  python3 installer.py
3. Open: http://YOUR-SERVER-IP:8080
4. Fill in the form and click Install — watch it run in real time.
5. Installer deletes itself when done.
"""

import http.server, json, os, shutil, socket, subprocess, sys, threading
from urllib.parse import parse_qs, urlparse

PORT       = 8080
REPO_URL   = "https://github.com/TheCodeOrbit/oxypc.git"
INSTALL_DIR = "/opt/oxypc"
SERVICE     = "oxypc"
APP_PORT    = 8000

# ── shared state ────────────────────────────────────────────────────────────
_state = {"phase": "idle", "log": [], "done": False, "error": None}
_lock  = threading.Lock()

def _log(msg):
    with _lock:
        _state["log"].append(str(msg))
    print(msg, flush=True)

def _run(cmd, cwd=None, env=None):
    _log(f"$ {cmd}")
    e = {**os.environ, **(env or {})}
    p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, cwd=cwd, env=e, text=True)
    for ln in p.stdout:
        _log(ln.rstrip())
    p.wait()
    if p.returncode != 0:
        raise RuntimeError(f"Failed (exit {p.returncode}): {cmd}")

# ── installer logic ──────────────────────────────────────────────────────────
def _install(cfg):
    try:
        db_url = (f"postgresql+asyncpg://{cfg['db_user']}:{cfg['db_pass']}"
                  f"@{cfg['db_host']}:{cfg.get('db_port','5432')}/{cfg['db_name']}")
        secret = cfg.get("secret_key") or os.urandom(32).hex()
        venv   = os.path.join(INSTALL_DIR, "venv")
        pip    = os.path.join(venv, "bin", "pip")
        python = os.path.join(venv, "bin", "python")
        uvicorn= os.path.join(venv, "bin", "uvicorn")

        # ── 1. Clone ────────────────────────────────────────────────────────
        with _lock: _state["phase"] = "Cloning repository…"
        if os.path.exists(os.path.join(INSTALL_DIR, ".git")):
            _log("Repo exists — pulling latest…")
            _run("git pull origin main", cwd=INSTALL_DIR)
        else:
            os.makedirs(INSTALL_DIR, exist_ok=True)
            _run(f"git clone {REPO_URL} {INSTALL_DIR}")

        # ── 2. Venv + deps ──────────────────────────────────────────────────
        with _lock: _state["phase"] = "Installing Python packages…"
        if not os.path.exists(venv):
            _run(f"python3 -m venv {venv}")
        _run(f"{pip} install --upgrade pip --quiet")
        _run(f"{pip} install -r {INSTALL_DIR}/requirements.txt --quiet")
        _run(f"{pip} install uvicorn --quiet")

        # ── 3. .env ─────────────────────────────────────────────────────────
        with _lock: _state["phase"] = "Writing configuration…"
        env_content = (
            f"DATABASE_URL={db_url}\n"
            f"SECRET_KEY={secret}\n"
            f"APP_PORT={APP_PORT}\n"
        )
        with open(os.path.join(INSTALL_DIR, ".env"), "w") as f:
            f.write(env_content)
        _log("✔ .env written")

        # ── 4. DB migrations ────────────────────────────────────────────────
        with _lock: _state["phase"] = "Running database migrations…"
        db_initialized = os.path.join(INSTALL_DIR, ".db_initialized")
        if not os.path.exists(db_initialized):
            _run(f"{python} setup_db.py", cwd=INSTALL_DIR)
            _run(f"{python} -m alembic stamp head", cwd=INSTALL_DIR)
            open(db_initialized, "w").close()
        else:
            _run(f"{python} -m alembic upgrade head", cwd=INSTALL_DIR)

        # ── 5. systemd service ──────────────────────────────────────────────
        with _lock: _state["phase"] = "Creating system service…"
        svc = f"""[Unit]
Description=OxyPC FastAPI Application
After=network.target

[Service]
User=root
WorkingDirectory={INSTALL_DIR}
Environment="PATH={venv}/bin"
ExecStart={uvicorn} main:app --host 127.0.0.1 --port {APP_PORT}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""
        with open(f"/etc/systemd/system/{SERVICE}.service", "w") as f:
            f.write(svc)
        _run("systemctl daemon-reload")
        _run(f"systemctl enable {SERVICE}")
        _run(f"systemctl restart {SERVICE}")

        # ── 6. Done ─────────────────────────────────────────────────────────
        with _lock:
            _state["phase"] = "done"
            _state["done"]  = True
        _log("✅ OxyPC is installed and running!")

        # Self-delete installer after 30s
        def _cleanup():
            import time; time.sleep(30)
            try: os.remove(__file__)
            except: pass
        threading.Thread(target=_cleanup, daemon=True).start()

    except Exception as ex:
        with _lock:
            _state["phase"] = "error"
            _state["error"] = str(ex)
        _log(f"❌ {ex}")


# ── HTML ─────────────────────────────────────────────────────────────────────
_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OxyPC Installer</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css" rel="stylesheet">
<style>
  body{background:#0f172a;color:#e2e8f0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:2rem 1rem}
  .card{background:#1e293b;border:1px solid #334155;border-radius:1rem;max-width:640px;width:100%;box-shadow:0 25px 50px rgba(0,0,0,.5)}
  .card-header{background:linear-gradient(135deg,#1d4ed8,#0ea5e9);border-radius:1rem 1rem 0 0;padding:1.5rem 2rem}
  .card-body{padding:2rem}
  .form-control,.form-select{background:#0f172a;border-color:#334155;color:#e2e8f0}
  .form-control:focus,.form-select:focus{background:#0f172a;border-color:#3b82f6;color:#e2e8f0;box-shadow:0 0 0 .25rem rgba(59,130,246,.25)}
  .form-control::placeholder{color:#64748b}
  .form-label{color:#94a3b8;font-size:.85rem;font-weight:500}
  #logBox{background:#0f172a;border:1px solid #334155;border-radius:.5rem;height:280px;overflow-y:auto;padding:1rem;font-family:monospace;font-size:.8rem;color:#86efac;white-space:pre-wrap}
  .step-badge{display:inline-flex;align-items:center;gap:.4rem;background:#1d4ed8;color:#fff;border-radius:2rem;padding:.25rem .75rem;font-size:.8rem;font-weight:600}
  .progress{height:6px;background:#0f172a}
  #successBox{display:none}
  #installForm{}
  .divider{border-color:#334155}
</style>
</head>
<body>
<div class="card">
  <div class="card-header">
    <div class="d-flex align-items-center gap-3">
      <i class="bi bi-pc-display-horizontal fs-2 text-white"></i>
      <div>
        <h4 class="mb-0 fw-bold text-white">OxyPC Installer</h4>
        <div class="text-white-50 small">Web-based setup wizard</div>
      </div>
    </div>
  </div>

  <div class="card-body">

    <!-- ── FORM ── -->
    <div id="installForm">
      <div class="d-flex align-items-center gap-2 mb-3">
        <span class="step-badge"><i class="bi bi-database me-1"></i>Database</span>
        <span class="text-muted small">Enter your PostgreSQL credentials</span>
      </div>

      <div class="row g-3 mb-3">
        <div class="col-8">
          <label class="form-label">Database Host</label>
          <input id="db_host" class="form-control form-control-sm" value="localhost" placeholder="localhost">
        </div>
        <div class="col-4">
          <label class="form-label">Port</label>
          <input id="db_port" class="form-control form-control-sm" value="5432" placeholder="5432">
        </div>
        <div class="col-12">
          <label class="form-label">Database Name</label>
          <input id="db_name" class="form-control form-control-sm" placeholder="oxypc_inventory_db">
        </div>
        <div class="col-6">
          <label class="form-label">Database User</label>
          <input id="db_user" class="form-control form-control-sm" placeholder="postgres">
        </div>
        <div class="col-6">
          <label class="form-label">Database Password</label>
          <input id="db_pass" type="password" class="form-control form-control-sm" placeholder="••••••••">
        </div>
      </div>

      <hr class="divider">

      <div class="d-flex align-items-center gap-2 mb-3 mt-3">
        <span class="step-badge"><i class="bi bi-gear me-1"></i>App Settings</span>
        <span class="text-muted small">Optional — leave blank for defaults</span>
      </div>

      <div class="mb-4">
        <label class="form-label">Secret Key <span class="text-muted">(auto-generated if blank)</span></label>
        <input id="secret_key" class="form-control form-control-sm" placeholder="Leave blank to auto-generate">
      </div>

      <div id="errMsg" class="alert alert-danger py-2 small d-none"></div>

      <button onclick="startInstall()" class="btn btn-primary w-100 py-2 fw-semibold">
        <i class="bi bi-lightning-charge me-2"></i>Install OxyPC
      </button>
    </div>

    <!-- ── PROGRESS ── -->
    <div id="progressBox" style="display:none">
      <div class="d-flex align-items-center justify-content-between mb-2">
        <span id="phaseLabel" class="step-badge"><i class="bi bi-arrow-clockwise me-1 spin"></i>Installing…</span>
        <span id="pct" class="text-muted small">0%</span>
      </div>
      <div class="progress mb-3"><div id="bar" class="progress-bar progress-bar-striped progress-bar-animated" style="width:0%"></div></div>
      <div id="logBox"></div>
    </div>

    <!-- ── SUCCESS ── -->
    <div id="successBox">
      <div class="text-center mb-4">
        <i class="bi bi-check-circle-fill text-success" style="font-size:3rem"></i>
        <h5 class="mt-3 mb-1 fw-bold">Installation Complete!</h5>
        <p class="text-muted small">OxyPC is now running on your server.</p>
      </div>
      <div class="alert alert-success small py-2 mb-3">
        <i class="bi bi-info-circle me-1"></i>
        <strong>Next:</strong> Set up auto-deploy from GitHub →
        Go to <strong>GitHub repo → Settings → Actions → Runners → New self-hosted runner</strong>
        and run the commands in your server SSH.
      </div>
      <a href="/" class="btn btn-success w-100 fw-semibold" onclick="window.location.replace('http://'+location.hostname)">
        <i class="bi bi-box-arrow-up-right me-2"></i>Open OxyPC App
      </a>
    </div>

  </div>
</div>

<style>
@keyframes spin{to{transform:rotate(360deg)}}
.spin{display:inline-block;animation:spin .8s linear infinite}
</style>
<script>
var PHASES=['Cloning repository…','Installing Python packages…','Writing configuration…','Running database migrations…','Creating system service…'];
var timer=null;

function startInstall(){
  var required={db_host:'DB Host',db_name:'Database Name',db_user:'DB User',db_pass:'DB Password'};
  for(var id in required){
    if(!document.getElementById(id).value.trim()){
      show('errMsg');
      document.getElementById('errMsg').textContent=required[id]+' is required.';
      document.getElementById('errMsg').classList.remove('d-none');
      return;
    }
  }
  document.getElementById('errMsg').classList.add('d-none');
  var data=new URLSearchParams({
    db_host:v('db_host'),db_port:v('db_port'),db_name:v('db_name'),
    db_user:v('db_user'),db_pass:v('db_pass'),secret_key:v('secret_key')
  });
  fetch('/start',{method:'POST',body:data,headers:{'Content-Type':'application/x-www-form-urlencoded'}})
    .then(function(r){return r.json();})
    .then(function(j){
      if(!j.ok){alert(j.error||'Failed to start');return;}
      document.getElementById('installForm').style.display='none';
      document.getElementById('progressBox').style.display='block';
      timer=setInterval(poll,1000);
    });
}

var lastLen=0;
function poll(){
  fetch('/status').then(function(r){return r.json();}).then(function(s){
    var log=document.getElementById('logBox');
    var newLines=(s.log||[]).slice(lastLen);
    lastLen=(s.log||[]).length;
    newLines.forEach(function(l){log.textContent+=l+'\n';});
    log.scrollTop=log.scrollHeight;

    var idx=PHASES.indexOf(s.phase);
    var pct=idx>=0?Math.round((idx+1)/PHASES.length*90):s.done?100:s.phase==='error'?100:10;
    document.getElementById('bar').style.width=pct+'%';
    document.getElementById('pct').textContent=pct+'%';

    if(s.phase&&s.phase!=='idle')
      document.getElementById('phaseLabel').innerHTML='<i class="bi bi-arrow-clockwise me-1 spin"></i>'+s.phase;

    if(s.done){
      clearInterval(timer);
      document.getElementById('bar').style.width='100%';
      document.getElementById('pct').textContent='100%';
      setTimeout(function(){
        document.getElementById('progressBox').style.display='none';
        document.getElementById('successBox').style.display='block';
      },1500);
    }
    if(s.error){
      clearInterval(timer);
      document.getElementById('phaseLabel').innerHTML='<i class="bi bi-x-circle me-1"></i>Error';
      document.getElementById('bar').classList.remove('progress-bar-striped','progress-bar-animated');
      document.getElementById('bar').classList.add('bg-danger');
    }
  });
}
function v(id){return document.getElementById(id).value.trim();}
</script>
</body>
</html>"""


# ── HTTP handler ─────────────────────────────────────────────────────────────
class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_): pass

    def _json(self, data, code=200):
        b = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _html(self, html):
        b = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html;charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/install"):
            self._html(_HTML)
        elif path == "/status":
            with _lock:
                self._json(dict(_state))
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length).decode()
        params = parse_qs(body)
        flat   = {k: v[0] for k, v in params.items()}
        path   = urlparse(self.path).path

        if path == "/start":
            with _lock:
                if _state["phase"] not in ("idle", "error"):
                    self._json({"ok": False, "error": "Already running"}); return
                _state.update({"phase": "starting", "log": [], "done": False, "error": None})
            threading.Thread(target=_install, args=(flat,), daemon=True).start()
            self._json({"ok": True})
        else:
            self.send_response(404); self.end_headers()


# ── main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        ip = "YOUR-SERVER-IP"

    print(f"""
╔══════════════════════════════════════════════════╗
║            OxyPC Web Installer                   ║
╠══════════════════════════════════════════════════╣
║  Open this URL in your browser:                  ║
║                                                  ║
║    http://{ip:<38}║
║    http://localhost:{PORT:<30}║
╚══════════════════════════════════════════════════╝
Press Ctrl+C to stop.
""".replace(f"http://{ip}", f"http://{ip}:{PORT}"))

    server = http.server.HTTPServer(("0.0.0.0", PORT), _Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nInstaller stopped.")

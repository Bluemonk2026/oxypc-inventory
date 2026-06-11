"""
OxyPC Inventory — Unified Launcher
Manages: FastAPI App + Cloudflare Tunnel
PostgreSQL is expected to already be running (as a Windows service or system install).
Ctrl+C shuts everything down cleanly.
"""
import os
import sys
import time
import signal
import socket
import subprocess
import json
import urllib.request
import webbrowser
from pathlib import Path

# ─── Paths ────────────────────────────────────────────────────────────────────
APP_DIR  = Path(__file__).resolve().parent
CF       = APP_DIR / "cloudflared.exe"
LOGS_DIR = APP_DIR / "logs"
APPPORT  = 8000

LOGS_DIR.mkdir(exist_ok=True)

# ─── Find Python interpreter ─────────────────────────────────────────────────
def find_python():
    candidates = [
        APP_DIR / "venv" / "Scripts" / "python.exe",   # local venv (priority)
        APP_DIR / "python" / "python.exe",              # bundled python
        Path(r"C:\Python313\python.exe"),
        Path(r"C:\Python312\python.exe"),
        Path(r"C:\Python311\python.exe"),
        Path(sys.executable),                           # same interpreter running this
    ]
    for c in candidates:
        if c.exists():
            return c
    # Fall back to PATH
    import shutil
    p = shutil.which("python")
    if p:
        return Path(p)
    return None

PYTHON = find_python() or Path(sys.executable)

# ─── ANSI colours ─────────────────────────────────────────────────────────────
os.system("")
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

_procs = []

def banner(text, colour=CYAN):
    w = 62
    print(f"\n{colour}{BOLD}{'='*w}{RESET}")
    print(f"{colour}{BOLD}  {text}{RESET}")
    print(f"{colour}{BOLD}{'='*w}{RESET}\n")

def step(n, total, msg):
    print(f"  {GREEN}[{n}/{total}]{RESET} {msg}")

def ok(msg):    print(f"         {GREEN}OK{RESET}  {msg}")
def warn(msg):  print(f"         {YELLOW}!!{RESET}  {msg}")
def err(msg):   print(f"         {RED}XX{RESET}  {msg}")

# ─── Shutdown ─────────────────────────────────────────────────────────────────
def shutdown(sig=None, frame=None):
    print(f"\n{YELLOW}  Shutting down OxyPC...{RESET}")
    for p in reversed(_procs):
        try:
            p.terminate()
        except Exception:
            pass
    time.sleep(1)
    print(f"  {GREEN}All services stopped. Goodbye!{RESET}\n")
    sys.exit(0)

signal.signal(signal.SIGINT,  shutdown)
signal.signal(signal.SIGTERM, shutdown)

# ─── Port helpers ─────────────────────────────────────────────────────────────
def port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0

def wait_for_port(port, timeout=40, label=""):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(1)
    err(f"Timeout waiting for {label} on port {port}")
    return False

# ─── Get Cloudflare public URL from its local API ─────────────────────────────
def get_tunnel_url(timeout=35):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = urllib.request.urlopen("http://localhost:4040/api/tunnels", timeout=3)
            data = json.loads(resp.read())
            for t in data.get("tunnels", []):
                url = t.get("public_url", "")
                if url.startswith("https://"):
                    return url
        except Exception:
            pass
        time.sleep(2)
    return None

# ─── Local IP ─────────────────────────────────────────────────────────────────
def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "192.168.x.x"

# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    banner("OxyPC Inventory  |  Starting UAT Server", CYAN)

    TOTAL = 4

    # ── 1. Check PostgreSQL connectivity ─────────────────────────────────────
    step(1, TOTAL, "Checking PostgreSQL connectivity...")
    import configparser
    cfg = configparser.ConfigParser()
    cfg.read(str(APP_DIR / "config.ini"))
    db_url = cfg.get("database", "url",
                     fallback="postgresql+asyncpg://oxypc:oxypc123@localhost:5432/oxypc_db")
    # Extract port from URL
    try:
        pg_port = int(db_url.split(":")[3].split("/")[0])
    except Exception:
        pg_port = 5432
    if wait_for_port(pg_port, timeout=5, label="PostgreSQL"):
        ok(f"PostgreSQL is reachable on port {pg_port}")
    else:
        err(f"Cannot reach PostgreSQL on port {pg_port}. Is the service running?")
        err("Start it via:  services.msc  -> Find postgresql -> Start")
        input("  Press Enter to exit...")
        sys.exit(1)

    # ── 2. Run migrations ─────────────────────────────────────────────────────
    step(2, TOTAL, "Running database migrations...")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(APP_DIR)
    result = subprocess.run(
        [str(PYTHON), str(APP_DIR / "upgrade_db.py")],
        cwd=str(APP_DIR), env=env,
        capture_output=True, text=True
    )
    if result.returncode == 0:
        ok("Migrations complete")
    else:
        warn("Migration returned non-zero. Continuing anyway.")

    # ── 3. Start FastAPI app ─────────────────────────────────────────────────
    step(3, TOTAL, f"Starting OxyPC app on port {APPPORT}...")
    if not port_free(APPPORT):
        ok(f"App already running on port {APPPORT}")
    else:
        app_log = open(LOGS_DIR / "app.log", "w", encoding="utf-8")
        p = subprocess.Popen(
            [str(PYTHON), "-m", "uvicorn", "main:app",
             "--host", "0.0.0.0", "--port", str(APPPORT), "--log-level", "warning"],
            cwd=str(APP_DIR),
            env=env,
            stdout=app_log,
            stderr=app_log,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        _procs.append(p)
        if not wait_for_port(APPPORT, timeout=30, label="App"):
            err("App failed to start — check logs\\app.log")
            shutdown()
        ok(f"App running at http://localhost:{APPPORT}")

    # ── 4. Start Cloudflare tunnel ────────────────────────────────────────────
    step(4, TOTAL, "Starting internet tunnel (Cloudflare)...")
    public_url = None
    if CF.exists():
        cf_log = open(LOGS_DIR / "cloudflared.log", "w", encoding="utf-8")
        cp = subprocess.Popen(
            [str(CF), "tunnel", "--url", f"http://localhost:{APPPORT}", "--no-autoupdate"],
            stdout=cf_log, stderr=cf_log,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        _procs.append(cp)
        public_url = get_tunnel_url(timeout=35)
        if public_url:
            ok(f"Tunnel live: {public_url}")
        else:
            warn("Could not get tunnel URL — check logs\\cloudflared.log")
    else:
        warn("cloudflared.exe not found — internet access unavailable")

    # ── Open browser locally ──────────────────────────────────────────────────
    time.sleep(0.8)
    webbrowser.open(f"http://localhost:{APPPORT}")

    # ─── Print summary ────────────────────────────────────────────────────────
    banner("SERVER IS RUNNING  —  Share the INTERNET link below", GREEN)

    lan = local_ip()
    if public_url:
        print(f"  {BOLD}{'INTERNET (share this):':<26}{RESET}{CYAN}{public_url}{RESET}")
    else:
        print(f"  {YELLOW}INTERNET  : not available (cloudflared.exe missing){RESET}")
    print(f"  {BOLD}{'LAN:':<26}{RESET}http://{lan}:{APPPORT}")
    print(f"  {BOLD}{'LOCAL:':<26}{RESET}http://localhost:{APPPORT}")
    print()
    print(f"  {BOLD}Admin login   :{RESET}  admin  /  oxypc@admin123")
    print(f"  {BOLD}UAT logins    :{RESET}  see UAT_Credentials_Sheet.txt")
    print()
    print(f"  {YELLOW}Press Ctrl+C in this window to stop the server.{RESET}")
    print(f"  {'='*62}\n")

    while True:
        time.sleep(5)
        for p in _procs:
            if p.poll() is not None:
                warn(f"A background process stopped unexpectedly (PID {p.pid})")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        shutdown()

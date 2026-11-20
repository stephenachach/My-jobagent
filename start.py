#!/usr/bin/env python3
"""One-command launcher: installs dependencies if missing, then starts the dashboard.

Works when double-clicked from START_AGENT.bat or run from any folder.
"""
import importlib
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

NEEDED = {"flask": "flask", "requests": "requests", "bs4": "beautifulsoup4",
          "yaml": "PyYAML", "pypdf": "pypdf", "reportlab": "reportlab",
          "pymupdf": "pymupdf"}
missing = []
for mod, pip_name in NEEDED.items():
    try:
        importlib.import_module(mod)
    except ImportError:
        missing.append(pip_name)
if missing:
    print("Installing missing packages (first run only, may take a few minutes):",
          ", ".join(missing), flush=True)
    # No --quiet: show pip progress so the window does not look frozen.
    subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])

# Browser engine for the web-application filler (one-time download, ~115 MB).
# A failure here must NOT stop the dashboard from starting.
try:
    from playwright.sync_api import sync_playwright  # noqa
    with sync_playwright() as _pw:
        if not _pw.chromium.executable_path or not os.path.exists(_pw.chromium.executable_path):
            raise RuntimeError("chromium missing")
    print("browser engine: ready")
except Exception as exc:
    print(f"browser engine not ready ({exc}); web auto-fill may be unavailable.")
    print("You can install it later with:  python -m playwright install chromium")
    # Do not force a download on every start: it can take minutes and looked
    # like a hang when START_AGENT.bat was double-clicked.

from agent.config import load_settings  # noqa: E402
port = int((load_settings().get("dashboard") or {}).get("port", 7860))
print(f"Starting dashboard on http://127.0.0.1:{port} ...", flush=True)

import webbrowser  # noqa: E402
import threading  # noqa: E402
threading.Timer(2.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()

# Run the real Flask app in-process so the launcher's chdir and error handling apply.
from dashboard import app  # noqa: E402
app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

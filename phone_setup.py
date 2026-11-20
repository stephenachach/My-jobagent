#!/usr/bin/env python3
"""Phone setup helper — shows exactly how to open the dashboard from your phone.

Run on the computer where the agent is running:  python3 phone_setup.py
"""
import socket

PORT = 7860


def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))          # no traffic sent; just picks a route
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


print("=" * 62)
print("  CONNECT YOUR PHONE TO THE JOB AGENT DASHBOARD")
print("=" * 62)

ip = lan_ip()
print(f"""
STEP 1 — same WiFi (free, works at home)
  1. Make sure the agent is running on this computer
     (double-click START_AGENT.bat or run:  python start.py)
  2. Connect your PHONE to the same WiFi as this computer
  3. On the phone's browser, open:

        http://{ip}:{PORT}

STEP 2 — if the phone can't reach it, allow the port through
  Windows firewall (open PowerShell as Administrator, run once):

     netsh advfirewall firewall add rule name="Job Agent" dir=in action=allow protocol=TCP localport={PORT}

STEP 3 — want access ANYWHERE (mobile data, not just home WiFi)?
  Easiest free option — Cloudflare Tunnel (no account needed).
  Install cloudflared from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
  then run:

     cloudflared tunnel --url http://localhost:{PORT}

  It prints a public https://xxx.trycloudflare.com address — open that on
  your phone from anywhere. Paste it into config/settings.yaml under
  schedule.base_url so notification emails contain working links.

TIP: bookmark http://{ip}:{PORT} on your phone's home screen.
Your laptop must be ON and awake for the dashboard to work.
""")

# 🖥️ Running the Job Agent on YOUR computer — the complete guide

## PHP vs Python — what changes for you

| In your PHP world | Here (Python) |
|---|---|
| XAMPP / WAMP / Apache | ❌ Not needed — Python has its own web server |
| MySQL database | ❌ Not needed — SQLite (one file: `data/jobagent.db`) |
| htdocs folder | ❌ Not needed — the app runs from its own folder |
| "Start WAMP" button | ✅ `START_AGENT.bat` — double-click to start |
| localhost/yourfile.php | ✅ http://localhost:7860 |

Your XAMPP/PHP setup is **not affected** — both can live on the same PC (different ports).

---

## Setup (once, ~10 minutes)

**STEP 1 — Install Python**
1. Go to **python.org/downloads** → download Python 3.12+
2. Run the installer — on the FIRST screen, **tick "Add python.exe to PATH"** ⚠️ most important checkbox
3. Click Install

**STEP 2 — Put the app in a simple place**
- Extract `jobagent_for_pc.zip` to **`C:\jobagent`**
- Avoid OneDrive-synced folders (Desktop under OneDrive, Documents) — syncing can lock the database

**STEP 3 — Start it**
- Double-click **`START_AGENT.bat`**
- First run: it installs everything automatically, including the browser engine for web applications (~115 MB, one time only — be patient)
- The window must stay **open or minimized**

**STEP 4 — Open the dashboard**
- Browser → **http://localhost:7860**
- Bookmark it

**STEP 5 — Phone access (optional)** — see the "B" section below

---

## If Windows asks / blocks something

| What you see | What to do |
|---|---|
| Blue window: "Windows protected your PC" (SmartScreen) on the .bat | Click **More info → Run anyway** (it's your own script) |
| Firewall prompt when starting | Tick **Private networks** → Allow |
| Antivirus flags the Chromium download | It's Google's official Chromium (Playwright uses it for web applications) — allow it |
| `[!] PYTHON NOT FOUND` | The .bat tells you — install Python with "Add to PATH" ticked, then retry |
| Port 7860 already in use | Edit `config/settings.yaml` → `dashboard:` → `port: 7870` (any free port), restart; open localhost:7870 |
| Window closes instantly | It now stays open with the error visible — read it / screenshot it |

---

## Daily use

- **Start:** double-click `START_AGENT.bat` (or set up auto-start below)
- **Stop:** close the window
- The agent searches every **4 hours** by itself, drafts with AI, and emails you at **your notification address** when there's something to approve
- Approve from the dashboard (PC or phone) — it applies and proves it

### Auto-start with Windows (optional, recommended)
1. `Win + R` → type `taskschd.msc` → Enter
2. **Create Basic Task** → name: Job Agent → Trigger: **When I log on**
3. Action: **Start a program** → Program: `C:\jobagent\START_AGENT.bat` → Finish
4. Keep the laptop plugged in; set *Settings → Power → Sleep* to Never (screen can still turn off)

---

## ⚠️ Updating the app later (IMPORTANT)

When you get a new `jobagent_for_pc.zip`, **never delete these two folders** — they hold your passwords and history:
- `config/` — your profile, email settings, search tuning
- `data/` — your job database, statuses, proofs

Safe update: extract the new zip to a NEW folder, then copy your old `config/` and `data/` folders INTO it, replacing the new ones. Or simply copy only the changed code files over your old folder.

---

## Quick reference

| Do this | How |
|---|---|
| Start agent | `START_AGENT.bat` |
| Dashboard | http://localhost:7860 |
| Phone (same WiFi) | run `python phone_setup.py` → gives the address |
| Phone (anywhere) | `cloudflared tunnel --url http://localhost:7860` |
| Change search time/queries | `config/settings.yaml` |
| Change port | `config/settings.yaml` → `dashboard.port` |
| My profile | `config/profile.yaml` |

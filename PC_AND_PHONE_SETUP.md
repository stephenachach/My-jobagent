# 🖥️📱 Running the Agent Daily — on your PC + phone approval

The agent is fully portable: same files, three ways to run it.

---

## A. On your computer (2-minute setup, one-time)

**Requirements:** Python 3.10+ installed (python.org/downloads — tick *"Add Python to PATH"* during install).

1. Copy the whole `jobagent` folder to your computer (e.g. `C:\jobagent`)
2. Double-click **`START_AGENT.bat`**
   - first run installs everything automatically
   - a window opens — **leave it minimized**, that's the agent alive
3. Open **http://localhost:7860** in your browser → your dashboard

That's it. While the window is open the agent will:
- ⏰ search + draft **daily at 07:00** (change `schedule.time` in `config/settings.yaml`)
- 📧 email you a morning digest at **your notification address**
- 📤 send applications the moment you click *Approve* (postings with an email)

### Start automatically when Windows starts (optional)
1. Press `Win + R`, type `taskschd.msc`, Enter
2. **Create Basic Task** → name "Job Agent" → Trigger: *When I log on* →
   Action: *Start a program* → Program: `C:\jobagent\START_AGENT.bat` → Finish
3. Now it wakes with your laptop every day.

> ⚠️ The agent only works while the computer is **on and awake**.
> Keep the laptop plugged in and set *Settings → Power → Sleep* to "Never"
> (screen can still turn off).

---

## B. Approve from your phone

### At home (same WiFi) — free
1. On the PC (with agent running), run: `python phone_setup.py`
   — it prints your dashboard address, e.g. `http://192.168.1.50:7860`
2. Phone (same WiFi) → open that address → **bookmark/add to home screen**
3. Email notification arrives → tap the link → read the CV → *Approve* → done ✅

### Anywhere (mobile data) — free Cloudflare Tunnel
1. Install **cloudflared** on the PC: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
2. Run in Command Prompt:
   ```
   cloudflared tunnel --url http://localhost:7860
   ```
3. It prints an address like `https://random-words.trycloudflare.com` — open it on your phone from anywhere
4. Paste that address into `config/settings.yaml` → `schedule.base_url` (in quotes) and restart the agent → **notification emails now contain tappable links**

---

## C. 24/7 even with the laptop OFF (upgrade path, later)
- Host on a free/cheap always-on server (Oracle Cloud free tier, a ~$5 VPS, or even a Raspberry Pi at home)
- Same files, same commands — ask me and I'll walk you through it when you're ready

---

## Quick reference

| Do this | How |
|---|---|
| Start agent | double-click `START_AGENT.bat` |
| Dashboard (PC) | http://localhost:7860 |
| Dashboard (phone) | `http://<pc-ip>:7860` from `phone_setup.py`, or tunnel URL |
| Change daily search time | `config/settings.yaml` → `schedule.time` |
| Change search queries | `config/settings.yaml` → `search.queries` |
| Your profile/skills | `config/profile.yaml` |
| Revoke email access | Google Account → Security → App passwords → delete |

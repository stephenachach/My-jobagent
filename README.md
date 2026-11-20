# 🤖 Job Agent — your automated job-hunting assistant

Finds jobs that fit **your** qualifications → drafts a tailored CV + cover
letter for each → **waits for your approval** → sends → notifies you.

## Quick start

```bash
cd jobagent
cp config/settings.example.yaml config/settings.yaml   # add your real key here
cp config/profile.example.yaml  config/profile.yaml    # add your real CV here
python3 check_ai.py          # optional: verify the AI engine works
python3 run_search.py        # 1. fetch jobs + generate drafts
python3 refresh_cv.py        # 2. after editing config/profile.yaml, refresh saved drafts (instant, offline)
python3 dashboard.py         # 3. open dashboard, review, approve
```

On Windows, double-click `START_AGENT.bat` instead. Both `config/settings.yaml`
and `config/profile.yaml` are **gitignored** - they hold your API key, email
settings and CV, so they never go to GitHub. A fresh clone works without them
because the app falls back to the `*.example.yaml` templates. You can also
supply `GEMINI_API_KEY`, `SMTP_APP_PASSWORD` and `NOTIFY_EMAIL` as environment
variables.

## Professional CV layout

The CV is plain text that renders like a professionally typeset document. Section
headings and subheadings are bold, with clear space above and below them, and no
separating lines or rules between paragraphs. Where a
section holds several separate sentences, each one starts with a single round dot
bullet and ends with a full stop. PROFILE and the application letter stay as
flowing paragraphs. Links sit on their own line after a plain `Code`, `Portfolio`
or `Live demo` label. There are no markdown hashes, asterisks, hyphens used as
bullets, decorative brackets, pipes or em dashes. Real names such as `M-Pesa`
and real URLs are unchanged.

The PROFILE always opens with the real skills that match the vacancy. For a data
or analytics job it opens with Excel, PivotTables, databases, business
intelligence, accurate data collection and reporting; the job-matched SKILLS
bullets move to the top too. `agent/tailor.py` applies the same cleanup to
AI-written drafts, and `refresh_cv.py` uses your own profile wording without
calling the AI API, so refreshing saved drafts is instant.

## How it works

```
 FETCH                SCORE                 DRAFT              APPROVE         SEND
 MyJobMag (KE)   →   rule-based        →   AI/template    →   you click     →  email
 Remotive (remote)   matcher (0-100)       CV + letter       ✓ / ✕           (Phase 2)
 RemoteOK (remote)   + your profile        per job           in dashboard    + notify
```

## Sources
| Source | Coverage | How |
|---|---|---|
| MyJobMag | Kenya 🇰🇪 | polite HTML scrape |
| Remotive | Remote 🌍 | free public API |
| RemoteOK | Remote 🌍 | free public API |
| WhatsApp channels | Any 🇰🇪🌍 | paste the messages → smart filter (dashboard "WhatsApp inbox") |
| BrighterMonday | Kenya 🇰🇪 | needs headless browser (Phase 3) |

## WhatsApp job channels
WhatsApp Channels have **no public API**, so you feed them in by pasting:
1. Dashboard → **💬 WhatsApp inbox** tab → paste the copied messages → **Filter & add jobs**.
   It filters the noise *and* drafts the CV + letter in one step.
2. Or paste into `data/whatsapp_inbox.txt`, then click **Run job search now** (autopilot also reads it).

The agent keeps the real vacancies, throws away greetings, jokes, forwards and
chatter, skips adverts whose deadline has passed, then sends each through the
normal **score → draft → approve → send** flow. An AI key (Gemini) makes the
filtering much smarter; without one a solid built-in filter is used.

**Image adverts:** save screenshots/photos into `data/whatsapp_media/` — the AI
reads the text in each image and extracts the vacancy (each processed image is
moved to `data/whatsapp_media/processed/` so it is not read twice). Needs an AI key.

**Links:** when a post links to MyJobMag, BrighterMonday or Fuzu, the agent
follows the link and pulls the full job details + apply email automatically.



## Make it AI-smart
1. Free key: https://aistudio.google.com/apikey (new keys start with `AQ.`).
2. Paste it into `config/settings.yaml` → `llm.api_key`, or set `GEMINI_API_KEY`.
3. Run `python3 check_ai.py` to confirm the model responds.
Drafts switch from template mode to full AI writing automatically. If the AI call
fails, the dashboard header shows the error and the template engine takes over.

## Phase 2 checklist (next session)
- [ ] Replace placeholders in the local `config/profile.yaml` with your real CV details
- [ ] Add your personal projects under `projects:` in that local profile
- [ ] Gmail App Password → `config/settings.yaml` → `email:`
- [ ] Approve → auto-email CV + letter + get email notifications

## Files
- `run_search.py` — pipeline CLI
- `dashboard.py` — review/approve web dashboard (port 7860)
- `agent/sources/` — job fetchers (add new boards here)
- `agent/sources/whatsapp.py` — pasted WhatsApp channel text → filtered jobs
- `agent/matcher.py` — job↔profile scoring
- `agent/tailor.py` — CV/letter generation (AI or template), plain human cleanup
- `agent/sender.py` — email sending + digests (Phase 2)
- `data/jobagent.db` — all jobs, drafts, statuses

## Check the AI is really working

`python check_ai.py` makes one tiny Gemini call and prints either
`RESULT: AI is WORKING` or the exact reason it failed in plain words. The dashboard
header repeats the state (`AI` or `template`) and the `/ai` page lists provider,
model, masked key and the last error, so a silent fallback can never look like a
success again.

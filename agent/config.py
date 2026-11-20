"""Shared configuration loader.

A fresh clone has only `*.example.yaml` files (the real ones hold secrets and are
gitignored). Every module must still start, so this loader:

  1. reads config/<name>.yaml when it exists (your PC),
  2. otherwise falls back to config/<name>.example.yaml (fresh clone),
  3. applies environment-variable overrides,
  4. strips placeholder values so the app never tries to call an AI provider
     with the literal string "REPLACE_ME".

Usage:
    from agent.config import load_settings, load_profile
    SETTINGS = load_settings()
    PROFILE = load_profile()
"""
import os

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT, "config")

PLACEHOLDERS = {
    "", "REPLACE_ME", "REPLACE_WITH_GEMINI_API_KEY", "REPLACE_WITH_GCP_API_KEY",
    "REPLACE_WITH_TOKEN", "REPLACE_WITH_PRIVATE_KEY", "YOUR_API_KEY",
    "CHANGEME", "TODO", "NONE", "NULL",
}


def _is_placeholder(value) -> bool:
    return isinstance(value, str) and value.strip().upper() in {
        p.upper() for p in PLACEHOLDERS
    } or value is None


# Python's YAML reader rejects these, and a single one anywhere in the file
# (often invisible, pasted in with a key) used to make the whole settings file
# unreadable. They are removed before parsing instead.
_CONTROL_CHARS = {ch: None for ch in range(0x00, 0x09)}
_CONTROL_CHARS.update({ch: None for ch in range(0x0B, 0x20)})
_CONTROL_CHARS.update({0x7F: None, 0x85: None, 0x9D: None, 0x8D: None,
                       0x8F: None, 0x90: None, 0x9C: None, 0xAD: None})


# Writers that guess an encoding (PowerShell 5 `>`, Notepad "ANSI", some editors)
# turn an invisible byte into U+FFFD, the replacement diamond. Remove those too.
_EXTRA_JUNK = {0xFFFD: None, 0x200B: None, 0xFEFF: None}


def scrub_text(text: str) -> str:
    """Drop characters that make a YAML file unreadable or look invisible."""
    return str(text).translate(_CONTROL_CHARS).translate(_EXTRA_JUNK)


def _sanitize_file(path: str) -> str | None:
    """If a config file holds junk characters, clean it in place and keep a
    one-time backup next to it. Returns the original text when changed."""
    try:
        with open(path, encoding="utf-8-sig") as fh:
            raw = fh.read()
    except (OSError, UnicodeDecodeError):
        return None
    fixed = scrub_text(raw)
    if fixed == raw:
        return None
    backup = path + ".broken-backup"
    try:
        if not os.path.exists(backup):
            with open(backup, "w", encoding="utf-8") as fh:
                fh.write(raw)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(fixed)
        removed = len(raw) - len(fixed)
        print(f"[config] cleaned {removed} invisible character(s) from "
              f"{os.path.basename(path)}; original kept in "
              f"{os.path.basename(backup)}", flush=True)
    except OSError:
        return raw
    return raw


def _read_yaml(filename: str) -> dict:
    path = os.path.join(CONFIG_DIR, filename)
    if not os.path.exists(path):
        return {}
    _sanitize_file(path)
    try:
        with open(path, encoding="utf-8-sig") as fh:
            text = fh.read()
        return yaml.safe_load(scrub_text(text)) or {}
    except Exception as exc:
        # Never take the whole application down because of one settings file.
        print(f"[config] could not read {filename}: {exc}", flush=True)
        print(f"[config] using {filename.replace('.yaml', '.example.yaml')} instead",
              flush=True)
        return {}


def _load(name: str) -> dict:
    data = _read_yaml(name)
    source = name
    if not data:
        example = name.replace(".yaml", ".example.yaml")
        data = _read_yaml(example)
        source = example
    if not isinstance(data, dict):
        print(f"[config] {source} did not contain a mapping", flush=True)
        return {}
    return data


def _overrides(cfg: dict) -> dict:
    """Environment variables win over file values (keeps secrets out of git)."""
    pairs = (
        ("GEMINI_API_KEY", ("llm", "api_key")),
        ("GCP_API_KEY", ("llm", "api_key")),
        ("SMTP_USERNAME", ("email", "username")),
        ("SMTP_APP_PASSWORD", ("email", "app_password")),
        ("NOTIFY_EMAIL", ("notify", "email_to")),
        ("APPLICATION_CC", ("email", "application_cc")),
        ("FROM_NAME", ("email", "from_name")),
    )
    for env_name, (section, key) in pairs:
        val = os.environ.get(env_name)
        if val and val.strip():
            cfg.setdefault(section, {})[key] = val.strip()
    return cfg


def _clean_secret(value) -> str:
    """Keys are pasted by hand, so strip invisible characters and the word
    `Bearer` and accidental surrounding quotes. This is what turns a mysterious
    HTTP 400 into a working call."""
    v = str(value or "")
    for ch in ("\u200b", "\u200e", "\u200f", "\ufeff", "\u00a0", "\r", "\n", "\t"):
        v = v.replace(ch, "")
    v = v.strip().strip('"').strip("'").strip()
    if v.lower().startswith("bearer "):
        v = v[7:].strip()
    return v


def _strip_placeholders(cfg: dict) -> dict:
    for section, key in (
        ("llm", "api_key"), ("email", "username"), ("email", "app_password"),
        ("email", "from_name"), ("email", "application_cc"),
        ("notify", "email_to"), ("schedule", "base_url"),
    ):
        node = cfg.get(section)
        if isinstance(node, dict) and _is_placeholder(node.get(key)):
            node[key] = "" if key != "base_url" else ""
        elif isinstance(node, dict) and key in ("api_key", "app_password"):
            node[key] = _clean_secret(node.get(key))
    return cfg


def load_settings(refresh: bool = False) -> dict:
    """Return settings, with example-file fallback and env overrides.

    `refresh=True` is used by the autopilot so edits to settings.yaml are
    picked up without restarting the dashboard.
    """
    cfg = _load("settings.yaml")
    return _strip_placeholders(_overrides(cfg))


def load_profile() -> dict:
    """Return the CV profile, with example-file fallback on a fresh clone."""
    return _load("profile.yaml")


def config_status() -> dict:
    """Small diagnostic used by check_ai.py and the dashboard header."""
    settings_path = os.path.join(CONFIG_DIR, "settings.yaml")
    profile_path = os.path.join(CONFIG_DIR, "profile.yaml")
    return {
        "settings_source": "settings.yaml" if os.path.exists(settings_path) else "settings.example.yaml",
        "profile_source": "profile.yaml" if os.path.exists(profile_path) else "profile.example.yaml",
        "settings": load_settings(),
    }

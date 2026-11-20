#!/usr/bin/env python3
"""Check whether the AI drafting engine is actually working.

Run from the project folder:   python check_ai.py

It reports which config file is in use, whether a real key is present, and (if
so) makes one tiny Gemini request so you can see the real HTTP status / error
instead of the agent silently falling back to template drafts.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.config import _clean_secret, config_status, load_settings  # noqa: E402
from agent import tailor  # noqa: E402


def main() -> int:
    st = config_status()
    llm = st["settings"].get("llm") or {}
    print("=" * 62)
    print("JOB AGENT - AI CHECK")
    print("=" * 62)
    print(f"settings file : {st['settings_source']}")
    print(f"profile file  : {st['profile_source']}")
    print(f"provider      : {llm.get('provider', 'none')}")
    print(f"model         : {llm.get('model', '(default gemini-3.8-flash)')}")
    key = str(llm.get("api_key") or "")
    print(f"API key       : {'present (' + key[:4] + '... , ' + str(len(key)) + ' chars)' if key else 'NOT SET'}")
    if key:
        cleaned = _clean_secret(key)
        print(f"clean key     : {'yes (' + str(len(cleaned)) + ' chars)' if cleaned == key else 'NO - hidden spaces or quotes were removed'}")
        if cleaned.startswith(("sk-", "hf_", "AIza")) and not cleaned.startswith("AQ"):
            print("               (note: this does not look like a Gemini key from Google AI Studio)")

    if not tailor.ai_available():
        print("\nRESULT: AI is OFF - drafts will use the built-in template engine.")
        print("Fix: put a real Gemini key in config/settings.yaml -> llm.api_key,")
        print("     or set the GEMINI_API_KEY environment variable.")
        print("     Placeholder values like REPLACE_ME count as 'not set'.")
        return 1

    print("\nSending a small test request to Gemini ...")
    t0 = time.time()
    try:
        text = tailor._call_gemini(
            'Reply with exactly this JSON and nothing else: {"cv_md":"ok","letter_md":"ok"}')
        print(f"HTTP/parse  : OK in {time.time() - t0:.1f}s")
        print(f"response    : {text[:200]!r}")
        print("\nRESULT: AI is WORKING. Drafts will be AI-written.")
        return 0
    except Exception as exc:
        print(f"FAILED after {time.time() - t0:.1f}s: {type(exc).__name__}: {exc}")
        print("\nRESULT: AI is BROKEN - the agent is falling back to the template engine,")
        print("so every draft you see is template-written, not AI-written.")
        print("The message above says what to fix. If it mentions the key, create a fresh")
        print("key at https://aistudio.google.com/apikey and paste it into")
        print("config/settings.yaml under llm.api_key, then run this check again.")
        print("If it mentions the model, set llm.model to gemini-3.5-flash or")
        print("gemini-flash-latest. If it mentions region, try again without a VPN.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Loads bot settings, and walks first-time users through adding their token.

Settings live in a .env file:
- when running from source: in the project root
- when running the packaged Jamcord.exe: next to the .exe
"""

import os
import sys
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv, set_key, unset_key

_TOKEN_KEY = "DISCORD_TOKEN"
_PLACEHOLDER_TOKEN = "your_bot_token_here"
_DEVELOPER_PORTAL_URL = "https://discord.com/developers/applications"

_SETUP_GUIDE = f"""
==============================================================
  Welcome to Jamcord! Let's connect your Discord bot.
==============================================================

Your browser is opening the Discord Developer Portal:
  {_DEVELOPER_PORTAL_URL}

  1. Log in and click "New Application". Give it a name.
  2. Click "Bot" in the menu on the left.
  3. Click "Reset Token", confirm, then click "Copy".
  4. Come back here and paste it below (right-click or Ctrl+V).
"""


@dataclass(frozen=True)
class Settings:
    discord_token: str


def is_packaged() -> bool:
    """True when running as the bundled Jamcord.exe (built with PyInstaller)."""
    return getattr(sys, "frozen", False)


def app_dir() -> Path:
    """The folder Jamcord runs from: next to the .exe, or the project root."""
    if is_packaged():
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


ENV_FILE = app_dir() / ".env"


def load_settings() -> Settings:
    """Read settings from .env, asking for the token on first run."""
    load_dotenv(ENV_FILE)
    token = os.getenv(_TOKEN_KEY, "").strip()

    if not token or token == _PLACEHOLDER_TOKEN:
        if not sys.stdin.isatty():
            raise SystemExit(f"{_TOKEN_KEY} is missing. Add it to {ENV_FILE}.")
        token = _ask_for_token()
        ENV_FILE.touch(exist_ok=True)
        set_key(ENV_FILE, _TOKEN_KEY, token)
        print(f"\nSaved! You won't be asked again. (Stored in {ENV_FILE})\n")

    return Settings(discord_token=token)


def forget_token() -> None:
    """Remove a token that Discord rejected, so the next start asks for a new one."""
    os.environ.pop(_TOKEN_KEY, None)
    if ENV_FILE.exists():
        unset_key(ENV_FILE, _TOKEN_KEY)


def _ask_for_token() -> str:
    print(_SETUP_GUIDE)
    webbrowser.open(_DEVELOPER_PORTAL_URL)
    while True:
        token = clean_token(input("Bot token: "))
        if looks_like_token(token):
            return token
        print("That doesn't look like a bot token. Copy it again from the Bot page and paste it here.\n")


def clean_token(raw: str) -> str:
    """Pasted tokens sometimes come with spaces or quotes around them."""
    return raw.strip().strip("\"'")


def looks_like_token(token: str) -> bool:
    """Bot tokens have three parts separated by dots, and are long."""
    parts = token.split(".")
    return len(parts) == 3 and all(parts) and len(token) > 50

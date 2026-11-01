"""Loads bot settings from environment variables (and the .env file)."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

_PLACEHOLDER_TOKEN = "your_bot_token_here"


@dataclass(frozen=True)
class Settings:
    discord_token: str


def load_settings() -> Settings:
    """Read settings from .env and exit with a clear message if they are invalid."""
    load_dotenv()

    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token or token == _PLACEHOLDER_TOKEN:
        raise SystemExit("DISCORD_TOKEN is missing. Copy .env.example to .env and add your bot token.")

    return Settings(discord_token=token)

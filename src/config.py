"""Loads bot settings from environment variables (and the .env file)."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

_PLACEHOLDER_TOKEN = "your_bot_token_here"


@dataclass(frozen=True)
class Settings:
    discord_token: str
    # Optional: when set, slash commands sync to this server instantly
    # instead of the global sync, which can take up to an hour.
    guild_id: int | None


def load_settings() -> Settings:
    """Read settings from .env and exit with a clear message if they are invalid."""
    load_dotenv()

    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token or token == _PLACEHOLDER_TOKEN:
        raise SystemExit("DISCORD_TOKEN is missing. Copy .env.example to .env and add your bot token.")

    guild_id_raw = os.getenv("GUILD_ID", "").strip()
    if guild_id_raw and not guild_id_raw.isdigit():
        raise SystemExit("GUILD_ID must be a numeric Discord server ID.")

    return Settings(
        discord_token=token,
        guild_id=int(guild_id_raw) if guild_id_raw else None,
    )

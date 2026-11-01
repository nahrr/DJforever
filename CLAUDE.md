# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Jamcord

Private self-hosted Discord music bot (Python).
Runs locally so a small group can listen to the same YouTube tracks together.

## Architecture
Modules in `src/` import each other by bare name (`import audio`), which works because `python src/bot.py` puts `src/` on the import path.

- `bot.py` — entry point. `JamcordBot.setup_hook` loads the `Music` cog and syncs slash commands (to `GUILD_ID` if set, else globally).
- `config.py` — reads `.env` into a frozen `Settings` dataclass; exits with a clear message on bad config.
- `music.py` — the `Music` cog: all slash commands, plus a `guild_id → GuildPlayer` map.
- `player.py` — `GuildPlayer`: one per server, owns the queue and `VoiceClient`. When a track ends, discord.py calls `_on_track_end` from its audio thread, which schedules `play_next` back on the event loop. Skip/stop work by calling `voice.stop()` and letting that callback advance the queue. An `asyncio.Lock` stops two commands from starting playback at once.
- `audio.py` — yt-dlp wrapper. yt-dlp is blocking, so calls run through `asyncio.to_thread`.

## yt-dlp workarounds
- Stream URLs expire after a few hours, so the queue stores the page URL and the stream URL is resolved right before playback (`audio.get_stream_url`).
- FFmpeg reconnect flags (`audio.FFMPEG_OPTIONS`) stop playback from cutting out when YouTube drops the connection.

## Goal
- Play YouTube URLs / search results into Discord voice channels
- Shared queue with basic controls
- Completely private (token stays on the machine)

## Stack
- Python 3.10+ (the dev machine runs 3.10; yt-dlp has deprecated 3.10, so upgrade before it drops support)
- discord.py (with voice)
- yt-dlp + ffmpeg for audio
- python-dotenv for config

## Commands
- /play <url or query>
- /skip
- /stop
- /queue
- /nowplaying
- /leave

## Discord setup notes
- Invite the bot with the `bot` and `applications.commands` scopes, plus Connect and Speak permissions.
- Slash commands must be synced with `bot.tree.sync()`. Syncing to a single guild is instant; global sync can take up to an hour.

## Conventions
- Keep it simple and reliable
- Always use simple, concise commit messages following the Conventional Commits format (e.g. `feat: add login`)
- Never include co-author or co-written lines in commit messages
- Document any yt-dlp workarounds

## How to run
Full user setup (Discord portal, invite URL) is in README.md.
1. Install ffmpeg and make sure it's on PATH (e.g. `sudo apt install ffmpeg`)
2. Copy .env.example → .env and add the Discord token (and optionally `GUILD_ID`)
3. python3 -m venv .venv && source .venv/bin/activate
4. pip install -r requirements.txt
5. python src/bot.py

There are no tests or linter yet. Quick check that everything imports: `cd src && ../.venv/bin/python -c "import bot"`.
If YouTube playback breaks, try `pip install -U yt-dlp` first (requirements.txt intentionally doesn't pin it).

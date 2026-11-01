# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Jamcord

Private self-hosted Discord music bot (Python).
Runs locally so a small group can listen to the same YouTube tracks together.

## Architecture
Modules in `src/` import each other by bare name (`import audio`), which works because `python src/bot.py` puts `src/` on the import path.

- `bot.py` — entry point. `setup_hook` loads the `Music` cog; `on_ready` (first time only) and `on_guild_join` sync slash commands to each server separately. Commands are never synced globally, because per-server sync is instant.
- `config.py` — reads `.env` into a frozen `Settings` dataclass; exits with a clear message on bad config.
- `music.py` — the `Music` cog: slash commands, plus a `guild_id → Session` map. A `Session` holds the `GuildPlayer`, the text channel and the current now-playing message. It replaces that card whenever the player reports a track change, and leaves voice when the bot is alone.
- `player.py` — `GuildPlayer`: one per server, owns the queue, `VoiceClient` and elapsed-time tracking. It has no Discord UI code; it reports changes through the `on_track_change(track | None)` callback. When a track ends, discord.py calls `_on_track_end` from its audio thread, which schedules `play_next` back on the event loop. Skip/stop work by calling `voice.stop()` and letting that callback advance the queue. An `asyncio.Lock` stops two commands from starting playback at once.
- `ui.py` — all presentation: embeds (now playing, added to queue, queue) and the `PlayerControls` button view. Control buttons and `/skip` `/stop` `/leave` only work for users in the bot's voice channel.
- `audio.py` — yt-dlp wrapper. yt-dlp is blocking, so calls run through `asyncio.to_thread`.

## yt-dlp workarounds
- Stream URLs expire after a few hours, so the queue stores the page URL and the stream URL is resolved right before playback (`audio.get_stream_url`).
- Audio: yt-dlp prefers Opus formats and the player uses `FFmpegOpusAudio.from_probe`, so YouTube's Opus is passed through to Discord without re-encoding. Other codecs are re-encoded at the source's bitrate (`from_probe` picks it; it doesn't accept a `bitrate` argument).
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
- Invite the bot with the `bot` and `applications.commands` scopes, plus Connect, Speak, Send Messages and Embed Links permissions (the now-playing cards are sent with `channel.send`, which needs Embed Links).

## Conventions
- Keep it simple and reliable
- Always use simple, concise commit messages following the Conventional Commits format (e.g. `feat: add login`)
- Never include co-author or co-written lines in commit messages
- Document any yt-dlp workarounds

## How to run
Full user setup (Discord portal, invite URL) is in README.md.
1. Install ffmpeg and make sure it's on PATH (e.g. `sudo apt install ffmpeg`)
2. Copy .env.example → .env and add the Discord token
3. python3 -m venv .venv && source .venv/bin/activate
4. pip install -r requirements.txt
5. python src/bot.py

There are no tests or linter yet. Quick check that everything imports: `cd src && ../.venv/bin/python -c "import bot"`.
If YouTube playback breaks, try `pip install -U yt-dlp` first (requirements.txt intentionally doesn't pin it).

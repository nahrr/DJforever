# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Jamcord

Private self-hosted Discord music bot (Python).
Runs locally so a small group can listen to the same YouTube tracks together.

## Architecture
Modules in `src/` import each other by bare name (`import audio`), which works because `python src/bot.py` puts `src/` on the import path.

- `bot.py` — entry point. `setup_hook` loads the `Music` cog; `on_ready` (first time only) and `on_guild_join` sync slash commands to each server separately. Commands are never synced globally, because per-server sync is instant.
- `config.py` — reads `.env` into a frozen `Settings` dataclass. `.env` lives in the project root from source, or next to `Jamcord.exe` when packaged (`app_dir()`). With no token, it prints a setup guide, opens the Developer Portal and prompts for one. If Discord rejects a token, `bot.py` calls `forget_token()` so the next start asks again.
- `music.py` — the `Music` cog: slash commands, plus a `guild_id → Session` map. A `Session` holds the `GuildPlayer`, the text channel and the current now-playing message. It replaces that card whenever the player reports a track change, and leaves voice when the bot is alone.
- `player.py` — `GuildPlayer`: one per server, owns the queue, `VoiceClient` and elapsed-time tracking. It has no Discord UI code; it reports changes through the `on_track_change(track | None)` callback. A track that ends on its own within `_FAILED_START_SECONDS` (not skipped or stopped) counts as failed: it's put back at the front of the queue and fetched again with a fresh URL, up to `_MAX_RETRIES` times, without posting a new card. When a track ends, discord.py calls `_on_track_end` from its audio thread, which schedules `play_next` back on the event loop. Skip/stop work by calling `voice.stop()` and letting that callback advance the queue. An `asyncio.Lock` stops two commands from starting playback at once.
- `ui.py` — all presentation: embeds (now playing, added to queue, queue) and the `PlayerControls` button view. Control buttons and `/skip` `/stop` `/leave` only work for users in the bot's voice channel.
- `audio.py` — yt-dlp lookups (`find_track` for metadata, `get_stream` right before playback). yt-dlp is blocking, so calls run through `asyncio.to_thread`.
- `streaming.py` — `Stream.to_audio_source()` builds the discord.py audio source. See the yt-dlp workarounds below.

## Packaging (Windows app for non-developers)
- `.github/workflows/build.yml` runs PyInstaller on `windows-latest` (manual run, or on `v*` tags → GitHub Release). Output: `Jamcord-windows.zip` holding `Jamcord.exe`, `_internal/`, `tools/` (ffmpeg, deno) and `packaging/START HERE.txt`.
- At startup `bot.py` puts `<app dir>/tools` first on PATH, so the bundled ffmpeg and Deno are found. In packaged mode it also waits for Enter before closing, so errors stay readable.
- Build deps are in `requirements-build.txt`. To test-build locally (Linux binary, but the same bundling): `.venv/bin/pyinstaller --noconfirm --name Jamcord --paths src --collect-all davey src/bot.py`.
- Keep `packaging/START HERE.txt` in plain non-technical language; it's written for someone who isn't a developer.

## yt-dlp workarounds
- yt-dlp needs a JS runtime (Deno) plus `yt-dlp-ejs` (from `yt-dlp[default]`) to solve YouTube's JS challenges. The packaged app bundles both. The preferred `visionos` client doesn't need them; they're used by the fallback to yt-dlp's default clients.
- Stream URLs expire after a few hours, so the queue stores the page URL and the stream URL is resolved right before playback (`audio.get_stream`).
- **YouTube client choice (`audio._CLIENTS_BY_ATTEMPT`).** With a JS runtime available, yt-dlp's default clients are `tv_samsung, visionos, web`, and it often picks the TV client's audio (`c=TVHTML5` in the URL), which returned 403 on the Windows app even through yt-dlp's own HTTP client. Without a JS runtime it uses only `visionos`, which has been reliable. So lookups force `player_client=["visionos"]`, fall back to yt-dlp's defaults if visionos can't handle a video, and the player's last retry (`attempt=2`) uses the defaults too. If 403s come back, check the `c=` parameter of the failing URL first.
- **FFmpeg never downloads from YouTube directly.** Handing it googlevideo URLs gave random 403s on Windows: FFmpeg exit code 3436169992 is AVERROR_HTTP_FORBIDDEN. Instead `streaming.ChunkedReader` fetches the bytes through yt-dlp's own HTTP client (`YoutubeDL.urlopen`) in ~10 MB `Range` requests with retries, the same way yt-dlp's downloader does. The bytes are piped into FFmpeg (`pipe=True`), which only repackages them.
- `ChunkedReader.readinto` must never raise. discord.py's `_pipe_writer` thread doesn't catch read errors, so FFmpeg would wait forever for input. Failures are returned as end-of-stream (`failed = True`), and the player's retry takes over. 4xx errors (except 429) aren't retried with the same URL.
- Live streams (`is_live`, or a non-http protocol such as HLS) can't be fetched in ranges, so they go to FFmpeg directly, with yt-dlp's `http_headers` and reconnect flags.
- Audio quality: yt-dlp prefers Opus, and when `acodec == "opus"` the source uses `codec="copy"`, so Discord gets YouTube's audio without re-encoding. Don't use `FFmpegOpusAudio.from_probe`: its ffprobe request goes to YouTube directly.

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

## Tests
- `pip install -r requirements-dev.txt`, then `pytest` (all tests), `pytest tests/test_player.py` (one file) or `pytest -k retry` (by name). They're fast and need no network: yt-dlp, the voice client and the HTTP server are faked.
- `tests/conftest.py` has the shared fakes: `FakeVoice`, the `stream_lookups` and `player_with_changes` fixtures, and `finish_current_track()`, which simulates a track ending after N seconds.
- `pytest.ini` puts `src/` on the path and enables `asyncio_mode = auto`, so tests can be plain `async def`.
- CI: `.github/workflows/tests.yml` runs pytest on Ubuntu and Windows for every push. `build.yml` runs it before building, so a failing build is never published.
If YouTube playback breaks, try `pip install -U yt-dlp` first (requirements.txt intentionally doesn't pin it).

# Jamcord

A private, self-hosted Discord music bot. Run it on your own machine and listen to YouTube together in a voice channel. Your bot token never leaves your computer.

## Commands

| Command | What it does |
| --- | --- |
| `/play <url or search>` | Play a YouTube link or the top search result, or add it to the queue |
| `/skip` | Skip the current track |
| `/stop` | Stop playback and clear the queue |
| `/queue` | Show what's playing and what's next (only you see it) |
| `/nowplaying` | Bring the now-playing card and its buttons back to the bottom of the chat |
| `/leave` | Disconnect from the voice channel |

Each new track gets a now-playing card with the thumbnail, a progress bar and ⏸ ⏭ ⏹ 📜 buttons. Only people in the bot's voice channel can use the controls. The bot leaves on its own a minute after everyone else has left.

## Requirements

- Python 3.10+
- ffmpeg on your PATH (`sudo apt install ffmpeg` on Debian/Ubuntu)
- On Debian/Ubuntu also: `sudo apt install python3-venv`

## Setup

### 1. Create the Discord bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) → **New Application**.
2. Open the **Bot** tab → **Reset Token** → copy the token. It is shown only once.
3. Open **OAuth2** → **URL Generator**:
   - Scopes: `bot` and `applications.commands`
   - Bot permissions: Connect, Speak, Send Messages, Embed Links
4. Open the generated URL and invite the bot to your server.

### 2. Configure

```bash
cp .env.example .env
```

Set `DISCORD_TOKEN` in `.env`. That's the only setting: on startup the bot registers its slash commands in every server it's in, so they show up right away.

### 3. Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python src/bot.py
```

The bot is online only while this process is running.

### Adding the bot to more servers

On startup the bot logs an invite link (`Invite me to another server: …`). Open it, pick the server, and the slash commands appear there right away. No config changes are needed.

## Troubleshooting

- **Playback suddenly stops working:** YouTube changes often. Update yt-dlp first: `pip install -U yt-dlp`.
- **"Can't register commands in …" warning on startup:** the bot was invited without the `applications.commands` scope. Invite it again with the URL from step 1.
- **Commands don't show up:** restart the bot and reload Discord (Ctrl+R).

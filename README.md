# Jamcord

A private, self-hosted Discord music bot. Run it on your own machine and listen to YouTube together in a voice channel. Your bot token never leaves your computer.

## Commands

| Command | What it does |
| --- | --- |
| `/play <url or search>` | Play a YouTube link or the top search result, or add it to the queue |
| `/skip` | Skip the current track |
| `/stop` | Stop playback and clear the queue |
| `/queue` | Show what's playing and what's next |
| `/nowplaying` | Show the current track |
| `/leave` | Disconnect from the voice channel |

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
   - Bot permissions: Connect, Speak, Send Messages
4. Open the generated URL and invite the bot to your server.

### 2. Configure

```bash
cp .env.example .env
```

Set `DISCORD_TOKEN` in `.env`. Optionally set `GUILD_ID` to your server's ID so slash commands appear instantly. Without it, Discord can take up to an hour to show them. (To get the ID: in Discord, Settings → Advanced → Developer Mode, then right-click the server → Copy Server ID.)

### 3. Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python src/bot.py
```

The bot is online only while this process is running.

## Troubleshooting

- **Playback suddenly stops working:** YouTube changes often. Update yt-dlp first: `pip install -U yt-dlp`.
- **`403 Forbidden (error code: 50001): Missing Access` on startup:** the bot isn't in the server from `GUILD_ID`, or it was invited without the `applications.commands` scope. Invite it again with the URL from step 1.
- **Commands don't show up:** set `GUILD_ID`, restart the bot, and reload Discord (Ctrl+R).

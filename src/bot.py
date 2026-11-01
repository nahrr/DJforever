"""Entry point: python src/bot.py"""

import logging
import os
import traceback
import webbrowser

import discord
from discord.ext import commands

import config
from music import Music

log = logging.getLogger(__name__)


class JamcordBot(commands.Bot):
    def __init__(self) -> None:
        # Default intents cover guilds and voice states, which is all a
        # slash-command music bot needs (no message content).
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=discord.Intents.default(),
            # Shown under the bot's name in the member list: "Listening to /play".
            activity=discord.Activity(type=discord.ActivityType.listening, name="/play"),
        )
        self._commands_synced = False

    async def setup_hook(self) -> None:
        """Runs once after login, before the bot connects to Discord's gateway."""
        await self.add_cog(Music(self))

    async def on_ready(self) -> None:
        log.info("Logged in as %s", self.user)
        # on_ready fires again after reconnects, so only do this the first time.
        if not self._commands_synced:
            self._commands_synced = True
            invite_url = self._invite_url()
            if not self.guilds:
                log.info("I'm not in any server yet. Opening the invite page: %s", invite_url)
                webbrowser.open(invite_url)
            else:
                log.info("Invite me to another server: %s", invite_url)
            for guild in self.guilds:
                await self._sync_commands(guild)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        await self._sync_commands(guild)

    def _invite_url(self) -> str:
        """The link for adding the bot to a server, with the scopes and permissions it needs."""
        permissions = discord.Permissions(connect=True, speak=True, send_messages=True, embed_links=True)
        return discord.utils.oauth_url(
            self.application_id, permissions=permissions, scopes=("bot", "applications.commands")
        )

    async def _sync_commands(self, guild: discord.Guild) -> None:
        """Register the slash commands in one server.

        Per-server commands show up instantly, while global ones can take up
        to an hour. Syncing to every server the bot is in gives the best of
        both, and is fine for a bot in a handful of servers.
        """
        self.tree.copy_global_to(guild=guild)
        try:
            synced = await self.tree.sync(guild=guild)
        except discord.Forbidden:
            log.warning(
                "Can't register commands in %s. Invite the bot again with the 'applications.commands' scope.",
                guild.name,
            )
            return
        log.info("Synced %d commands to %s", len(synced), guild.name)


def _use_bundled_tools() -> None:
    """The packaged app ships ffmpeg and Deno in a "tools" folder; put it first on PATH so they're found."""
    tools = config.app_dir() / "tools"
    if tools.is_dir():
        os.environ["PATH"] = f"{tools}{os.pathsep}{os.environ.get('PATH', '')}"


def main() -> None:
    _use_bundled_tools()
    try:
        settings = config.load_settings()
        bot = JamcordBot()
        print("Starting Jamcord. Keep this window open while you listen; closing it stops the bot.\n")
        # bot.run sets up logging and handles Ctrl+C shutdown for us.
        # root_logger=True also shows our own log messages, not just discord.py's.
        bot.run(settings.discord_token, root_logger=True)
    except discord.LoginFailure:
        config.forget_token()
        print("\nDiscord didn't accept that token. Start Jamcord again and paste a fresh one.")
    except Exception:
        # Print the error before the "Press Enter" prompt so it's visible.
        traceback.print_exc()
        print("\nJamcord crashed. The error above explains why.")
    finally:
        # When double-clicked, the window would close instantly and hide any message.
        if config.is_packaged():
            input("\nPress Enter to close...")


# Only run when executed directly, not when imported (like a Main method).
if __name__ == "__main__":
    main()

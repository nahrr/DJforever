"""Entry point: python src/bot.py"""

import logging

import discord
from discord.ext import commands

from config import Settings, load_settings
from music import Music

log = logging.getLogger(__name__)


class JamcordBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        # Default intents cover guilds and voice states, which is all a
        # slash-command music bot needs (no message content).
        super().__init__(command_prefix=commands.when_mentioned, intents=discord.Intents.default())
        self.settings = settings

    async def setup_hook(self) -> None:
        """Runs once after login, before the bot connects to Discord's gateway."""
        await self.add_cog(Music(self))

        if self.settings.guild_id:
            guild = discord.Object(id=self.settings.guild_id)
            self.tree.copy_global_to(guild=guild)
            try:
                synced = await self.tree.sync(guild=guild)
            except discord.Forbidden:
                raise SystemExit(
                    f"Can't register commands in server {self.settings.guild_id}. Check that GUILD_ID is the "
                    "server ID and that the bot was invited with the 'bot' and 'applications.commands' scopes."
                ) from None
            log.info("Synced %d commands to guild %s", len(synced), self.settings.guild_id)
        else:
            synced = await self.tree.sync()
            log.info("Synced %d commands globally (may take up to an hour to appear)", len(synced))

    async def on_ready(self) -> None:
        log.info("Logged in as %s", self.user)


def main() -> None:
    settings = load_settings()
    bot = JamcordBot(settings)
    # bot.run sets up logging and handles Ctrl+C shutdown for us.
    # root_logger=True also shows our own log messages, not just discord.py's.
    bot.run(settings.discord_token, root_logger=True)


# Only run when executed directly, not when imported (like a Main method).
if __name__ == "__main__":
    main()

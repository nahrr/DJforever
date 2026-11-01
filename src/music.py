"""Slash commands for music playback.

A Cog is discord.py's way of grouping related commands and their state,
similar to a controller class in ASP.NET.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

import audio
from player import GuildPlayer

log = logging.getLogger(__name__)

_QUEUE_PREVIEW_LENGTH = 10


class MissingVoicePermissionsError(Exception):
    def __init__(self, channel_name: str) -> None:
        super().__init__(channel_name)
        self.channel_name = channel_name


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.players: dict[int, GuildPlayer] = {}  # keyed by guild ID

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        """Reply with a short message when a command crashes, instead of leaving Discord "thinking" forever."""
        log.error("/%s failed", interaction.command.name if interaction.command else "?", exc_info=error)
        message = "Something went wrong. Check the bot's log for details."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    def _get_player(self, interaction: discord.Interaction) -> GuildPlayer | None:
        player = self.players.get(interaction.guild_id)
        if player and not player.voice.is_connected():
            # The bot was disconnected (kicked, moved, network drop); forget the old state.
            del self.players[interaction.guild_id]
            return None
        return player

    async def _join_user_channel(self, interaction: discord.Interaction) -> GuildPlayer | None:
        """Connect to (or move to) the caller's voice channel and return its player."""
        user_voice = interaction.user.voice
        if user_voice is None or user_voice.channel is None:
            return None

        channel = user_voice.channel
        permissions = channel.permissions_for(interaction.guild.me)
        if not (permissions.connect and permissions.speak):
            raise MissingVoicePermissionsError(channel.name)

        player = self._get_player(interaction)
        if player is None:
            voice = await channel.connect(self_deaf=True)
            player = GuildPlayer(voice)
            self.players[interaction.guild_id] = player
        elif player.voice.channel != channel:
            await player.voice.move_to(channel)
        return player

    @app_commands.command(description="Play a YouTube URL or search query")
    @app_commands.describe(query="YouTube URL or search words")
    @app_commands.guild_only()
    async def play(self, interaction: discord.Interaction, query: str) -> None:
        # Lookups can take longer than Discord's 3-second reply window, so
        # "defer" first (shows "thinking...") and send the real reply later.
        await interaction.response.defer()

        try:
            player = await self._join_user_channel(interaction)
        except MissingVoicePermissionsError as error:
            await interaction.followup.send(f"I'm not allowed to join and speak in **{error.channel_name}**.")
            return
        if player is None:
            await interaction.followup.send("Join a voice channel first.")
            return

        try:
            track = await audio.find_track(query, requested_by=interaction.user.display_name)
        except audio.TrackNotFoundError:
            await interaction.followup.send(f"Couldn't find anything for **{query}**.")
            return

        await player.add(track)
        if player.current is track:
            await interaction.followup.send(f"▶️ Now playing **{track.title}** ({track.duration_text})")
        else:
            await interaction.followup.send(
                f"➕ Queued **{track.title}** ({track.duration_text}), position {len(player.queue)}"
            )

    @app_commands.command(description="Skip the current track")
    @app_commands.guild_only()
    async def skip(self, interaction: discord.Interaction) -> None:
        player = self._get_player(interaction)
        if player is None or not player.is_active:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)
            return

        skipped = player.current
        player.skip()
        await interaction.response.send_message(f"⏭️ Skipped **{skipped.title if skipped else 'track'}**")

    @app_commands.command(description="Stop playback and clear the queue")
    @app_commands.guild_only()
    async def stop(self, interaction: discord.Interaction) -> None:
        player = self._get_player(interaction)
        if player is None:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)
            return

        player.stop()
        await interaction.response.send_message("⏹️ Stopped and cleared the queue.")

    @app_commands.command(description="Show the queue")
    @app_commands.guild_only()
    async def queue(self, interaction: discord.Interaction) -> None:
        player = self._get_player(interaction)
        if player is None or (player.current is None and not player.queue):
            await interaction.response.send_message("The queue is empty.", ephemeral=True)
            return

        lines = []
        if player.current:
            lines.append(f"**Now playing:** {player.current.title} ({player.current.duration_text})\n")

        upcoming = list(player.queue)
        for position, track in enumerate(upcoming[:_QUEUE_PREVIEW_LENGTH], start=1):
            lines.append(f"`{position}.` {track.title} ({track.duration_text}) · {track.requested_by}")
        if len(upcoming) > _QUEUE_PREVIEW_LENGTH:
            lines.append(f"…and {len(upcoming) - _QUEUE_PREVIEW_LENGTH} more")

        embed = discord.Embed(title="Queue", description="\n".join(lines), color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed)

    @app_commands.command(description="Show the current track")
    @app_commands.guild_only()
    async def nowplaying(self, interaction: discord.Interaction) -> None:
        player = self._get_player(interaction)
        if player is None or player.current is None:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)
            return

        track = player.current
        await interaction.response.send_message(
            f"🎵 **{track.title}** ({track.duration_text}) · requested by {track.requested_by}\n{track.webpage_url}"
        )

    @app_commands.command(description="Leave the voice channel")
    @app_commands.guild_only()
    async def leave(self, interaction: discord.Interaction) -> None:
        player = self.players.pop(interaction.guild_id, None)
        if player is None:
            await interaction.response.send_message("I'm not in a voice channel.", ephemeral=True)
            return

        await player.disconnect()
        await interaction.response.send_message("👋 Left the voice channel.")

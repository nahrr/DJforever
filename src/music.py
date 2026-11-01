"""Slash commands for music playback.

A Cog is discord.py's way of grouping related commands and their state,
similar to a controller class in ASP.NET.
"""

import asyncio
import functools
import logging
from dataclasses import dataclass

import discord
from discord import app_commands
from discord.ext import commands

import audio
import ui
from audio import Track
from player import GuildPlayer

log = logging.getLogger(__name__)

# How long the bot stays in a voice channel after everyone else has left.
_ALONE_TIMEOUT_SECONDS = 60

# Channels where slash commands can be used and messages posted.
MessageChannel = discord.TextChannel | discord.VoiceChannel | discord.StageChannel | discord.Thread


class MissingVoicePermissionsError(Exception):
    def __init__(self, channel_name: str) -> None:
        super().__init__(channel_name)
        self.channel_name = channel_name


@dataclass
class Session:
    """Everything the bot tracks for one server while it's in a voice channel."""

    player: GuildPlayer
    channel: MessageChannel  # where now-playing cards are posted
    now_playing_message: discord.Message | discord.PartialMessage | None = None


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.sessions: dict[int, Session] = {}  # keyed by guild ID

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

    # ---------- Commands ----------

    @app_commands.command(description="Play a YouTube URL or search query")
    @app_commands.describe(query="YouTube URL or search words")
    @app_commands.guild_only()
    async def play(self, interaction: discord.Interaction, query: str) -> None:
        # Lookups can take longer than Discord's 3-second reply window, so
        # "defer" first (shows "thinking...") and send the real reply later.
        await interaction.response.defer()

        try:
            session = await self._join_user_channel(interaction)
        except MissingVoicePermissionsError as error:
            await interaction.followup.send(f"I'm not allowed to join and speak in **{error.channel_name}**.")
            return
        if session is None:
            await interaction.followup.send("Join a voice channel first.")
            return

        try:
            track = await audio.find_track(query, requester_id=interaction.user.id)
        except audio.TrackNotFoundError:
            await interaction.followup.send(f"Couldn't find anything for **{query}**.")
            return

        await session.player.add(track)

        if session.player.current is not track:
            await interaction.followup.send(embed=ui.added_to_queue_embed(track, session.player))
            await self._refresh_now_playing(session)
        elif session.now_playing_message:
            # The now-playing card was already posted, so the "thinking..." reply isn't needed.
            await interaction.delete_original_response()
        else:
            # Posting the card failed (likely missing permissions); fall back to plain text.
            await interaction.followup.send(f"▶️ Now playing **{track.title}**")

    @app_commands.command(description="Skip the current track")
    @app_commands.guild_only()
    async def skip(self, interaction: discord.Interaction) -> None:
        session = await self._get_controllable_session(interaction)
        if session is None:
            return
        skipped = session.player.current
        session.player.skip()
        await interaction.response.send_message(f"⏭️ Skipped **{skipped.title if skipped else 'track'}**")

    @app_commands.command(description="Stop playback and clear the queue")
    @app_commands.guild_only()
    async def stop(self, interaction: discord.Interaction) -> None:
        session = await self._get_controllable_session(interaction)
        if session is None:
            return
        session.player.stop()
        await interaction.response.send_message("⏹️ Stopped and cleared the queue.")

    @app_commands.command(description="Show the queue")
    @app_commands.guild_only()
    async def queue(self, interaction: discord.Interaction) -> None:
        session = self._get_session(interaction.guild_id)
        if session is None or (session.player.current is None and not session.player.queue):
            await interaction.response.send_message("The queue is empty.", ephemeral=True)
            return
        await interaction.response.send_message(embed=ui.queue_embed(session.player), ephemeral=True)

    @app_commands.command(description="Show the current track with player controls")
    @app_commands.guild_only()
    async def nowplaying(self, interaction: discord.Interaction) -> None:
        session = self._get_session(interaction.guild_id)
        if session is None or session.player.current is None:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)
            return

        # Move the card (and its buttons) down to the bottom of the chat.
        await interaction.response.send_message(
            embed=ui.now_playing_embed(session.player), view=ui.PlayerControls(session.player)
        )
        await self._delete_now_playing(session)
        message = await interaction.original_response()
        session.channel = interaction.channel
        # Store it as a plain channel message: interaction replies can only be
        # edited/deleted through the interaction for 15 minutes.
        session.now_playing_message = interaction.channel.get_partial_message(message.id)

    @app_commands.command(description="Leave the voice channel")
    @app_commands.guild_only()
    async def leave(self, interaction: discord.Interaction) -> None:
        session = await self._get_controllable_session(interaction)
        if session is None:
            return
        await self._end_session(interaction.guild_id)
        await interaction.response.send_message("👋 Left the voice channel.")

    # ---------- Events ----------

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        """Clean up when the bot is disconnected, and leave when everyone else has left."""
        session = self.sessions.get(member.guild.id)
        if session is None:
            return

        if member.id == self.bot.user.id:
            if after.channel is None:  # kicked from voice or connection lost
                await self._end_session(member.guild.id)
            return

        bot_channel = session.player.voice.channel
        someone_left = before.channel == bot_channel and after.channel != bot_channel
        if not someone_left or not _is_alone(bot_channel):
            return

        await asyncio.sleep(_ALONE_TIMEOUT_SECONDS)
        still_same_session = self.sessions.get(member.guild.id) is session
        if still_same_session and _is_alone(session.player.voice.channel):
            await self._end_session(member.guild.id)
            try:
                await session.channel.send("👋 Left the voice channel since everyone else did.", delete_after=60)
            except discord.HTTPException:
                pass

    # ---------- Session helpers ----------

    def _get_session(self, guild_id: int | None) -> Session | None:
        session = self.sessions.get(guild_id)
        if session and not session.player.voice.is_connected():
            # Disconnected without us noticing; forget the old state.
            del self.sessions[guild_id]
            return None
        return session

    async def _get_controllable_session(self, interaction: discord.Interaction) -> Session | None:
        """Return the session if the caller may control it; otherwise reply with why not."""
        session = self._get_session(interaction.guild_id)
        if session is None:
            await interaction.response.send_message("I'm not playing anything.", ephemeral=True)
            return None
        if not ui.is_listening(interaction.user, session.player.voice.channel):
            await interaction.response.send_message("Join my voice channel to control playback.", ephemeral=True)
            return None
        return session

    async def _join_user_channel(self, interaction: discord.Interaction) -> Session | None:
        """Connect to (or move to) the caller's voice channel and return its session."""
        user_voice = interaction.user.voice
        if user_voice is None or user_voice.channel is None:
            return None

        channel = user_voice.channel
        permissions = channel.permissions_for(interaction.guild.me)
        if not (permissions.connect and permissions.speak):
            raise MissingVoicePermissionsError(channel.name)

        session = self._get_session(interaction.guild_id)
        if session is None:
            voice = await channel.connect(self_deaf=True)
            # functools.partial pre-fills the guild ID, like a C# lambda capturing it.
            on_track_change = functools.partial(self._on_track_change, interaction.guild_id)
            session = Session(player=GuildPlayer(voice, on_track_change), channel=interaction.channel)
            self.sessions[interaction.guild_id] = session
        elif session.player.voice.channel != channel:
            await session.player.voice.move_to(channel)
        return session

    async def _end_session(self, guild_id: int) -> None:
        session = self.sessions.pop(guild_id, None)
        if session is None:
            return
        await self._delete_now_playing(session)
        await session.player.disconnect()

    # ---------- Now-playing card ----------

    async def _on_track_change(self, guild_id: int, track: Track | None) -> None:
        """Replace the old now-playing card with a new one (or none when the queue ends)."""
        session = self.sessions.get(guild_id)
        if session is None:
            return
        await self._delete_now_playing(session)
        # The track may already have ended while we were busy (e.g. it failed
        # right away), so only post a card for what's actually playing now.
        if track is None or session.player.current is not track:
            return
        try:
            session.now_playing_message = await session.channel.send(
                embed=ui.now_playing_embed(session.player), view=ui.PlayerControls(session.player)
            )
        except discord.HTTPException as error:
            log.warning("Couldn't post the now-playing card: %s", error)

    async def _refresh_now_playing(self, session: Session) -> None:
        """Update the card, e.g. so "Up next" shows a newly queued track."""
        if session.now_playing_message is None or session.player.current is None:
            return
        try:
            await session.now_playing_message.edit(embed=ui.now_playing_embed(session.player))
        except discord.HTTPException as error:
            log.warning("Couldn't update the now-playing card: %s", error)

    async def _delete_now_playing(self, session: Session) -> None:
        message, session.now_playing_message = session.now_playing_message, None
        if message is None:
            return
        try:
            await message.delete()
        except discord.HTTPException:
            pass  # someone already deleted it


def _is_alone(channel: discord.abc.Connectable | None) -> bool:
    """True if no humans are left in the voice channel."""
    return channel is not None and not any(not member.bot for member in channel.members)

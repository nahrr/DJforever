"""How the bot looks in Discord: embeds (message cards) and the player buttons.

Keeping all presentation here means music.py only deals with behavior.
"""

import logging

import discord

from audio import Track, format_duration
from player import GuildPlayer

log = logging.getLogger(__name__)

ACCENT_COLOR = discord.Color.from_rgb(139, 92, 246)  # violet
PAUSED_COLOR = discord.Color.from_rgb(113, 113, 122)  # grey

_PROGRESS_BAR_WIDTH = 16
_QUEUE_PREVIEW_LENGTH = 10
_MAX_LINK_TITLE_LENGTH = 55
_MAX_EMBED_TITLE_LENGTH = 256  # Discord's limit


def is_listening(user: discord.User | discord.Member, channel: discord.abc.Connectable | None) -> bool:
    """True if the user is in the given voice channel."""
    return isinstance(user, discord.Member) and user.voice is not None and user.voice.channel == channel


# ---------- Embeds ----------


def now_playing_embed(player: GuildPlayer) -> discord.Embed:
    track = player.current
    if track is None:
        raise ValueError("now_playing_embed needs a track that's playing")

    paused = player.is_paused
    embed = discord.Embed(
        title=_truncate(track.title, _MAX_EMBED_TITLE_LENGTH),
        url=track.webpage_url,
        description=_progress_bar(player.elapsed_seconds, track.duration_seconds),
        color=PAUSED_COLOR if paused else ACCENT_COLOR,
    )
    embed.set_author(name="⏸  Paused" if paused else "♪  Now playing")
    embed.add_field(name="Requested by", value=f"<@{track.requester_id}>")
    if track.uploader:
        embed.add_field(name="Channel", value=discord.utils.escape_markdown(track.uploader))

    up_next = player.queue[0] if player.queue else None
    embed.add_field(name="Up next", value=_link(up_next) if up_next else "Nothing yet. Use `/play` to add more.", inline=False)

    if track.thumbnail_url:
        embed.set_image(url=track.thumbnail_url)
    embed.set_footer(text=_queue_summary(player))
    return embed


def added_to_queue_embed(track: Track, player: GuildPlayer) -> discord.Embed:
    embed = discord.Embed(
        title=_truncate(track.title, _MAX_EMBED_TITLE_LENGTH),
        url=track.webpage_url,
        color=ACCENT_COLOR,
    )
    embed.set_author(name="➕  Added to queue")
    embed.add_field(name="Position", value=f"#{_queue_position(track, player)}")
    embed.add_field(name="Duration", value=track.duration_text)
    wait = player.seconds_until(track)
    if wait is not None:
        embed.add_field(name="Plays in", value=f"~{format_duration(wait)}")
    if track.thumbnail_url:
        embed.set_thumbnail(url=track.thumbnail_url)
    return embed


def queue_embed(player: GuildPlayer) -> discord.Embed:
    lines: list[str] = []
    if player.current:
        lines.append(f"**Now playing**\n{_link(player.current)} · `{player.current.duration_text}`")

    upcoming = list(player.queue)
    if upcoming:
        lines.append("\n**Up next**")
        for position, track in enumerate(upcoming[:_QUEUE_PREVIEW_LENGTH], start=1):
            lines.append(f"`{position:>2}.` {_link(track)} · `{track.duration_text}` · <@{track.requester_id}>")
        hidden = len(upcoming) - _QUEUE_PREVIEW_LENGTH
        if hidden > 0:
            lines.append(f"*…and {hidden} more*")

    embed = discord.Embed(title="📜  Queue", description="\n".join(lines), color=ACCENT_COLOR)
    if player.current and player.current.thumbnail_url:
        embed.set_thumbnail(url=player.current.thumbnail_url)
    embed.set_footer(text=_queue_summary(player))
    return embed


# ---------- Buttons ----------


class PlayerControls(discord.ui.View):
    """The ⏸ ⏭ ⏹ 📜 buttons under the now-playing card."""

    def __init__(self, player: GuildPlayer) -> None:
        # timeout=None keeps the buttons working for as long as the bot runs.
        super().__init__(timeout=None)
        self.player = player
        self._update_pause_button()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Runs before every button click; returning False blocks the click."""
        if self.player.current is None or not self.player.voice.is_connected():
            await interaction.response.send_message("This player isn't active anymore.", ephemeral=True)
            return False
        if not is_listening(interaction.user, self.player.voice.channel):
            await interaction.response.send_message("Join my voice channel to use the controls.", ephemeral=True)
            return False
        return True

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        log.error("Button %s failed", item, exc_info=error)
        if not interaction.response.is_done():
            await interaction.response.send_message("Something went wrong.", ephemeral=True)

    # The decorator turns each method into a button. Inside the class, the
    # method name (e.g. self.pause_button) then refers to the Button object.
    @discord.ui.button(emoji="⏸️", style=discord.ButtonStyle.secondary)
    async def pause_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.player.is_paused:
            self.player.resume()
        else:
            self.player.pause()
        self._update_pause_button()
        await interaction.response.edit_message(embed=now_playing_embed(self.player), view=self)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary)
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        # Acknowledge the click; the new track's card replaces this message.
        await interaction.response.defer()
        self.player.skip()

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.secondary)
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        self.player.stop()

    @discord.ui.button(emoji="📜", style=discord.ButtonStyle.secondary)
    async def queue_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(embed=queue_embed(self.player), ephemeral=True)

    def _update_pause_button(self) -> None:
        self.pause_button.emoji = "▶️" if self.player.is_paused else "⏸️"


# ---------- Helpers ----------


def _progress_bar(elapsed: int, duration: int | None) -> str:
    if duration is None:
        return "🔴 **LIVE**"
    filled = round(_PROGRESS_BAR_WIDTH * min(elapsed / duration, 1)) if duration else 0
    bar = "▰" * filled + "▱" * (_PROGRESS_BAR_WIDTH - filled)
    return f"{bar}  `{format_duration(elapsed)} / {format_duration(duration)}`"


def _queue_summary(player: GuildPlayer) -> str:
    count = len(player.queue)
    if count == 0:
        return "Queue is empty"
    total = sum(track.duration_seconds or 0 for track in player.queue)
    noun = "track" if count == 1 else "tracks"
    return f"{count} {noun} in queue · {format_duration(total)} total"


def _queue_position(track: Track, player: GuildPlayer) -> int:
    for position, queued in enumerate(player.queue, start=1):
        if queued is track:
            return position
    return len(player.queue)


def _link(track: Track) -> str:
    """A markdown link to the track, with the title made safe for link text."""
    title = track.title.replace("[", "(").replace("]", ")")
    title = discord.utils.escape_markdown(_truncate(title, _MAX_LINK_TITLE_LENGTH))
    return f"[{title}]({track.webpage_url})"


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"

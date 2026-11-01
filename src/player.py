"""Per-server playback state: the queue, the current track and the voice connection."""

import asyncio
import logging
from collections import deque
from concurrent.futures import Future

import discord

import audio
from audio import Track

log = logging.getLogger(__name__)


class GuildPlayer:
    """Plays a queue of tracks in one Discord server (a "guild" in the API)."""

    def __init__(self, voice: discord.VoiceClient) -> None:
        self.voice = voice
        self.queue: deque[Track] = deque()
        self.current: Track | None = None
        self._loop = asyncio.get_running_loop()
        # Stops two commands from starting playback at the same time.
        self._lock = asyncio.Lock()

    @property
    def is_active(self) -> bool:
        return self.voice.is_playing() or self.voice.is_paused()

    async def add(self, track: Track) -> None:
        """Queue a track and start playing if nothing is playing yet."""
        self.queue.append(track)
        await self.play_next()

    def skip(self) -> None:
        # Stopping the voice client fires _on_track_end, which plays the next track.
        self.voice.stop()

    def stop(self) -> None:
        """Clear the queue and stop the current track."""
        self.queue.clear()
        self.voice.stop()

    async def disconnect(self) -> None:
        self.stop()
        await self.voice.disconnect()

    async def play_next(self) -> None:
        """Start the next queued track, unless something is already playing."""
        async with self._lock:
            if self.is_active or not self.voice.is_connected():
                return

            while self.queue:
                track = self.queue.popleft()
                try:
                    stream_url = await audio.get_stream_url(track)
                except audio.TrackNotFoundError:
                    log.warning("Skipping unplayable track: %s", track.title)
                    continue

                source = discord.FFmpegPCMAudio(stream_url, **audio.FFMPEG_OPTIONS)
                self.current = track
                self.voice.play(source, after=self._on_track_end)
                return

            self.current = None

    def _on_track_end(self, error: Exception | None) -> None:
        # discord.py calls this from its audio thread, not the event loop,
        # so the coroutine has to be handed back to the loop thread-safely.
        if error:
            log.error("Playback error: %s", error)
        future = asyncio.run_coroutine_threadsafe(self.play_next(), self._loop)
        # Errors inside the future would otherwise vanish silently.
        future.add_done_callback(_log_failure)


def _log_failure(future: "Future[None]") -> None:
    if not future.cancelled() and future.exception():
        log.error("Couldn't start the next track", exc_info=future.exception())

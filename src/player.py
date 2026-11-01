"""Per-server playback state: the queue, the current track and the voice connection.

This module knows nothing about how things look in Discord. It reports track
changes through a callback, and music.py decides what to show.
"""

import asyncio
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from concurrent.futures import Future

import discord

import audio
from audio import Track

log = logging.getLogger(__name__)

# Called with the new track when one starts, or None when the queue runs out.
TrackChangeCallback = Callable[[Track | None], Awaitable[None]]


class GuildPlayer:
    """Plays a queue of tracks in one Discord server (a "guild" in the API)."""

    def __init__(self, voice: discord.VoiceClient, on_track_change: TrackChangeCallback) -> None:
        self.voice = voice
        self.queue: deque[Track] = deque()
        self.current: Track | None = None
        self._on_track_change = on_track_change
        self._loop = asyncio.get_running_loop()
        # Stops two commands from starting playback at the same time.
        self._lock = asyncio.Lock()

        # For the progress bar. time.monotonic() is like C#'s Stopwatch:
        # it's unaffected by clock changes.
        self._started_at = 0.0
        self._paused_at: float | None = None
        self._paused_total = 0.0

    @property
    def is_active(self) -> bool:
        return self.voice.is_playing() or self.voice.is_paused()

    @property
    def is_paused(self) -> bool:
        return self.voice.is_paused()

    @property
    def elapsed_seconds(self) -> int:
        """How far into the current track playback is, not counting pauses."""
        if self.current is None:
            return 0
        now = self._paused_at if self._paused_at is not None else time.monotonic()
        return int(now - self._started_at - self._paused_total)

    def seconds_until(self, track: Track) -> int | None:
        """Estimated wait before a queued track starts, or None if unknown (e.g. a live stream is ahead)."""
        if self.current is None or self.current.duration_seconds is None:
            return None
        wait = self.current.duration_seconds - self.elapsed_seconds
        for queued in self.queue:
            if queued is track:
                return max(wait, 0)
            if queued.duration_seconds is None:
                return None
            wait += queued.duration_seconds
        return None

    async def add(self, track: Track) -> None:
        """Queue a track and start playing if nothing is playing yet."""
        self.queue.append(track)
        await self.play_next()

    def pause(self) -> None:
        if self.voice.is_playing():
            self.voice.pause()
            self._paused_at = time.monotonic()

    def resume(self) -> None:
        if self.voice.is_paused() and self._paused_at is not None:
            self.voice.resume()
            self._paused_total += time.monotonic() - self._paused_at
            self._paused_at = None

    def skip(self) -> None:
        # Stopping the voice client fires _on_track_end, which plays the next track.
        self.voice.stop()

    def stop(self) -> None:
        """Clear the queue and stop the current track."""
        self.queue.clear()
        self.voice.stop()

    async def disconnect(self) -> None:
        self.stop()
        # force=True also cleans up if the connection already dropped.
        await self.voice.disconnect(force=True)

    async def play_next(self) -> None:
        """Start the next queued track, unless something is already playing."""
        async with self._lock:
            if self.is_active or not self.voice.is_connected():
                return
            previous = self.current
            current = self.current = await self._start_next_playable()

        # Notify outside the lock so slow Discord calls don't hold up playback.
        if current is not previous:
            await self._on_track_change(current)

    async def _start_next_playable(self) -> Track | None:
        """Pop tracks until one starts playing. Returns None if the queue runs out."""
        while self.queue:
            track = self.queue.popleft()
            try:
                stream = await audio.get_stream(track)
            except audio.TrackNotFoundError:
                log.warning("Skipping unplayable track: %s", track.title)
                continue

            self.voice.play(stream.to_audio_source(), after=self._on_track_end)
            self._started_at = time.monotonic()
            self._paused_at = None
            self._paused_total = 0.0
            return track
        return None

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

"""Turns a resolved YouTube stream into audio that discord.py can play.

yt-dlp workaround: handing YouTube stream URLs straight to FFmpeg is
unreliable. Depending on which YouTube client yt-dlp used, FFmpeg's single
plain request can get 403 Forbidden, even when yt-dlp itself downloads the
same URL fine. So we fetch the bytes the way yt-dlp's own downloader does,
through yt-dlp's HTTP client in ~10 MB ranges with retries, and pipe them
into FFmpeg. FFmpeg then only repackages the audio and never talks to YouTube.

Live streams (HLS playlists) are the exception: they are handed to FFmpeg
directly, since they aren't one file that can be fetched in ranges.
"""

import io
import logging
import random
import shlex
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import discord
import yt_dlp
from yt_dlp.networking import Request
from yt_dlp.networking.exceptions import HTTPError

log = logging.getLogger(__name__)

# yt-dlp uses the same chunk size for YouTube. Each range is randomized a
# little (as yt-dlp does) so requests don't all look identical.
CHUNK_SIZE = 10 * 1024 * 1024
# Network hiccups mid-track are retried, resuming where the last read ended.
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 1.0

# For live streams only: lets FFmpeg reconnect if YouTube drops the connection.
_FFMPEG_RECONNECT = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"

# Opens an HTTP request and returns a response with .read(n) and .close().
Opener = Callable[[Request], io.IOBase]


@dataclass(frozen=True)
class Stream:
    """A resolved audio stream for one track."""

    url: str
    http_headers: dict[str, str] = field(default_factory=dict)
    is_opus: bool = False
    filesize: int | None = None
    is_live: bool = False

    def to_audio_source(self) -> discord.FFmpegOpusAudio:
        # Opus is Discord's own codec, so "copy" passes it through untouched:
        # no quality loss from re-encoding. Anything else is encoded to Opus.
        codec = "copy" if self.is_opus else None

        if self.is_live:
            return discord.FFmpegOpusAudio(
                self.url, codec=codec, before_options=self._live_before_options(), options="-vn"
            )

        # yt-dlp's HTTP client, so requests match yt-dlp's own downloads.
        ydl = yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True})
        reader = ChunkedReader(ydl.urlopen, self.url, self.http_headers, self.filesize, on_close=ydl.close)
        return _PipedOpusAudio(reader, codec=codec)

    def _live_before_options(self) -> str:
        options = _FFMPEG_RECONNECT
        if self.http_headers:
            headers = "".join(f"{name}: {value}\r\n" for name, value in self.http_headers.items())
            options += f" -headers {shlex.quote(headers)}"
        return options


class _PipedOpusAudio(discord.FFmpegOpusAudio):
    """FFmpeg audio fed from a ChunkedReader, which is closed when playback ends."""

    def __init__(self, reader: "ChunkedReader", codec: str | None) -> None:
        # pipe=True: discord.py reads from `reader` in a thread and feeds FFmpeg's stdin.
        super().__init__(reader, pipe=True, codec=codec, options="-vn")
        self._reader = reader

    def cleanup(self) -> None:
        # discord.py calls this when the track ends or is skipped.
        super().cleanup()
        self._reader.close()


class ChunkedReader(io.RawIOBase):
    """A read-only file that downloads a URL in HTTP ranges, retrying on errors.

    discord.py calls .read() on it from a background thread, so blocking
    network calls here are fine.
    """

    def __init__(
        self,
        opener: Opener,
        url: str,
        headers: dict[str, str] | None = None,
        filesize: int | None = None,
        chunk_size: int = CHUNK_SIZE,
        retry_delay: float = RETRY_DELAY_SECONDS,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._opener = opener
        self._on_close = on_close
        self._url = url
        self._headers = headers or {}
        self._filesize = filesize
        self._chunk_size = chunk_size
        self._retry_delay = retry_delay

        self._position = 0  # bytes delivered so far
        self._response: io.IOBase | None = None
        self._chunk_end = 0  # last byte (inclusive) of the current range
        self._finished = False
        self.failed = False  # True if the download gave up because of errors

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: memoryview) -> int:
        """Fill `buffer` with the next bytes. Returns 0 at the end of the stream.

        Never raises: discord.py's feeder thread doesn't catch read errors,
        and FFmpeg would then wait forever for more input. A failed download
        is reported as end-of-stream instead. The track ends early, and
        GuildPlayer retries it with a fresh URL.
        """
        failures = 0
        while not self._finished and not self.closed:
            try:
                if self._response is None:
                    self._open_next_chunk()
                    if self._finished:
                        break
                data = self._response.read(len(buffer))
            except Exception as error:
                failures += 1
                self._close_response()
                if self.closed:
                    break  # closed from another thread (track skipped); not an error
                if _is_permanent(error) or failures > MAX_RETRIES:
                    log.error("Giving up on audio stream after %d attempt(s): %s", failures, error)
                    self.failed = True
                    self._finished = True
                    break
                log.warning("Audio stream hiccup (%s); retrying %d/%d", error, failures, MAX_RETRIES)
                time.sleep(self._retry_delay)
                continue

            if data:
                size = len(data)
                buffer[:size] = data
                self._position += size
                return size

            # This range is used up. If it ended early, so did the file.
            ended_early = self._position <= self._chunk_end
            self._close_response()
            if ended_early or self._reached_known_end():
                self._finished = True
        return 0

    def close(self) -> None:
        if self.closed:
            return
        self._close_response()
        if self._on_close:
            self._on_close()
        super().close()

    def _open_next_chunk(self) -> None:
        if self._reached_known_end():
            self._finished = True
            return

        # Same idea as yt-dlp: vary each range's size by up to 5%.
        size = random.randint(int(self._chunk_size * 0.95), self._chunk_size)
        end = self._position + size - 1
        if self._filesize is not None:
            end = min(end, self._filesize - 1)

        headers = {**self._headers, "Range": f"bytes={self._position}-{end}"}
        try:
            self._response = self._opener(Request(self._url, headers=headers))
        except HTTPError as error:
            if error.status == 416:  # "Range Not Satisfiable": we're past the end
                self._finished = True
                return
            raise
        self._chunk_end = end

    def _reached_known_end(self) -> bool:
        return self._filesize is not None and self._position >= self._filesize

    def _close_response(self) -> None:
        if self._response is not None:
            try:
                self._response.close()
            except Exception:
                pass
            self._response = None


def _is_permanent(error: Exception) -> bool:
    """Client errors like 403 Forbidden won't fix themselves by retrying the same URL."""
    return isinstance(error, HTTPError) and 400 <= error.status < 500 and error.status != 429


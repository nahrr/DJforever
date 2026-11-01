"""YouTube lookups via yt-dlp.

yt-dlp is synchronous (blocking), so every call is pushed to a worker thread
with asyncio.to_thread to keep the bot's event loop responsive.
"""

import asyncio
from dataclasses import dataclass
from typing import Any

import yt_dlp

_YTDL_OPTIONS: dict[str, Any] = {
    # Prefer Opus: it's Discord's own codec, so the audio can be passed
    # through without re-encoding (see FFmpegOpusAudio.from_probe in player.py).
    "format": "bestaudio[acodec=opus]/bestaudio/best",
    "noplaylist": True,
    "default_search": "ytsearch",  # plain text becomes a YouTube search
    "quiet": True,
    "no_warnings": True,
}

# Passed to FFmpeg when streaming. The reconnect flags stop playback from
# cutting out when YouTube drops the connection mid-track.
FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",  # audio only
}


class TrackNotFoundError(Exception):
    """Raised when a URL or search query returns nothing playable."""


def format_duration(seconds: int | None) -> str:
    """Format seconds as m:ss or h:mm:ss. None means a live stream."""
    if seconds is None:
        return "live"
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02}:{seconds:02}"
    return f"{minutes}:{seconds:02}"


@dataclass(frozen=True)
class Track:
    title: str
    webpage_url: str
    duration_seconds: int | None  # None for live streams
    thumbnail_url: str | None
    uploader: str | None  # the YouTube channel name
    requester_id: int  # Discord user ID of whoever queued it

    @property
    def duration_text(self) -> str:
        return format_duration(self.duration_seconds)


def _extract_info(query: str) -> dict[str, Any]:
    with yt_dlp.YoutubeDL(_YTDL_OPTIONS) as ydl:
        try:
            info = ydl.extract_info(query, download=False)
        except yt_dlp.utils.DownloadError as error:
            raise TrackNotFoundError(str(error)) from error

    # Searches come back as a list of results; take the first one.
    if info and "entries" in info:
        entries = [entry for entry in info["entries"] if entry]
        info = entries[0] if entries else None

    if not info:
        raise TrackNotFoundError(f"No results for: {query}")
    return info


async def find_track(query: str, requester_id: int) -> Track:
    """Look up a YouTube URL or search query and return its metadata."""
    info = await asyncio.to_thread(_extract_info, query)
    duration = info.get("duration")
    return Track(
        title=info.get("title", "Unknown title"),
        webpage_url=info.get("webpage_url") or query,
        duration_seconds=int(duration) if duration else None,
        thumbnail_url=info.get("thumbnail"),
        uploader=info.get("uploader") or info.get("channel"),
        requester_id=requester_id,
    )


async def get_stream_url(track: Track) -> str:
    """Resolve a direct audio stream URL for a track.

    yt-dlp workaround: YouTube stream URLs expire after a few hours, so we
    resolve the stream right before playing instead of when the track is
    queued. Otherwise tracks deep in a long queue could fail to play.
    """
    info = await asyncio.to_thread(_extract_info, track.webpage_url)
    return info["url"]

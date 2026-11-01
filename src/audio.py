"""YouTube lookups via yt-dlp.

yt-dlp is synchronous (blocking), so every call is pushed to a worker thread
with asyncio.to_thread to keep the bot's event loop responsive.
"""

import asyncio
from dataclasses import dataclass
from typing import Any

import yt_dlp

from streaming import Stream

_YTDL_OPTIONS: dict[str, Any] = {
    # Prefer Opus: it's Discord's own codec, so the audio can be passed
    # through without re-encoding (see streaming.Stream.to_audio_source).
    "format": "bestaudio[acodec=opus]/bestaudio/best",
    "noplaylist": True,
    "default_search": "ytsearch",  # plain text becomes a YouTube search
    "quiet": True,
    "no_warnings": True,
}

# yt-dlp workaround: which YouTube "client" yt-dlp pretends to be decides
# which stream URLs it gets. With a JS runtime (Deno) available, yt-dlp's
# defaults include TV clients whose URLs often return 403 Forbidden. The
# visionos client doesn't need Deno and has been reliable, so try it first.
# The first retry tries it again with a fresh URL; the last one falls back to
# yt-dlp's default clients (None = yt-dlp decides).
_PREFERRED_CLIENTS = ["visionos"]
_CLIENTS_BY_ATTEMPT: tuple[list[str] | None, ...] = (_PREFERRED_CLIENTS, _PREFERRED_CLIENTS, None)


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


def _extract_info(query: str, clients: list[str] | None = _PREFERRED_CLIENTS) -> dict[str, Any]:
    """Look up a URL or search with yt-dlp.

    If the given clients can't handle the video (some are age-restricted or
    region-locked for one client but not another), fall back to yt-dlp's defaults.
    """
    try:
        return _extract_info_with(query, clients)
    except TrackNotFoundError:
        if clients is None:
            raise
        return _extract_info_with(query, None)


def _extract_info_with(query: str, clients: list[str] | None) -> dict[str, Any]:
    options = dict(_YTDL_OPTIONS)
    if clients:
        options["extractor_args"] = {"youtube": {"player_client": clients}}
    with yt_dlp.YoutubeDL(options) as ydl:
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


async def get_stream(track: Track, attempt: int = 0) -> Stream:
    """Resolve the audio stream for a track.

    yt-dlp workaround: YouTube stream URLs expire after a few hours, so we
    resolve the stream right before playing instead of when the track is
    queued. Otherwise tracks deep in a long queue could fail to play.

    `attempt` counts retries after a failed start; later attempts use other
    YouTube clients (see _CLIENTS_BY_ATTEMPT).
    """
    clients = _CLIENTS_BY_ATTEMPT[min(attempt, len(_CLIENTS_BY_ATTEMPT) - 1)]
    info = await asyncio.to_thread(_extract_info, track.webpage_url, clients)
    return Stream(
        url=info["url"],
        http_headers=info.get("http_headers") or {},
        is_opus=info.get("acodec") == "opus",
        filesize=info.get("filesize"),
        # Live streams and other playlist formats (HLS) can't be fetched in byte ranges.
        is_live=bool(info.get("is_live")) or info.get("protocol") not in ("http", "https"),
    )

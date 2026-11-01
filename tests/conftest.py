"""Shared test helpers. pytest loads this file automatically."""

import pytest

import audio
from audio import Track
from player import GuildPlayer


class FakeVoice:
    """Stands in for discord.VoiceClient: records what it was asked to play."""

    def __init__(self) -> None:
        self.channel = None
        self.connected = True
        self.playing = False
        self.paused = False
        self.played: list[object] = []

    def is_connected(self) -> bool:
        return self.connected

    def is_playing(self) -> bool:
        return self.playing

    def is_paused(self) -> bool:
        return self.paused

    def play(self, source: object, after) -> None:
        self.played.append(source)
        self.playing = True

    def stop(self) -> None:
        self.playing = self.paused = False

    def pause(self) -> None:
        self.playing, self.paused = False, True

    def resume(self) -> None:
        self.playing, self.paused = True, False


class FakeStream:
    def to_audio_source(self) -> object:
        return object()


def make_track(title: str = "Song", duration: int | None = 200, **overrides) -> Track:
    fields = dict(
        title=title,
        webpage_url=f"https://youtu.be/{title.replace(' ', '')}",
        duration_seconds=duration,
        thumbnail_url="https://i.ytimg.com/vi/x/hq.jpg",
        uploader="Some Channel",
        requester_id=1234,
    )
    fields.update(overrides)
    return Track(**fields)


@pytest.fixture
def stream_lookup_attempts() -> list[int]:
    """The `attempt` number of each stream lookup, in order."""
    return []


@pytest.fixture
def stream_lookups(monkeypatch, stream_lookup_attempts) -> list[Track]:
    """Replaces the YouTube lookup with a fake; returns the list of tracks looked up."""
    looked_up: list[Track] = []

    async def fake_get_stream(track: Track, attempt: int = 0) -> FakeStream:
        looked_up.append(track)
        stream_lookup_attempts.append(attempt)
        return FakeStream()

    monkeypatch.setattr(audio, "get_stream", fake_get_stream)
    return looked_up


@pytest.fixture
async def player_with_changes(stream_lookups):
    """A GuildPlayer on a FakeVoice, plus the list of track changes it reported."""
    changes: list[Track | None] = []

    async def on_track_change(track: Track | None) -> None:
        changes.append(track)

    player = GuildPlayer(FakeVoice(), on_track_change)
    return player, changes


async def finish_current_track(player: GuildPlayer, *, after_seconds: float) -> None:
    """Simulate the current track ending after playing for `after_seconds`.

    This is what discord.py's "after" callback leads to in real playback.
    """
    player._started_at -= after_seconds
    player.voice.playing = False
    await player.play_next()

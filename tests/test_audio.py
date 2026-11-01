"""YouTube lookups, with yt-dlp replaced by a fake (no network)."""

import pytest
import yt_dlp

import audio


class FakeYoutubeDL:
    """Returns whatever `result` is set to, like yt_dlp.YoutubeDL.extract_info would.

    `clients_used` records the YouTube clients each lookup asked for (None =
    yt-dlp's defaults). `failing_clients` makes lookups with those clients fail.
    """

    result: dict | None = None
    error: Exception | None = None
    failing_clients: list[list[str] | None] = []
    clients_used: list[list[str] | None] = []

    def __init__(self, options) -> None:
        self.clients = options.get("extractor_args", {}).get("youtube", {}).get("player_client")

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        pass

    def extract_info(self, query, download):
        FakeYoutubeDL.clients_used.append(self.clients)
        if FakeYoutubeDL.error or self.clients in FakeYoutubeDL.failing_clients:
            raise FakeYoutubeDL.error or yt_dlp.utils.DownloadError("not available for this client")
        return FakeYoutubeDL.result


@pytest.fixture(autouse=True)
def fake_ytdl(monkeypatch):
    FakeYoutubeDL.result, FakeYoutubeDL.error = None, None
    FakeYoutubeDL.failing_clients, FakeYoutubeDL.clients_used = [], []
    monkeypatch.setattr(audio.yt_dlp, "YoutubeDL", FakeYoutubeDL)


VIDEO = {
    "title": "Song",
    "webpage_url": "https://www.youtube.com/watch?v=abc",
    "duration": 213.4,
    "thumbnail": "https://i.ytimg.com/vi/abc/hq.jpg",
    "uploader": "Artist",
    "url": "https://rr1.googlevideo.com/videoplayback?x",
    "http_headers": {"User-Agent": "UA"},
    "acodec": "opus",
    "filesize": 3433755,
    "protocol": "https",
}


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(None, "live"), (0, "0:00"), (59, "0:59"), (213, "3:33"), (3600, "1:00:00"), (3725, "1:02:05")],
)
def test_format_duration(seconds, text):
    assert audio.format_duration(seconds) == text


async def test_find_track_reads_metadata():
    FakeYoutubeDL.result = VIDEO

    track = await audio.find_track("song", requester_id=42)

    assert track.title == "Song"
    assert track.duration_seconds == 213
    assert track.uploader == "Artist"
    assert track.requester_id == 42


async def test_search_takes_first_result():
    FakeYoutubeDL.result = {"entries": [None, VIDEO, {**VIDEO, "title": "Second"}]}

    track = await audio.find_track("song", requester_id=1)

    assert track.title == "Song"


async def test_search_without_results_raises():
    FakeYoutubeDL.result = {"entries": []}

    with pytest.raises(audio.TrackNotFoundError):
        await audio.find_track("nothing", requester_id=1)


async def test_ytdlp_errors_become_track_not_found():
    FakeYoutubeDL.error = yt_dlp.utils.DownloadError("Video unavailable")

    with pytest.raises(audio.TrackNotFoundError):
        await audio.find_track("https://youtu.be/gone", requester_id=1)


async def test_get_stream_for_regular_video():
    FakeYoutubeDL.result = VIDEO
    track = await audio.find_track("song", requester_id=1)

    stream = await audio.get_stream(track)

    assert stream.is_opus
    assert not stream.is_live
    assert stream.filesize == 3433755
    assert stream.http_headers == {"User-Agent": "UA"}


@pytest.mark.parametrize("live_info", [{"is_live": True}, {"protocol": "m3u8_native"}])
async def test_get_stream_detects_live_streams(live_info):
    FakeYoutubeDL.result = {**VIDEO, **live_info}
    track = await audio.find_track("live", requester_id=1)

    assert (await audio.get_stream(track)).is_live


async def test_lookups_prefer_the_visionos_client():
    FakeYoutubeDL.result = VIDEO

    await audio.find_track("song", requester_id=1)

    assert FakeYoutubeDL.clients_used == [["visionos"]]


async def test_falls_back_to_default_clients_when_preferred_one_fails():
    FakeYoutubeDL.result = VIDEO
    FakeYoutubeDL.failing_clients = [["visionos"]]

    track = await audio.find_track("age restricted song", requester_id=1)

    assert track.title == "Song"
    assert FakeYoutubeDL.clients_used == [["visionos"], None]


async def test_retries_switch_to_default_clients_on_the_last_attempt():
    FakeYoutubeDL.result = VIDEO
    track = await audio.find_track("song", requester_id=1)
    FakeYoutubeDL.clients_used.clear()

    for attempt in range(3):
        await audio.get_stream(track, attempt=attempt)

    assert FakeYoutubeDL.clients_used == [["visionos"], ["visionos"], None]

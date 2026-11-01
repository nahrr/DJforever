"""YouTube lookups, with yt-dlp replaced by a fake (no network)."""

import pytest
import yt_dlp

import audio


class FakeYoutubeDL:
    """Returns whatever `result` is set to, like yt_dlp.YoutubeDL.extract_info would."""

    result: dict | None = None
    error: Exception | None = None

    def __init__(self, options) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        pass

    def extract_info(self, query, download):
        if FakeYoutubeDL.error:
            raise FakeYoutubeDL.error
        return FakeYoutubeDL.result


@pytest.fixture(autouse=True)
def fake_ytdl(monkeypatch):
    FakeYoutubeDL.result, FakeYoutubeDL.error = None, None
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

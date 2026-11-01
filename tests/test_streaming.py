"""ChunkedReader: downloading audio in HTTP ranges, and surviving errors."""

import io
import re

from yt_dlp.networking import Response
from yt_dlp.networking.exceptions import HTTPError, TransportError

import streaming
from streaming import ChunkedReader

CONTENT = bytes(range(256)) * 40  # 10,240 bytes of recognizable data
CHUNK = 1000


def http_error(status: int) -> HTTPError:
    return HTTPError(Response(io.BytesIO(b""), "https://example.test", {}, status=status))


class FakeServer:
    """Serves CONTENT, honoring Range headers like YouTube does.

    `failures` is a list of errors to raise on the next requests, in order.
    `drop_after` makes the next response break after that many bytes.
    """

    def __init__(self, content: bytes = CONTENT) -> None:
        self.content = content
        self.requests: list[dict[str, str]] = []
        self.failures: list[Exception] = []
        self.drop_after: int | None = None

    def open(self, request) -> io.IOBase:
        self.requests.append(dict(request.headers))
        if self.failures:
            raise self.failures.pop(0)

        start, end = map(int, re.fullmatch(r"bytes=(\d+)-(\d+)", request.headers["Range"]).groups())
        if start >= len(self.content):
            raise http_error(416)
        body = self.content[start : end + 1]

        if self.drop_after is not None:
            body, self.drop_after = body[: self.drop_after], None
            return _BreakingResponse(body)
        return io.BytesIO(body)


class _BreakingResponse(io.BytesIO):
    """Returns its bytes, then fails like a dropped connection."""

    def read(self, size: int = -1) -> bytes:
        data = super().read(size)
        if not data:
            raise TransportError("connection reset")
        return data


def read_all(reader: ChunkedReader) -> bytes:
    out = bytearray()
    while chunk := reader.read(300):
        out += chunk
    return bytes(out)


def make_reader(server: FakeServer, filesize: int | None = len(CONTENT), **kwargs) -> ChunkedReader:
    return ChunkedReader(
        server.open, "https://example.test/audio", {"User-Agent": "test"}, filesize,
        chunk_size=CHUNK, retry_delay=0, **kwargs,
    )


def test_reads_whole_file_in_several_ranges():
    server = FakeServer()
    reader = make_reader(server)

    assert read_all(reader) == CONTENT
    assert len(server.requests) > 1
    assert not reader.failed


def test_sends_original_headers_with_each_range():
    server = FakeServer()
    read_all(make_reader(server))

    assert all(r["User-Agent"] == "test" for r in server.requests)
    assert server.requests[0]["Range"].startswith("bytes=0-")


def test_unknown_size_stops_when_a_range_comes_back_short():
    server = FakeServer()
    assert read_all(make_reader(server, filesize=None)) == CONTENT


def test_unknown_size_stops_on_range_not_satisfiable(monkeypatch):
    # Content that ends exactly on a range boundary, so the next request gets 416.
    monkeypatch.setattr(streaming.random, "randint", lambda low, high: high)  # exact ranges
    server = FakeServer(CONTENT[: CHUNK * 2])
    reader = make_reader(server, filesize=None)

    assert read_all(reader) == CONTENT[: CHUNK * 2]
    assert not reader.failed


def test_resumes_after_dropped_connection_without_losing_bytes():
    server = FakeServer()
    server.drop_after = 450
    reader = make_reader(server)

    assert read_all(reader) == CONTENT
    assert not reader.failed
    # The retry asked for the bytes right after the ones already received.
    assert server.requests[1]["Range"].startswith("bytes=450-")


def test_retries_transient_errors_when_opening():
    server = FakeServer()
    server.failures = [TransportError("timeout"), http_error(503)]
    reader = make_reader(server)

    assert read_all(reader) == CONTENT
    assert not reader.failed


def test_forbidden_ends_stream_without_raising():
    # Raising would hang FFmpeg (discord.py doesn't catch read errors), so a
    # permanent error must look like end-of-stream instead.
    server = FakeServer()
    server.failures = [http_error(403)]
    reader = make_reader(server)

    assert reader.read(100) == b""
    assert reader.failed
    assert len(server.requests) == 1  # 403 isn't retried with the same URL


def test_gives_up_after_too_many_transient_errors():
    server = FakeServer()
    server.failures = [TransportError("timeout")] * (streaming.MAX_RETRIES + 1)
    reader = make_reader(server)

    assert reader.read(100) == b""
    assert reader.failed


def test_close_runs_cleanup_once_and_stops_reading():
    closed = []
    server = FakeServer()
    reader = make_reader(server, on_close=lambda: closed.append(True))
    reader.read(10)

    reader.close()
    reader.close()

    assert closed == [True]
    # discord.py's feeder thread may still call read() right as a skip closes
    # the reader; it must get end-of-stream, not an exception.
    assert reader.read(10) == b""

"""GuildPlayer: queueing, track changes, retries and timing."""

import audio
import player as player_module
from conftest import finish_current_track, make_track


async def test_first_track_starts_and_is_announced(player_with_changes):
    player, changes = player_with_changes
    song = make_track("First")

    await player.add(song)

    assert player.current is song
    assert changes == [song]
    assert len(player.voice.played) == 1


async def test_second_track_waits_in_queue(player_with_changes):
    player, changes = player_with_changes
    first, second = make_track("First"), make_track("Second")

    await player.add(first)
    await player.add(second)

    assert player.current is first
    assert list(player.queue) == [second]
    assert changes == [first]


async def test_next_track_plays_when_current_one_ends(player_with_changes):
    player, changes = player_with_changes
    first, second = make_track("First"), make_track("Second")
    await player.add(first)
    await player.add(second)

    await finish_current_track(player, after_seconds=200)

    assert player.current is second
    assert changes == [first, second]


async def test_queue_running_out_reports_none(player_with_changes):
    player, changes = player_with_changes
    song = make_track()
    await player.add(song)

    await finish_current_track(player, after_seconds=200)

    assert player.current is None
    assert changes == [song, None]


async def test_track_failing_right_away_is_retried_with_a_fresh_stream(player_with_changes, stream_lookups):
    player, changes = player_with_changes
    song, next_song = make_track("Flaky"), make_track("Next")
    await player.add(song)
    await player.add(next_song)

    await finish_current_track(player, after_seconds=0.5)

    assert player.current is song
    assert stream_lookups == [song, song]  # looked up again for a fresh URL
    assert list(player.queue) == [next_song]
    assert changes == [song]  # no new card for a retry


async def test_retries_count_up_the_attempt_number(player_with_changes, stream_lookup_attempts):
    # audio.get_stream uses the attempt number to switch YouTube clients.
    player, _ = player_with_changes
    await player.add(make_track("Flaky"))

    for _ in range(player_module._MAX_RETRIES):
        await finish_current_track(player, after_seconds=0.5)

    assert stream_lookup_attempts == list(range(player_module._MAX_RETRIES + 1))


async def test_gives_up_after_max_retries_and_moves_on(player_with_changes, stream_lookups):
    player, changes = player_with_changes
    song, next_song = make_track("Broken"), make_track("Next")
    await player.add(song)
    await player.add(next_song)

    for _ in range(player_module._MAX_RETRIES + 1):
        await finish_current_track(player, after_seconds=0.5)

    assert player.current is next_song
    assert stream_lookups.count(song) == 1 + player_module._MAX_RETRIES


async def test_retry_counter_resets_for_each_track(player_with_changes, stream_lookups):
    player, _ = player_with_changes
    first, second = make_track("First"), make_track("Second")
    await player.add(first)
    await player.add(second)

    await finish_current_track(player, after_seconds=0.5)   # first: one retry
    await finish_current_track(player, after_seconds=200)   # first: ends normally
    await finish_current_track(player, after_seconds=0.5)   # second: still gets retries

    assert player.current is second
    assert stream_lookups == [first, first, second, second]


async def test_skipping_right_after_start_is_not_retried(player_with_changes):
    player, changes = player_with_changes
    first, second = make_track("First"), make_track("Second")
    await player.add(first)
    await player.add(second)

    player.skip()
    await finish_current_track(player, after_seconds=0.5)

    assert player.current is second


async def test_stop_clears_queue_without_retrying(player_with_changes):
    player, changes = player_with_changes
    await player.add(make_track("First"))
    await player.add(make_track("Second"))

    player.stop()
    await finish_current_track(player, after_seconds=0.5)

    assert player.current is None
    assert not player.queue


async def test_very_short_track_ending_quickly_is_not_a_failure(player_with_changes, stream_lookups):
    player, _ = player_with_changes
    blip = make_track("Blip", duration=2)
    await player.add(blip)

    await finish_current_track(player, after_seconds=2)

    assert player.current is None
    assert stream_lookups == [blip]


async def test_unplayable_track_is_skipped(player_with_changes, monkeypatch):
    player, changes = player_with_changes
    broken, good = make_track("Broken"), make_track("Good")
    real_get_stream = audio.get_stream

    async def get_stream(track, attempt=0):
        if track is broken:
            raise audio.TrackNotFoundError("gone")
        return await real_get_stream(track, attempt)

    monkeypatch.setattr(audio, "get_stream", get_stream)
    player.queue.extend([broken, good])
    await player.play_next()

    assert player.current is good
    assert changes == [good]


async def test_elapsed_time_does_not_count_pauses(player_with_changes):
    player, _ = player_with_changes
    await player.add(make_track())
    # Timeline: started 130 s ago, played 30 s, then paused for 100 s until now.
    player._started_at -= 130
    player.pause()
    player._paused_at -= 100
    player.resume()

    assert player.elapsed_seconds == 30


async def test_seconds_until_adds_up_remaining_and_queued_time(player_with_changes):
    player, _ = player_with_changes
    current, a, b = make_track("Now", 200), make_track("A", 100), make_track("B", 50)
    await player.add(current)
    await player.add(a)
    await player.add(b)
    player._started_at -= 50  # 150 s left of the current track

    assert player.seconds_until(a) == 150
    assert player.seconds_until(b) == 250


async def test_seconds_until_is_unknown_behind_a_live_stream(player_with_changes):
    player, _ = player_with_changes
    await player.add(make_track("Now"))
    live, after = make_track("Live", duration=None), make_track("After")
    await player.add(live)
    await player.add(after)

    assert player.seconds_until(after) is None

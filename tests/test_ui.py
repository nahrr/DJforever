"""Embeds: they build in every state, and titles can't break the markdown."""

import pytest

import ui
from conftest import make_track


async def test_now_playing_card(player_with_changes):
    player, _ = player_with_changes
    await player.add(make_track("Current"))
    await player.add(make_track("Up Next"))

    embed = ui.now_playing_embed(player).to_dict()

    assert embed["title"] == "Current"
    assert "Now playing" in embed["author"]["name"]
    assert embed["image"]["url"].startswith("https://")
    fields = {f["name"]: f["value"] for f in embed["fields"]}
    assert fields["Requested by"] == "<@1234>"
    assert "Up Next" in fields["Up next"]


async def test_now_playing_card_when_paused(player_with_changes):
    player, _ = player_with_changes
    await player.add(make_track())
    player.pause()

    embed = ui.now_playing_embed(player)

    assert "Paused" in embed.author.name
    assert embed.color == ui.PAUSED_COLOR


async def test_now_playing_card_for_live_stream(player_with_changes):
    player, _ = player_with_changes
    await player.add(make_track(duration=None, thumbnail_url=None, uploader=None))

    embed = ui.now_playing_embed(player).to_dict()

    assert "LIVE" in embed["description"]
    assert "image" not in embed


async def test_now_playing_card_needs_a_track(player_with_changes):
    player, _ = player_with_changes
    with pytest.raises(ValueError):
        ui.now_playing_embed(player)


async def test_long_titles_are_shortened(player_with_changes):
    player, _ = player_with_changes
    await player.add(make_track("x" * 400))

    assert len(ui.now_playing_embed(player).title) == 256


async def test_queue_card_lists_tracks_and_hides_the_rest(player_with_changes):
    player, _ = player_with_changes
    await player.add(make_track("Current"))
    for i in range(15):
        await player.add(make_track(f"Track {i}"))

    description = ui.queue_embed(player).description

    assert "Track 0" in description and "Track 9" in description
    assert "Track 10" not in description
    assert "and 5 more" in description


async def test_added_to_queue_card_shows_position_and_wait(player_with_changes):
    player, _ = player_with_changes
    await player.add(make_track("Current", 200))
    queued = make_track("Queued")
    await player.add(queued)

    fields = {f["name"]: f["value"] for f in ui.added_to_queue_embed(queued, player).to_dict()["fields"]}

    assert fields["Position"] == "#1"
    assert fields["Plays in"].startswith("~")


def test_link_text_is_made_safe():
    link = ui._link(make_track("Song [Official] *Video*"))
    title = link[1 : link.index("](")]

    assert "[" not in title and "]" not in title  # brackets would end the link early
    assert "\\*Video\\*" in title  # markdown escaped


@pytest.mark.parametrize(
    ("elapsed", "duration", "filled"),
    [(0, 200, 0), (100, 200, 8), (200, 200, 16), (500, 200, 16)],
)
def test_progress_bar(elapsed, duration, filled):
    bar = ui._progress_bar(elapsed, duration)
    assert bar.count("▰") == filled
    assert bar.count("▱") == 16 - filled

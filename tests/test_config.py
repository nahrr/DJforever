"""Token handling: validation, loading from .env and forgetting a bad token."""

import pytest

import config

# Clearly fake, with the right shape (three dot-separated parts, long enough).
# Built from pieces so secret scanners don't mistake it for a real token.
VALID_TOKEN = ".".join(["fake" * 6, "test" * 2, "not-a-real-token" * 3])


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    """Point config at a temporary .env and clear any token from the environment."""
    path = tmp_path / ".env"
    monkeypatch.setattr(config, "ENV_FILE", path)
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    return path


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(f"  {VALID_TOKEN}  ", VALID_TOKEN), (f'"{VALID_TOKEN}"', VALID_TOKEN), (f"'{VALID_TOKEN}'\n", VALID_TOKEN)],
)
def test_clean_token_strips_spaces_and_quotes(raw, expected):
    assert config.clean_token(raw) == expected


@pytest.mark.parametrize(
    ("token", "valid"),
    [
        (VALID_TOKEN, True),
        ("", False),
        ("your_bot_token_here", False),
        ("1566490404826910890", False),  # an application ID, a common mix-up
        ("a.b.c", False),  # right shape, too short
        ("abc..def" + "x" * 60, False),  # empty middle part
    ],
)
def test_looks_like_token(token, valid):
    assert config.looks_like_token(token) is valid


def test_loads_token_from_env_file(env_file):
    env_file.write_text(f"DISCORD_TOKEN={VALID_TOKEN}\n")

    assert config.load_settings().discord_token == VALID_TOKEN


def test_missing_token_without_a_terminal_exits_with_a_message(env_file, monkeypatch):
    monkeypatch.setattr(config.sys.stdin, "isatty", lambda: False, raising=False)

    with pytest.raises(SystemExit, match="DISCORD_TOKEN is missing"):
        config.load_settings()


def test_forget_token_removes_it_from_env_file(env_file):
    env_file.write_text(f"DISCORD_TOKEN={VALID_TOKEN}\nOTHER=keep\n")

    config.forget_token()

    contents = env_file.read_text()
    assert VALID_TOKEN not in contents
    assert "OTHER=keep" in contents

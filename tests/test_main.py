import sys

import pytest

import tubeupac.__main__ as cli
from tubeupac import __version__


@pytest.fixture
def captured(monkeypatch):
    """Capture TubeUp() construction and archive_urls() args without doing any work."""
    seen = {}

    class FakeTubeUp:
        def __init__(self, **kwargs):
            seen["init"] = kwargs

        def archive_urls(self, *args):
            seen["archive_urls"] = args
            yield "youtube-abc", {"title": "T"}

    monkeypatch.setattr(cli, "TubeUp", FakeTubeUp)
    return seen


def run_cli(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["tubeupac", *argv])
    cli.run()


def test_cli_maps_arguments(monkeypatch, captured, capsys):
    run_cli(
        monkeypatch,
        "https://www.youtube.com/watch?v=abc",
        "--metadata=collection:test",
        "--metadata=subject:a",
        "--metadata=subject:b",
        "--cookies=c.txt",
        "--proxy", "http://proxy:1",
        "--use-download-archive",
        "--ignore-existing-item",
        "--new-item-id", "newid",
        "--ydl-option-format", "best",
        "--ia-s3-access", "AK",
        "--ia-s3-secret", "SK",
        "--write-metadata",
        "--quiet",
    )

    assert captured["init"] == dict(
        verbose=False, output_template=None, ia_user=None, ia_s3_access="AK", ia_s3_secret="SK"
    )
    urls, metadata, cookie_file, proxy, user, password, use_archive, ignore_existing, \
        skip_download, recode, new_item_id, fmt, subslangs, write_metadata = captured["archive_urls"]
    assert urls == ["https://www.youtube.com/watch?v=abc"]
    assert metadata == {"collection": "test", "subject": ["a", "b"]}
    assert (cookie_file, proxy, user, password) == ("c.txt", "http://proxy:1", None, None)
    assert (use_archive, ignore_existing, skip_download) == (True, True, False)
    assert (recode, new_item_id, fmt, subslangs) == (None, "newid", "best", None)
    assert write_metadata is True
    assert "https://archive.org/details/youtube-abc" in capsys.readouterr().out


def test_cli_defaults(monkeypatch, captured):
    run_cli(monkeypatch, "https://example.com/v")
    assert captured["init"]["verbose"] is True
    assert captured["archive_urls"][1] == {}


def test_cli_subtitleslangs_takes_a_value(monkeypatch, captured):
    run_cli(monkeypatch, "https://example.com/v", "--ydl-option-subtitleslangs", "all,-live_chat")
    assert captured["archive_urls"][0] == ["https://example.com/v"]
    assert captured["archive_urls"][12] == "all,-live_chat"


def test_cli_exits_1_on_error(monkeypatch, captured):
    def boom(self, *args):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli.TubeUp, "archive_urls", boom)
    with pytest.raises(SystemExit) as exc:
        run_cli(monkeypatch, "https://example.com/v")
    assert exc.value.code == 1


def test_cli_version(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        run_cli(monkeypatch, "--version")
    assert exc.value.code in (None, 0)
    assert capsys.readouterr().out.strip() == __version__

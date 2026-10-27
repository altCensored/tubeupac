import pytest

from tubeupac.utils import (
    check_is_file_empty,
    get_itemname,
    key_value_to_dict,
    retry,
    retry_wrap,
    sanitize_identifier,
    update_extractor,
    update_id,
)


def test_preserve_valid_identifiers():
    valid = ["youtube--QBwhSklJks", "youtube-_--M04_mN-M", "youtube-Xy2jZABDB40"]
    assert [sanitize_identifier(x) for x in valid] == valid


def test_sanitize_bad_identifiers():
    bad = ["twitch:vod-v181464551", "twitch:clips-1003820974", "twitter:card-1192732384065708032"]
    expect = ["twitch-vod-v181464551", "twitch-clips-1003820974", "twitter-card-1192732384065708032"]
    assert [sanitize_identifier(x) for x in bad] == expect


def test_check_is_file_empty_when_file_is_empty(tmp_path):
    f = tmp_path / "empty.txt"
    f.write_text("")
    assert check_is_file_empty(str(f))


def test_check_is_file_empty_when_file_is_not_empty(tmp_path):
    f = tmp_path / "notempty.txt"
    f.write_text("just a text")
    assert not check_is_file_empty(str(f))


def test_check_is_file_empty_when_file_doesnt_exist():
    with pytest.raises(FileNotFoundError, match=r"^Path 'file_that_doesnt_exist.txt' doesn't exist$"):
        check_is_file_empty("file_that_doesnt_exist.txt")


@pytest.mark.parametrize(
    "infodict, new_item_id, expected",
    [
        ({"extractor": "youtube", "id": "abc"}, None, "youtube-abc"),
        ({"extractor": "youtube", "id": "abc", "display_id": "disp"}, None, "youtube-disp"),
        ({"extractor": "youtube+oauth2", "id": "abc"}, None, "youtube-abc"),
        ({"extractor": "bitchute", "id": "abc"}, "newid", "youtube-newid"),
        ({"extractor": "twitch:vod", "id": "v1"}, None, "twitch-vod-v1"),
    ],
)
def test_get_itemname(infodict, new_item_id, expected):
    assert get_itemname(infodict, new_item_id) == expected


def test_update_extractor():
    assert update_extractor("bitchute", None) == "bitchute"
    assert update_extractor("youtube+oauth2", None) == "youtube"
    assert update_extractor("bitchute", "x") == "youtube"


def test_update_id():
    assert update_id("abc", None) == "abc"
    assert update_id("abc", "new") == "new"


def test_key_value_to_dict_empty():
    assert key_value_to_dict([]) == {}


def test_key_value_to_dict_single_string():
    assert key_value_to_dict("collection:test") == {"collection": "test"}


def test_key_value_to_dict_value_may_contain_colon():
    assert key_value_to_dict(["source:https://x.example/a"]) == {"source": "https://x.example/a"}


def test_key_value_to_dict_repeated_key_becomes_list():
    assert key_value_to_dict(["subject:a", "subject:b", "title:t"]) == {"subject": ["a", "b"], "title": "t"}


def test_key_value_to_dict_missing_value():
    with pytest.raises(AssertionError):
        key_value_to_dict(["collection:"])


def flaky(failures, exc=ConnectionError):
    calls = []

    def f(*args):
        calls.append(args)
        if len(calls) <= failures:
            raise exc("fail %d" % len(calls))
        return "ok"

    return f, calls


def test_retry_succeeds_after_failures(sleeps):
    f, calls = flaky(2)
    assert retry(f, "p", retries=3, delay=5) == "ok"
    assert calls == [("p",)] * 3
    assert sleeps == [5, 5]


def test_retry_returns_none_when_exhausted(sleeps):
    f, calls = flaky(10)
    assert retry(f, "p", retries=3, delay=1) is None
    assert len(calls) == 3
    assert sleeps == [1, 1]


def test_retry_does_not_catch_unlisted_exceptions():
    f, _ = flaky(1, exc=KeyError)
    with pytest.raises(KeyError):
        retry(f, "p", exceptions=(ConnectionError,))


def test_retry_wrap_backs_off(sleeps):
    f, calls = flaky(2)
    assert retry_wrap(tries=3, delay=10, backoff=3, exceptions=(ConnectionError,))(f)() == "ok"
    assert len(calls) == 3
    assert sleeps == [10, 30]


def test_retry_wrap_reraises_on_last_try(sleeps):
    f, calls = flaky(10)
    with pytest.raises(ConnectionError):
        retry_wrap(tries=3, delay=1, exceptions=(ConnectionError,))(f)()
    assert len(calls) == 3


def test_retry_wrap_does_not_catch_unlisted_exceptions(sleeps):
    f, calls = flaky(1, exc=ValueError)
    with pytest.raises(ValueError):
        retry_wrap(tries=3, exceptions=(ConnectionError,))(f)()
    assert len(calls) == 1
    assert sleeps == []

import copy
import csv
import glob
import json
import logging
import os
import time
import types

import internetarchive
import pytest
import requests_mock
import urllib3.exceptions
from yt_dlp import YoutubeDL

import tubeupac.TubeUp as tubeup_module
from tubeupac import __version__
from tubeupac.TubeUp import DOWNLOAD_DIR_NAME, TubeUp

from .conftest import IA_CONFIG_PATH, UPLOAD_FILES_DIR, get_testfile_path
from .constants import info_dict_playlist, info_dict_video

SCANNER = "TubeUp Video Stream Mirroring Application {}".format(__version__)

MOUNTAIN = "Mountain_3_-_Video_Background_HD_1080p-6iRV8liah8A"
KDSN_URL = "https://www.youtube.com/watch?v=KdsN9YhkDrY"

MOUNTAIN_DESCRIPTION = (
    "Mountain 3 - Video Background HD 1080p<br>"
    "If you use this video please put credits to my "
    "channel in description:<br>https://www.youtube.com"
    "/channel/UCWpsozCMdAnfI16rZHQ9XDg<br>© Don't "
    "forget to SUBSCRIBE, LIKE, COMMENT and RATE. "
    "Hope you all enjoy!"
)
MOUNTAIN_SUBJECT = (
    "Youtube;video;Entertainment;Video Background;Footage;"
    "Animation;Cinema;stock video footage;Royalty "
    "free videos;Creative Commons videos;free movies "
    "online;youtube;HD;1080p;Amazing Nature;Mountain;"
)
MOUNTAIN_METADATA = {
    "mediatype": "movies",
    "channel": "http://www.youtube.com/channel/UCWpsozCMdAnfI16rZHQ9XDg",
    "creator": "Video Background",
    "collection": "opensource_movies",
    "title": "Mountain 3 - Video Background HD 1080p",
    "description": MOUNTAIN_DESCRIPTION,
    "date": "2015-01-05",
    "year": "2015",
    "subject": MOUNTAIN_SUBJECT,
    "originalurl": "https://www.youtube.com/watch?v=6iRV8liah8A",
    "licenseurl": "https://creativecommons.org/licenses/by/3.0/",
    "scanner": SCANNER,
}
KDSN_METADATA = {
    "mediatype": "movies",
    "creator": "RelaxingWorld",
    "channel": "http://www.youtube.com/channel/UCWpsozCMdAnfI16rZHQ9XDg",
    "collection": "opensource_movies",
    "title": "Epic Ramadan - Video Background HD1080p",
    "description": (
        "If you enjoy my work, please consider Subscribe to my NEW "
        "channel for more videos: <br>"
        "https://www.youtube.com/MusicForRelaxation?sub_confirmation=1 <br>"
        "▷ If you use this video, please put credits to my channel "
        "in description: <br>"
        "Source from RelaxingWorld: https://goo.gl/HsW75m<br>"
        "<br>"
        "▷ Also, do not forget to Subscribe to my channel. Thanks!"
    ),
    "date": "2016-06-25",
    "year": "2016",
    "subject": (
        "Youtube;video;Film & Animation;Video Background;"
        "Footage;Animation;Cinema;Royalty Free Videos;"
        "Stock Video Footage;Video Backdrops;"
        "Amazing Nature;youtube;HD;1080p;Creative Commons Videos;"
        "relaxing music;Ramadan;"
    ),
    "originalurl": KDSN_URL,
    "licenseurl": "",
    "scanner": SCANNER,
}


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def mocked_ydl_progress_hook(d):
    pass


def mock_ia_upload(m, ia_id, videobasename):
    """Mock every archive.org endpoint `internetarchive` hits for one upload."""
    # `internetarchive` checks the S3 upload limit before uploading.
    m.get(
        "https://s3.us.archive.org",
        content=b'{"over_limit": 0}',
        headers={"content-type": "application/json"},
    )
    m.get(
        "https://archive.org/metadata/%s" % ia_id,
        content=b"{}",
        headers={"content-type": "application/json"},
    )
    for file_path in glob.glob(videobasename + "*"):
        m.put(
            "https://s3.us.archive.org/%s/%s" % (ia_id, os.path.basename(file_path)),
            content=b"",
            headers={"content-type": "text/plain"},
        )


class FakeItem:
    def __init__(self, identifier, exists=False, upload_errors=()):
        self.identifier = identifier
        self.exists = exists
        self.upload_errors = list(upload_errors)
        self.upload_calls = []

    def upload(self, files, **kwargs):
        self.upload_calls.append((sorted(files), kwargs))
        if self.upload_errors:
            raise self.upload_errors.pop(0)


@pytest.fixture
def fake_items(monkeypatch):
    """Replace `internetarchive.get_item`; preset entries in the returned dict."""
    items = {}

    def get_item(identifier):
        return items.setdefault(identifier, FakeItem(identifier))

    monkeypatch.setattr(internetarchive, "get_item", get_item)
    return items


@pytest.fixture
def fake_ydl(monkeypatch):
    """Replace YoutubeDL in TubeUp with an offline fake fed from `FakeYDL.infos`."""

    class FakeYDL:
        infos = {}
        archived = set()
        instances = []

        def __init__(self, params):
            self.params = params
            self.extract_calls = []
            self.recorded = []
            # A real YoutubeDL is only used to render filenames from outtmpl.
            self._real = YoutubeDL(
                {"outtmpl": params["outtmpl"], "restrictfilenames": True, "quiet": True}
            )
            FakeYDL.instances.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=True):
            self.extract_calls.append((url, download))
            return copy.deepcopy(FakeYDL.infos[url])

        def prepare_filename(self, info):
            return self._real.prepare_filename(info)

        def in_download_archive(self, info):
            return info["id"] in FakeYDL.archived

        def record_download_archive(self, info):
            self.recorded.append(info["id"])

    monkeypatch.setattr(tubeup_module, "YoutubeDL", FakeYDL)
    return FakeYDL


# --- construction / dir_path -------------------------------------------------


def test_default_dir_path_is_under_home(isolated_fs):
    tu = TubeUp()
    expected_root = str(isolated_fs / "home" / ".tubeup")
    assert tu.dir_path == {
        "root": expected_root,
        "downloads": os.path.join(expected_root, DOWNLOAD_DIR_NAME),
    }
    assert os.path.isdir(tu.dir_path["downloads"])


def test_set_dir_path(tmp_path):
    root = str(tmp_path / "custom")
    tu = TubeUp(dir_path=root)
    assert tu.dir_path == {"root": root, "downloads": os.path.join(root, DOWNLOAD_DIR_NAME)}
    assert os.path.isdir(tu.dir_path["downloads"])


def test_set_dir_path_accepts_pathlike(tmp_path):
    tu = TubeUp(dir_path=tmp_path / "p")
    assert tu.dir_path["root"] == str(tmp_path / "p")


@pytest.mark.parametrize("bad", ["", "   ", None, 42])
def test_set_dir_path_rejects_invalid(bad):
    with pytest.raises(TubeUp.DirError):
        TubeUp(dir_path=bad)


def test_set_dir_path_rejects_root_that_is_a_file(tmp_path):
    f = tmp_path / "afile"
    f.write_text("keep me")
    with pytest.raises(TubeUp.DirError, match="already exists as a file"):
        TubeUp(dir_path=str(f))
    assert f.read_text() == "keep me"


def test_set_dir_path_rejects_downloads_that_is_a_file(tmp_path):
    (tmp_path / DOWNLOAD_DIR_NAME).write_text("keep me")
    with pytest.raises(TubeUp.DirError, match="already exists as a file"):
        TubeUp(dir_path=str(tmp_path))


def test_logger_quiet_mode():
    tu = TubeUp()
    assert isinstance(tu.logger, logging.Logger)
    assert tu.logger.level == logging.ERROR


def test_logger_verbose_mode():
    assert isinstance(TubeUp(verbose=True).logger, logging.Logger)


def test_s3_keys_default_to_none():
    tu = TubeUp()
    assert tu.ia_s3_access is None
    assert tu.ia_s3_secret is None


def test_ia_user_sets_config_path():
    tu = TubeUp(ia_user="root")
    assert tu.ia_config_path == os.path.join(
        os.path.expanduser("~root"), ".config", "internetarchive", "ia.ini"
    )


def test_custom_output_template(tmp_path):
    tu = TubeUp(dir_path=str(tmp_path), output_template="%(title)s.%(ext)s")
    opts = tu.generate_ydl_options(mocked_ydl_progress_hook)
    assert opts["outtmpl"] == os.path.join(tu.dir_path["downloads"], "%(title)s.%(ext)s")


# --- static helpers ----------------------------------------------------------


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://soundcloud.com/testurl", "opensource_audio"),
        ("https://www.youtube.com/watch?v=testVideo", "opensource_movies"),
    ],
)
def test_determine_collection_type(url, expected):
    assert TubeUp.determine_collection_type(url) == expected


@pytest.mark.parametrize(
    "meta, expected",
    [
        ({"license": "Attribution-ShareAlike"}, "https://creativecommons.org/licenses/by-sa/2.0/"),
        ({"license": "Some unknown license"}, None),
        ({"license": None}, ""),
        ({}, ""),
    ],
)
def test_determine_licenseurl(meta, expected):
    assert TubeUp.determine_licenseurl(meta) == expected


def test_create_basenames_from_ydl_info_dict_video():
    result = TubeUp().create_basenames_from_ydl_info_dict(YoutubeDL(), info_dict_video)
    assert result == {
        "Video and Blog Competition 2017 - Bank Indonesia & NET TV #BIGoesToCampus [hlG3LeFaQwU]"
    }


def test_create_basenames_from_ydl_info_dict_playlist():
    result = TubeUp().create_basenames_from_ydl_info_dict(YoutubeDL(), info_dict_playlist)
    assert result == {
        "Live Streaming Rafid Aslam [7gjgkH5iPaE]",
        "Live Streaming Rafid Aslam [q92kxPm-pqM]",
        "Cara Membuat Laptop Menjadi Hotspot WiFi Dengan CMD [YjFwMSDNphM]",
        "[CSO] Defeat Boss in Dead End With Thanatos 7 [EEm6MwXLse0]",
        "Cara Bermain Minecraft Multiplayer Dengan LAN [g2vTZ2ka-tM]",
        "Live Streaming Rafid Aslam [AXhuSS5_9YU]",
        "Cara Membuat Disk Baru di Komputer [KDOygJnK7Sw]",
        "Cara Mendownload Lewat Torrent [cC-9RghkvXs]",
    }


def test_create_basenames_strips_format_suffix():
    class StubYDL:
        def prepare_filename(self, info):
            return "/d/abc.f137.mp4"

    assert TubeUp().create_basenames_from_ydl_info_dict(StubYDL(), {"id": "abc"}) == {"/d/abc"}


# --- generate_ydl_options ----------------------------------------------------


def base_ydl_options(tu, verbose=False):
    return {
        "outtmpl": os.path.join(tu.dir_path["downloads"], "%(id)s.%(ext)s"),
        "restrictfilenames": True,
        "verbose": verbose,
        "quiet": not verbose,
        "progress_with_newline": True,
        "forcetitle": True,
        "continuedl": True,
        "retries": 9001,
        "fragment_retries": 9001,
        "forcejson": False,
        "writeinfojson": True,
        "writedescription": True,
        "writethumbnail": True,
        "writeannotations": True,
        "writesubtitles": True,
        "allsubtitles": True,
        "ignoreerrors": False,
        "fixup": "detect_or_warn",
        "nooverwrites": True,
        "consoletitle": True,
        "prefer_ffmpeg": True,
        "call_home": False,
        "logger": tu.logger,
        "usenetrc": True,
        "progress_hooks": [mocked_ydl_progress_hook],
    }


def test_generate_ydl_options():
    tu = TubeUp()
    assert tu.generate_ydl_options(mocked_ydl_progress_hook) == base_ydl_options(tu)


def test_generate_ydl_options_verbose():
    tu = TubeUp(verbose=True)
    assert tu.generate_ydl_options(mocked_ydl_progress_hook) == base_ydl_options(tu, verbose=True)


@pytest.mark.parametrize(
    "kwargs, delta",
    [
        ({"cookie_file": "c.txt"}, {"cookiefile": "c.txt"}),
        ({"proxy_url": "http://proxytest.com:8080"}, {"proxy": "http://proxytest.com:8080"}),
        (
            {"ydl_username": "testUsername", "ydl_password": "testPassword"},
            {"username": "testUsername", "password": "testPassword"},
        ),
        ({"ydl_option_format": "bestvideo+bestaudio"}, {"format": "bestvideo+bestaudio"}),
        ({"ydl_option_subtitleslangs": "all,-live_chat"}, {"subtitleslangs": "all,-live_chat"}),
        (
            {"extractor_args": {"youtube": {"player_client": ["mweb"]}}},
            {"extractor_args": {"youtube": {"player_client": ["mweb"]}}},
        ),
        (
            {"recode_video": "mp4"},
            {"postprocessors": [{"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}]},
        ),
        ({"skip_download": True}, {"skip_download": True}),
    ],
)
def test_generate_ydl_options_with_option(kwargs, delta):
    tu = TubeUp()
    result = tu.generate_ydl_options(mocked_ydl_progress_hook, **kwargs)
    assert result == {**base_ydl_options(tu), **delta}


def test_generate_ydl_options_with_download_archive():
    tu = TubeUp()
    result = tu.generate_ydl_options(mocked_ydl_progress_hook, use_download_archive=True)
    delta = {"download_archive": os.path.join(tu.dir_path["root"], ".ytdlarchive")}
    assert result == {**base_ydl_options(tu), **delta}


# --- create_archive_org_metadata_from_youtubedl_meta -------------------------


def test_metadata():
    vid_meta = load_json(get_testfile_path(MOUNTAIN + ".info.json"))
    assert TubeUp.create_archive_org_metadata_from_youtubedl_meta(vid_meta) == MOUNTAIN_METADATA


def test_metadata_description_text_null():
    vid_meta = load_json(get_testfile_path("description_text_null.json"))
    assert TubeUp.create_archive_org_metadata_from_youtubedl_meta(vid_meta)["description"] == ""


def test_metadata_no_uploader():
    vid_meta = load_json(get_testfile_path(MOUNTAIN + ".info_no_uploader.json"))
    expected = dict(MOUNTAIN_METADATA, creator="http://www.youtube.com/channel/UCWpsozCMdAnfI16rZHQ9XDg")
    assert TubeUp.create_archive_org_metadata_from_youtubedl_meta(vid_meta) == expected


def test_metadata_no_uploader_at_all():
    vid_meta = load_json(get_testfile_path(MOUNTAIN + ".info.json"))
    vid_meta["uploader"] = None
    vid_meta["uploader_url"] = None
    assert TubeUp.create_archive_org_metadata_from_youtubedl_meta(vid_meta)["creator"] == "tubeup.py"


def test_metadata_no_date(monkeypatch):
    # Pin "now" so the test can't straddle midnight / New Year.
    fake_time = types.SimpleNamespace(strftime=lambda fmt: time.strftime(fmt, time.gmtime(0)))
    monkeypatch.setattr(tubeup_module, "time", fake_time)
    vid_meta = load_json(get_testfile_path(MOUNTAIN + ".info_no_date.json"))
    expected = dict(MOUNTAIN_METADATA, date="1970-01-01", year="1970")
    assert TubeUp.create_archive_org_metadata_from_youtubedl_meta(vid_meta) == expected


def test_metadata_twitch_clips():
    vid_meta = load_json(get_testfile_path("EA_Play_2016_Live_from_the_Novo_Theatre-42850523.info.json"))
    assert TubeUp.create_archive_org_metadata_from_youtubedl_meta(vid_meta) == {
        "mediatype": "movies",
        "creator": "EA",
        "collection": "opensource_movies",
        "title": "EA Play 2016 Live from the Novo Theatre",
        "description": "",
        "date": "2016-06-12",
        "year": "2016",
        "subject": "TwitchClips;video;",
        "originalurl": "https://clips.twitch.tv/FaintLightGullWholeWheat",
        "licenseurl": "",
        "scanner": SCANNER,
    }


def test_metadata_mass_of_tags():
    vid_meta = load_json(get_testfile_path(MOUNTAIN + ".info.json"))
    vid_meta["tags"] = [f"t{i}" for i in range(0, 300)]
    result = TubeUp.create_archive_org_metadata_from_youtubedl_meta(vid_meta)
    assert len(result["subject"].encode("utf-8")) <= 255


def test_metadata_soundcloud_is_audio():
    vid_meta = load_json(get_testfile_path(MOUNTAIN + ".info.json"))
    vid_meta["webpage_url"] = "https://soundcloud.com/a/b"
    result = TubeUp.create_archive_org_metadata_from_youtubedl_meta(vid_meta)
    assert (result["mediatype"], result["collection"]) == ("audio", "opensource_audio")


def test_metadata_channel_url_fallback():
    vid_meta = load_json(get_testfile_path(MOUNTAIN + ".info.json"))
    del vid_meta["uploader_url"]
    vid_meta["channel_url"] = "https://www.youtube.com/channel/X"
    result = TubeUp.create_archive_org_metadata_from_youtubedl_meta(vid_meta)
    assert result["channel"] == "https://www.youtube.com/channel/X"


# --- get_resource_basenames (offline, fake YoutubeDL) ------------------------


def kdsn_info():
    return load_json(os.path.join(UPLOAD_FILES_DIR, "KdsN9YhkDrY.info.json"))


def test_get_resource_basenames_ignore_existing_item(tu, fake_ydl, fake_items):
    fake_ydl.infos[KDSN_URL] = kdsn_info()
    result = tu.get_resource_basenames([KDSN_URL], ignore_existing_item=True)
    assert result == {os.path.join(tu.dir_path["downloads"], "KdsN9YhkDrY")}
    assert fake_ydl.instances[0].extract_calls == [(KDSN_URL, True)]
    assert fake_items == {}  # no archive.org lookup


def test_get_resource_basenames_downloads_new_item(tu, fake_ydl, fake_items):
    fake_ydl.infos[KDSN_URL] = kdsn_info()
    result = tu.get_resource_basenames([KDSN_URL])
    assert result == {os.path.join(tu.dir_path["downloads"], "KdsN9YhkDrY")}
    assert fake_ydl.instances[0].extract_calls == [(KDSN_URL, False), (KDSN_URL, True)]
    assert list(fake_items) == ["youtube-KdsN9YhkDrY"]


def test_get_resource_basenames_skips_existing_item(root_dir, fake_ydl, fake_items):
    tu = TubeUp(dir_path=str(root_dir), verbose=True)
    fake_ydl.infos[KDSN_URL] = kdsn_info()
    fake_items["youtube-KdsN9YhkDrY"] = FakeItem("youtube-KdsN9YhkDrY", exists=True)
    assert tu.get_resource_basenames([KDSN_URL]) == set()
    ydl = fake_ydl.instances[0]
    assert ydl.extract_calls == [(KDSN_URL, False)]
    assert ydl.recorded == ["KdsN9YhkDrY"]


def test_get_resource_basenames_skips_download_archive(tu, fake_ydl, fake_items):
    fake_ydl.infos[KDSN_URL] = kdsn_info()
    fake_ydl.archived.add("KdsN9YhkDrY")
    assert tu.get_resource_basenames([KDSN_URL]) == set()
    assert fake_items == {}


def test_get_resource_basenames_new_item_id(tu, fake_ydl, fake_items):
    fake_ydl.infos[KDSN_URL] = kdsn_info()
    tu.get_resource_basenames([KDSN_URL], new_item_id="abc123")
    assert list(fake_items) == ["youtube-abc123"]


def test_get_resource_basenames_playlist(tu, fake_ydl, fake_items):
    playlist_url = "https://www.youtube.com/playlist?list=X"
    playlist = copy.deepcopy(info_dict_playlist)
    playlist["entries"].append(None)  # unavailable video
    fake_ydl.infos[playlist_url] = playlist
    for entry in info_dict_playlist["entries"]:
        fake_ydl.infos[entry["webpage_url"]] = entry

    result = tu.get_resource_basenames([playlist_url])

    expected = {os.path.join(tu.dir_path["downloads"], e["id"]) for e in info_dict_playlist["entries"]}
    assert result == expected
    assert len(fake_items) == len(info_dict_playlist["entries"])


def test_get_resource_basenames_ia_unreachable_raises(tu, fake_ydl, monkeypatch, sleeps):
    fake_ydl.infos[KDSN_URL] = kdsn_info()

    def get_item(identifier):
        raise ConnectionError("archive.org down")

    monkeypatch.setattr(internetarchive, "get_item", get_item)
    with pytest.raises(Exception, match="Could not check whether archive.org item youtube-KdsN9YhkDrY exists"):
        tu.get_resource_basenames([KDSN_URL])
    assert fake_ydl.instances[0].extract_calls == [(KDSN_URL, False)]  # nothing downloaded
    assert sleeps == [2, 2, 2, 2]


# --- upload_ia ---------------------------------------------------------------


def test_upload_ia_end_to_end(tu):
    """Real `internetarchive` upload path with HTTP mocked by requests_mock."""
    videobasename = os.path.join(tu.dir_path["downloads"], MOUNTAIN)
    with requests_mock.Mocker() as m:
        mock_ia_upload(m, "youtube-6iRV8liah8A", videobasename)
        result = tu.upload_ia(videobasename)

    assert result == ("youtube-6iRV8liah8A", MOUNTAIN_METADATA)
    assert glob.glob(videobasename + "*") == []  # uploaded files are removed


def test_upload_ia_uploads_all_files_with_config_keys(tu, fake_items):
    videobasename = os.path.join(tu.dir_path["downloads"], MOUNTAIN)
    expected_files = sorted(glob.glob(videobasename + "*"))

    tu.upload_ia(videobasename)

    [(files, kwargs)] = fake_items["youtube-6iRV8liah8A"].upload_calls
    assert files == expected_files
    assert (kwargs["access_key"], kwargs["secret_key"]) == ("accessKey", "secretKey")
    assert kwargs["metadata"] == MOUNTAIN_METADATA
    assert kwargs["delete"] is False


def test_upload_ia_cli_keys_override_config(root_dir, fake_items):
    tu = TubeUp(dir_path=str(root_dir), ia_config_path=IA_CONFIG_PATH, ia_s3_access="A", ia_s3_secret="S")
    tu.upload_ia(os.path.join(tu.dir_path["downloads"], MOUNTAIN))
    [(_, kwargs)] = fake_items["youtube-6iRV8liah8A"].upload_calls
    assert (kwargs["access_key"], kwargs["secret_key"]) == ("A", "S")


def test_upload_ia_missing_keys_raises(root_dir, tmp_path, fake_items):
    empty_config = tmp_path / "empty.ini"
    empty_config.write_text("")
    tu = TubeUp(dir_path=str(root_dir), ia_config_path=str(empty_config))
    with pytest.raises(Exception, match="not configured properly"):
        tu.upload_ia(os.path.join(tu.dir_path["downloads"], MOUNTAIN))
    assert fake_items["youtube-6iRV8liah8A"].upload_calls == []


def test_upload_ia_custom_meta_and_new_item_id(tu, fake_items):
    _, meta = tu.upload_ia(
        os.path.join(tu.dir_path["downloads"], MOUNTAIN),
        custom_meta={"collection": "mycoll", "extra": "x"},
        new_item_id="newid",
    )
    assert meta["collection"] == "mycoll"
    assert meta["extra"] == "x"
    assert list(fake_items) == ["youtube-newid"]


def test_upload_ia_write_metadata_csv(tu, fake_items, isolated_fs):
    tu.upload_ia(os.path.join(tu.dir_path["downloads"], MOUNTAIN), write_metadata=True)
    with open(isolated_fs / "youtube-6iRV8liah8A.csv", encoding="utf-8", newline="") as f:
        [row] = list(csv.DictReader(f))
    assert row == dict(identifier="youtube-6iRV8liah8A", **MOUNTAIN_METADATA)


@pytest.mark.parametrize("stub", [".part", ".f303.mp4", ".ytdl", ".temp"])
def test_upload_ia_refuses_incomplete_download(tu, fake_items, stub):
    videobasename = os.path.join(tu.dir_path["downloads"], MOUNTAIN)
    open(videobasename + stub, "w").close()
    with pytest.raises(Exception, match="Video download incomplete"):
        tu.upload_ia(videobasename)
    assert fake_items == {}
    assert os.path.exists(videobasename + ".mp4")


def test_upload_ia_drops_empty_description_and_annotations(tu, fake_items):
    videobasename = os.path.join(tu.dir_path["downloads"], MOUNTAIN)
    for ext in (".description", ".annotations.xml"):
        open(videobasename + ext, "w").close()

    tu.upload_ia(videobasename)

    [(files, _)] = fake_items["youtube-6iRV8liah8A"].upload_calls
    assert videobasename + ".description" not in files
    assert videobasename + ".annotations.xml" not in files


def test_upload_ia_retries_on_protocol_error(tu, fake_items, sleeps):
    fake_items["youtube-6iRV8liah8A"] = FakeItem(
        "youtube-6iRV8liah8A", upload_errors=[urllib3.exceptions.ProtocolError("reset")]
    )
    videobasename = os.path.join(tu.dir_path["downloads"], MOUNTAIN)
    tu.upload_ia(videobasename)
    assert len(fake_items["youtube-6iRV8liah8A"].upload_calls) == 2
    assert sleeps == [10]
    assert glob.glob(videobasename + "*") == []


def test_upload_ia_keeps_files_when_upload_fails(tu, fake_items):
    fake_items["youtube-6iRV8liah8A"] = FakeItem("youtube-6iRV8liah8A", upload_errors=[ValueError("boom")])
    videobasename = os.path.join(tu.dir_path["downloads"], MOUNTAIN)
    with pytest.raises(ValueError):
        tu.upload_ia(videobasename)
    assert os.path.exists(videobasename + ".info.json")


# --- archive_urls ------------------------------------------------------------


def test_archive_urls(tu, fake_ydl):
    fake_ydl.infos[KDSN_URL] = kdsn_info()
    videobasename = os.path.join(tu.dir_path["downloads"], "KdsN9YhkDrY")
    with requests_mock.Mocker() as m:
        mock_ia_upload(m, "youtube-KdsN9YhkDrY", videobasename)
        result = list(tu.archive_urls([KDSN_URL]))
    assert result == [("youtube-KdsN9YhkDrY", KDSN_METADATA)]


def test_archive_urls_passes_extractor_args_to_ydl_options(tu, fake_ydl):
    extractor_args = {"youtube": {"player_client": ["mweb"]}}
    fake_ydl.infos[KDSN_URL] = {**kdsn_info(), "_type": "playlist", "entries": []}
    list(tu.archive_urls([KDSN_URL], extractor_args=extractor_args))
    assert fake_ydl.instances[0].params["extractor_args"] == extractor_args


# --- real network smoke tests (opt-in: pytest -m network) ---------------------


@pytest.mark.network
def test_network_get_resource_basenames(tu):
    result = tu.get_resource_basenames([KDSN_URL], ignore_existing_item=True, skip_download=True)
    assert result == {os.path.join(tu.dir_path["downloads"], "KdsN9YhkDrY")}

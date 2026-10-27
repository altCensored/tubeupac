import os
import shutil
import socket
import types

import pytest

import tubeupac.utils
from tubeupac.TubeUp import TubeUp

TESTS_DIR = os.path.dirname(os.path.realpath(__file__))
TESTFILES_DIR = os.path.join(TESTS_DIR, "test_tubeupac_files")
UPLOAD_FILES_DIR = os.path.join(TESTFILES_DIR, "files_for_upload_and_download_tests")
IA_CONFIG_PATH = os.path.join(TESTFILES_DIR, "ia_config_for_test.ini")


def get_testfile_path(name):
    return os.path.join(TESTFILES_DIR, name)


@pytest.fixture(autouse=True)
def isolated_fs(tmp_path, monkeypatch):
    """Keep tests out of ~/.tubeup, the repo, and the caller's cwd."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def no_network(request, monkeypatch):
    """Fail fast on any real network access unless the test is marked `network`."""
    if request.node.get_closest_marker("network"):
        return

    def guard(*args, **kwargs):
        raise RuntimeError("Network access attempted in an offline test: %r" % (args,))

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket.socket, "connect_ex", guard)
    monkeypatch.setattr(socket, "getaddrinfo", guard)


@pytest.fixture(autouse=True)
def sleeps(monkeypatch):
    """Make retry helpers instant; returns the list of requested delays."""
    calls = []
    fake_time = types.SimpleNamespace(sleep=calls.append)
    monkeypatch.setattr(tubeupac.utils, "time", fake_time)
    return calls


@pytest.fixture
def root_dir(tmp_path):
    """A TubeUp root dir whose downloads/ holds a fresh copy of the upload fixtures."""
    root = tmp_path / "root"
    shutil.copytree(UPLOAD_FILES_DIR, str(root / "downloads"))
    return root


@pytest.fixture
def tu(root_dir):
    return TubeUp(dir_path=str(root_dir), ia_config_path=IA_CONFIG_PATH)

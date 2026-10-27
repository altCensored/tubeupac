import datetime
import importlib.util
import io
import os
import tarfile
import zipfile

import pytest

HOOKS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), ".claude", "hooks")


def load_hook(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HOOKS_DIR, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bump = load_hook("bump_version")
publish = load_hook("pypi_publish")

SHA = "a" * 40


@pytest.mark.parametrize(
    "current, today, expected",
    [
        ("2026.10.27.1", datetime.date(2026, 10, 27), "2026.10.27.2"),
        ("2026.10.27.9", datetime.date(2026, 10, 27), "2026.10.27.10"),
        ("2026.10.27.5", datetime.date(2026, 10, 28), "2026.10.28.1"),
        ("2026.9.30.3", datetime.date(2026, 10, 1), "2026.10.1.1"),
        ("2026.1.2.4", datetime.date(2026, 1, 2), "2026.1.2.5"),
    ],
)
def test_next_version(current, today, expected):
    assert bump.next_version(current, today) == expected


@pytest.mark.parametrize(
    "command, branch, head, origin_main, subject, expected",
    [
        ("git push origin main", "main", SHA, SHA, "Merge branch 'x'", True),
        ("cd /repo && git push origin main", "main", SHA, SHA, "Merge branch 'x'", True),
        ("git push origin feature/x", "feature/x", SHA, SHA, "wip", False),
        ("echo $(git push)", "main", SHA, SHA, "Merge branch 'x'", False),
        ("git pushx", "main", SHA, SHA, "Merge branch 'x'", False),
        ("git push origin main", "main", SHA, "b" * 40, "Merge branch 'x'", False),
        ("git push origin main", "main", "", "", "Merge branch 'x'", False),
        ("git push origin main", "main", SHA, SHA, "chore: bump version to 2026.10.27.2", False),
        ("git push", "main", SHA, SHA, "Merge branch 'x'", True),
        ("git push origin", "main", SHA, SHA, "Merge branch 'x'", True),
        ("git push origin HEAD:main", "main", SHA, SHA, "Merge branch 'x'", True),
        ("git push origin main && git log -1", "main", SHA, SHA, "Merge branch 'x'", True),
        ("git push --dry-run origin main", "main", SHA, SHA, "Merge branch 'x'", False),
        ("git push -n origin main", "main", SHA, SHA, "Merge branch 'x'", False),
        ("git push origin feature/x", "main", SHA, SHA, "Merge branch 'x'", False),
        ("git push origin v2026.10.27.2", "main", SHA, SHA, "Merge branch 'x'", False),
        ("git push origin feature/x && echo main", "main", SHA, SHA, "Merge branch 'x'", False),
    ],
)
def test_should_bump(command, branch, head, origin_main, subject, expected):
    assert bump.should_bump(command, branch, head, origin_main, subject) is expected


VERSION = "2026.10.27.2"


def add_tar_file(tf, name, content):
    data = content.encode()
    info = tarfile.TarInfo(name)
    info.size = len(data)
    tf.addfile(info, io.BytesIO(data))


def make_artifacts(tmp_path, version=VERSION, extra_wheel_files=(), metadata_version=None, sdist_files=None):
    wheel = tmp_path / f"tubeupac-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as zf:
        zf.writestr("tubeupac/__init__.py", f'__version__ = "{version}"\n')
        zf.writestr(f"tubeupac-{version}.dist-info/METADATA",
                    f"Metadata-Version: 2.4\nName: tubeupac\nVersion: {metadata_version or version}\n")
        for name in extra_wheel_files:
            zf.writestr(name, "")
    sdist = tmp_path / f"tubeupac-{version}.tar.gz"
    if sdist_files is None:
        sdist_files = {
            f"tubeupac-{version}/PKG-INFO": f"Metadata-Version: 2.4\nName: tubeupac\nVersion: {version}\n",
            f"tubeupac-{version}/tubeupac/__init__.py": f'__version__ = "{version}"\n',
        }
    with tarfile.open(sdist, "w:gz") as tf:
        for name, content in sdist_files.items():
            add_tar_file(tf, name, content)
    return [str(sdist), str(wheel)]


def test_check_artifacts_ok(tmp_path):
    publish.check_artifacts(make_artifacts(tmp_path), VERSION)


def test_check_artifacts_rejects_stray_tests_package(tmp_path):
    paths = make_artifacts(tmp_path, extra_wheel_files=["tests/__init__.py"])
    with pytest.raises(publish.PublishError, match="outside tubeupac/"):
        publish.check_artifacts(paths, VERSION)


def test_check_artifacts_rejects_metadata_version_mismatch(tmp_path):
    paths = make_artifacts(tmp_path, metadata_version="2026.10.27.1")
    with pytest.raises(publish.PublishError, match="METADATA version"):
        publish.check_artifacts(paths, VERSION)


def test_check_artifacts_rejects_wrong_version_in_names(tmp_path):
    with pytest.raises(publish.PublishError, match="unexpected wheel name"):
        publish.check_artifacts(make_artifacts(tmp_path, version="2026.10.27.1"), VERSION)


def test_check_artifacts_rejects_missing_sdist(tmp_path):
    paths = make_artifacts(tmp_path)
    with pytest.raises(publish.PublishError, match="one wheel and one sdist"):
        publish.check_artifacts([p for p in paths if p.endswith(".whl")], VERSION)


def test_check_artifacts_rejects_empty_sdist(tmp_path):
    paths = make_artifacts(tmp_path, sdist_files={})
    with pytest.raises(publish.PublishError, match="sdist has no"):
        publish.check_artifacts(paths, VERSION)


def test_check_artifacts_rejects_sdist_version_mismatch(tmp_path):
    paths = make_artifacts(tmp_path, sdist_files={
        f"tubeupac-{VERSION}/PKG-INFO": "Metadata-Version: 2.4\nName: tubeupac\nVersion: 2026.10.27.1\n",
        f"tubeupac-{VERSION}/tubeupac/__init__.py": "",
    })
    with pytest.raises(publish.PublishError, match="sdist PKG-INFO version"):
        publish.check_artifacts(paths, VERSION)


def test_check_artifacts_rejects_malformed_sdist(tmp_path):
    paths = make_artifacts(tmp_path)
    with open(paths[0], "wb") as f:
        f.write(b"not a tarball")
    with pytest.raises(publish.PublishError, match="unreadable sdist"):
        publish.check_artifacts(paths, VERSION)


@pytest.mark.parametrize("error", [
    "http_503", "url_error", "timeout",
])
def test_on_pypi_transient_errors_keep_polling(monkeypatch, error):
    import urllib.error

    def urlopen(*args, **kwargs):
        if error == "http_503":
            raise urllib.error.HTTPError("u", 503, "unavailable", {}, None)
        if error == "url_error":
            raise urllib.error.URLError("reset")
        raise TimeoutError()

    monkeypatch.setattr(publish.urllib.request, "urlopen", urlopen)
    assert publish.on_pypi(VERSION) is False


def test_on_pypi_client_error_raises(monkeypatch):
    import urllib.error

    def urlopen(*args, **kwargs):
        raise urllib.error.HTTPError("u", 403, "forbidden", {}, None)

    monkeypatch.setattr(publish.urllib.request, "urlopen", urlopen)
    with pytest.raises(urllib.error.HTTPError):
        publish.on_pypi(VERSION)

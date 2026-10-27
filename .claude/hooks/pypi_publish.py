#!/usr/bin/env python3
"""Build tubeupac's wheel + sdist from a git tag and upload them to PyPI.

Started in the background by bump_version.py after a release bump. Safe to
re-run by hand for the same version if the upload failed:

    .venv/bin/python .claude/hooks/pypi_publish.py <version>
    .venv/bin/python .claude/hooks/pypi_publish.py --dry-run   # build + check HEAD, no upload

Builds only from tracked files (`git archive`), so untracked dist/, egg-info or
test leftovers can never end up in a release. Uploads with the token in
~/.pypirc (twine reads it).
"""
import argparse
import glob
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

script_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.dirname(os.path.dirname(script_dir))
venv_bin = os.path.join(project_dir, '.venv', 'bin')
pypirc = os.path.expanduser('~/.pypirc')
dist_cache = os.path.expanduser('~/.cache/tubeupac-dist')

VERSION_RE = re.compile(r'__version__ = "(\d+\.\d+\.\d+\.\d+)"')
PYPI_POLL_SECONDS = 120


class PublishError(Exception):
    pass


def git(*args: str) -> str:
    return subprocess.run(
        ['git', *args], cwd=project_dir, capture_output=True, text=True, check=True
    ).stdout.strip()


def version_at(ref: str) -> str:
    m = VERSION_RE.search(git('show', f'{ref}:tubeupac/__init__.py'))
    if not m:
        raise PublishError(f'no __version__ in tubeupac/__init__.py at {ref}')
    return m.group(1)


def check_release_state(version: str) -> None:
    tag = f'v{version}'
    if git('branch', '--show-current') != 'main':
        raise PublishError('not on main')
    if git('rev-parse', f'{tag}^{{commit}}') != git('rev-parse', 'HEAD'):
        raise PublishError(f'tag {tag} does not point at HEAD')
    if not os.path.exists(pypirc):
        raise PublishError(f'{pypirc} not found')
    if stat.S_IMODE(os.stat(pypirc).st_mode) & 0o077:
        raise PublishError(f'{pypirc} must not be readable by group/others (chmod 600)')


def check_artifacts(paths: list, version: str) -> None:
    """Raise PublishError unless `paths` is exactly one clean wheel + one sdist of `version`."""
    wheels = [p for p in paths if p.endswith('.whl')]
    sdists = [p for p in paths if p.endswith('.tar.gz')]
    if len(wheels) != 1 or len(sdists) != 1 or len(paths) != 2:
        raise PublishError(f'expected one wheel and one sdist, got {[os.path.basename(p) for p in paths]}')
    wheel, sdist = wheels[0], sdists[0]
    if os.path.basename(wheel) != f'tubeupac-{version}-py3-none-any.whl':
        raise PublishError(f'unexpected wheel name {os.path.basename(wheel)}')
    if os.path.basename(sdist) != f'tubeupac-{version}.tar.gz':
        raise PublishError(f'unexpected sdist name {os.path.basename(sdist)}')

    dist_info = f'tubeupac-{version}.dist-info/'
    with zipfile.ZipFile(wheel) as zf:
        names = zf.namelist()
        stray = [n for n in names if not n.startswith(('tubeupac/', dist_info))]
        if stray:
            raise PublishError(f'wheel contains files outside tubeupac/: {stray}')
        metadata = zf.read(dist_info + 'METADATA').decode()
    m = re.search(r'^Version: (.+)$', metadata, re.M)
    if not m or m.group(1).strip() != version:
        raise PublishError(f'wheel METADATA version {m and m.group(1)!r} != {version}')


def build(ref: str, workdir: str) -> list:
    src = os.path.join(workdir, 'src')
    out = os.path.join(workdir, 'dist')
    os.makedirs(src)
    archive = subprocess.run(['git', 'archive', ref], cwd=project_dir, capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tf:
        tf.extractall(src, filter='data')
    subprocess.run([os.path.join(venv_bin, 'python'), '-m', 'build', '--outdir', out, src], check=True)
    return sorted(glob.glob(os.path.join(out, '*')))


def on_pypi(version: str) -> bool:
    try:
        with urllib.request.urlopen(f'https://pypi.org/pypi/tubeupac/{version}/json', timeout=15) as r:
            return json.load(r)['info']['version'] == version
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise


def publish(version, dry_run: bool) -> str:
    if version is None:
        version = version_at('HEAD')
    ref = 'HEAD' if dry_run else f'v{version}'
    if not dry_run:
        check_release_state(version)
    print(f'== building tubeupac {version} from {ref}', flush=True)

    with tempfile.TemporaryDirectory() as workdir:
        paths = build(ref, workdir)
        check_artifacts(paths, version)
        subprocess.run([os.path.join(venv_bin, 'twine'), 'check', '--strict', *paths], check=True)
        keep = os.path.join(dist_cache, version + ('-dry-run' if dry_run else ''))
        shutil.rmtree(keep, ignore_errors=True)
        os.makedirs(keep)
        for p in paths:
            shutil.copy(p, keep)
        print(f'== artifacts OK, kept in {keep}', flush=True)
        if dry_run:
            return f'DRY-RUN OK {version}'
        subprocess.run([os.path.join(venv_bin, 'twine'), 'upload', '--skip-existing', '--non-interactive', *paths],
                       check=True)

    deadline = time.monotonic() + PYPI_POLL_SECONDS
    while not on_pypi(version):
        if time.monotonic() > deadline:
            raise PublishError(f'{version} uploaded but not visible on pypi.org after {PYPI_POLL_SECONDS}s')
        time.sleep(10)
    return f'PUBLISHED {version}'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('version', nargs='?', help='version to publish (default: read from the tag/HEAD)')
    parser.add_argument('--dry-run', action='store_true', help='build and check HEAD; do not upload')
    args = parser.parse_args()
    try:
        print(publish(args.version, args.dry_run), flush=True)
    except (PublishError, subprocess.CalledProcessError, OSError) as e:
        print(f'FAILED: {e}', flush=True)
        sys.exit(1)


if __name__ == '__main__':
    main()

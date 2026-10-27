#!/usr/bin/env python3
"""PostToolUse hook: after `git push` on main, bump the version, tag and push
it, and start the PyPI publish in the background.

The hook's `if: Bash(git push*)` filter also lets through commands that are not
pushes (e.g. ones containing `$(...)` or `$VAR`), so this script re-checks the
command from the hook input and refuses to run unless a real push of new work
just happened.
"""
import re
import datetime
import json
import os
import subprocess
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.dirname(os.path.dirname(script_dir))
init_path = os.path.join(project_dir, 'tubeupac', '__init__.py')
publish_log = os.path.expanduser('~/.cache/tubeupac-pypi-publish.log')

BUMP_SUBJECT_PREFIX = 'chore: bump version to '
PUSH_COMMAND_RE = re.compile(r'^\s*(?:cd\s+\S+\s*&&\s*)?git\s+push\b')
VERSION_RE = re.compile(r'__version__ = "(\d+\.\d+\.\d+\.\d+)"')
MAIN_REFS = ('main', 'refs/heads/main', 'HEAD')


def git(*args: str) -> str:
    return subprocess.run(
        ['git', *args], cwd=project_dir, capture_output=True, text=True
    ).stdout.strip()


def is_push_command(command: str) -> bool:
    """True for a real `git push` that pushes main: not a dry run, and either no
    refspec (pushes the current branch, main) or one whose destination is main."""
    m = PUSH_COMMAND_RE.match(command)
    if not m:
        return False
    args = re.split(r'[;&|]', command[m.end():], maxsplit=1)[0].split()
    if any(a in ('-n', '--dry-run') for a in args):
        return False
    refspecs = [a for a in args if not a.startswith('-')][1:]
    return not refspecs or any(r.split(':')[-1].lstrip('+') in MAIN_REFS for r in refspecs)


def should_bump(command: str, branch: str, head: str, origin_main: str, head_subject: str) -> bool:
    if branch != 'main' or not is_push_command(command):
        return False
    # Push must have landed: local main matches origin/main
    if not head or head != origin_main:
        return False
    # Nothing new since the last bump
    return not head_subject.startswith(BUMP_SUBJECT_PREFIX)


def next_version(current: str, today: datetime.date) -> str:
    """YYYY.M.D.N, no zero-padding; N increments within a day, else resets to 1."""
    prefix = f'{today.year}.{today.month}.{today.day}'
    current_prefix, n = current.rsplit('.', 1)
    return f'{prefix}.{int(n) + 1 if current_prefix == prefix else 1}'


def read_hook_command() -> str:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return ''
    return (data.get('tool_input') or {}).get('command', '') or ''


def start_pypi_publish(version: str) -> None:
    os.makedirs(os.path.dirname(publish_log), exist_ok=True)
    with open(publish_log, 'w') as log:
        subprocess.Popen(
            [sys.executable, '-B', os.path.join(script_dir, 'pypi_publish.py'), version],
            cwd=project_dir,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )


def main() -> None:
    command = read_hook_command()
    if not should_bump(
        command,
        branch=git('branch', '--show-current'),
        head=git('rev-parse', 'HEAD'),
        origin_main=git('rev-parse', 'origin/main'),
        head_subject=git('log', '-1', '--format=%s'),
    ):
        sys.exit(0)

    with open(init_path) as f:
        content = f.read()

    m = VERSION_RE.search(content)
    if not m:
        sys.exit(0)
    new_ver = next_version(m.group(1), datetime.date.today())
    content = content.replace(m.group(0), f'__version__ = "{new_ver}"')
    with open(init_path, 'w') as f:
        f.write(content)
    # Commit only the version file, even if other changes are staged
    subprocess.run(
        ['git', 'commit', '-m', f'{BUMP_SUBJECT_PREFIX}{new_ver}', '--', init_path],
        cwd=project_dir,
        check=True,
    )
    tag = f'v{new_ver}'
    subprocess.run(['git', 'tag', '-a', tag, '-m', f'version {new_ver}'], cwd=project_dir, check=True)
    subprocess.run(
        ['git', 'push', '--atomic', 'origin', 'main', f'refs/tags/{tag}'],
        cwd=project_dir,
        check=True,
    )
    start_pypi_publish(new_ver)
    print(json.dumps({
        "systemMessage": f"Version bumped to {new_ver}, tagged {tag} and pushed; "
                         f"PyPI publish started (log: {publish_log})"
    }))


if __name__ == '__main__':
    main()

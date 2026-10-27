# tubeupac — Claude Code Project Instructions

## What This Project Does

altCensored fork of tubeup: downloads a video with yt-dlp and uploads it with its metadata to the Internet
Archive. Published on PyPI as `tubeupac`. Main consumer: yt-syncac (`yt_syncac/uploads.py`) imports `TubeUp`
and calls `archive_urls(...)` through the library API, not the CLI. Its `pyproject.toml` pins a floor
(`tubeupac>=…`), so keep the `TubeUp.__init__` / `archive_urls` keyword arguments backwards compatible.

- `tubeupac/TubeUp.py` — `TubeUp`: yt-dlp options, download, IA metadata, upload
- `tubeupac/utils.py` — identifier helpers, `retry`, `retry_wrap`, `key_value_to_dict`
- `tubeupac/__main__.py` — docopt CLI (`tubeupac`). docopt reads the option spec from the docstring: an
  option's description must start two or more spaces after `<arg>`, otherwise the option takes no value
- `tubeupac/__init__.py` — `__version__`, the only place the version lives

## Testing

- Setup: `python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'`
- `.venv/bin/pytest`: offline suite, under 1 s. `tests/conftest.py` isolates `HOME`/cwd in `tmp_path`, fails any
  socket use, and no-ops retry sleeps. yt-dlp is faked in tests (`fake_ydl`), and archive.org is faked
  (`fake_items`) or mocked with `requests_mock`.
- `.venv/bin/pytest -m network`: opt-in smoke test against real YouTube (`--skip-download`). This is the manual
  "tested" check before a release.
- `.venv/bin/flake8` must be clean (CI runs it).
- **Never do a real IA upload in dev.** IA uploads can't be undone.

## Versioning

`__version__ = "YYYY.M.D.N"` in `tubeupac/__init__.py`, with no zero padding. N goes up by one within a day and
resets to 1 on a new day (`.claude/hooks/bump_version.py:next_version`). **Never edit the version by hand or on a
feature branch.** Only the post-push hook bumps it on `main`, and every bump gets an annotated tag `v<version>`.

## Development Workflow

1. `git checkout -b feature/description`
2. Make changes. `.venv/bin/pytest` and `.venv/bin/flake8` must pass.
3. User runs `.venv/bin/pytest -m network` and/or a real `--skip-download` run, then says "tested".
4. Claude runs the release sequence below.
5. Deploy (see below).

### Automated Release Sequence

When the user confirms testing is done, Claude runs these steps in order:

0. `.venv/bin/pytest` and `.venv/bin/flake8`: all must pass. Hard stop on failure until the user re-confirms "tested".
1. Commit any uncommitted changes on the feature branch
2. `git push origin <branch>` (the hook does nothing off `main`)
3. `gh pr create`: title and body come from the branch name and commits
4. `git checkout main && git pull origin main`
5. `git merge --no-ff <branch>`
6. `git push origin main`: this triggers the post-push hook, which bumps the version, commits, tags `v<version>`,
   pushes both atomically, then starts the PyPI publish in the background
7. `gh api -X DELETE repos/altCensored/tubeupac/git/refs/heads/<branch>`
8. `git branch -d <branch>`
9. Check `~/.cache/tubeupac-pypi-publish.log`. Its last line is `PUBLISHED <version>` or `FAILED: <reason>`.

**Merge with local `git merge --no-ff` + `git push origin main`, never with `gh pr merge` or the GitHub web UI.**
Those skip the hook, so no bump, no tag, no PyPI release.
**Never push directly to main without a feature branch and PR. Never open a PR before the user has tested.
Never commit to a branch after its PR has been merged.**

**The hook:** `.claude/settings.json` has a PostToolUse hook that runs `.claude/hooks/bump_version.py`.
It re-checks that the command really was `git push` on `main`, that local `main` equals `origin/main`, and that
HEAD is not already a bump commit. Its own push runs inside the script, so it cannot re-trigger itself. It then
starts `.claude/hooks/pypi_publish.py <version>` detached. That script builds a wheel and sdist from
`git archive v<version>` (tracked files only), checks that the wheel contains only `tubeupac/` + dist-info with
the right version, runs `twine check --strict`, runs `twine upload --skip-existing`, and waits until pypi.org
shows the version. Artifacts are kept in `~/.cache/tubeupac-dist/<version>/`.

- PyPI token: `~/.pypirc` (mode 600, a token scoped to the `tubeupac` project), never committed. The publish
  script refuses to run if the file is group- or world-readable.
- `make release-check` = `pypi_publish.py --dry-run`: builds and checks HEAD, uploads nothing.
- **If the publish fails** after the bump was pushed: fix the cause, then run
  `.venv/bin/python -B .claude/hooks/pypi_publish.py <version>` again. Don't bump again. PyPI never allows
  re-uploading a version, so if a bad artifact got published, yank it on pypi.org and ship the fix as a new
  branch and release.

## Deploy after a release

All nodes are production.
- www, orcl (native): `sudo pip3 install --upgrade --break-system-packages tubeupac==<version>`, then
  `pip show tubeupac`. **Always with sudo**: without it, pip installs into `~/.local` and shadows the system
  copy for that user.
- rn1, rn4, www2 (Docker): tubeupac comes with the yt-syncac image, so these need a yt-syncac image rebuild.
- If yt-syncac needs the new version, raise its `tubeupac>=` floor in a separate yt-syncac PR.

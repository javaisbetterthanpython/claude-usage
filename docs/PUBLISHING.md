# Publishing

Steps to turn this local project into a public repo and a `pip install`-able
package. No CI is configured by default.

## 1. Check the names

- **PyPI distribution: `claude-usage-limits`** — `pip install claude-usage-limits`.
- Import package: `claude_usage` under `src/`.
- Console command: `claude-usage`.
- GitHub repo: `javaisbetterthanpython/claude-usage`.

The distribution name deliberately differs from the repo and command: the PyPI
names `claude-usage`, `claude-usage-cli`, and `claude-code-usage` are already taken
by unrelated projects. Keep the badge and install commands on `claude-usage-limits`.
The Homepage/Issues URLs and generic contributor author are already filled in.

## 2. Run the tests locally

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e . pytest
.venv/bin/pytest -q
.venv/bin/claude-usage --help
.venv/bin/claude-usage --version
```

Tests use temporary config directories and mock the HTTP boundary. Do not poll
the live endpoint to test a release: back-to-back calls trigger minutes of 429s.
On Windows, use `.venv\Scripts\python` / `pip` / `pytest` / `claude-usage` instead.

## 3. Create the public GitHub repo

Run from the project root when ready to publish:

```bash
gh repo create javaisbetterthanpython/claude-usage --public --source=. --remote=origin --push
```

The README embeds `docs/demo.gif` by its raw GitHub URL, so it renders on PyPI
too once the repo is public.

## 4. Publish to PyPI

Activate the venv (`source .venv/bin/activate`) first, then:

```bash
python -m pip install --upgrade build twine
python -m build                 # creates dist/*.whl and dist/*.tar.gz
twine check dist/*
twine upload dist/*
```

The PyPI API token is in the macOS keychain for
`https://upload.pypi.org/legacy/`, user `__token__`, so twine needs no prompt
when its keyring integration can read that entry. Keep the token out of shell
history, command arguments, and this repo. On another publishing machine,
configure twine's credential store first. These are publishing-only tools;
the installed CLI still has no dependencies.

Then anyone can:

```bash
pip install claude-usage-limits
claude-usage
```

## 5. Versioning

Bump `version` in both `pyproject.toml` and `src/claude_usage/__init__.py`, commit,
tag `vX.Y.Z`, and push the commit and tag:

```bash
git tag v0.2.0
git push origin main
git push origin v0.2.0
```

<details>
<summary>Optional: automate PyPI releases on tag (requires GitHub Actions)</summary>

If you later want automated releases, add `.github/workflows/release.yml`
using PyPI Trusted Publishing (OIDC):

```yaml
name: release
on:
  push:
    tags: ["v*"]
permissions:
  id-token: write
jobs:
  pypi:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install build && python -m build
      - uses: pypa/gh-action-pypi-publish@release/v1
```

Configure the matching Trusted Publisher on PyPI for project **claude-usage-limits**,
repository **javaisbetterthanpython/claude-usage**, and that workflow filename.
No workflow is included in the initial project.
</details>

## Note on data & secrets

Nothing account-specific belongs in this repo. Virtualenvs, build output,
egg-info, and caches are git-ignored. Credentials and usage caches stay in
Claude Code's local config directory, outside the repo; tokens are read only
at runtime and are never committed.

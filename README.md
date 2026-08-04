# uv-pep723-upgrade

A pre-commit hook that updates dependencies in [PEP 723](https://peps.python.org/pep-0723/) inline Python scripts using `uv`.

It finds `# /// script` metadata blocks and delegates dependency updates to:

```bash
uv add --script
```

The hook does not modify TOML directly.

## Requirements

- Python >= 3.11
- `uv` installed and available in `PATH`

## Installation

Add to `.pre-commit-config.toml`:

```toml
[[repos]]
repo = "https://github.com/<owner>/pre-commit-uv-pep723-upgrade"
rev = "v1.0.0"

[[repos.hooks]]
id = "uv-pep723-upgrade"
stages = ["manual"]
```

## Usage

Update all Python scripts in a repository:

```bash
pre-commit run uv-pep723-upgrade --all-files --hook-stage manual -- --all
```

Or run on selected files:

```bash
pre-commit run uv-pep723-upgrade --files script.py
```

## Behavior

For each script containing:

```python
# ///
# dependencies = [
#     "requests",
# ]
# ///
```

the hook runs:

```bash
uv add --script script.py requests
```

Only files with PEP 723 metadata are modified.

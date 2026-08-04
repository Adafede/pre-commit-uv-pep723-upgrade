#!/usr/bin/env python3
"""Upgrade dependencies in PEP 723 inline Python scripts.

This pre-commit hook updates all dependencies declared in PEP 723
`# /// script` metadata blocks to the latest versions resolvable by uv.

It intentionally does NOT edit TOML itself. Instead it:

1. Finds the canonical PEP 723 script metadata block.
2. Extracts package names from the dependency list.
3. Delegates dependency resolution and TOML rewriting to:
       uv add --script

This keeps dependency resolution, formatting, and TOML mutation owned by uv.

Usage:

    # Scan explicitly provided files
    uv-pep723-upgrade script.py tools/foo.py

    # Scan the whole repository
    uv-pep723-upgrade --all

Exit codes:

    0  No changes
    1  Files were modified (pre-commit will ask you to review/stage them)
    2  Usage/configuration error

Requires:

    - Python >= 3.11
    - uv
"""

# ///
# requires-python = ">=3.11"
# dependencies = [
#     "packaging",
# ]
# ///


from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement


_BLOCK_RE = re.compile(
    r"(?m)^# /// (?P<type>[A-Za-z0-9-]+)$\s"
    r"(?P<content>(^#(| .*)$\s)+)^# ///$"
)


def find_pep723_block(source: str) -> str | None:
    """Extract the TOML content from a PEP 723 script block."""

    blocks = [
        match
        for match in _BLOCK_RE.finditer(source)
        if match.group("type") == "script"
    ]

    if not blocks:
        return None

    if len(blocks) > 1:
        raise ValueError("multiple PEP 723 script blocks found")

    return "".join(
        line[2:] if line.startswith("# ") else line[1:]
        for line in blocks[0].group("content").splitlines(keepends=True)
    )


def dependency_names(raw_toml: str) -> list[str]:
    """Return normalized package names from dependencies."""

    metadata = tomllib.loads(raw_toml)

    names: list[str] = []

    for dependency in metadata.get("dependencies", []):
        try:
            names.append(Requirement(dependency).name)
        except InvalidRequirement:
            print(
                f"  ! ignoring invalid dependency: {dependency!r}",
                file=sys.stderr,
            )

    return sorted(set(names))


def python_files(root: Path) -> list[Path]:
    """Find Python files suitable for PEP 723 scripts."""

    return [
        path
        for path in root.rglob("*.py")
        if ".git" not in path.parts
        and ".venv" not in path.parts
        and "__pycache__" not in path.parts
    ]


def bump_file(path: Path) -> bool:
    """Upgrade one file. Return True if modified."""

    if not path.is_file():
        return False

    before = path.read_text(encoding="utf-8")

    try:
        block = find_pep723_block(before)
    except ValueError as exc:
        print(f"{path}: {exc}", file=sys.stderr)
        return False

    if block is None:
        return False

    packages = dependency_names(block)

    if not packages:
        return False

    if shutil.which("uv") is None:
        print(
            "error: uv executable not found in PATH",
            file=sys.stderr,
        )
        raise SystemExit(2)

    result = subprocess.run(
        [
            "uv",
            "add",
            "--script",
            str(path),
            *packages,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0:
        print(
            f"{path}: uv failed:\n{result.stderr.strip()}",
            file=sys.stderr,
        )
        return False

    changed = path.read_text(encoding="utf-8") != before

    if changed:
        print(f"✓ upgraded {path}")

    return changed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Upgrade dependencies in PEP 723 Python scripts."
    )

    parser.add_argument(
        "files",
        nargs="*",
        type=Path,
        help="Python scripts to inspect",
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="scan the repository recursively",
    )

    args = parser.parse_args()

    if args.all and args.files:
        parser.error("--all cannot be combined with files")

    if args.all:
        files = python_files(Path.cwd())
    else:
        files = args.files

    if not files:
        parser.error("provide files or use --all")

    changed = any(
        bump_file(path)
        for path in files
    )

    return 1 if changed else 0


if __name__ == "__main__":
    raise SystemExit(main())

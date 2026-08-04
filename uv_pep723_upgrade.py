#!/usr/bin/env python3
"""Upgrade dependencies in PEP 723 inline Python scripts.

This pre-commit hook updates dependencies declared in PEP 723
`# /// script` metadata blocks.

Default mode delegates everything to:

    uv add --script --upgrade

With --force-update, existing version operators are preserved while versions
are refreshed:

    fire==0.7.0  ->  fire==0.8.0
    rich>=13.0   ->  rich>=14.0
    jinja2~=3.1  ->  jinja2~=3.2

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


def find_pep723_match(source: str) -> re.Match[str] | None:
    blocks = [
        match
        for match in _BLOCK_RE.finditer(source)
        if match.group("type") == "script"
    ]

    if not blocks:
        return None

    if len(blocks) > 1:
        raise ValueError("multiple PEP 723 script blocks found")

    return blocks[0]


def extract_block(match: re.Match[str]) -> str:
    return "".join(
        line[2:] if line.startswith("# ") else line[1:]
        for line in match.group("content").splitlines(keepends=True)
    )


def dependency_requirements(raw_toml: str) -> list[Requirement]:
    metadata = tomllib.loads(raw_toml)

    result = []

    for dependency in metadata.get("dependencies", []):
        try:
            result.append(Requirement(dependency))
        except InvalidRequirement:
            print(
                f"! ignoring invalid dependency: {dependency}",
                file=sys.stderr,
            )

    return result


def dependency_names(raw_toml: str) -> list[str]:
    return sorted(
        {
            req.name
            for req in dependency_requirements(raw_toml)
        }
    )


def render_requirement_without_version(req: Requirement) -> str:
    value = req.name

    if req.extras:
        value += "[" + ",".join(sorted(req.extras)) + "]"

    if req.marker:
        value += f"; {req.marker}"

    return value


def replace_dependencies(
    source: str,
    match: re.Match[str],
    dependencies: list[str],
) -> str:
    block = extract_block(match)

    metadata = tomllib.loads(block)

    old = metadata.get("dependencies", [])

    if not old:
        return source

    replacements = iter(dependencies)

    new_block = re.sub(
        r'("dependencies"\s*=\s*\[\s*)(.*?)(\])',
        lambda m: (
            m.group(1)
            + "\n"
            + "".join(
                f'    "{next(replacements)}",\n'
                for _ in old
            )
            + m.group(3)
        ),
        block,
        flags=re.S,
    )

    old_commented = match.group("content")

    old_rendered = "".join(
        line[2:] if line.startswith("# ") else line[1:]
        for line in old_commented.splitlines(keepends=True)
    )

    commented = "".join(
        "# " + line if line.strip() else "#\n"
        for line in new_block.splitlines(keepends=True)
    )

    return (
        source[: match.start("content")]
        + commented
        + source[match.end("content") :]
    )


def replace_dependency_versions(
    source: str,
    original: list[Requirement],
) -> str:
    match = find_pep723_match(source)

    if match is None:
        return source

    resolved = dependency_requirements(
        extract_block(match)
    )

    resolved_map = {
        req.name: req
        for req in resolved
    }

    rebuilt = []

    for old in original:
        new = resolved_map.get(old.name)

        if new is None:
            rebuilt.append(str(old))
            continue

        if not old.specifier:
            rebuilt.append(str(new))
            continue

        latest_version = next(
            iter(new.specifier)
        ).version

        operator = next(
            iter(old.specifier)
        ).operator

        value = old.name

        if old.extras:
            value += "[" + ",".join(sorted(old.extras)) + "]"

        value += f"{operator}{latest_version}"

        if old.marker:
            value += f"; {old.marker}"

        rebuilt.append(value)

    return replace_dependencies(
        source,
        match,
        rebuilt,
    )


def python_files(root: Path) -> list[Path]:
    return [
        path
        for path in root.rglob("*.py")
        if ".git" not in path.parts
        and ".venv" not in path.parts
        and "__pycache__" not in path.parts
    ]


def run_uv(path: Path) -> bool:
    result = subprocess.run(
        [
            "uv",
            "add",
            "--script",
            "--upgrade",
            str(path),
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

    return True


def bump_file(
    path: Path,
    force_update: bool,
) -> bool:
    if not path.is_file():
        return False

    before = path.read_text(encoding="utf-8")

    try:
        match = find_pep723_match(before)
    except ValueError as exc:
        print(f"{path}: {exc}", file=sys.stderr)
        return False

    if match is None:
        return False

    block = extract_block(match)

    if force_update:
        original = dependency_requirements(block)

        temporary = replace_dependencies(
            before,
            match,
            [
                render_requirement_without_version(req)
                for req in original
            ],
        )

        path.write_text(
            temporary,
            encoding="utf-8",
        )

        if not run_uv(path):
            path.write_text(before, encoding="utf-8")
            return False

        after = replace_dependency_versions(
            path.read_text(encoding="utf-8"),
            original,
        )

        path.write_text(
            after,
            encoding="utf-8",
        )

    else:
        if not run_uv(path):
            return False

    changed = (
        path.read_text(encoding="utf-8")
        != before
    )

    if changed:
        print(f"✓ upgraded {path}")

    return changed


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "files",
        nargs="*",
        type=Path,
    )

    parser.add_argument(
        "--all",
        action="store_true",
    )

    parser.add_argument(
        "--force-update",
        action="store_true",
        help=(
            "Update versions while preserving "
            "existing version operators."
        ),
    )

    args = parser.parse_args()

    if args.all and args.files:
        parser.error(
            "--all cannot be combined with files"
        )

    if args.all:
        files = python_files(Path.cwd())
    else:
        files = args.files

    if not files:
        parser.error(
            "provide files or use --all"
        )

    if shutil.which("uv") is None:
        print(
            "error: uv executable not found",
            file=sys.stderr,
        )
        return 2

    changed = any(
        bump_file(
            path,
            args.force_update,
        )
        for path in files
    )

    return 1 if changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
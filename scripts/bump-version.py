#!/usr/bin/env python3
"""Bump the neo4j-skills bundle version.

Usage:
  python scripts/bump-version.py patch             # 1.0.0 → 1.0.1
  python scripts/bump-version.py minor             # 1.0.0 → 1.1.0
  python scripts/bump-version.py major             # 1.0.0 → 2.0.0
  python scripts/bump-version.py --version 2.1.0
  python scripts/bump-version.py patch --dry-run   # preview changes, no writes

Updates:
  - .claude-plugin/plugin.json
  - .codex-plugin/plugin.json
  - .qoder-plugin/plugin.json
  - gemini-extension.json
  - version: field in all neo4j-*-skill/SKILL.md (adds if missing)

Then runs lint_skills.py and prints the git commands to review and run.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

VERSION_FILES = [
    ROOT / ".claude-plugin" / "plugin.json",
    ROOT / ".codex-plugin" / "plugin.json",
    ROOT / ".qoder-plugin" / "plugin.json",
    ROOT / "gemini-extension.json",
]

VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

# Frontmatter version field — present or absent
FM_VERSION_RE = re.compile(r"^(version:\s*)(.+)$", re.MULTILINE)
FM_END_RE = re.compile(r"^---\s*$", re.MULTILINE)


def read_current_version() -> str:
    data = json.loads(VERSION_FILES[0].read_text())
    return data["version"]


def bump(version: str, kind: str) -> str:
    m = VERSION_RE.match(version)
    if not m:
        sys.exit(f"Cannot parse current version: {version!r}")
    major, minor, patch = int(m[1]), int(m[2]), int(m[3])
    if kind == "major":
        return f"{major + 1}.0.0"
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    if kind == "patch":
        return f"{major}.{minor}.{patch + 1}"
    sys.exit(f"Unknown bump kind: {kind!r}")


def update_json_files(new_version: str, *, dry_run: bool = False) -> list[str]:
    updated = []
    for path in VERSION_FILES:
        data = json.loads(path.read_text())
        old = data.get("version", "<unset>")
        if not dry_run:
            data["version"] = new_version
            path.write_text(json.dumps(data, indent=2) + "\n")
        updated.append(f"  {path.relative_to(ROOT)}  {old} → {new_version}")
    return updated


def update_skill_md_files(new_version: str, *, dry_run: bool = False) -> list[str]:
    updated, added = [], []
    for skill_md in sorted(ROOT.glob("neo4j-*-skill/SKILL.md")):
        text = skill_md.read_text()

        # Frontmatter is between first --- and second ---
        lines = text.splitlines(keepends=True)
        if not lines or lines[0].strip() != "---":
            continue  # no frontmatter, skip

        # Find end of frontmatter block
        fm_end_idx = None
        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                fm_end_idx = i
                break
        if fm_end_idx is None:
            continue

        fm_block = "".join(lines[1:fm_end_idx])
        rel = skill_md.relative_to(ROOT)

        if FM_VERSION_RE.search(fm_block):
            # Replace existing version
            new_fm = FM_VERSION_RE.sub(rf"\g<1>{new_version}", fm_block)
            if new_fm != fm_block:
                if not dry_run:
                    lines[1:fm_end_idx] = list(new_fm)
                    skill_md.write_text("".join(lines))
                updated.append(f"  {rel}")
        else:
            # Insert version: before the closing ---
            if not dry_run:
                insert_line = f"version: {new_version}\n"
                lines.insert(fm_end_idx, insert_line)
                skill_md.write_text("".join(lines))
            added.append(f"  {rel}")

    result = []
    if updated:
        result.append(f"Updated version in {len(updated)} SKILL.md file(s):")
        result.extend(updated)
    if added:
        result.append(f"Added version to {len(added)} SKILL.md file(s):")
        result.extend(added)
    return result


def check_plugin_json_sync() -> list[str]:
    """Warn if plugin.json skills list is out of sync with skill directories in the repo."""
    issues = []
    data = json.loads(VERSION_FILES[0].read_text())
    in_manifest = {Path(s).name for s in data.get("skills", [])}
    on_disk = {p.name for p in ROOT.glob("neo4j-*-skill") if p.is_dir()}
    for skill in sorted(on_disk - in_manifest):
        issues.append(f"  WARNING: {skill}/ exists in repo but is missing from plugin.json")
    for skill in sorted(in_manifest - on_disk):
        issues.append(f"  WARNING: {skill} is listed in plugin.json but not found on disk")
    return issues


def run_lint() -> bool:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "lint_skills.py")],
        cwd=ROOT,
    )
    return result.returncode == 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("kind", nargs="?", choices=["patch", "minor", "major"])
    group.add_argument("--version", metavar="X.Y.Z")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without writing any files")
    args = parser.parse_args()

    current = read_current_version()
    new_version = args.version if args.version else bump(current, args.kind)

    if not VERSION_RE.match(new_version):
        sys.exit(f"Invalid version: {new_version!r}  (expected X.Y.Z)")

    dry_run = args.dry_run
    if dry_run:
        print(f"\n[DRY RUN] Would bump  {current}  →  {new_version}\n")
    else:
        print(f"\nBumping  {current}  →  {new_version}\n")

    # --- update files ---
    for line in update_json_files(new_version, dry_run=dry_run):
        print(line)
    print()
    for line in update_skill_md_files(new_version, dry_run=dry_run):
        print(line)
    print()

    if dry_run:
        print("[DRY RUN] No files written. Re-run without --dry-run to apply.")
        return

    # --- plugin.json sync check ---
    sync_issues = check_plugin_json_sync()
    if sync_issues:
        print("plugin.json sync warnings:")
        for line in sync_issues:
            print(line)
        print()

    # --- lint ---
    print("Running lint_skills.py …")
    if not run_lint():
        print("\nLint failed — fix errors above before committing.", file=sys.stderr)
        sys.exit(1)
    print()

    # --- print git commands for user to review and run ---
    tag = f"v{new_version}"
    print("=" * 60)
    print("Lint passed. Review the diff, then run:\n")
    print(f"  git add .claude-plugin/plugin.json .codex-plugin/plugin.json .qoder-plugin/plugin.json gemini-extension.json")
    print(f"  git add neo4j-*-skill/SKILL.md")
    print(f'  git commit -m "release: bump version to {tag}"')
    print(f"  git tag {tag}")
    print(f"  git push origin main")
    print(f"  git push origin {tag}")
    print()
    print("Pushing the tag triggers the GH release workflow.")
    print("=" * 60)


if __name__ == "__main__":
    main()

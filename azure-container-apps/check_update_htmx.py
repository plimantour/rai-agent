#!/usr/bin/env python3
"""Utility for checking and updating the bundled htmx asset."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import textwrap
import urllib.error
import urllib.request
from pathlib import Path

GITHUB_RELEASES_API = "https://api.github.com/repos/bigskysoftware/htmx/releases/latest"
DOWNLOAD_URL_TEMPLATE = "https://unpkg.com/htmx.org@{version}/dist/htmx.min.js"
USER_AGENT = "rai-assessment-htmx-checker"


def read_local_version(htmx_path: Path) -> str | None:
    """Extract the version string embedded in the local htmx bundle."""
    try:
        text = htmx_path.read_text(encoding="utf-8", errors="ignore")
    except FileNotFoundError:
        return None
    match = re.search(r'version:"([^"]+)"', text)
    if match:
        return match.group(1)
    return None


def fetch_latest_release() -> tuple[str, str, str]:
    """Return (version, release_url, release_notes) for the latest GitHub release."""
    request = urllib.request.Request(
        GITHUB_RELEASES_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.load(response)
    tag = payload.get("tag_name", "").lstrip("v")
    return tag, payload.get("html_url", ""), payload.get("body", "") or ""


def format_release_notes(notes: str) -> str:
    """Wrap release notes for console output."""
    if not notes.strip():
        return "No release notes provided."
    wrapped: list[str] = []
    for line in notes.splitlines():
        if not line.strip():
            wrapped.append("")
            continue
        wrapped.extend(textwrap.wrap(line, width=88))
    return "\n".join(wrapped)


def download_htmx(version: str) -> bytes:
    """Download the minified htmx bundle for the given version."""
    url = DOWNLOAD_URL_TEMPLATE.format(version=version)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def backup_file(path: Path) -> Path:
    """Create a timestamped backup alongside the original file."""
    timestamp = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    backup_path = path.with_name(f"{path.name}.{timestamp}.bak")
    backup_path.write_bytes(path.read_bytes())
    return backup_path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    default_htmx = repo_root / "static" / "js" / "htmx.min.js"

    parser = argparse.ArgumentParser(description="Check or update the bundled htmx asset.")
    parser.add_argument(
        "--htmx-path",
        default=str(default_htmx),
        help=f"Path to the local htmx bundle (default: {default_htmx})",
    )
    parser.add_argument(
        "--update-htmx-file",
        action="store_true",
        help="Download the latest htmx bundle and update the local file if a newer version exists.",
    )
    args = parser.parse_args()

    htmx_path = Path(args.htmx_path)
    current_version = read_local_version(htmx_path)
    print(f"Local htmx path: {htmx_path}")
    print(f"Current bundled version: {current_version or 'unknown'}")

    try:
        latest_version, release_url, release_notes = fetch_latest_release()
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"Failed to query latest release: {exc}", file=sys.stderr)
        return 1

    print(f"Latest upstream version: {latest_version}")
    if release_url:
        print(f"Release: {release_url}")
    print("\nRelease notes:\n")
    print(format_release_notes(release_notes))
    print()

    if not args.update_htmx_file:
        return 0

    if not latest_version:
        print("Cannot update without a valid upstream version.", file=sys.stderr)
        return 1

    if current_version == latest_version:
        print("Local htmx bundle already up to date.")
        return 0

    if not htmx_path.exists():
        print(f"Local bundle not found at {htmx_path}, it will be created.")
    else:
        backup = backup_file(htmx_path)
        print(f"Created backup: {backup}")

    try:
        bundle = download_htmx(latest_version)
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"Failed to download htmx {latest_version}: {exc}", file=sys.stderr)
        return 1

    htmx_path.parent.mkdir(parents=True, exist_ok=True)
    htmx_path.write_bytes(bundle)
    print(f"Updated {htmx_path} to htmx {latest_version}.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

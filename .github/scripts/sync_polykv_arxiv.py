#!/usr/bin/env python3
"""Refresh the build-time cache for PolyKV's arXiv metadata.

The website remains static: Jekyll reads _data/arxiv.json during a GitHub Pages
build. This script is deliberately scoped to PolyKV's stable arXiv identifier.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from pathlib import Path


ARXIV_ID = "2606.15157"
API_URL = f"https://export.arxiv.org/api/query?id_list={ARXIV_ID}"
CACHE_PATH = Path("_data/arxiv.json")
ATOM = "{http://www.w3.org/2005/Atom}"
ID_PATTERN = re.compile(r"(?P<base>\d{4}\.\d{4,5})(?:v(?P<version>\d+))?$")


def normalized_text(value: str | None) -> str:
    return " ".join((value or "").split())


def fetch_metadata() -> dict[str, object]:
    request = urllib.request.Request(
        API_URL,
        headers={
            "User-Agent": "cf3i.github.io arXiv metadata sync (contact: chao.fei@kaust.edu.sa)"
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = response.read()

    root = ET.fromstring(payload)
    entry = root.find(f"{ATOM}entry")
    if entry is None:
        raise ValueError(f"arXiv returned no record for {ARXIV_ID}")

    returned_id = normalized_text(entry.findtext(f"{ATOM}id"))
    match = ID_PATTERN.search(returned_id.rsplit("/", maxsplit=1)[-1])
    if match is None or match.group("base") != ARXIV_ID:
        raise ValueError(f"arXiv returned an unexpected identifier: {returned_id!r}")

    title = normalized_text(entry.findtext(f"{ATOM}title"))
    authors = [
        normalized_text(author.findtext(f"{ATOM}name"))
        for author in entry.findall(f"{ATOM}author")
    ]
    if not title or not authors or any(not author for author in authors):
        raise ValueError("arXiv record is missing a title or author name")

    version = int(match.group("version") or "1")
    return {
        "title": title,
        "authors": authors,
        "published": normalized_text(entry.findtext(f"{ATOM}published")),
        "updated": normalized_text(entry.findtext(f"{ATOM}updated")),
        "version": version,
    }


def read_cache() -> dict[str, object]:
    if not CACHE_PATH.exists():
        return {}
    with CACHE_PATH.open(encoding="utf-8") as handle:
        content = json.load(handle)
    if not isinstance(content, dict):
        raise ValueError(f"{CACHE_PATH} must contain a JSON object")
    return content


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def write_cache(cache: dict[str, object]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=CACHE_PATH.parent, delete=False
    ) as temporary_file:
        json.dump(cache, temporary_file, indent=2, ensure_ascii=False)
        temporary_file.write("\n")
        temporary_path = Path(temporary_file.name)
    temporary_path.replace(CACHE_PATH)


def metadata_matches(cache: dict[str, object], metadata: dict[str, object]) -> bool:
    return cache.get(ARXIV_ID) == metadata


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero when the cached record differs from arXiv",
    )
    parser.add_argument(
        "--heartbeat-days",
        type=int,
        default=45,
        help="refresh the cache timestamp at most once per this many days",
    )
    args = parser.parse_args()
    if args.heartbeat_days < 1:
        parser.error("--heartbeat-days must be positive")

    metadata = fetch_metadata()
    cache = read_cache()
    unchanged = metadata_matches(cache, metadata)
    if args.check:
        if unchanged:
            print(f"Cached arXiv metadata for {ARXIV_ID} matches v{metadata['version']}.")
            return 0
        print(f"Cached arXiv metadata for {ARXIV_ID} is stale.", file=sys.stderr)
        return 1

    now = datetime.now(UTC)
    last_checked = parse_timestamp(cache.get("_last_checked_at"))
    heartbeat_due = (
        last_checked is None or now - last_checked >= timedelta(days=args.heartbeat_days)
    )
    if unchanged and not heartbeat_due:
        print(f"No PolyKV arXiv metadata change (v{metadata['version']}).")
        return 0

    cache[ARXIV_ID] = metadata
    cache["_last_checked_at"] = now.isoformat().replace("+00:00", "Z")
    write_cache(cache)
    reason = "metadata changed" if not unchanged else "heartbeat due"
    print(f"Refreshed PolyKV arXiv cache: {reason} (v{metadata['version']}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

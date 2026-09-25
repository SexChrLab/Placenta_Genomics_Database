"""Shared file handling and caching for public repository metadata."""

import csv
import hashlib
import json
import time
from datetime import datetime, timezone

import requests


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows, fields=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def source_info(path):
    """Read the URL, retrieval time and checksum saved beside a response."""
    return json.loads(path.with_name(path.name + ".source.json").read_text())


def cached_get(session, url, path, params=None, refresh=False):
    """Reuse a saved response unless a fresh download was requested."""
    provenance = path.with_name(path.name + ".source.json")
    if path.exists() and provenance.exists() and not refresh:
        return path.read_bytes(), source_info(path)

    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        try:
            response = session.get(url, params=params, timeout=(15, 60))
            response.raise_for_status()
            if path.suffix == ".json":
                response.json()
            info = {
                "response_url": response.url,
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "bytes": len(response.content),
                "sha256": hashlib.sha256(response.content).hexdigest(),
            }
            path.write_bytes(response.content)
            provenance.write_text(json.dumps(info, indent=2) + "\n")
            time.sleep(0.3)
            return response.content, info
        except (requests.RequestException, ValueError):
            if attempt == 2:
                raise
            # Brief retries help with temporary server failures.
            time.sleep(2 ** attempt)

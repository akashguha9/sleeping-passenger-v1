"""Resumable JSONL store for scraped problems.

One file per section. Each line is one Problem (as JSON). On resume we read
the URL set from the existing file and skip those.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Iterable

log = logging.getLogger(__name__)


class JsonlStore:
    def __init__(self, path: str | os.PathLike) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def known_urls(self) -> set[str]:
        seen: set[str] = set()
        if self.path.stat().st_size == 0:
            return seen
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    log.warning("skipping malformed JSONL line in %s", self.path)
                    continue
                url = obj.get("url")
                if url:
                    seen.add(url)
        return seen

    def append(self, record: dict) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False))
            fh.write("\n")

    def append_many(self, records: Iterable[dict]) -> int:
        n = 0
        with self.path.open("a", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec, ensure_ascii=False))
                fh.write("\n")
                n += 1
        return n

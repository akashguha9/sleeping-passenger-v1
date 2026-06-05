"""Fail-closed safety validation for the zip simulation corpus.

Nothing in this subsystem trusts the archive.  Before any parsing we classify
the whole archive and every member into one of:

* ``SAFE``     — proceed normally.
* ``WARNING``  — proceed, but flagged (e.g. extreme compression ratio, very
                 large member streamed rather than parsed as text).
* ``BLOCKED``  — refuse to extract/parse this member or archive (path
                 traversal, absolute paths, corruption, impossible metadata).

The validator never extracts to disk; it reads the central directory and
streams member bytes only for hashing/sampling.
"""
from __future__ import annotations

import os
import re
import zipfile
from dataclasses import dataclass
from enum import Enum


class SafetyStatus(str, Enum):
    SAFE = "SAFE"
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class SafetyConfig:
    """Tunable thresholds.  Conservative defaults; overridable via CLI/config."""

    # Per-file compression ratio flag (uncompressed / max(compressed, 1)).
    r_max: float = 100.0
    # Whole-archive compression ratio flag.
    cr_total_max: float = 50.0
    # Members larger than this are streamed/hashed but NOT parsed as text.
    max_member_uncompressed_bytes: int = 50 * 1024 * 1024  # 50 MiB
    # Hard ceiling for the whole archive's declared uncompressed size.  A zip
    # that claims to expand beyond this is treated as a zip-bomb risk.
    max_total_uncompressed_bytes: int = 20 * 1024 * 1024 * 1024  # 20 GiB
    # Hard ceiling on the on-disk zip file size we will even open.
    max_zip_file_bytes: int = 8 * 1024 * 1024 * 1024  # 8 GiB
    # Cap bytes hashed per member (streaming); larger members get a sampled,
    # explicitly-truncated hash rather than blocking the whole run.
    max_hash_bytes_per_member: int = 256 * 1024 * 1024  # 256 MiB
    # Text-ish extensions that may be sampled/parsed as UTF-8.
    text_extensions: tuple[str, ...] = (
        ".pgn", ".md", ".txt", ".json", ".csv", ".tsv", ".ipynb", ".py",
        ".js", ".ts", ".tsx", ".jsx", ".html", ".htm", ".css", ".yaml",
        ".yml", ".xml", ".log",
    )


# A member path component of exactly ".." is traversal; a drive letter or a
# leading slash/backslash is an absolute target; UNC (\\host) is absolute too.
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def is_unsafe_member_path(archive_path: str) -> tuple[bool, str]:
    """Return ``(is_blocked, reason)`` for a member path.

    Detects zip-slip (``..`` traversal), absolute paths, drive letters, and
    UNC paths.  Pure string analysis — never touches the filesystem.
    """
    raw = archive_path or ""
    norm = raw.replace("\\", "/")
    if not norm:
        return True, "empty_member_path"
    if norm.startswith("/"):
        return True, "absolute_path"
    if raw.startswith("\\\\") or norm.startswith("//"):
        return True, "unc_absolute_path"
    if _DRIVE_RE.match(raw):
        return True, "windows_drive_absolute_path"
    parts = [p for p in norm.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return True, "path_traversal_dotdot"
    # Defense in depth: simulate a join and confirm it cannot escape a root.
    joined = os.path.normpath(os.path.join("__root__", norm))
    if not (joined == "__root__" or joined.startswith("__root__" + os.sep)):
        return True, "path_escapes_root"
    return False, ""


@dataclass(slots=True)
class MemberSafety:
    status: SafetyStatus
    reason: str
    compression_ratio: float
    too_large_to_parse: bool


def classify_member_safety(
    info: zipfile.ZipInfo, config: SafetyConfig
) -> MemberSafety:
    """Classify a single member without extracting it."""
    blocked, reason = is_unsafe_member_path(info.filename)
    comp = max(int(info.compress_size), 1)
    uncomp = int(info.file_size)
    ratio = uncomp / comp
    if blocked:
        return MemberSafety(SafetyStatus.BLOCKED, reason, ratio, False)
    if uncomp < 0 or info.compress_size < 0:
        return MemberSafety(
            SafetyStatus.BLOCKED, "impossible_negative_size", ratio, False
        )
    reasons: list[str] = []
    status = SafetyStatus.SAFE
    too_large = uncomp > config.max_member_uncompressed_bytes
    if ratio > config.r_max:
        status = SafetyStatus.WARNING
        reasons.append(f"compression_ratio_{ratio:.0f}_gt_{config.r_max:.0f}")
    if too_large:
        status = SafetyStatus.WARNING
        reasons.append("member_too_large_stream_only_no_text_parse")
    return MemberSafety(status, ",".join(reasons), ratio, too_large)


@dataclass(slots=True)
class ArchiveSafety:
    status: SafetyStatus
    reason: str
    file_exists: bool
    extension_ok: bool
    openable: bool
    zip_file_bytes: int
    total_compressed_bytes: int
    total_uncompressed_bytes: int
    cr_total: float
    member_count: int
    checks: dict[str, bool]


class ZipSafetyValidator:
    """Validates an archive path and (if openable) its central directory."""

    def __init__(self, config: SafetyConfig | None = None) -> None:
        self.config = config or SafetyConfig()

    def validate_archive(self, zip_path: str) -> ArchiveSafety:
        cfg = self.config
        checks: dict[str, bool] = {}
        exists = os.path.isfile(zip_path)
        checks["file_exists"] = exists
        ext_ok = str(zip_path).lower().endswith(".zip")
        checks["extension_is_zip"] = ext_ok
        if not exists:
            return ArchiveSafety(
                SafetyStatus.BLOCKED, "file_not_found", False, ext_ok, False,
                0, 0, 0, 0.0, 0, checks,
            )
        size = os.path.getsize(zip_path)
        checks["within_max_zip_file_bytes"] = size <= cfg.max_zip_file_bytes
        if not ext_ok:
            return ArchiveSafety(
                SafetyStatus.BLOCKED, "extension_not_zip", True, False, False,
                size, 0, 0, 0.0, 0, checks,
            )
        if size > cfg.max_zip_file_bytes:
            return ArchiveSafety(
                SafetyStatus.BLOCKED, "zip_file_too_large", True, True, False,
                size, 0, 0, 0.0, 0, checks,
            )
        # Try to open + read central directory.  BadZipFile => corrupted.
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                infos = zf.infolist()
                total_comp = sum(max(int(i.compress_size), 0) for i in infos)
                total_uncomp = sum(max(int(i.file_size), 0) for i in infos)
        except (zipfile.BadZipFile, OSError, EOFError, RuntimeError) as exc:
            checks["openable"] = False
            return ArchiveSafety(
                SafetyStatus.BLOCKED, f"unreadable_or_corrupted:{type(exc).__name__}",
                True, True, False, size, 0, 0, 0.0, 0, checks,
            )
        checks["openable"] = True
        cr_total = total_uncomp / max(total_comp, 1)
        checks["within_max_total_uncompressed"] = (
            total_uncomp <= cfg.max_total_uncompressed_bytes
        )
        checks["compression_ratio_within_limit"] = cr_total <= cfg.cr_total_max
        # Any blocked member path blocks the whole archive (zip-slip present).
        blocked_members = [
            i.filename for i in infos
            if is_unsafe_member_path(i.filename)[0]
        ]
        checks["no_path_traversal"] = not blocked_members
        status = SafetyStatus.SAFE
        reasons: list[str] = []
        if blocked_members:
            status = SafetyStatus.BLOCKED
            reasons.append(f"unsafe_member_paths:{len(blocked_members)}")
        if total_uncomp > cfg.max_total_uncompressed_bytes:
            status = SafetyStatus.BLOCKED
            reasons.append("declared_uncompressed_exceeds_cap_zipbomb_risk")
        if cr_total > cfg.cr_total_max and status is not SafetyStatus.BLOCKED:
            status = SafetyStatus.WARNING
            reasons.append(f"archive_compression_ratio_{cr_total:.0f}")
        return ArchiveSafety(
            status, ",".join(reasons) or "ok", True, True, True, size,
            total_comp, total_uncomp, cr_total, len(infos), checks,
        )


__all__ = [
    "SafetyStatus",
    "SafetyConfig",
    "ZipSafetyValidator",
    "ArchiveSafety",
    "MemberSafety",
    "classify_member_safety",
    "is_unsafe_member_path",
]

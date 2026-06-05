"""Streaming provenance hashing for zip members.

We never load a 700 MB member into memory.  Hashing reads the decompressed
stream in fixed-size chunks.  The per-record ``provenance_id`` binds three
facts together so a derived simulation record is always traceable back to the
exact source bytes:

    provenance_id = SHA256(
        zip_path_normalized || "::" || archive_path_normalized || "::" ||
        sha256(file_bytes)
    )
"""
from __future__ import annotations

import hashlib
import zipfile

_CHUNK = 1 << 20  # 1 MiB


def normalize_archive_path(path: str) -> str:
    """Deterministic, forward-slashed, stripped archive path."""
    return path.replace("\\", "/").strip().lstrip("/")


def normalize_zip_path(path: str) -> str:
    """Deterministic representation of the source zip path.

    Only normalizes separators and trims whitespace.  We intentionally keep
    the operator-supplied path text (so provenance encodes which archive a
    record came from) rather than resolving it against the local filesystem,
    which would make hashes machine-dependent.
    """
    return str(path).replace("\\", "/").strip()


class ProvenanceHasher:
    """Computes streaming SHA-256 of zip members and derived provenance ids."""

    def __init__(self, *, chunk_size: int = _CHUNK) -> None:
        self.chunk_size = max(1, int(chunk_size))

    def sha256_member(
        self,
        zf: zipfile.ZipFile,
        info: zipfile.ZipInfo,
        *,
        max_bytes: int | None = None,
    ) -> tuple[str | None, int, bool]:
        """Stream-hash a single member.

        Returns ``(hexdigest_or_None, bytes_read, truncated)``.  If
        ``max_bytes`` is set and the member is larger, hashing stops early and
        ``truncated`` is True with ``hexdigest`` left as ``None`` (we refuse to
        emit a misleading partial hash as if it were the full-file digest).
        """
        digest = hashlib.sha256()
        read = 0
        try:
            with zf.open(info, "r") as handle:
                while True:
                    if max_bytes is not None and read >= max_bytes:
                        return None, read, True
                    chunk = handle.read(self.chunk_size)
                    if not chunk:
                        break
                    read += len(chunk)
                    if max_bytes is not None and read > max_bytes:
                        return None, read, True
                    digest.update(chunk)
        except (zipfile.BadZipFile, RuntimeError, OSError, EOFError):
            return None, read, False
        return digest.hexdigest(), read, False

    @staticmethod
    def provenance_id(
        zip_path: str, archive_path: str, file_sha256: str | None
    ) -> str:
        """Deterministic provenance id binding zip + member + content hash."""
        material = "::".join(
            [
                normalize_zip_path(zip_path),
                normalize_archive_path(archive_path),
                file_sha256 or "NO_CONTENT_HASH",
            ]
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


__all__ = ["ProvenanceHasher", "normalize_archive_path", "normalize_zip_path"]

"""Safe zip inventory scanning without full extraction.

``ZipInventoryScanner`` reads the central directory and streams each member
once to compute a content hash and a small classification sample.  It never
extracts to disk and never loads a whole large member into memory.

``ZipManifestBuilder`` assembles a deterministic, sorted manifest suitable for
reproducible JSON output.
"""
from __future__ import annotations

import datetime as _dt
import os
import zipfile
from dataclasses import asdict, dataclass, field

from src.simulation_zip.classifier import DatasetClassifier
from src.simulation_zip.provenance import ProvenanceHasher, normalize_archive_path
from src.simulation_zip.safety import (
    SafetyConfig,
    SafetyStatus,
    classify_member_safety,
)

# Bytes sampled from each text-ish member for family classification.
_SAMPLE_BYTES = 64 * 1024


@dataclass(slots=True)
class ManifestEntry:
    archive_path: str
    safe_normalized_path: str
    extension: str
    file_name: str
    directory: str
    compressed_size_bytes: int
    uncompressed_size_bytes: int
    compression_ratio: float
    modified_datetime_from_zip: str
    sha256: str | None
    sha256_truncated: bool
    content_type_guess: str
    dataset_family_guess: str
    confidence: float
    confidence_class: str
    classification_features: dict[str, int]
    family_scores: dict[str, float]
    parser_candidate: str
    safety_status: str
    reason: str
    provenance_id: str
    is_dir: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _zip_datetime(info: zipfile.ZipInfo) -> str:
    try:
        y, mo, d, h, mi, s = info.date_time
        if y < 1980:
            return ""
        return _dt.datetime(y, mo, d, h, mi, s).isoformat()
    except (ValueError, TypeError):
        return ""


class ZipInventoryScanner:
    def __init__(
        self,
        *,
        config: SafetyConfig | None = None,
        classifier: DatasetClassifier | None = None,
        hasher: ProvenanceHasher | None = None,
        sample_bytes: int = _SAMPLE_BYTES,
    ) -> None:
        self.config = config or SafetyConfig()
        self.classifier = classifier or DatasetClassifier()
        self.hasher = hasher or ProvenanceHasher()
        self.sample_bytes = sample_bytes

    def _read_sample(
        self, zf: zipfile.ZipFile, info: zipfile.ZipInfo, ext: str
    ) -> bytes:
        if ext not in self.config.text_extensions:
            return b""
        try:
            with zf.open(info, "r") as handle:
                return handle.read(self.sample_bytes)
        except (zipfile.BadZipFile, RuntimeError, OSError, EOFError):
            return b""

    def scan_member(
        self, zf: zipfile.ZipFile, info: zipfile.ZipInfo, zip_path: str
    ) -> ManifestEntry:
        archive_path = info.filename
        norm = normalize_archive_path(archive_path)
        ext = os.path.splitext(norm)[1].lower()
        file_name = os.path.basename(norm)
        directory = os.path.dirname(norm)
        is_dir = info.is_dir()

        member_safety = classify_member_safety(info, self.config)
        blocked = member_safety.status is SafetyStatus.BLOCKED

        sha: str | None = None
        truncated = False
        sample = b""
        if not blocked and not is_dir:
            sha, _read, truncated = self.hasher.sha256_member(
                zf, info, max_bytes=self.config.max_hash_bytes_per_member
            )
            if not member_safety.too_large_to_parse:
                sample = self._read_sample(zf, info, ext)

        cls = self.classifier.classify(norm, sample)
        provenance = self.hasher.provenance_id(zip_path, archive_path, sha)

        return ManifestEntry(
            archive_path=archive_path,
            safe_normalized_path=norm,
            extension=ext,
            file_name=file_name,
            directory=directory,
            compressed_size_bytes=int(info.compress_size),
            uncompressed_size_bytes=int(info.file_size),
            compression_ratio=round(member_safety.compression_ratio, 4),
            modified_datetime_from_zip=_zip_datetime(info),
            sha256=sha,
            sha256_truncated=truncated,
            content_type_guess=cls.content_type_guess,
            dataset_family_guess=cls.family.value,
            confidence=cls.confidence,
            confidence_class=cls.confidence_class.value,
            classification_features=cls.features,
            family_scores=cls.all_scores,
            parser_candidate=cls.parser_candidate if not blocked else "none",
            safety_status=member_safety.status.value,
            reason=member_safety.reason or ("blocked" if blocked else "ok"),
            provenance_id=provenance,
            is_dir=is_dir,
        )

    def scan(self, zip_path: str) -> list[ManifestEntry]:
        entries: list[ManifestEntry] = []
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                entries.append(self.scan_member(zf, info, zip_path))
        return entries


class ZipManifestBuilder:
    """Builds a deterministic manifest dict from scanned entries."""

    def build(
        self, zip_path: str, entries: list[ManifestEntry]
    ) -> dict[str, object]:
        files = [e for e in entries if not e.is_dir]
        ordered = sorted(files, key=lambda e: e.safe_normalized_path)
        family_counts: dict[str, int] = {}
        safety_counts: dict[str, int] = {}
        ext_counts: dict[str, int] = {}
        for e in ordered:
            family_counts[e.dataset_family_guess] = (
                family_counts.get(e.dataset_family_guess, 0) + 1
            )
            safety_counts[e.safety_status] = safety_counts.get(e.safety_status, 0) + 1
            ext_counts[e.extension or "<none>"] = (
                ext_counts.get(e.extension or "<none>", 0) + 1
            )
        return {
            "zip_path": str(zip_path).replace("\\", "/"),
            "member_count": len(ordered),
            "directory_count": sum(1 for e in entries if e.is_dir),
            "family_counts": dict(sorted(family_counts.items())),
            "safety_counts": dict(sorted(safety_counts.items())),
            "extension_counts": dict(sorted(ext_counts.items())),
            "files": [e.to_dict() for e in ordered],
        }


__all__ = ["ZipInventoryScanner", "ZipManifestBuilder", "ManifestEntry"]

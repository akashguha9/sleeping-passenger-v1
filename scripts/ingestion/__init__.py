"""Global Signal Fabric — read-only source-loader package (Phase 2)."""

from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader

__all__ = ["BaseSourceLoader", "LoaderResult", "SkipLoader"]

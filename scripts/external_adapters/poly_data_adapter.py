from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any

from scripts.external_adapters.base import (
    ExternalAdapter,
    ExternalAdapterStatus,
    ExternalEvidence,
    ExternalEvidenceType,
    ExternalExecutionPermission,
    bounded_score,
    safe_float,
    safe_str,
)


class PolyDataAdapter(ExternalAdapter):
    """Read-only GPL sidecar reader for exported poly_data CSV artifacts."""

    source_name = "poly_data"
    evidence_type = ExternalEvidenceType.PREDICTION_MARKET
    license_boundary = "GPL-3.0 sidecar - no source code copied into MVP core"
    default_execution_permission = ExternalExecutionPermission.WATCH_ONLY

    def _resolve_root(self, context: dict[str, Any] | None = None) -> Path:
        ctx = context or {}
        candidate = safe_str(ctx.get("path"))
        if candidate:
            return Path(candidate)
        env_name = safe_str(self.config.get("path_env"), "POLY_DATA_PATH")
        env_value = safe_str(os.environ.get(env_name))
        if env_value:
            return Path(env_value)
        return Path(safe_str(self.config.get("fallback_path"), "external/poly_data"))

    def _read_csv_rows(self, path: Path, max_rows: int) -> list[dict[str, str]]:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows: list[dict[str, str]] = []
            for index, row in enumerate(reader):
                if index >= max_rows:
                    break
                rows.append({str(k): safe_str(v) for k, v in row.items()})
            return rows

    def collect(self, context: dict[str, Any] | None = None) -> list[ExternalEvidence]:
        if not bool(self.config.get("enabled", False)):
            return []
        root = self._resolve_root(context)
        max_rows = int(self.config.get("max_rows", 5000) or 5000)
        file_specs = [
            ("markets", root / "markets.csv"),
            ("trades", root / "trades.csv"),
            ("processed_trades", root / "processed" / "trades.csv"),
            ("order_filled", root / "orderFilled.csv"),
            ("goldsky_order_filled", root / "goldsky" / "orderFilled.csv"),
        ]
        warnings: list[str] = []
        errors: list[str] = []
        markets: list[dict[str, Any]] = []
        trades: list[dict[str, Any]] = []
        files_seen: list[str] = []

        if not root.exists():
            return [
                self.build_failure_evidence(
                    message=f"poly_data sidecar path not found: {root}",
                    adapter_status=ExternalAdapterStatus.UNAVAILABLE,
                    data_truth_origin="external_csv_poly_data",
                    warnings=["adapter degraded gracefully; no sidecar path available"],
                )
            ]

        for label, path in file_specs:
            if not path.exists():
                warnings.append(f"missing optional file: {path.as_posix()}")
                continue
            files_seen.append(path.as_posix())
            try:
                rows = self._read_csv_rows(path, max_rows=max_rows)
            except OSError as exc:
                errors.append(f"failed to read {path.as_posix()}: {exc}")
                continue
            for row in rows:
                if label == "markets":
                    question = safe_str(
                        row.get("question") or row.get("title") or row.get("market_question")
                    )
                    price = safe_float(
                        row.get("price") or row.get("yes_price") or row.get("last_price"),
                        default=-1.0,
                    )
                    if not question:
                        warnings.append("skipped market row without question")
                        continue
                    if not 0.0 <= price <= 1.0 and price != -1.0:
                        warnings.append(f"skipped market row with invalid price for {question}")
                        continue
                    markets.append(
                        {
                            "question": question,
                            "market_id": safe_str(row.get("market_id") or row.get("condition_id")),
                            "price": price if price != -1.0 else None,
                            "category": safe_str(row.get("category")),
                        }
                    )
                else:
                    price = safe_float(row.get("price") or row.get("execution_price"), default=-1.0)
                    usd_amount = safe_float(row.get("usd_amount"), default=0.0)
                    token_amount = safe_float(row.get("token_amount"), default=0.0)
                    if price != -1.0 and not 0.0 <= price <= 1.0:
                        warnings.append("skipped trade row with invalid price")
                        continue
                    if usd_amount < 0.0 or token_amount < 0.0:
                        warnings.append("skipped trade row with negative amounts")
                        continue
                    trades.append(
                        {
                            "market_question": safe_str(
                                row.get("question") or row.get("market_question") or row.get("title")
                            ),
                            "price": None if price == -1.0 else price,
                            "usd_amount": usd_amount,
                            "token_amount": token_amount,
                            "trade_id": safe_str(row.get("trade_id") or row.get("id")),
                            "source_file": label,
                        }
                    )

        status = (
            ExternalAdapterStatus.AVAILABLE
            if (markets or trades)
            else ExternalAdapterStatus.DEGRADED
        )
        quality = bounded_score((len(markets) + len(trades)) / max(len(markets) + len(trades) + len(warnings), 1))
        evidence = self.build_evidence(
            normalized_payload={
                "root_path": root.as_posix(),
                "files_seen": files_seen,
                "markets": markets,
                "trades": trades,
            },
            data_truth_origin="external_csv_poly_data",
            adapter_status=status,
            warnings=warnings,
            errors=errors,
            confidence_proxy=0.55 if markets else 0.35,
            evidence_quality_score=quality,
            context_tags=["prediction_market", "sidecar", "gpl_boundary"],
        )
        return [evidence]

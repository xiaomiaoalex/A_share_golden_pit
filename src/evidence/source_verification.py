"""Verify immutable local evidence snapshots and point-in-time availability.

The research stages deliberately do not dereference arbitrary URLs during an
import.  Every cited source must instead point to a local snapshot whose bytes
and searchable text are locked by SHA-256.  This makes an imported conclusion
reproducible without turning the importer into a network client or an SSRF
surface.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
TEXT_SUFFIXES = {".txt", ".md", ".json", ".csv", ".tsv", ".html", ".xml"}


class SourceVerificationError(ValueError):
    """Raised when a source cannot be reproduced from its declared snapshot."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_file(value: str, base_dir: Path, field: str) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    candidate = candidate.resolve()
    if not candidate.is_file():
        raise SourceVerificationError(f"{field}不存在或不是文件: {candidate}")
    return candidate


def _parse_available_at(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise SourceVerificationError(f"available_at不是ISO 8601时间: {value}") from exc
    if parsed.tzinfo is None:
        raise SourceVerificationError("available_at必须包含时区")
    return parsed


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _searchable_text(source: dict[str, Any], snapshot: Path, base_dir: Path) -> str:
    extracted_value = source.get("extracted_text_path")
    if extracted_value:
        extracted = _resolve_file(str(extracted_value), base_dir, "extracted_text_path")
        expected = str(source.get("extracted_text_sha256", "")).lower()
        actual = _sha256(extracted)
        if actual != expected:
            raise SourceVerificationError(
                f"提取文本SHA-256不一致: expected={expected}, actual={actual}"
            )
        text_path = extracted
    elif snapshot.suffix.lower() in TEXT_SUFFIXES:
        text_path = snapshot
    else:
        raise SourceVerificationError(
            "二进制快照必须同时提供extracted_text_path和extracted_text_sha256"
        )
    try:
        return text_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise SourceVerificationError(f"证据文本必须是UTF-8: {text_path}") from exc


def verify_sources(
    sources: Iterable[dict[str, Any]],
    *,
    as_of: date,
    base_dir: str | Path,
    required_claims: Iterable[str] = (),
    context: str,
) -> None:
    """Verify source dates, immutable bytes, excerpts and claim coverage."""

    root = Path(base_dir).resolve()
    claims = {str(item).strip() for item in required_claims if str(item).strip()}
    covered: set[str] = set()
    for source_index, source in enumerate(sources):
        prefix = f"{context}.sources[{source_index}]"
        published = date.fromisoformat(str(source["date"]))
        if published > as_of:
            raise SourceVerificationError(f"{prefix}引用了as-of之后的来源")
        available = _parse_available_at(str(source["available_at"]))
        cutoff = datetime.combine(as_of, time.max, tzinfo=SHANGHAI)
        if available.astimezone(SHANGHAI) > cutoff:
            raise SourceVerificationError(f"{prefix}在as-of之后才可得")

        snapshot = _resolve_file(str(source["snapshot_path"]), root, "snapshot_path")
        expected_hash = str(source["content_sha256"]).lower()
        actual_hash = _sha256(snapshot)
        if actual_hash != expected_hash:
            raise SourceVerificationError(
                f"{prefix}快照SHA-256不一致: expected={expected_hash}, actual={actual_hash}"
            )

        evidence_text = _normalized_text(_searchable_text(source, snapshot, root))
        excerpt = _normalized_text(str(source["evidence_excerpt"]))
        if excerpt not in evidence_text:
            raise SourceVerificationError(f"{prefix}声明的证据摘录未在快照文本中找到")

        source_claims = {
            str(item).strip() for item in source["supported_claims"] if str(item).strip()
        }
        unknown_claims = source_claims - claims if claims else set()
        if unknown_claims:
            raise SourceVerificationError(
                f"{prefix}映射了当前事实集合之外的声明: {sorted(unknown_claims)}"
            )
        covered.update(source_claims)

    missing = claims - covered
    if missing:
        raise SourceVerificationError(
            f"{context}存在未绑定到可验证来源的事实: {sorted(missing)}"
        )

"""Reproducible Parquet snapshots queried through a read-only whitelist."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import duckdb

from src.ai_research import DataEgressClass, ResearchRepository
from src.strategies.golden_pit.persistence.tier1_repository import Tier1Repository


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SnapshotService:
    def __init__(self, db_path: str | Path, snapshot_root: str | Path) -> None:
        self.db_path = Path(db_path)
        self.snapshot_root = Path(snapshot_root)
        self.snapshot_root.mkdir(parents=True, exist_ok=True)

    def migrate(self) -> None:
        Tier1Repository(self.db_path).migrate_all()

    def publish(
        self,
        *,
        dataset_type: str,
        as_of_date: str,
        rows: Iterable[Mapping[str, Any]],
        lineage: Mapping[str, Any],
        quality: Mapping[str, Any],
    ) -> dict[str, Any]:
        materialized = [dict(row) for row in rows]
        if not materialized:
            raise ValueError("不可发布空快照")
        columns = tuple(materialized[0])
        if any(tuple(row) != columns for row in materialized):
            raise ValueError("快照行的字段顺序和集合必须一致")
        canonical = sorted(materialized, key=lambda item: json.dumps(item, sort_keys=True, default=str))
        snapshot_id = str(uuid.uuid4())
        target_dir = self.snapshot_root / dataset_type / as_of_date
        target_dir.mkdir(parents=True, exist_ok=True)
        temporary = target_dir / f".{snapshot_id}.tmp.parquet"
        connection = duckdb.connect(":memory:")
        try:
            connection.execute("CREATE TABLE snapshot AS SELECT * FROM (VALUES (NULL)) WHERE 1=0")
            connection.execute("DROP TABLE snapshot")
            import pandas as pd

            frame = pd.DataFrame(canonical, columns=columns)
            connection.register("snapshot_input", frame)
            connection.execute(
                "COPY (SELECT * FROM snapshot_input) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
                [str(temporary)],
            )
            schema_rows = connection.execute(
                "DESCRIBE SELECT * FROM snapshot_input"
            ).fetchall()
        finally:
            connection.close()
        content_hash = hashlib.sha256(temporary.read_bytes()).hexdigest()
        final_path = target_dir / f"{content_hash}.parquet"
        if final_path.exists():
            temporary.unlink()
        else:
            os.replace(temporary, final_path)
        schema = [{"name": row[0], "type": row[1]} for row in schema_rows]
        with sqlite3.connect(self.db_path, timeout=10) as db:
            db.execute(
                """
                INSERT INTO data_snapshots(
                    snapshot_id, dataset_type, as_of_date, parquet_path,
                    content_hash, row_count, schema_json, lineage_json,
                    quality_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dataset_type, as_of_date, content_hash) DO NOTHING
                """,
                (
                    snapshot_id,
                    dataset_type,
                    as_of_date,
                    str(final_path.resolve()),
                    content_hash,
                    len(canonical),
                    json.dumps(schema, ensure_ascii=False, sort_keys=True),
                    json.dumps(lineage, ensure_ascii=False, sort_keys=True),
                    json.dumps(quality, ensure_ascii=False, sort_keys=True),
                    _now(),
                ),
            )
            row = db.execute(
                """
                SELECT * FROM data_snapshots
                WHERE dataset_type=? AND as_of_date=? AND content_hash=?
                """,
                (dataset_type, as_of_date, content_hash),
            ).fetchone()
            columns_db = [item[0] for item in db.execute("SELECT * FROM data_snapshots LIMIT 0").description]
        return dict(zip(columns_db, row))

    def query(
        self,
        snapshot_id: str,
        *,
        fields: Sequence[str],
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not fields or limit < 1 or limit > 1000:
            raise ValueError("查询字段不能为空且 limit 必须在 1 到 1000 之间")
        with sqlite3.connect(self.db_path, timeout=10) as db:
            db.row_factory = sqlite3.Row
            snapshot = db.execute(
                "SELECT * FROM data_snapshots WHERE snapshot_id=?", (snapshot_id,)
            ).fetchone()
        if snapshot is None:
            raise ValueError("未知数据快照")
        allowed = {item["name"] for item in json.loads(snapshot["schema_json"])}
        if not set(fields).issubset(allowed):
            raise ValueError("查询包含快照白名单以外的字段")
        quoted = ", ".join(f'"{field}"' for field in fields)
        connection = duckdb.connect(":memory:")
        try:
            result = connection.execute(
                f"SELECT {quoted} FROM read_parquet(?) LIMIT ?",  # noqa: S608
                [snapshot["parquet_path"], limit],
            )
            names = [item[0] for item in result.description]
            return [dict(zip(names, row)) for row in result.fetchall()]
        finally:
            connection.close()

    def set_egress_policy(
        self, field_path: str, egress_class: DataEgressClass, mask_rule: str = ""
    ) -> None:
        with sqlite3.connect(self.db_path, timeout=10) as db:
            db.execute(
                """
                INSERT INTO field_egress_policies(field_path, egress_class, mask_rule, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(field_path) DO UPDATE SET
                    egress_class=excluded.egress_class,
                    mask_rule=excluded.mask_rule,
                    updated_at=excluded.updated_at
                """,
                (field_path, egress_class.value, mask_rule or None, _now()),
            )

    def publish_ai_dataset(
        self,
        *,
        dataset_id: str,
        snapshot_id: str,
        strategy_id: str,
        release_id: str,
        fields: Sequence[str],
        target_region: str = "CN",
    ) -> None:
        with sqlite3.connect(self.db_path, timeout=10) as db:
            db.row_factory = sqlite3.Row
            snapshot = db.execute(
                "SELECT * FROM data_snapshots WHERE snapshot_id=?", (snapshot_id,)
            ).fetchone()
            policies = {
                row["field_path"]: DataEgressClass(row["egress_class"])
                for row in db.execute("SELECT * FROM field_egress_policies").fetchall()
            }
        if snapshot is None:
            raise ValueError("未知数据快照")
        blocked = []
        for field in fields:
            policy = policies.get(field, DataEgressClass.DENY_AI)
            if policy in {
                DataEgressClass.DENY_AI,
                DataEgressClass.LOCAL_ONLY,
                DataEgressClass.MASK_BEFORE_SEND,
            }:
                blocked.append(field)
            if target_region != "CN" and policy != DataEgressClass.APPROVED_EXTERNAL:
                blocked.append(field)
        if blocked:
            raise ValueError(f"字段外发策略阻断: {sorted(set(blocked))}")
        ResearchRepository(self.db_path).create_dataset(
            dataset_id=dataset_id,
            strategy_id=strategy_id,
            release_id=release_id,
            as_of_date=str(snapshot["as_of_date"]),
            content_hash=str(snapshot["content_hash"]),
            egress_class=(
                DataEgressClass.DOMESTIC_ALLOWED
                if target_region == "CN"
                else DataEgressClass.APPROVED_EXTERNAL
            ),
            manifest={
                "snapshot_id": snapshot_id,
                "parquet_path": snapshot["parquet_path"],
                "fields": list(fields),
                "row_count": snapshot["row_count"],
                "quality": json.loads(snapshot["quality_json"]),
                "lineage": json.loads(snapshot["lineage_json"]),
            },
        )

    def overview(self) -> dict[str, Any]:
        with sqlite3.connect(self.db_path, timeout=10) as db:
            db.row_factory = sqlite3.Row
            snapshots = db.execute(
                """
                SELECT snapshot_id, dataset_type, as_of_date, content_hash,
                       row_count, schema_json, lineage_json, quality_json, created_at
                FROM data_snapshots ORDER BY created_at DESC LIMIT 100
                """
            ).fetchall()
            policies = db.execute(
                """
                SELECT field_path, egress_class, mask_rule, updated_at
                FROM field_egress_policies ORDER BY field_path
                """
            ).fetchall()
            report_versions = db.execute(
                """
                SELECT security_id, report_period, announcement_date, revision,
                       content_hash, source_record_id
                FROM financial_report_versions
                ORDER BY announcement_date DESC LIMIT 100
                """
            ).fetchall()
        items = []
        for row in snapshots:
            item = dict(row)
            item["schema"] = json.loads(item.pop("schema_json"))
            item["lineage"] = json.loads(item.pop("lineage_json"))
            item["quality"] = json.loads(item.pop("quality_json"))
            items.append(item)
        return {
            "snapshots": items,
            "egress_policies": [dict(row) for row in policies],
            "financial_report_versions": [dict(row) for row in report_versions],
        }

"""采集数据标注业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "tag"
REQUIRED_FIELDS = ["标注编号", "数据记录", "标注类型"]
OPTIONAL_FIELDS = ["标注标签", "标注批次", "标注人"]
STATUS_ORDER = ["草稿", "已标注", "已复核", "已归档"]
ACTION_RULES = {"提交复核": "已标注", "归档标注": "已复核", "删除标注": "已归档"}
NEGATIVE_ACTIONS = []
REVIEW_STATUSES = ["待裁定", "已裁定", "已退回"]

# 列表筛选口径：查询参数 -> 记录字段。多个条件同时给出时逐层收窄，取交集。
FILTER_FIELDS = {
    "tag_type": "标注类型",
    "tag_label": "标注标签",
    "tag_batch": "标注批次",
}


class TagService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        review_status: str | None = None,
        page: int = 1,
        size: int = 20,
        **filters: str | None,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("标注编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if review_status:
            rows = [row for row in rows if row.get("复核状态") == review_status]
        for param, field in FILTER_FIELDS.items():
            value = (filters.get(param) or "").strip()
            if value:
                rows = [row for row in rows if value in str(row.get(field, ""))]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def distinct_values(self, field: str) -> list[str]:
        """列出某字段已出现的取值（如全部标注批次），供筛选与建批时下拉选择。"""
        seen: list[str] = []
        for row in store.rows(MODULE):
            value = str(row.get(field) or "").strip()
            if value and value not in seen:
                seen.append(value)
        return seen

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS + OPTIONAL_FIELDS})
        entry["标注时间"] = str(values.get("标注时间") or date.today().isoformat())
        entry["复核状态"] = "待裁定"
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["revision"] = 1
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"标注记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于采集数据标注可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        entry["revision"] = int(entry.get("revision", 1)) + 1
        return entry, f"标注记录已{action}"

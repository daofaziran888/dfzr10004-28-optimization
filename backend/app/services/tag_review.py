"""标注复核批次：把同一标注批次的条目编成复核队列，记录已完成位置与最后修改时间。

设计口径：
- 打开批次时按「标注批次 + 标注标签 + 标注类型」取交集生成复核队列；
- 已复核/已归档的条目入队即记为已裁定，不再推进，已保存的标签原样保留；
- 重新打开批次时延续已完成位置，新登记的记录只追加到队尾，不插入已完成的位置；
- 裁定提交携带 base_revision，先完成状态推进的一方生效，后到请求收到明确的冲突提示；
- 每次变更同步重算待复核数量（供校验清单读取）并落一条审计记录。
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from app.services import audit as audit_service
from app.store import store

MODULE = "tagreview"
TAG_MODULE = "tag"

# 队列里仍需处理的状态：待裁定或已退回；已裁定的条目不再出现在复核工作集里。
QUEUE_OPEN_STATES = ("待裁定", "已退回")
DECISIONS = {"通过": "已裁定", "退回": "已退回"}
DEFAULT_GROUP_SIZE = 5
MAX_GROUP_SIZE = 50

_lock = threading.Lock()
# 单调递增的更新序号：时间排序的决胜键，保证同一秒内的多次变更新旧有序。
_seq = 0


class ReviewConflict(Exception):
    """复核提交冲突：已有请求先完成了状态推进，或条目无需重复裁定。"""


class ReviewBatchError(Exception):
    """批次或条目定位失败，消息可直接回给前端。"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _touch(batch: dict[str, Any]) -> None:
    """记录一次批次变更：刷新最后修改时间并递增更新序号。"""
    global _seq
    _seq += 1
    batch["更新序号"] = _seq
    batch["最后修改时间"] = _now()


def _initial_state(entry: dict[str, Any]) -> str:
    """入队初始状态：已复核/已归档视为已裁定；曾被退回的保持已退回。"""
    if entry.get("status") in ("已复核", "已归档"):
        return "已裁定"
    if entry.get("复核状态") == "已退回":
        return "已退回"
    return "待裁定"


def _matches(entry: dict[str, Any], batch_no: str, label: str | None, tag_type: str | None) -> bool:
    if str(entry.get("标注批次") or "") != batch_no:
        return False
    if label and label not in str(entry.get("标注标签") or ""):
        return False
    if tag_type and tag_type not in str(entry.get("标注类型") or ""):
        return False
    return True


def _recalc_cursor(batch: dict[str, Any]) -> None:
    """已完成位置只前进不后退：跳过队首连续的已裁定条目。"""
    queue = batch["队列"]
    cursor = int(batch.get("已完成位置", 0))
    while cursor < len(queue) and queue[cursor]["状态"] == "已裁定":
        cursor += 1
    batch["已完成位置"] = cursor


def _refresh_status(batch: dict[str, Any]) -> None:
    done = progress(batch)["待复核"] == 0
    batch["status"] = "已完成" if done else "进行中"
    batch["pending"] = not done


def progress(batch: dict[str, Any]) -> dict[str, int]:
    queue = batch.get("队列", [])
    done = sum(1 for item in queue if item["状态"] == "已裁定")
    returned = sum(1 for item in queue if item["状态"] == "已退回")
    waiting = sum(1 for item in queue if item["状态"] == "待裁定")
    return {
        "总数": len(queue),
        "已裁定": done,
        "待裁定": waiting,
        "已退回": returned,
        "待复核": waiting + returned,
        "已完成位置": int(batch.get("已完成位置", 0)),
    }


def serialize(batch: dict[str, Any]) -> dict[str, Any]:
    view = {
        "id": batch["id"],
        "批次号": batch["批次号"],
        "定位条件": batch.get("定位条件", {}),
        "status": batch.get("status"),
        "pending": batch.get("pending"),
        "最后修改时间": batch.get("最后修改时间"),
        "创建时间": batch.get("创建时间"),
    }
    view.update(progress(batch))
    return view


def _find_batch(batch_id: int) -> dict[str, Any] | None:
    return store.find(MODULE, batch_id)


def _find_batch_by_scope(batch_no: str, label: str | None, tag_type: str | None) -> dict[str, Any] | None:
    for batch in store.rows(MODULE):
        scope = batch.get("定位条件", {})
        if (
            batch.get("批次号") == batch_no
            and (scope.get("标注标签") or None) == (label or None)
            and (scope.get("标注类型") or None) == (tag_type or None)
        ):
            return batch
    return None


def list_batches(sort: str = "batch", order: str | None = None, page: int = 1, size: int = 20) -> tuple[list[dict[str, Any]], int]:
    """复核批次列表：默认按批次顺序排列，也可按最后修改时间排序，支持翻页。"""
    batches = list(store.rows(MODULE))
    if sort == "time":
        # 时间相同按更新序号分先后，保证最近变更的批次稳定排在前面
        key = lambda item: (str(item.get("最后修改时间") or ""), int(item.get("更新序号", 0)))
        reverse = order != "asc"
    else:
        key = lambda item: str(item.get("批次号") or "")
        reverse = order == "desc"
    batches.sort(key=key, reverse=reverse)
    total = len(batches)
    start = max(page - 1, 0) * size
    return [serialize(batch) for batch in batches[start:start + size]], total


def open_batch(
    batch_no: str,
    label: str | None = None,
    tag_type: str | None = None,
    operator: str | None = None,
) -> tuple[dict[str, Any], bool, int]:
    """打开（或重新打开）复核批次。

    返回 (批次, 是否新建, 本次追加的新记录数)。重开时已完成位置延续，
    符合定位条件的新记录只追加到队尾。
    """
    batch_no = batch_no.strip()
    if not batch_no:
        raise ReviewBatchError("打开复核批次必须给出标注批次号")
    with _lock:
        batch = _find_batch_by_scope(batch_no, label, tag_type)
        created = False
        appended = 0
        if batch is None:
            queue = [
                {"entry_id": int(entry["id"]), "状态": _initial_state(entry), "裁定": None, "完成时间": None}
                for entry in store.rows(TAG_MODULE)
                if _matches(entry, batch_no, label, tag_type)
            ]
            if not queue:
                raise ReviewBatchError(f"标注批次 {batch_no} 下没有符合定位条件的标注记录")
            rows = store.rows(MODULE)
            batch = {
                "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
                "批次号": batch_no,
                "定位条件": {k: v for k, v in {"标注标签": label, "标注类型": tag_type}.items() if v},
                "队列": queue,
                "已完成位置": 0,
                "创建时间": _now(),
                "最后修改时间": None,
                "更新序号": 0,
                "status": "进行中",
                "pending": True,
                "abnormal": False,
            }
            rows.append(batch)
            created = True
            _touch(batch)
        else:
            known = {item["entry_id"] for item in batch["队列"]}
            scope = batch.get("定位条件", {})
            for entry in store.rows(TAG_MODULE):
                if int(entry.get("id", 0)) in known:
                    continue
                if _matches(entry, batch["批次号"], scope.get("标注标签"), scope.get("标注类型")):
                    batch["队列"].append(
                        {"entry_id": int(entry["id"]), "状态": _initial_state(entry), "裁定": None, "完成时间": None}
                    )
                    appended += 1
            if appended:
                _touch(batch)
        _recalc_cursor(batch)
        _refresh_status(batch)
        if created or appended:
            summary = progress(batch)
            audit_service.record_change(
                操作类型="标注复核",
                采集计划=batch_no,
                执行人=operator or "复核员",
                结果摘要=("打开复核批次" if created else "复核批次补充新记录"),
                变更内容=(
                    f"队列 {summary['总数']} 条，待复核 {summary['待复核']} 条"
                    + ("" if created else f"，本次追加 {appended} 条至队尾")
                ),
            )
        return batch, created, appended


def get_batch(batch_id: int) -> dict[str, Any]:
    batch = _find_batch(batch_id)
    if batch is None:
        raise ReviewBatchError(f"复核批次 {batch_id} 不存在")
    return batch


def next_group(batch_id: int, size: int = DEFAULT_GROUP_SIZE) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """定位同一批次的下一组未完成条目：从已完成位置起，只留下待裁定或已退回的。"""
    batch = get_batch(batch_id)
    size = max(1, min(size, MAX_GROUP_SIZE))
    items: list[dict[str, Any]] = []
    with _lock:
        queue = batch["队列"]
        for item in queue[int(batch.get("已完成位置", 0)):]:
            if item["状态"] not in QUEUE_OPEN_STATES:
                continue
            entry = store.find(TAG_MODULE, item["entry_id"])
            if entry is None:
                continue
            items.append({
                "entry_id": item["entry_id"],
                "队列状态": item["状态"],
                "revision": int(entry.get("revision", 1)),
                "标注编号": entry.get("标注编号"),
                "数据记录": entry.get("数据记录"),
                "标注类型": entry.get("标注类型"),
                "标注标签": entry.get("标注标签"),
                "标注批次": entry.get("标注批次"),
                "复核状态": entry.get("复核状态"),
                "标注人": entry.get("标注人"),
                "标注时间": entry.get("标注时间"),
            })
            if len(items) >= size:
                break
    return items, serialize(batch)


def submit_review(
    batch_id: int,
    entry_id: int,
    decision: str,
    base_revision: Any,
    operator: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """对队列内的一条记录提交裁定。

    冲突处理：条目必须仍处于待裁定/已退回，且 base_revision 与当前版本一致；
    否则说明已有请求先完成状态推进，本次提交不生效并给出明确提示。
    """
    if decision not in DECISIONS:
        raise ReviewBatchError(f"裁定结果「{decision}」不支持，可选：{'、'.join(DECISIONS)}")
    with _lock:
        batch = get_batch(batch_id)
        item = next((q for q in batch["队列"] if q["entry_id"] == entry_id), None)
        if item is None:
            raise ReviewBatchError(f"标注记录 {entry_id} 不在本批复核队列中")
        entry = store.find(TAG_MODULE, entry_id)
        if entry is None:
            raise ReviewBatchError(f"标注记录 {entry_id} 不存在或已归档")
        code = entry.get("标注编号", entry_id)
        if item["状态"] not in QUEUE_OPEN_STATES:
            raise ReviewConflict(f"记录 {code} 已完成裁定（{item['状态']}），无需重复提交")
        current_revision = int(entry.get("revision", 1))
        try:
            expected = int(base_revision)
        except (TypeError, ValueError):
            raise ReviewBatchError("提交复核必须携带 base_revision，用于防止并发覆盖")
        if current_revision != expected:
            raise ReviewConflict(
                f"记录 {code} 已被先行推进（当前版本 {current_revision}，本次基于 {expected}），"
                "本次提交未生效，请刷新后重试"
            )
        target = DECISIONS[decision]
        now = _now()
        item["状态"] = target
        item["裁定"] = decision
        item["完成时间"] = now
        entry["revision"] = current_revision + 1
        entry["复核状态"] = target
        if decision == "通过":
            entry["status"] = "已复核"
            entry["pending"] = False
        else:
            entry["status"] = "已标注"
            entry["pending"] = True
        _recalc_cursor(batch)
        _refresh_status(batch)
        _touch(batch)
        summary = progress(batch)
        audit_service.record_change(
            操作类型="标注复核",
            采集计划=batch["批次号"],
            执行人=operator or "复核员",
            结果摘要=f"{code} 裁定{decision}",
            变更内容=(
                f"复核状态→{target}；批次已完成位置 {summary['已完成位置']}/{summary['总数']}，"
                f"待复核 {summary['待复核']} 条"
            ),
        )
        return dict(entry), serialize(batch)


def pending_summary() -> dict[str, Any]:
    """全部批次的待复核汇总：校验清单每次读取时按当前批次进度重算。"""
    waiting = returned = 0
    last: str | None = None
    batches = store.rows(MODULE)
    for batch in batches:
        summary = progress(batch)
        waiting += summary["待裁定"]
        returned += summary["已退回"]
        modified = str(batch.get("最后修改时间") or "")
        if modified and (last is None or modified > last):
            last = modified
    return {
        "批次": len(batches),
        "待裁定": waiting,
        "已退回": returned,
        "待复核": waiting + returned,
        "最后修改时间": last,
    }

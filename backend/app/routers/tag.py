"""采集数据标注接口：维护标注记录，覆盖提交复核、归档标注、删除标注等动作。

复核批次：按批次 + 标签 + 类型定位生成复核队列，支持增量复核与并发冲突提示。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services import tag_review
from app.services.tag import TagService

router = APIRouter(prefix="/api/tag", tags=["采集数据标注"])

service = TagService()

LIST_FIELDS = ["标注编号", "数据记录", "标注类型", "标注标签", "标注批次", "复核状态", "标注人", "标注时间"]
STATUSES = ["草稿", "已标注", "已复核", "已归档"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    request: Request,
    keyword: str | None = Query(default=None, description="按标注编号检索"),
    status: str | None = Query(default=None, description="草稿、已标注、已复核、已归档"),
    review_status: str | None = Query(default=None, description="待裁定、已裁定、已退回"),
    tag_type: str | None = Query(default=None, description="按标注类型过滤"),
    tag_label: str | None = Query(default=None, description="按标注标签过滤"),
    tag_batch: str | None = Query(default=None, description="按标注批次过滤"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """标注列表：编号、状态、复核状态、类型、标签、批次多条件取交集；没有数据时返回空页。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    params = request.query_params
    # 兼容直接以中文字段名发来的查询条件，同样参与交集。
    keyword = keyword or params.get("标注编号")
    tag_type = tag_type or params.get("标注类型")
    tag_label = tag_label or params.get("标注标签")
    tag_batch = tag_batch or params.get("标注批次")
    review_status = review_status or params.get("复核状态")
    items, total = service.list_entries(
        keyword=keyword,
        status=status,
        review_status=review_status,
        tag_type=tag_type,
        tag_label=tag_label,
        tag_batch=tag_batch,
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/batches")
def list_tag_batches() -> dict[str, Any]:
    """列出已出现的标注批次与标签，供打开复核批次时选择。"""
    return {"批次": service.distinct_values("标注批次"), "标签": service.distinct_values("标注标签")}


@router.get("/review-batches", response_model=PageResult[dict])
def list_review_batches(
    sort: str = Query(default="batch", description="batch 按批次顺序，time 按最后修改时间"),
    order: str | None = Query(default=None, description="asc 升序、desc 降序；批次默认升序，时间默认降序"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """复核批次列表：按批次顺序或最后修改时间排列，支持翻页与页码跳转。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = tag_review.list_batches(sort=sort, order=order, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("/review-batches", response_model=ActionResult)
def open_review_batch(payload: EntryPayload) -> ActionResult:
    """打开（或重新打开）复核批次：已完成位置延续，新记录只追加到队尾。"""
    values = payload.values
    try:
        batch, created, appended = tag_review.open_batch(
            str(values.get("批次号") or values.get("标注批次") or ""),
            label=values.get("标注标签") or None,
            tag_type=values.get("标注类型") or None,
            operator=values.get("复核人") or None,
        )
    except tag_review.ReviewBatchError as error:
        raise HTTPException(status_code=400, detail=str(error))
    view = tag_review.serialize(batch)
    if created:
        message = f"复核批次已建立：队列 {view['总数']} 条，待复核 {view['待复核']} 条"
    elif appended:
        message = f"复核批次已重开：延续已完成位置 {view['已完成位置']}，{appended} 条新记录追加至队尾"
    else:
        message = f"复核批次已重开：延续已完成位置 {view['已完成位置']}，待复核 {view['待复核']} 条"
    return ActionResult(ok=True, message=message, entry=view)


@router.get("/review-batches/{batch_id}")
def get_review_batch(batch_id: int) -> dict[str, Any]:
    """读取复核批次进度：已完成位置、最后修改时间与各状态数量。"""
    try:
        return tag_review.serialize(tag_review.get_batch(batch_id))
    except tag_review.ReviewBatchError as error:
        raise HTTPException(status_code=404, detail=str(error))


@router.get("/review-batches/{batch_id}/next")
def next_review_group(batch_id: int, size: int = tag_review.DEFAULT_GROUP_SIZE) -> dict[str, Any]:
    """定位同一批次的下一组未完成条目：从已完成位置起，只留下待裁定或已退回的。"""
    try:
        items, batch = tag_review.next_group(batch_id, size=size)
    except tag_review.ReviewBatchError as error:
        raise HTTPException(status_code=404, detail=str(error))
    return {"batch": batch, "items": items, "size": size}


@router.post("/review-batches/{batch_id}/entries/{entry_id}", response_model=ActionResult)
def submit_review(batch_id: int, entry_id: int, payload: EntryPayload) -> ActionResult:
    """提交一条记录的复核裁定；并发冲突时先完成状态推进的一方生效，后到请求收到明确提示。"""
    values = payload.values
    try:
        entry, batch = tag_review.submit_review(
            batch_id,
            entry_id,
            decision=str(values.get("裁定") or "").strip(),
            base_revision=values.get("base_revision"),
            operator=values.get("复核人") or None,
        )
    except tag_review.ReviewConflict as error:
        raise HTTPException(status_code=409, detail=str(error))
    except tag_review.ReviewBatchError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return ActionResult(
        ok=True,
        message=(
            f"{entry.get('标注编号')} 裁定完成；批次待复核 {batch['待复核']} 条，"
            f"已完成位置 {batch['已完成位置']}/{batch['总数']}"
        ),
        entry={"记录": entry, "批次": batch},
    )


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出采集数据标注清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "tag", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条标注记录明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"标注记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条标注记录，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="标注记录已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条标注记录执行提交复核、归档标注、删除标注；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)

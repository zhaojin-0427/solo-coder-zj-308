from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List, Optional
from datetime import datetime, timedelta
import json

from ..database import get_db
from ..models import (
    Baby, Caregiver, Shift, HandoverItem, TodoTask,
    ConsumptionRecord, InventoryRecord, PlanReminder
)
from ..schemas import (
    CaregiverCreate, CaregiverUpdate, CaregiverResponse,
    ShiftCreate, ShiftEnd, ShiftResponse,
    HandoverItemCreate, HandoverItemUpdate, HandoverItemResponse,
    TodoTaskCreate, TodoTaskComplete, TodoTaskResponse,
    CAREGIVER_ROLE_PERMISSIONS, RolePermissionResponse,
    validate_datetime_format
)
from ..utils import success_response, not_found_response, bad_request_response
from ..collaboration_risk import (
    CollaborationRiskDetector, HandoverSummaryGenerator, WorkloadStatistics
)

router = APIRouter(prefix="/api/collaboration", tags=["多照护人协同与交接班"])


def _parse_datetime(v: str) -> Optional[datetime]:
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(v, fmt)
        except (ValueError, TypeError):
            continue
    return None


def _check_baby_exists(db: Session, baby_id: int) -> Optional[Baby]:
    return db.query(Baby).filter(Baby.id == baby_id).first()


def _check_caregiver_exists(db: Session, caregiver_id: int, baby_id: Optional[int] = None) -> Optional[Caregiver]:
    query = db.query(Caregiver).filter(Caregiver.id == caregiver_id)
    if baby_id is not None:
        query = query.filter(Caregiver.baby_id == baby_id)
    return query.first()


def _check_shift_exists(db: Session, shift_id: int, baby_id: Optional[int] = None) -> Optional[Shift]:
    query = db.query(Shift).filter(Shift.id == shift_id)
    if baby_id is not None:
        query = query.filter(Shift.baby_id == baby_id)
    return query.first()


# ==================== 角色权限接口 ====================

@router.get("/roles", summary="获取所有照护人角色及权限说明")
def get_caregiver_roles():
    roles = []
    for role_key, role_info in CAREGIVER_ROLE_PERMISSIONS.items():
        roles.append({
            "role": role_key,
            "name": role_info["name"],
            "description": role_info["description"],
            "permissions": role_info["permissions"]
        })
    return success_response(roles)


# ==================== 照护人管理接口 ====================

@router.post("/caregivers", summary="新增照护人")
def create_caregiver(caregiver_data: CaregiverCreate, db: Session = Depends(get_db)):
    baby = _check_baby_exists(db, caregiver_data.baby_id)
    if not baby:
        return not_found_response("宝宝不存在")

    try:
        db_caregiver = Caregiver(
            baby_id=caregiver_data.baby_id,
            name=caregiver_data.name,
            role=caregiver_data.role,
            phone=caregiver_data.phone,
            notes=caregiver_data.notes
        )
        db.add(db_caregiver)
        db.commit()
        db.refresh(db_caregiver)

        return success_response(
            CaregiverResponse.model_validate(db_caregiver).model_dump(),
            "照护人创建成功"
        )
    except Exception as e:
        db.rollback()
        return bad_request_response(f"创建失败: {str(e)}")


@router.get("/caregivers", summary="获取宝宝的照护人列表")
def get_caregivers(
    baby_id: int = Query(..., description="宝宝ID"),
    is_active: Optional[bool] = Query(default=None, description="是否只显示活跃照护人"),
    db: Session = Depends(get_db)
):
    baby = _check_baby_exists(db, baby_id)
    if not baby:
        return not_found_response("宝宝不存在")

    query = db.query(Caregiver).filter(Caregiver.baby_id == baby_id)
    if is_active is not None:
        query = query.filter(Caregiver.is_active == is_active)

    caregivers = query.order_by(Caregiver.created_at.desc()).all()
    return success_response([
        CaregiverResponse.model_validate(c).model_dump()
        for c in caregivers
    ])


@router.get("/caregivers/{caregiver_id}", summary="获取照护人详情")
def get_caregiver(caregiver_id: int, db: Session = Depends(get_db)):
    caregiver = _check_caregiver_exists(db, caregiver_id)
    if not caregiver:
        return not_found_response("照护人不存在")

    role_perms = CAREGIVER_ROLE_PERMISSIONS.get(caregiver.role, {})

    return success_response({
        **CaregiverResponse.model_validate(caregiver).model_dump(),
        "role_name": role_perms.get("name", ""),
        "role_description": role_perms.get("description", ""),
        "permissions": role_perms.get("permissions", [])
    })


@router.put("/caregivers/{caregiver_id}", summary="更新照护人信息")
def update_caregiver(
    caregiver_id: int,
    caregiver_data: CaregiverUpdate,
    db: Session = Depends(get_db)
):
    caregiver = _check_caregiver_exists(db, caregiver_id)
    if not caregiver:
        return not_found_response("照护人不存在")

    try:
        update_data = caregiver_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(caregiver, key, value)
        caregiver.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(caregiver)

        return success_response(
            CaregiverResponse.model_validate(caregiver).model_dump(),
            "更新成功"
        )
    except Exception as e:
        db.rollback()
        return bad_request_response(f"更新失败: {str(e)}")


@router.delete("/caregivers/{caregiver_id}", summary="删除（停用）照护人")
def delete_caregiver(caregiver_id: int, db: Session = Depends(get_db)):
    caregiver = _check_caregiver_exists(db, caregiver_id)
    if not caregiver:
        return not_found_response("照护人不存在")

    try:
        caregiver.is_active = False
        caregiver.updated_at = datetime.utcnow()
        db.commit()

        return success_response(None, "照护人已停用")
    except Exception as e:
        db.rollback()
        return bad_request_response(f"操作失败: {str(e)}")


# ==================== 班次管理接口 ====================

@router.post("/shifts", summary="创建（开始）班次")
def create_shift(shift_data: ShiftCreate, db: Session = Depends(get_db)):
    baby = _check_baby_exists(db, shift_data.baby_id)
    if not baby:
        return not_found_response("宝宝不存在")

    caregiver = _check_caregiver_exists(db, shift_data.caregiver_id, shift_data.baby_id)
    if not caregiver:
        return not_found_response("照护人不存在或不属于该宝宝")

    if not caregiver.is_active:
        return bad_request_response("该照护人已停用，无法创建班次")

    shift_start = _parse_datetime(shift_data.shift_start)
    if not shift_start:
        return bad_request_response("班次开始时间格式不正确")

    active_shifts = db.query(Shift).filter(
        Shift.baby_id == shift_data.baby_id,
        Shift.status == "active"
    ).all()
    if active_shifts:
        return bad_request_response(f"存在进行中的班次（ID: {active_shifts[0].id}），请先结束当前班次")

    prev_shift = db.query(Shift).filter(
        Shift.baby_id == shift_data.baby_id
    ).order_by(Shift.shift_start.desc()).first()

    if prev_shift and prev_shift.shift_end and shift_start < prev_shift.shift_end:
        return bad_request_response("班次开始时间不能早于上一班次结束时间")

    try:
        db_shift = Shift(
            baby_id=shift_data.baby_id,
            caregiver_id=shift_data.caregiver_id,
            shift_start=shift_start,
            inventory_snapshot=shift_data.inventory_snapshot,
            previous_shift_anomalies=shift_data.previous_shift_anomalies,
            notes=shift_data.notes,
            status="active"
        )
        db.add(db_shift)
        db.commit()
        db.refresh(db_shift)

        return success_response(
            ShiftResponse.model_validate(db_shift).model_dump(),
            "班次创建成功"
        )
    except Exception as e:
        db.rollback()
        return bad_request_response(f"创建失败: {str(e)}")


@router.put("/shifts/{shift_id}/end", summary="结束班次")
def end_shift(shift_id: int, end_data: ShiftEnd, db: Session = Depends(get_db)):
    shift = _check_shift_exists(db, shift_id)
    if not shift:
        return not_found_response("班次不存在")

    if shift.status == "ended":
        return bad_request_response("该班次已结束")

    shift_end = _parse_datetime(end_data.shift_end)
    if not shift_end:
        return bad_request_response("班次结束时间格式不正确")

    if shift_end <= shift.shift_start:
        return bad_request_response("班次结束时间必须晚于开始时间")

    try:
        shift.shift_end = shift_end
        shift.status = "ended"
        if end_data.inventory_snapshot:
            shift.inventory_snapshot = end_data.inventory_snapshot
        if end_data.notes:
            shift.notes = end_data.notes
        shift.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(shift)

        risk_detector = CollaborationRiskDetector(db)
        risks = risk_detector.detect_all_risks(shift.baby_id)

        return success_response({
            "shift": ShiftResponse.model_validate(shift).model_dump(),
            "detected_risks": len(risks),
            "risk_summary": {
                "high": sum(1 for r in risks if r.get("severity") == "high"),
                "medium": sum(1 for r in risks if r.get("severity") == "medium"),
                "low": sum(1 for r in risks if r.get("severity") == "low")
            }
        }, "班次已结束")
    except Exception as e:
        db.rollback()
        return bad_request_response(f"结束失败: {str(e)}")


@router.get("/shifts", summary="获取班次列表")
def get_shifts(
    baby_id: int = Query(..., description="宝宝ID"),
    status: Optional[str] = Query(default=None, description="班次状态 active/ended"),
    caregiver_id: Optional[int] = Query(default=None, description="照护人ID"),
    start_date: Optional[str] = Query(default=None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(default=None, description="结束日期 YYYY-MM-DD"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db)
):
    baby = _check_baby_exists(db, baby_id)
    if not baby:
        return not_found_response("宝宝不存在")

    query = db.query(Shift).filter(Shift.baby_id == baby_id)

    if status:
        if status not in ["active", "ended"]:
            return bad_request_response("状态必须是 active 或 ended")
        query = query.filter(Shift.status == status)

    if caregiver_id:
        caregiver = _check_caregiver_exists(db, caregiver_id, baby_id)
        if not caregiver:
            return not_found_response("照护人不存在或不属于该宝宝")
        query = query.filter(Shift.caregiver_id == caregiver_id)

    if start_date:
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            query = query.filter(Shift.shift_start >= start_dt)
        except ValueError:
            return bad_request_response("开始日期格式不正确，应为 YYYY-MM-DD")

    if end_date:
        try:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(Shift.shift_start < end_dt)
        except ValueError:
            return bad_request_response("结束日期格式不正确，应为 YYYY-MM-DD")

    total = query.count()
    shifts = query.order_by(Shift.shift_start.desc()).offset((page - 1) * page_size).limit(page_size).all()

    caregiver_map = {}
    for s in shifts:
        if s.caregiver_id not in caregiver_map:
            cg = db.query(Caregiver).filter(Caregiver.id == s.caregiver_id).first()
            caregiver_map[s.caregiver_id] = cg

    shift_list = []
    for s in shifts:
        cg = caregiver_map.get(s.caregiver_id)
        item_count = db.query(HandoverItem).filter(HandoverItem.shift_id == s.id).count()
        task_count = db.query(TodoTask).filter(TodoTask.shift_id == s.id).count()
        completed_count = db.query(TodoTask).filter(
            TodoTask.shift_id == s.id,
            TodoTask.is_completed == True
        ).count()

        shift_dict = ShiftResponse.model_validate(s).model_dump()
        shift_dict["caregiver_name"] = cg.name if cg else None
        shift_dict["caregiver_role"] = cg.role if cg else None
        shift_dict["handover_item_count"] = item_count
        shift_dict["todo_task_count"] = task_count
        shift_dict["completed_task_count"] = completed_count
        shift_list.append(shift_dict)

    return success_response({
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": shift_list
    })


@router.get("/shifts/{shift_id}", summary="获取班次详情")
def get_shift(shift_id: int, db: Session = Depends(get_db)):
    shift = _check_shift_exists(db, shift_id)
    if not shift:
        return not_found_response("班次不存在")

    caregiver = _check_caregiver_exists(db, shift.caregiver_id)

    items = db.query(HandoverItem).filter(HandoverItem.shift_id == shift_id).order_by(HandoverItem.created_at).all()
    tasks = db.query(TodoTask).filter(TodoTask.shift_id == shift_id).order_by(TodoTask.created_at).all()

    shift_dict = ShiftResponse.model_validate(shift).model_dump()
    shift_dict["caregiver_name"] = caregiver.name if caregiver else None
    shift_dict["caregiver_role"] = caregiver.role if caregiver else None
    shift_dict["handover_items"] = [
        HandoverItemResponse.model_validate(i).model_dump() for i in items
    ]
    shift_dict["todo_tasks"] = [
        TodoTaskResponse.model_validate(t).model_dump() for t in tasks
    ]

    return success_response(shift_dict)


@router.get("/shifts/current/active", summary="获取当前进行中的班次")
def get_active_shift(
    baby_id: int = Query(..., description="宝宝ID"),
    db: Session = Depends(get_db)
):
    baby = _check_baby_exists(db, baby_id)
    if not baby:
        return not_found_response("宝宝不存在")

    shift = db.query(Shift).filter(
        Shift.baby_id == baby_id,
        Shift.status == "active"
    ).first()

    if not shift:
        return success_response(None, "当前无进行中的班次")

    caregiver = _check_caregiver_exists(db, shift.caregiver_id)

    items = db.query(HandoverItem).filter(HandoverItem.shift_id == shift.id).order_by(HandoverItem.created_at).all()
    tasks = db.query(TodoTask).filter(TodoTask.shift_id == shift.id).order_by(TodoTask.created_at).all()

    shift_dict = ShiftResponse.model_validate(shift).model_dump()
    shift_dict["caregiver_name"] = caregiver.name if caregiver else None
    shift_dict["caregiver_role"] = caregiver.role if caregiver else None
    shift_dict["handover_items"] = [
        HandoverItemResponse.model_validate(i).model_dump() for i in items
    ]
    shift_dict["todo_tasks"] = [
        TodoTaskResponse.model_validate(t).model_dump() for t in tasks
    ]

    return success_response(shift_dict)


# ==================== 交接事项接口 ====================

@router.post("/handover-items", summary="新增交接事项")
def create_handover_item(item_data: HandoverItemCreate, db: Session = Depends(get_db)):
    baby = _check_baby_exists(db, item_data.baby_id)
    if not baby:
        return not_found_response("宝宝不存在")

    shift = _check_shift_exists(db, item_data.shift_id, item_data.baby_id)
    if not shift:
        return not_found_response("班次不存在或不属于该宝宝")

    caregiver = _check_caregiver_exists(db, item_data.caregiver_id, item_data.baby_id)
    if not caregiver:
        return not_found_response("照护人不存在或不属于该宝宝")

    if shift.status == "ended":
        return bad_request_response("班次已结束，无法添加交接事项")

    try:
        db_item = HandoverItem(
            shift_id=item_data.shift_id,
            baby_id=item_data.baby_id,
            caregiver_id=item_data.caregiver_id,
            item_type=item_data.item_type,
            content=item_data.content,
            priority=item_data.priority or "normal"
        )
        db.add(db_item)
        db.commit()
        db.refresh(db_item)

        return success_response(
            HandoverItemResponse.model_validate(db_item).model_dump(),
            "交接事项创建成功"
        )
    except Exception as e:
        db.rollback()
        return bad_request_response(f"创建失败: {str(e)}")


@router.get("/handover-items", summary="获取交接事项列表")
def get_handover_items(
    baby_id: int = Query(..., description="宝宝ID"),
    shift_id: Optional[int] = Query(default=None, description="班次ID"),
    item_type: Optional[str] = Query(default=None, description="事项类型"),
    is_resolved: Optional[bool] = Query(default=None, description="是否已解决"),
    priority: Optional[str] = Query(default=None, description="优先级"),
    db: Session = Depends(get_db)
):
    baby = _check_baby_exists(db, baby_id)
    if not baby:
        return not_found_response("宝宝不存在")

    query = db.query(HandoverItem).filter(HandoverItem.baby_id == baby_id)

    if shift_id:
        shift = _check_shift_exists(db, shift_id, baby_id)
        if not shift:
            return not_found_response("班次不存在或不属于该宝宝")
        query = query.filter(HandoverItem.shift_id == shift_id)

    if item_type:
        from ..schemas import VALID_HANDOVER_ITEM_TYPES
        if item_type not in VALID_HANDOVER_ITEM_TYPES:
            return bad_request_response(f"事项类型必须是以下之一: {', '.join(VALID_HANDOVER_ITEM_TYPES)}")
        query = query.filter(HandoverItem.item_type == item_type)

    if is_resolved is not None:
        query = query.filter(HandoverItem.is_resolved == is_resolved)

    if priority:
        from ..schemas import VALID_HANDOVER_PRIORITIES
        if priority not in VALID_HANDOVER_PRIORITIES:
            return bad_request_response(f"优先级必须是以下之一: {', '.join(VALID_HANDOVER_PRIORITIES)}")
        query = query.filter(HandoverItem.priority == priority)

    items = query.order_by(HandoverItem.created_at.desc()).all()

    return success_response([
        HandoverItemResponse.model_validate(i).model_dump()
        for i in items
    ])


@router.put("/handover-items/{item_id}", summary="更新交接事项")
def update_handover_item(
    item_id: int,
    item_data: HandoverItemUpdate,
    db: Session = Depends(get_db)
):
    item = db.query(HandoverItem).filter(HandoverItem.id == item_id).first()
    if not item:
        return not_found_response("交接事项不存在")

    try:
        update_data = item_data.model_dump(exclude_unset=True)

        if "is_resolved" in update_data and update_data["is_resolved"] and not item.is_resolved:
            item.resolved_at = datetime.utcnow()

        for key, value in update_data.items():
            if key != "is_resolved" or key in update_data:
                setattr(item, key, value)

        db.commit()
        db.refresh(item)

        return success_response(
            HandoverItemResponse.model_validate(item).model_dump(),
            "更新成功"
        )
    except Exception as e:
        db.rollback()
        return bad_request_response(f"更新失败: {str(e)}")


@router.put("/handover-items/{item_id}/resolve", summary="标记交接事项为已解决")
def resolve_handover_item(item_id: int, db: Session = Depends(get_db)):
    item = db.query(HandoverItem).filter(HandoverItem.id == item_id).first()
    if not item:
        return not_found_response("交接事项不存在")

    if item.is_resolved:
        return bad_request_response("该事项已解决")

    try:
        item.is_resolved = True
        item.resolved_at = datetime.utcnow()
        db.commit()
        db.refresh(item)

        return success_response(
            HandoverItemResponse.model_validate(item).model_dump(),
            "已标记为已解决"
        )
    except Exception as e:
        db.rollback()
        return bad_request_response(f"操作失败: {str(e)}")


# ==================== 待办任务接口 ====================

@router.post("/todo-tasks", summary="新增待办任务")
def create_todo_task(task_data: TodoTaskCreate, db: Session = Depends(get_db)):
    baby = _check_baby_exists(db, task_data.baby_id)
    if not baby:
        return not_found_response("宝宝不存在")

    shift = _check_shift_exists(db, task_data.shift_id, task_data.baby_id)
    if not shift:
        return not_found_response("班次不存在或不属于该宝宝")

    caregiver = _check_caregiver_exists(db, task_data.caregiver_id, task_data.baby_id)
    if not caregiver:
        return not_found_response("照护人不存在或不属于该宝宝")

    if shift.status == "ended":
        return bad_request_response("班次已结束，无法添加待办任务")

    due_time = None
    if task_data.due_time:
        due_time = _parse_datetime(task_data.due_time)
        if not due_time:
            return bad_request_response("截止时间格式不正确")

    try:
        db_task = TodoTask(
            shift_id=task_data.shift_id,
            baby_id=task_data.baby_id,
            caregiver_id=task_data.caregiver_id,
            task_type=task_data.task_type,
            description=task_data.description,
            due_time=due_time,
            notes=task_data.notes
        )
        db.add(db_task)
        db.commit()
        db.refresh(db_task)

        return success_response(
            TodoTaskResponse.model_validate(db_task).model_dump(),
            "待办任务创建成功"
        )
    except Exception as e:
        db.rollback()
        return bad_request_response(f"创建失败: {str(e)}")


@router.get("/todo-tasks", summary="获取待办任务列表")
def get_todo_tasks(
    baby_id: int = Query(..., description="宝宝ID"),
    shift_id: Optional[int] = Query(default=None, description="班次ID"),
    task_type: Optional[str] = Query(default=None, description="任务类型"),
    is_completed: Optional[bool] = Query(default=None, description="是否已完成"),
    is_overdue: Optional[bool] = Query(default=None, description="是否已逾期"),
    db: Session = Depends(get_db)
):
    baby = _check_baby_exists(db, baby_id)
    if not baby:
        return not_found_response("宝宝不存在")

    query = db.query(TodoTask).filter(TodoTask.baby_id == baby_id)

    if shift_id:
        shift = _check_shift_exists(db, shift_id, baby_id)
        if not shift:
            return not_found_response("班次不存在或不属于该宝宝")
        query = query.filter(TodoTask.shift_id == shift_id)

    if task_type:
        from ..schemas import VALID_TODO_TASK_TYPES
        if task_type not in VALID_TODO_TASK_TYPES:
            return bad_request_response(f"任务类型必须是以下之一: {', '.join(VALID_TODO_TASK_TYPES)}")
        query = query.filter(TodoTask.task_type == task_type)

    if is_completed is not None:
        query = query.filter(TodoTask.is_completed == is_completed)

    tasks = query.order_by(TodoTask.created_at.desc()).all()

    now = datetime.now()
    result = []
    for t in tasks:
        task_dict = TodoTaskResponse.model_validate(t).model_dump()
        overdue = False
        if t.due_time and not t.is_completed and t.due_time < now:
            overdue = True

        if is_overdue is not None and overdue != is_overdue:
            continue

        task_dict["is_overdue"] = overdue
        result.append(task_dict)

    return success_response(result)


@router.put("/todo-tasks/{task_id}/complete", summary="确认完成待办任务")
def complete_todo_task(
    task_id: int,
    complete_data: TodoTaskComplete,
    db: Session = Depends(get_db)
):
    task = db.query(TodoTask).filter(TodoTask.id == task_id).first()
    if not task:
        return not_found_response("待办任务不存在")

    if task.is_completed:
        return bad_request_response("该任务已完成")

    completed_by = _check_caregiver_exists(db, complete_data.completed_by_caregiver_id, task.baby_id)
    if not completed_by:
        return not_found_response("完成人不存在或不属于该宝宝")

    try:
        task.is_completed = True
        task.completed_at = datetime.utcnow()
        task.completed_by_caregiver_id = complete_data.completed_by_caregiver_id
        if complete_data.notes:
            task.notes = complete_data.notes

        db.commit()
        db.refresh(task)

        return success_response(
            TodoTaskResponse.model_validate(task).model_dump(),
            "任务已完成"
        )
    except Exception as e:
        db.rollback()
        return bad_request_response(f"操作失败: {str(e)}")


@router.get("/todo-tasks/{task_id}", summary="获取待办任务详情")
def get_todo_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(TodoTask).filter(TodoTask.id == task_id).first()
    if not task:
        return not_found_response("待办任务不存在")

    task_dict = TodoTaskResponse.model_validate(task).model_dump()
    now = datetime.now()
    task_dict["is_overdue"] = bool(
        task.due_time and not task.is_completed and task.due_time < now
    )

    return success_response(task_dict)


# ==================== 交接摘要接口 ====================

@router.get("/handover-summary", summary="获取照护交接摘要")
def get_handover_summary(
    baby_id: int = Query(..., description="宝宝ID"),
    shift_id: Optional[int] = Query(default=None, description="指定班次ID"),
    db: Session = Depends(get_db)
):
    baby = _check_baby_exists(db, baby_id)
    if not baby:
        return not_found_response("宝宝不存在")

    if shift_id:
        shift = _check_shift_exists(db, shift_id, baby_id)
        if not shift:
            return not_found_response("班次不存在或不属于该宝宝")

    try:
        generator = HandoverSummaryGenerator(db)
        summary = generator.generate_summary(baby_id, shift_id)

        if "error" in summary:
            return bad_request_response(summary["error"])

        return success_response(summary)
    except Exception as e:
        return bad_request_response(f"生成摘要失败: {str(e)}")


# ==================== 协作风险接口 ====================

@router.get("/risks", summary="获取协作风险列表")
def get_collaboration_risks(
    baby_id: int = Query(..., description="宝宝ID"),
    severity: Optional[str] = Query(default=None, description="风险级别 high/medium/low"),
    risk_type: Optional[str] = Query(default=None, description="风险类型"),
    db: Session = Depends(get_db)
):
    baby = _check_baby_exists(db, baby_id)
    if not baby:
        return not_found_response("宝宝不存在")

    valid_severities = ["high", "medium", "low"]
    if severity and severity not in valid_severities:
        return bad_request_response(f"风险级别必须是以下之一: {', '.join(valid_severities)}")

    valid_risk_types = [
        "inventory_not_synced",
        "continuous_leak_unhandled",
        "restock_reminder_unconfirmed",
        "duplicate_reporting",
        "task_omission",
        "task_omission_risk"
    ]
    if risk_type and risk_type not in valid_risk_types:
        return bad_request_response(f"风险类型必须是以下之一: {', '.join(valid_risk_types)}")

    try:
        detector = CollaborationRiskDetector(db)
        all_risks = detector.detect_all_risks(baby_id)

        filtered_risks = all_risks
        if severity:
            filtered_risks = [r for r in filtered_risks if r.get("severity") == severity]
        if risk_type:
            filtered_risks = [r for r in filtered_risks if r.get("risk_type") == risk_type]

        return success_response({
            "baby_id": baby_id,
            "total_count": len(filtered_risks),
            "high_count": sum(1 for r in filtered_risks if r.get("severity") == "high"),
            "medium_count": sum(1 for r in filtered_risks if r.get("severity") == "medium"),
            "low_count": sum(1 for r in filtered_risks if r.get("severity") == "low"),
            "risks": filtered_risks
        })
    except Exception as e:
        return bad_request_response(f"获取风险列表失败: {str(e)}")


@router.get("/risks/types", summary="获取所有风险类型说明")
def get_risk_types():
    risk_types = [
        {
            "type": "inventory_not_synced",
            "name": "库存未同步",
            "description": "交接班时库存数量与预期消耗后剩余量差异较大，可能存在库存记录不一致",
            "default_severity": "medium"
        },
        {
            "type": "continuous_leak_unhandled",
            "name": "连续漏尿未处理",
            "description": "连续多天出现夜间漏尿但未在交接班中记录处理措施",
            "default_severity": "high"
        },
        {
            "type": "restock_reminder_unconfirmed",
            "name": "补货提醒无人确认",
            "description": "补货提醒已触发但长时间未被任何照护人确认处理",
            "default_severity": "medium"
        },
        {
            "type": "duplicate_reporting",
            "name": "同一时段重复上报",
            "description": "不同照护人在短时间内上报了相同或相似的事项，可能存在重复记录",
            "default_severity": "low"
        },
        {
            "type": "task_omission",
            "name": "护理任务遗漏",
            "description": "班次中有已逾期的护理任务未完成",
            "default_severity": "high"
        },
        {
            "type": "task_omission_risk",
            "name": "任务完成率低",
            "description": "班次中任务完成率低于50%，存在护理任务遗漏风险",
            "default_severity": "medium"
        }
    ]
    return success_response(risk_types)


# ==================== 照护人工作量统计接口 ====================

@router.get("/workload-statistics", summary="获取照护人工作量统计")
def get_workload_statistics(
    baby_id: int = Query(..., description="宝宝ID"),
    days: int = Query(default=30, ge=1, le=365, description="统计天数"),
    db: Session = Depends(get_db)
):
    baby = _check_baby_exists(db, baby_id)
    if not baby:
        return not_found_response("宝宝不存在")

    try:
        stats = WorkloadStatistics(db)
        result = stats.get_caregiver_workload(baby_id, days)
        return success_response(result)
    except Exception as e:
        return bad_request_response(f"获取统计数据失败: {str(e)}")

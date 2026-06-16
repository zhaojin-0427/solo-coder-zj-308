from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime

from ..database import get_db
from ..models import (
    Baby, OutingPlan, OutingBagItem, OutingChangeSchedule,
    OutingEmergencyPlan, OutingConsumptionRecord, OutingRiskAlert,
    OutingCaregiverTask, OutingCaregiverAssignment, Caregiver,
    InventoryRecord
)
from ..schemas import (
    OutingPlanCreate, OutingPlanUpdate, OutingPlanResponse,
    OutingCaregiverAssignmentCreate, OutingCaregiverAssignmentResponse,
    OutingBagItemResponse, OutingChangeScheduleResponse,
    OutingEmergencyPlanResponse, OutingConsumptionRecordCreate,
    OutingConsumptionRecordResponse, OutingRiskAlertResponse,
    OutingCaregiverTaskCreate, OutingCaregiverTaskResponse,
    OutingPackingListResponse, OutingChangeScheduleListResponse,
    OutingRiskListResponse, OutingTaskAssignmentResponse,
    OutingSummaryResponse, OutingConsumptionSubmitRequest,
    OutingConsumptionSummaryResponse, validate_destination_type,
    validate_transportation_type, validate_restock_level,
    validate_outing_status
)
from ..utils import success_response, not_found_response, bad_request_response
from ..outing_packing import OutingPackingCalculator
from ..outing_risk import OutingRiskAssessor
from ..outing_emergency import OutingEmergencyPlanner


router = APIRouter(prefix="/api/outing", tags=["外出场景尿布包与应急护理"])


def _parse_datetime(dt_str: str) -> datetime:
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(dt_str)
    except ValueError:
        raise ValueError(f"无法解析日期时间: {dt_str}")


def _validate_caregiver_baby_belonging(db: Session, caregiver_id: int, baby_id: int) -> bool:
    caregiver = db.query(Caregiver).filter(
        Caregiver.id == caregiver_id,
        Caregiver.baby_id == baby_id,
        Caregiver.is_active == True
    ).first()
    return caregiver is not None


@router.post("/plans", summary="创建外出计划")
def create_outing_plan(plan_data: OutingPlanCreate, db: Session = Depends(get_db)):
    baby = db.query(Baby).filter(Baby.id == plan_data.baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    try:
        dep_time = _parse_datetime(plan_data.departure_time)
        ret_time = _parse_datetime(plan_data.return_time)
    except ValueError as e:
        return bad_request_response(str(e))

    if ret_time <= dep_time:
        return bad_request_response("返回时间必须晚于出发时间")

    duration_hours = (ret_time - dep_time).total_seconds() / 3600
    if duration_hours <= 0 or duration_hours > 720:
        return bad_request_response("外出时长必须在 0-720 小时之间")

    try:
        db_plan = OutingPlan(
            baby_id=plan_data.baby_id,
            plan_name=plan_data.plan_name,
            departure_time=dep_time,
            return_time=ret_time,
            destination_type=plan_data.destination_type,
            destination_name=plan_data.destination_name,
            estimated_duration_hours=round(duration_hours, 1),
            restock_convenience=plan_data.restock_convenience or "moderate",
            carry_capacity_limit=plan_data.carry_capacity_limit or 0,
            weather_temperature=plan_data.weather_temperature,
            transportation=plan_data.transportation or "car",
            leak_risk_preference=plan_data.leak_risk_preference or "moderate",
            skin_risk_preference=plan_data.skin_risk_preference or "moderate",
            notes=plan_data.notes,
            status="planned"
        )
        db.add(db_plan)
        db.commit()
        db.refresh(db_plan)

        return success_response(
            OutingPlanResponse.model_validate(db_plan).model_dump(),
            "外出计划创建成功"
        )
    except Exception as e:
        db.rollback()
        return bad_request_response(f"创建失败: {str(e)}")


@router.get("/plans/{plan_id}", summary="获取外出计划详情")
def get_outing_plan(plan_id: int, db: Session = Depends(get_db)):
    plan = db.query(OutingPlan).filter(OutingPlan.id == plan_id).first()
    if not plan:
        return not_found_response("外出计划不存在")

    return success_response(
        OutingPlanResponse.model_validate(plan).model_dump(),
        "获取成功"
    )


@router.get("/plans/baby/{baby_id}", summary="获取宝宝的外出计划列表")
def get_baby_outing_plans(
    baby_id: int,
    status: Optional[str] = None,
    limit: Optional[int] = 20,
    offset: Optional[int] = 0,
    db: Session = Depends(get_db)
):
    baby = db.query(Baby).filter(Baby.id == baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    if status is not None:
        try:
            validate_outing_status(status)
        except ValueError as e:
            return bad_request_response(str(e))

    query = db.query(OutingPlan).filter(OutingPlan.baby_id == baby_id)

    if status:
        query = query.filter(OutingPlan.status == status)

    total = query.count()
    plans = query.order_by(OutingPlan.departure_time.desc()).offset(offset).limit(limit).all()

    return success_response({
        "total": total,
        "offset": offset,
        "limit": limit,
        "plans": [OutingPlanResponse.model_validate(p).model_dump() for p in plans]
    }, "获取成功")


@router.put("/plans/{plan_id}", summary="更新外出计划")
def update_outing_plan(plan_id: int, plan_data: OutingPlanUpdate, db: Session = Depends(get_db)):
    plan = db.query(OutingPlan).filter(OutingPlan.id == plan_id).first()
    if not plan:
        return not_found_response("外出计划不存在")

    try:
        update_data = plan_data.model_dump(exclude_unset=True)

        if "departure_time" in update_data and update_data["departure_time"]:
            plan.departure_time = _parse_datetime(update_data["departure_time"])
            del update_data["departure_time"]

        if "return_time" in update_data and update_data["return_time"]:
            plan.return_time = _parse_datetime(update_data["return_time"])
            del update_data["return_time"]

        if "departure_time" in plan_data.model_dump() or "return_time" in plan_data.model_dump():
            if plan.return_time <= plan.departure_time:
                return bad_request_response("返回时间必须晚于出发时间")
            duration = (plan.return_time - plan.departure_time).total_seconds() / 3600
            if duration > 720:
                return bad_request_response("外出时长不能超过720小时")
            plan.estimated_duration_hours = round(duration, 1)

        for key, value in update_data.items():
            if value is not None:
                setattr(plan, key, value)

        plan.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(plan)

        return success_response(
            OutingPlanResponse.model_validate(plan).model_dump(),
            "更新成功"
        )
    except Exception as e:
        db.rollback()
        return bad_request_response(f"更新失败: {str(e)}")


@router.delete("/plans/{plan_id}", summary="删除外出计划")
def delete_outing_plan(plan_id: int, db: Session = Depends(get_db)):
    plan = db.query(OutingPlan).filter(OutingPlan.id == plan_id).first()
    if not plan:
        return not_found_response("外出计划不存在")

    try:
        db.delete(plan)
        db.commit()
        return success_response(None, "删除成功")
    except Exception as e:
        db.rollback()
        return bad_request_response(f"删除失败: {str(e)}")


@router.post("/plans/{plan_id}/caregivers", summary="添加同行照护人")
def add_caregiver_to_outing(assignment_data: OutingCaregiverAssignmentCreate, db: Session = Depends(get_db)):
    plan = db.query(OutingPlan).filter(OutingPlan.id == assignment_data.outing_plan_id).first()
    if not plan:
        return not_found_response("外出计划不存在")

    if not _validate_caregiver_baby_belonging(db, assignment_data.caregiver_id, plan.baby_id):
        return bad_request_response("照护人与宝宝无归属关系或照护人不存在")

    existing = db.query(OutingCaregiverAssignment).filter(
        OutingCaregiverAssignment.outing_plan_id == assignment_data.outing_plan_id,
        OutingCaregiverAssignment.caregiver_id == assignment_data.caregiver_id
    ).first()
    if existing:
        return bad_request_response("该照护人已添加到此外出计划")

    try:
        db_assignment = OutingCaregiverAssignment(
            outing_plan_id=assignment_data.outing_plan_id,
            caregiver_id=assignment_data.caregiver_id,
            role_in_outing=assignment_data.role_in_outing or "companion",
            is_primary=assignment_data.is_primary if assignment_data.is_primary is not None else False,
            notes=assignment_data.notes
        )
        db.add(db_assignment)
        db.commit()
        db.refresh(db_assignment)

        caregiver = db.query(Caregiver).filter(Caregiver.id == assignment_data.caregiver_id).first()

        response = OutingCaregiverAssignmentResponse.model_validate(db_assignment).model_dump()
        response["caregiver_name"] = caregiver.name if caregiver else None
        response["caregiver_role"] = caregiver.role if caregiver else None

        return success_response(response, "添加成功")
    except Exception as e:
        db.rollback()
        return bad_request_response(f"添加失败: {str(e)}")


@router.delete("/plans/{plan_id}/caregivers/{caregiver_id}", summary="移除同行照护人")
def remove_caregiver_from_outing(plan_id: int, caregiver_id: int, db: Session = Depends(get_db)):
    assignment = db.query(OutingCaregiverAssignment).filter(
        OutingCaregiverAssignment.outing_plan_id == plan_id,
        OutingCaregiverAssignment.caregiver_id == caregiver_id
    ).first()
    if not assignment:
        return not_found_response("照护人不在此外出计划中")

    try:
        db.delete(assignment)
        db.commit()
        return success_response(None, "移除成功")
    except Exception as e:
        db.rollback()
        return bad_request_response(f"移除失败: {str(e)}")


@router.get("/plans/{plan_id}/caregivers", summary="获取外出计划的同行照护人列表")
def get_outing_caregivers(plan_id: int, db: Session = Depends(get_db)):
    plan = db.query(OutingPlan).filter(OutingPlan.id == plan_id).first()
    if not plan:
        return not_found_response("外出计划不存在")

    assignments = db.query(OutingCaregiverAssignment).filter(
        OutingCaregiverAssignment.outing_plan_id == plan_id
    ).order_by(OutingCaregiverAssignment.is_primary.desc(), OutingCaregiverAssignment.id).all()

    result = []
    for a in assignments:
        resp = OutingCaregiverAssignmentResponse.model_validate(a).model_dump()
        caregiver = a.caregiver
        resp["caregiver_name"] = caregiver.name if caregiver else None
        resp["caregiver_role"] = caregiver.role if caregiver else None
        result.append(resp)

    return success_response(result, "获取成功")


@router.post("/plans/{plan_id}/generate-packing-list", summary="生成尿布包清单")
def generate_packing_list(plan_id: int, db: Session = Depends(get_db)):
    plan = db.query(OutingPlan).filter(OutingPlan.id == plan_id).first()
    if not plan:
        return not_found_response("外出计划不存在")

    baby = db.query(Baby).filter(Baby.id == plan.baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    try:
        calculator = OutingPackingCalculator(db)
        result = calculator.generate_full_packing_plan(plan, baby)

        risk_assessor = OutingRiskAssessor(db)
        risk_assessor.generate_risk_alerts(plan, baby)

        emergency_planner = OutingEmergencyPlanner(db)
        emergency_planner.generate_full_emergency_and_tasks(plan, baby)

        return success_response(result, "尿布包清单生成成功")
    except Exception as e:
        return bad_request_response(f"生成失败: {str(e)}")


@router.get("/plans/{plan_id}/packing-list", summary="获取尿布包清单")
def get_packing_list(plan_id: int, db: Session = Depends(get_db)):
    plan = db.query(OutingPlan).filter(OutingPlan.id == plan_id).first()
    if not plan:
        return not_found_response("外出计划不存在")

    items = db.query(OutingBagItem).filter(
        OutingBagItem.outing_plan_id == plan_id
    ).order_by(OutingBagItem.is_essential.desc(), OutingBagItem.priority.desc()).all()

    if not items:
        return success_response({
            "outing_plan_id": plan_id,
            "baby_id": plan.baby_id,
            "total_items_count": 0,
            "total_diapers_count": 0,
            "essential_items": [],
            "optional_items": [],
            "size_breakdown": {},
            "weight_estimate_kg": 0,
            "carry_capacity_sufficient": True,
            "capacity_limit": plan.carry_capacity_limit,
            "capacity_usage_pct": 0
        }, "清单为空，请先生成")

    item_responses = [OutingBagItemResponse.model_validate(item).model_dump() for item in items]

    essential = [i for i in item_responses if i["is_essential"]]
    optional = [i for i in item_responses if not i["is_essential"]]

    diaper_items = [i for i in items if i.item_type == "diaper"]
    total_diapers = sum(i.quantity for i in diaper_items)

    size_breakdown = {}
    for item in diaper_items:
        size = item.diaper_size or "unknown"
        size_breakdown[size] = size_breakdown.get(size, 0) + item.quantity

    capacity_sufficient = True
    capacity_usage_pct = 0.0
    if plan.carry_capacity_limit > 0:
        capacity_usage_pct = round(total_diapers / plan.carry_capacity_limit * 100, 1)
        capacity_sufficient = total_diapers <= plan.carry_capacity_limit

    weight_estimate = total_diapers * 0.03 + len([i for i in items if i.item_type != "diaper"]) * 0.1

    return success_response({
        "outing_plan_id": plan_id,
        "baby_id": plan.baby_id,
        "total_items_count": len(items),
        "total_diapers_count": total_diapers,
        "essential_items": essential,
        "optional_items": optional,
        "size_breakdown": size_breakdown,
        "weight_estimate_kg": round(weight_estimate, 2),
        "carry_capacity_sufficient": capacity_sufficient,
        "capacity_limit": plan.carry_capacity_limit,
        "capacity_usage_pct": capacity_usage_pct
    }, "获取成功")


@router.get("/plans/{plan_id}/change-schedule", summary="获取途中更换日程")
def get_change_schedule(plan_id: int, db: Session = Depends(get_db)):
    plan = db.query(OutingPlan).filter(OutingPlan.id == plan_id).first()
    if not plan:
        return not_found_response("外出计划不存在")

    schedules = db.query(OutingChangeSchedule).filter(
        OutingChangeSchedule.outing_plan_id == plan_id
    ).order_by(OutingChangeSchedule.scheduled_time).all()

    daytime_count = sum(1 for s in schedules if not s.is_nighttime)
    nighttime_count = sum(1 for s in schedules if s.is_nighttime)

    return success_response({
        "outing_plan_id": plan_id,
        "total_changes": len(schedules),
        "daytime_changes": daytime_count,
        "nighttime_changes": nighttime_count,
        "schedules": [OutingChangeScheduleResponse.model_validate(s).model_dump() for s in schedules]
    }, "获取成功")


@router.put("/change-schedules/{schedule_id}/complete", summary="标记更换日程为已完成")
def complete_change_schedule(schedule_id: int, db: Session = Depends(get_db)):
    schedule = db.query(OutingChangeSchedule).filter(
        OutingChangeSchedule.id == schedule_id
    ).first()
    if not schedule:
        return not_found_response("更换日程不存在")

    try:
        schedule.is_completed = True
        schedule.completed_at = datetime.utcnow()
        db.commit()
        db.refresh(schedule)
        return success_response(
            OutingChangeScheduleResponse.model_validate(schedule).model_dump(),
            "标记成功"
        )
    except Exception as e:
        db.rollback()
        return bad_request_response(f"操作失败: {str(e)}")


@router.get("/plans/{plan_id}/emergency-plan", summary="获取应急预案")
def get_emergency_plan(plan_id: int, db: Session = Depends(get_db)):
    plan = db.query(OutingPlan).filter(OutingPlan.id == plan_id).first()
    if not plan:
        return not_found_response("外出计划不存在")

    emergency = db.query(OutingEmergencyPlan).filter(
        OutingEmergencyPlan.outing_plan_id == plan_id
    ).first()

    if not emergency:
        baby = db.query(Baby).filter(Baby.id == plan.baby_id).first()
        if not baby:
            return not_found_response("宝宝不存在")

        try:
            planner = OutingEmergencyPlanner(db)
            data = planner.generate_emergency_plan(plan, baby)
            emergency = planner.save_emergency_plan(plan_id, data)
        except Exception as e:
            return bad_request_response(f"生成应急预案失败: {str(e)}")

    return success_response(
        OutingEmergencyPlanResponse.model_validate(emergency).model_dump(),
        "获取成功"
    )


@router.get("/plans/{plan_id}/risk-alerts", summary="获取外出风险提醒列表")
def get_risk_alerts(
    plan_id: int,
    resolved: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    plan = db.query(OutingPlan).filter(OutingPlan.id == plan_id).first()
    if not plan:
        return not_found_response("外出计划不存在")

    risk_assessor = OutingRiskAssessor(db)
    alerts = risk_assessor.get_risk_alerts(plan_id, resolved=resolved)

    high_count = sum(1 for a in alerts if a.risk_level == "high" or a.risk_level == "critical")
    medium_count = sum(1 for a in alerts if a.risk_level == "medium")
    low_count = sum(1 for a in alerts if a.risk_level == "low")

    return success_response({
        "outing_plan_id": plan_id,
        "total_count": len(alerts),
        "high_count": high_count,
        "medium_count": medium_count,
        "low_count": low_count,
        "risks": [OutingRiskAlertResponse.model_validate(a).model_dump() for a in alerts]
    }, "获取成功")


@router.put("/risk-alerts/{alert_id}/resolve", summary="标记风险提醒为已解决")
def resolve_risk_alert(
    alert_id: int,
    resolved: Optional[bool] = True,
    notes: Optional[str] = None,
    db: Session = Depends(get_db)
):
    risk_assessor = OutingRiskAssessor(db)
    alert = risk_assessor.resolve_risk_alert(alert_id, resolved=resolved, notes=notes)

    if not alert:
        return not_found_response("风险提醒不存在")

    return success_response(
        OutingRiskAlertResponse.model_validate(alert).model_dump(),
        "操作成功"
    )


@router.get("/plans/{plan_id}/caregiver-tasks", summary="获取照护人携带任务分配")
def get_caregiver_tasks(plan_id: int, db: Session = Depends(get_db)):
    plan = db.query(OutingPlan).filter(OutingPlan.id == plan_id).first()
    if not plan:
        return not_found_response("外出计划不存在")

    tasks = db.query(OutingCaregiverTask).filter(
        OutingCaregiverTask.outing_plan_id == plan_id
    ).order_by(OutingCaregiverTask.priority.desc(), OutingCaregiverTask.id).all()

    caregiver_summaries = {}
    for task in tasks:
        cid = task.caregiver_id
        if cid not in caregiver_summaries:
            caregiver = task.caregiver
            caregiver_summaries[cid] = {
                "caregiver_id": cid,
                "caregiver_name": caregiver.name if caregiver else None,
                "task_count": 0,
                "completed_count": 0
            }
        caregiver_summaries[cid]["task_count"] += 1
        if task.is_completed:
            caregiver_summaries[cid]["completed_count"] += 1

    task_responses = []
    for task in tasks:
        resp = OutingCaregiverTaskResponse.model_validate(task).model_dump()
        caregiver = task.caregiver
        resp["caregiver_name"] = caregiver.name if caregiver else None
        task_responses.append(resp)

    return success_response({
        "outing_plan_id": plan_id,
        "total_tasks": len(tasks),
        "completed_tasks": sum(1 for t in tasks if t.is_completed),
        "caregivers": list(caregiver_summaries.values()),
        "tasks": task_responses
    }, "获取成功")


@router.post("/plans/{plan_id}/caregiver-tasks", summary="添加照护人任务")
def add_caregiver_task(task_data: OutingCaregiverTaskCreate, db: Session = Depends(get_db)):
    plan = db.query(OutingPlan).filter(OutingPlan.id == task_data.outing_plan_id).first()
    if not plan:
        return not_found_response("外出计划不存在")

    if not _validate_caregiver_baby_belonging(db, task_data.caregiver_id, plan.baby_id):
        return bad_request_response("照护人与宝宝无归属关系")

    try:
        due_time = None
        if task_data.due_time:
            due_time = _parse_datetime(task_data.due_time)

        db_task = OutingCaregiverTask(
            outing_plan_id=task_data.outing_plan_id,
            caregiver_id=task_data.caregiver_id,
            task_type=task_data.task_type,
            task_description=task_data.task_description,
            item_category=task_data.item_category,
            quantity=task_data.quantity if task_data.quantity is not None else 0,
            priority=task_data.priority or "normal",
            due_time=due_time,
            notes=task_data.notes
        )
        db.add(db_task)
        db.commit()
        db.refresh(db_task)

        caregiver = db.query(Caregiver).filter(Caregiver.id == task_data.caregiver_id).first()
        resp = OutingCaregiverTaskResponse.model_validate(db_task).model_dump()
        resp["caregiver_name"] = caregiver.name if caregiver else None

        return success_response(resp, "任务添加成功")
    except Exception as e:
        db.rollback()
        return bad_request_response(f"添加失败: {str(e)}")


@router.put("/caregiver-tasks/{task_id}/complete", summary="标记照护人任务为已完成")
def complete_caregiver_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(OutingCaregiverTask).filter(
        OutingCaregiverTask.id == task_id
    ).first()
    if not task:
        return not_found_response("任务不存在")

    try:
        task.is_completed = True
        task.completed_at = datetime.utcnow()
        db.commit()
        db.refresh(task)

        caregiver = task.caregiver
        resp = OutingCaregiverTaskResponse.model_validate(task).model_dump()
        resp["caregiver_name"] = caregiver.name if caregiver else None

        return success_response(resp, "标记成功")
    except Exception as e:
        db.rollback()
        return bad_request_response(f"操作失败: {str(e)}")


@router.post("/plans/{plan_id}/consumption", summary="提交外出后实际消耗")
def submit_consumption(plan_id: int, submit_data: OutingConsumptionSubmitRequest, db: Session = Depends(get_db)):
    plan = db.query(OutingPlan).filter(OutingPlan.id == plan_id).first()
    if not plan:
        return not_found_response("外出计划不存在")

    baby = db.query(Baby).filter(Baby.id == plan.baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    for item in submit_data.items:
        if item.actual_quantity < 0:
            return bad_request_response("实际消耗数量不能为负数")
        if item.planned_quantity is not None and item.planned_quantity < 0:
            return bad_request_response("计划数量不能为负数")

    try:
        existing = db.query(OutingConsumptionRecord).filter(
            OutingConsumptionRecord.outing_plan_id == plan_id
        ).all()
        for rec in existing:
            db.delete(rec)

        saved_records = []
        for item_data in submit_data.items:
            db_record = OutingConsumptionRecord(
                outing_plan_id=plan_id,
                baby_id=plan.baby_id,
                item_type=item_data.item_type,
                item_name=item_data.item_name,
                diaper_size=item_data.diaper_size,
                planned_quantity=item_data.planned_quantity or 0,
                actual_quantity=item_data.actual_quantity,
                unit=item_data.unit or "pieces",
                notes=item_data.notes
            )
            db.add(db_record)
            saved_records.append(db_record)

        db.commit()
        for rec in saved_records:
            db.refresh(rec)

        calculator = OutingPackingCalculator(db)
        items_dict = [
            {
                "item_type": r.item_type,
                "item_name": r.item_name,
                "diaper_size": r.diaper_size,
                "actual_quantity": r.actual_quantity,
                "planned_quantity": r.planned_quantity,
                "unit": r.unit
            }
            for r in saved_records
        ]
        writeback_suggestions = calculator.calculate_inventory_writeback(plan, baby, items_dict)

        total_planned = sum(r.planned_quantity for r in saved_records)
        total_actual = sum(r.actual_quantity for r in saved_records)
        variance_pct = round((total_actual - total_planned) / total_planned * 100, 1) if total_planned > 0 else 0

        return success_response({
            "outing_plan_id": plan_id,
            "baby_id": plan.baby_id,
            "total_items": len(saved_records),
            "total_actual_quantity": total_actual,
            "total_planned_quantity": total_planned,
            "variance_pct": variance_pct,
            "items": [OutingConsumptionRecordResponse.model_validate(r).model_dump() for r in saved_records],
            "inventory_writeback_suggestions": writeback_suggestions
        }, "消耗记录提交成功")
    except Exception as e:
        db.rollback()
        return bad_request_response(f"提交失败: {str(e)}")


@router.get("/plans/{plan_id}/consumption", summary="获取外出消耗记录")
def get_consumption_records(plan_id: int, db: Session = Depends(get_db)):
    plan = db.query(OutingPlan).filter(OutingPlan.id == plan_id).first()
    if not plan:
        return not_found_response("外出计划不存在")

    records = db.query(OutingConsumptionRecord).filter(
        OutingConsumptionRecord.outing_plan_id == plan_id
    ).order_by(OutingConsumptionRecord.recorded_at.desc()).all()

    total_planned = sum(r.planned_quantity for r in records)
    total_actual = sum(r.actual_quantity for r in records)
    variance_pct = round((total_actual - total_planned) / total_planned * 100, 1) if total_planned > 0 else 0

    return success_response({
        "outing_plan_id": plan_id,
        "baby_id": plan.baby_id,
        "total_items": len(records),
        "total_actual_quantity": total_actual,
        "total_planned_quantity": total_planned,
        "variance_pct": variance_pct,
        "items": [OutingConsumptionRecordResponse.model_validate(r).model_dump() for r in records]
    }, "获取成功")


@router.get("/plans/{plan_id}/summary", summary="获取外出计划汇总")
def get_outing_summary(plan_id: int, db: Session = Depends(get_db)):
    plan = db.query(OutingPlan).filter(OutingPlan.id == plan_id).first()
    if not plan:
        return not_found_response("外出计划不存在")

    plan_resp = OutingPlanResponse.model_validate(plan).model_dump()

    caregivers_assignments = db.query(OutingCaregiverAssignment).filter(
        OutingCaregiverAssignment.outing_plan_id == plan_id
    ).all()
    caregiver_responses = []
    for a in caregivers_assignments:
        resp = OutingCaregiverAssignmentResponse.model_validate(a).model_dump()
        c = a.caregiver
        resp["caregiver_name"] = c.name if c else None
        resp["caregiver_role"] = c.role if c else None
        caregiver_responses.append(resp)

    bag_items = db.query(OutingBagItem).filter(
        OutingBagItem.outing_plan_id == plan_id
    ).all()
    diaper_items = [i for i in bag_items if i.item_type == "diaper"]
    total_diapers = sum(i.quantity for i in diaper_items)
    packing_summary = {
        "total_items": len(bag_items),
        "total_diapers": total_diapers,
        "essential_count": sum(1 for i in bag_items if i.is_essential),
        "optional_count": sum(1 for i in bag_items if not i.is_essential)
    }

    schedules = db.query(OutingChangeSchedule).filter(
        OutingChangeSchedule.outing_plan_id == plan_id
    ).all()
    change_summary = {
        "total_changes": len(schedules),
        "completed_changes": sum(1 for s in schedules if s.is_completed),
        "daytime_changes": sum(1 for s in schedules if not s.is_nighttime),
        "nighttime_changes": sum(1 for s in schedules if s.is_nighttime)
    }

    risk_alerts = db.query(OutingRiskAlert).filter(
        OutingRiskAlert.outing_plan_id == plan_id
    ).all()
    risk_summary = {
        "total_risks": len(risk_alerts),
        "high_risk_count": sum(1 for r in risk_alerts if r.risk_level in ["high", "critical"]),
        "medium_risk_count": sum(1 for r in risk_alerts if r.risk_level == "medium"),
        "low_risk_count": sum(1 for r in risk_alerts if r.risk_level == "low"),
        "resolved_count": sum(1 for r in risk_alerts if r.resolved)
    }

    emergency = db.query(OutingEmergencyPlan).filter(
        OutingEmergencyPlan.outing_plan_id == plan_id
    ).first()
    emergency_resp = OutingEmergencyPlanResponse.model_validate(emergency).model_dump() if emergency else None

    return success_response({
        "plan": plan_resp,
        "caregivers": caregiver_responses,
        "packing_list_summary": packing_summary,
        "change_schedule_summary": change_summary,
        "risk_summary": risk_summary,
        "emergency_plan": emergency_resp
    }, "获取成功")


@router.put("/plans/{plan_id}/status", summary="更新外出计划状态")
def update_outing_status(
    plan_id: int,
    status: str,
    db: Session = Depends(get_db)
):
    plan = db.query(OutingPlan).filter(OutingPlan.id == plan_id).first()
    if not plan:
        return not_found_response("外出计划不存在")

    try:
        validate_outing_status(status)
    except ValueError as e:
        return bad_request_response(str(e))

    try:
        plan.status = status
        plan.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(plan)
        return success_response(
            OutingPlanResponse.model_validate(plan).model_dump(),
            "状态更新成功"
        )
    except Exception as e:
        db.rollback()
        return bad_request_response(f"更新失败: {str(e)}")


@router.get("/plans/{plan_id}/inventory-writeback", summary="获取回家后库存回写建议")
def get_inventory_writeback_suggestions(plan_id: int, db: Session = Depends(get_db)):
    plan = db.query(OutingPlan).filter(OutingPlan.id == plan_id).first()
    if not plan:
        return not_found_response("外出计划不存在")

    baby = db.query(Baby).filter(Baby.id == plan.baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    consumption_records = db.query(OutingConsumptionRecord).filter(
        OutingConsumptionRecord.outing_plan_id == plan_id
    ).all()

    if not consumption_records:
        return success_response([], "暂无消耗记录，请先提交实际消耗")

    items_dict = [
        {
            "item_type": r.item_type,
            "item_name": r.item_name,
            "diaper_size": r.diaper_size,
            "actual_quantity": r.actual_quantity,
            "planned_quantity": r.planned_quantity,
            "unit": r.unit
        }
        for r in consumption_records
    ]

    calculator = OutingPackingCalculator(db)
    suggestions = calculator.calculate_inventory_writeback(plan, baby, items_dict)

    return success_response({
        "outing_plan_id": plan_id,
        "baby_id": baby.id,
        "suggestions": suggestions
    }, "获取成功")

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime

from ..database import get_db
from ..models import Baby, GrowthPlan, PackageSpec
from ..schemas import (
    GrowthPlanCreate, GrowthPlanUpdate, GrowthPlanResponse,
    PackageSpecCreate, PackageSpecUpdate, PackageSpecResponse,
    validate_diaper_size
)
from ..utils import success_response, not_found_response, bad_request_response
from ..prediction import GrowthPlanning
from ..alerts import PlanReminderSystem

router = APIRouter(prefix="/api/planning", tags=["成长计划与补货规划"])


@router.post("/growth-plan", summary="创建成长计划配置")
def create_growth_plan(plan_data: GrowthPlanCreate, db: Session = Depends(get_db)):
    baby = db.query(Baby).filter(Baby.id == plan_data.baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    existing = db.query(GrowthPlan).filter(GrowthPlan.baby_id == plan_data.baby_id).first()
    if existing:
        return bad_request_response("该宝宝已有成长计划，请使用更新接口")

    try:
        db_plan = GrowthPlan(
            baby_id=plan_data.baby_id,
            target_weight_kg=plan_data.target_weight_kg,
            target_date=plan_data.target_date,
            growth_rate_kg_per_month=plan_data.growth_rate_kg_per_month,
            promo_stocking_preference=plan_data.promo_stocking_preference or "moderate",
            preferred_brand=plan_data.preferred_brand,
            safety_stock_days=plan_data.safety_stock_days if plan_data.safety_stock_days is not None else 7,
            planning_horizon_days=plan_data.planning_horizon_days if plan_data.planning_horizon_days is not None else 90
        )
        db.add(db_plan)
        db.commit()
        db.refresh(db_plan)

        return success_response(
            GrowthPlanResponse.model_validate(db_plan).model_dump(),
            "成长计划创建成功"
        )
    except Exception as e:
        db.rollback()
        return bad_request_response(f"创建失败: {str(e)}")


@router.get("/growth-plan/{baby_id}", summary="获取成长计划配置")
def get_growth_plan(baby_id: int, db: Session = Depends(get_db)):
    baby = db.query(Baby).filter(Baby.id == baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    plan = db.query(GrowthPlan).filter(GrowthPlan.baby_id == baby_id).first()
    if not plan:
        plan = GrowthPlan(
            baby_id=baby_id,
            promo_stocking_preference="moderate",
            safety_stock_days=7,
            planning_horizon_days=90
        )
        return success_response({
            "baby_id": baby_id,
            "target_weight_kg": None,
            "target_date": None,
            "growth_rate_kg_per_month": None,
            "promo_stocking_preference": "moderate",
            "preferred_brand": None,
            "safety_stock_days": 7,
            "planning_horizon_days": 90,
            "is_default": True
        }, "使用默认配置")

    return success_response(
        GrowthPlanResponse.model_validate(plan).model_dump(),
        "获取成功"
    )


@router.put("/growth-plan/{baby_id}", summary="更新成长计划配置")
def update_growth_plan(baby_id: int, plan_data: GrowthPlanUpdate, db: Session = Depends(get_db)):
    baby = db.query(Baby).filter(Baby.id == baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    plan = db.query(GrowthPlan).filter(GrowthPlan.baby_id == baby_id).first()
    if not plan:
        plan = GrowthPlan(
            baby_id=baby_id,
            promo_stocking_preference="moderate",
            safety_stock_days=7,
            planning_horizon_days=90
        )
        db.add(plan)
        db.flush()

    try:
        update_data = plan_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            if value is not None:
                setattr(plan, key, value)
        plan.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(plan)

        return success_response(
            GrowthPlanResponse.model_validate(plan).model_dump(),
            "更新成功"
        )
    except Exception as e:
        db.rollback()
        return bad_request_response(f"更新失败: {str(e)}")


@router.post("/package-spec", summary="创建包装规格")
def create_package_spec(spec_data: PackageSpecCreate, db: Session = Depends(get_db)):
    baby = db.query(Baby).filter(Baby.id == spec_data.baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    try:
        db_spec = PackageSpec(
            baby_id=spec_data.baby_id,
            brand=spec_data.brand,
            size=spec_data.size.upper(),
            pieces_per_pack=spec_data.pieces_per_pack,
            packs_per_box=spec_data.packs_per_box or 1,
            price_per_pack=spec_data.price_per_pack,
            is_active=spec_data.is_active if spec_data.is_active is not None else True,
            notes=spec_data.notes
        )
        db.add(db_spec)
        db.commit()
        db.refresh(db_spec)

        return success_response(
            PackageSpecResponse.model_validate(db_spec).model_dump(),
            "包装规格创建成功"
        )
    except Exception as e:
        db.rollback()
        return bad_request_response(f"创建失败: {str(e)}")


@router.get("/package-spec/{baby_id}", summary="获取包装规格列表")
def get_package_specs(baby_id: int, size: Optional[str] = None, is_active: Optional[bool] = None,
                       db: Session = Depends(get_db)):
    baby = db.query(Baby).filter(Baby.id == baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    query = db.query(PackageSpec).filter(PackageSpec.baby_id == baby_id)

    if size:
        try:
            size = validate_diaper_size(size)
            query = query.filter(PackageSpec.size == size)
        except ValueError as e:
            return bad_request_response(str(e))

    if is_active is not None:
        query = query.filter(PackageSpec.is_active == is_active)

    specs = query.order_by(PackageSpec.size, PackageSpec.brand).all()

    return success_response([
        PackageSpecResponse.model_validate(s).model_dump()
        for s in specs
    ], "获取成功")


@router.put("/package-spec/{spec_id}", summary="更新包装规格")
def update_package_spec(spec_id: int, spec_data: PackageSpecUpdate, db: Session = Depends(get_db)):
    spec = db.query(PackageSpec).filter(PackageSpec.id == spec_id).first()
    if not spec:
        return not_found_response("包装规格不存在")

    try:
        update_data = spec_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            if value is not None:
                if key == "size":
                    value = value.upper()
                setattr(spec, key, value)
        spec.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(spec)

        return success_response(
            PackageSpecResponse.model_validate(spec).model_dump(),
            "更新成功"
        )
    except Exception as e:
        db.rollback()
        return bad_request_response(f"更新失败: {str(e)}")


@router.delete("/package-spec/{spec_id}", summary="删除包装规格")
def delete_package_spec(spec_id: int, db: Session = Depends(get_db)):
    spec = db.query(PackageSpec).filter(PackageSpec.id == spec_id).first()
    if not spec:
        return not_found_response("包装规格不存在")

    try:
        db.delete(spec)
        db.commit()
        return success_response(None, "删除成功")
    except Exception as e:
        db.rollback()
        return bad_request_response(f"删除失败: {str(e)}")


@router.get("/replenishment/{baby_id}", summary="获取阶段性补货计划")
def get_replenishment_plan(
    baby_id: int,
    planning_period_days: Optional[int] = 30,
    db: Session = Depends(get_db)
):
    baby = db.query(Baby).filter(Baby.id == baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    if planning_period_days is None or planning_period_days <= 0 or planning_period_days > 365:
        return bad_request_response("计划周期天数必须在 1-365 天之间")

    planner = GrowthPlanning(db)
    plan = planner.get_comprehensive_planning(baby, planning_period_days=planning_period_days)

    reminder_system = PlanReminderSystem(db)
    reminders = reminder_system.generate_plan_reminders(baby, planning_period_days=planning_period_days)

    reason_codes = list(set(r["reason_code"] for r in reminders))

    return success_response({
        **plan,
        "plan_reminders": reminders,
        "reason_codes": reason_codes,
        "reminder_count": len(reminders)
    }, "补货计划生成完成")


@router.get("/size-transition/{baby_id}", summary="获取换码过渡日历")
def get_size_transition_calendar(
    baby_id: int,
    planning_period_days: Optional[int] = 90,
    db: Session = Depends(get_db)
):
    baby = db.query(Baby).filter(Baby.id == baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    if planning_period_days is None or planning_period_days <= 0 or planning_period_days > 365:
        return bad_request_response("计划周期天数必须在 1-365 天之间")

    planner = GrowthPlanning(db)
    transition_windows = planner.calculate_size_transition_windows(baby, planning_period_days=planning_period_days)
    size_change_info = planner.estimate_size_change_date(baby)
    next_readiness = planner.calculate_next_size_readiness(baby)

    today = datetime.now()
    calendar_events = []

    for window in transition_windows:
        start_date = datetime.strptime(window["start_date"], "%Y-%m-%d")
        end_date = datetime.strptime(window["end_date"], "%Y-%m-%d")
        peak_date = datetime.strptime(window["peak_date"], "%Y-%m-%d")

        if start_date < today and window["transition_type"] == "past":
            event_type = "past_transition"
        elif window["transition_type"] == "current":
            event_type = "current_usage"
        else:
            event_type = "future_transition"

        calendar_events.append({
            "size": window["size"],
            "event_type": event_type,
            "start_date": window["start_date"],
            "end_date": window["end_date"],
            "peak_date": window["peak_date"],
            "duration_days": window["duration_days"],
            "confidence": window["confidence"],
            "transition_type": window["transition_type"]
        })

    if size_change_info.get("estimated_change_date"):
        calendar_events.append({
            "size": size_change_info["next_size"],
            "event_type": "size_change_date",
            "change_date": size_change_info["estimated_change_date"],
            "days_remaining": size_change_info["days_remaining"],
            "confidence": size_change_info["confidence"],
            "leak_adjustment_days": size_change_info.get("leak_adjustment_days", 0)
        })

    return success_response({
        "baby_id": baby_id,
        "baby_name": baby.name,
        "planning_period_days": planning_period_days,
        "current_size": baby.current_diaper_size,
        "transition_windows": transition_windows,
        "calendar_events": sorted(calendar_events, key=lambda x: x.get("start_date", x.get("change_date", ""))),
        "estimated_size_change_date": size_change_info,
        "next_size_readiness": next_readiness
    }, "换码过渡日历生成完成")


@router.get("/overstock-risk/{baby_id}", summary="获取囤货风险评估")
def get_overstock_risk_assessment(
    baby_id: int,
    planning_period_days: Optional[int] = 30,
    db: Session = Depends(get_db)
):
    baby = db.query(Baby).filter(Baby.id == baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    if planning_period_days is None or planning_period_days <= 0 or planning_period_days > 365:
        return bad_request_response("计划周期天数必须在 1-365 天之间")

    planner = GrowthPlanning(db)
    risk_items = planner.assess_overstock_risk(baby, planning_period_days=planning_period_days)

    high_risk_count = sum(1 for r in risk_items if r["risk_level"] == "high")
    medium_risk_count = sum(1 for r in risk_items if r["risk_level"] == "medium")
    low_risk_count = sum(1 for r in risk_items if r["risk_level"] == "low")

    total_overstock_pieces = sum(r["overstock_pieces"] for r in risk_items)

    overall_risk = "none"
    if high_risk_count > 0:
        overall_risk = "high"
    elif medium_risk_count > 0:
        overall_risk = "medium"
    elif low_risk_count > 0:
        overall_risk = "low"

    suggestions = []
    if overall_risk == "high":
        suggestions.append("高风险：建议立即停止囤货，优先消耗现有库存")
        suggestions.append("可考虑将多余库存转让、捐赠或作为礼物送出")
    elif overall_risk == "medium":
        suggestions.append("中风险：建议减少购买量，关注库存消耗速度")
        suggestions.append("促销期间谨慎囤货，避免库存积压")
    elif overall_risk == "low":
        suggestions.append("低风险：库存基本合理，可按正常节奏购买")
    else:
        suggestions.append("库存健康，无明显囤货风险")

    return success_response({
        "baby_id": baby_id,
        "baby_name": baby.name,
        "planning_period_days": planning_period_days,
        "overall_risk": overall_risk,
        "risk_summary": {
            "high_risk_count": high_risk_count,
            "medium_risk_count": medium_risk_count,
            "low_risk_count": low_risk_count,
            "total_overstock_pieces": total_overstock_pieces
        },
        "overstock_risk_items": risk_items,
        "suggestions": suggestions
    }, "囤货风险评估完成")


@router.get("/reminders/{baby_id}", summary="获取计划提醒列表")
def get_plan_reminders(
    baby_id: int,
    resolved: Optional[bool] = None,
    days: Optional[int] = 30,
    planning_period_days: Optional[int] = 30,
    db: Session = Depends(get_db)
):
    baby = db.query(Baby).filter(Baby.id == baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    if days is None or days <= 0 or days > 365:
        return bad_request_response("查询天数必须在 1-365 天之间")

    if planning_period_days is None or planning_period_days <= 0 or planning_period_days > 365:
        return bad_request_response("计划周期天数必须在 1-365 天之间")

    reminder_system = PlanReminderSystem(db)
    stored_reminders = reminder_system.get_plan_reminders(baby_id, resolved=resolved, days=days)
    statistics = reminder_system.get_plan_reminder_statistics(baby_id, days=days)

    live_reminders = reminder_system.generate_plan_reminders(baby, planning_period_days=planning_period_days)

    reason_codes = list(set(r["reason_code"] for r in live_reminders))

    return success_response({
        "baby_id": baby_id,
        "baby_name": baby.name,
        "statistics": statistics,
        "stored_reminders": stored_reminders,
        "live_reminders": live_reminders,
        "reason_codes": reason_codes
    }, "获取成功")


@router.post("/reminders/check/{baby_id}", summary="主动检查并创建计划提醒")
def check_and_create_reminders(
    baby_id: int,
    planning_period_days: Optional[int] = 30,
    db: Session = Depends(get_db)
):
    baby = db.query(Baby).filter(Baby.id == baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    if planning_period_days is None or planning_period_days <= 0 or planning_period_days > 365:
        return bad_request_response("计划周期天数必须在 1-365 天之间")

    reminder_system = PlanReminderSystem(db)
    new_reminders = reminder_system.check_and_create_plan_reminders(baby, planning_period_days=planning_period_days)

    return success_response({
        "baby_id": baby_id,
        "baby_name": baby.name,
        "new_reminders_count": len(new_reminders),
        "new_reminders": [
            {
                "id": r.id,
                "reminder_type": r.reminder_type,
                "reminder_level": r.reminder_level,
                "reason_code": r.reason_code,
                "message": r.message,
                "related_size": r.related_size
            }
            for r in new_reminders
        ]
    }, "检查完成")


@router.put("/reminders/{reminder_id}/resolve", summary="标记计划提醒为已解决")
def resolve_plan_reminder(
    reminder_id: int,
    resolved: Optional[bool] = True,
    db: Session = Depends(get_db)
):
    reminder_system = PlanReminderSystem(db)
    reminder = reminder_system.resolve_plan_reminder(reminder_id, resolved=resolved)

    if not reminder:
        return not_found_response("提醒不存在")

    return success_response({
        "id": reminder.id,
        "resolved": reminder.resolved,
        "resolved_at": reminder.resolved_at
    }, "操作成功")


@router.get("/purchase-priority/{baby_id}", summary="获取购买优先级排序")
def get_purchase_priority(
    baby_id: int,
    planning_period_days: Optional[int] = 30,
    db: Session = Depends(get_db)
):
    baby = db.query(Baby).filter(Baby.id == baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    if planning_period_days is None or planning_period_days <= 0 or planning_period_days > 365:
        return bad_request_response("计划周期天数必须在 1-365 天之间")

    planner = GrowthPlanning(db)
    priorities = planner.calculate_purchase_priority(baby, planning_period_days=planning_period_days)

    total_recommended_pieces = sum(p["recommended_pieces"] for p in priorities)
    total_recommended_packs = sum(p["recommended_packs"] for p in priorities)

    return success_response({
        "baby_id": baby_id,
        "baby_name": baby.name,
        "planning_period_days": planning_period_days,
        "total_recommended_pieces": int(total_recommended_pieces),
        "total_recommended_packs": round(total_recommended_packs, 1),
        "purchase_priority": priorities
    }, "获取成功")


@router.get("/comprehensive/{baby_id}", summary="获取综合成长规划报告")
def get_comprehensive_planning_report(
    baby_id: int,
    planning_period_days: Optional[int] = 30,
    db: Session = Depends(get_db)
):
    baby = db.query(Baby).filter(Baby.id == baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    if planning_period_days is None or planning_period_days <= 0 or planning_period_days > 365:
        return bad_request_response("计划周期天数必须在 1-365 天之间")

    planner = GrowthPlanning(db)
    plan = planner.get_comprehensive_planning(baby, planning_period_days=planning_period_days)

    reminder_system = PlanReminderSystem(db)
    reminders = reminder_system.generate_plan_reminders(baby, planning_period_days=planning_period_days)
    reminder_stats = reminder_system.get_plan_reminder_statistics(baby_id, days=planning_period_days)

    reason_codes = list(set(r["reason_code"] for r in reminders))

    return success_response({
        **plan,
        "plan_reminders": reminders,
        "reason_codes": reason_codes,
        "reminder_statistics": reminder_stats
    }, "综合规划报告生成完成")

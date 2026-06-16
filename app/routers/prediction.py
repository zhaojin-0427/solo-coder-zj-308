from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import Optional

from ..database import get_db
from ..models import Baby
from ..utils import success_response, not_found_response, bad_request_response
from ..prediction import DiaperPrediction

router = APIRouter(prefix="/api/prediction", tags=["消耗预测"])


@router.get("/{baby_id}", summary="获取消耗预测")
def get_consumption_prediction(
    baby_id: int,
    days: Optional[int] = 30,
    db: Session = Depends(get_db)
):
    if days is not None and days <= 0:
        return bad_request_response("预测天数必须为正整数")

    baby = db.query(Baby).filter(Baby.id == baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    predictor = DiaperPrediction(db)
    prediction = predictor.predict_future_consumption(baby, days=days)

    size_cycles = predictor.calculate_size_usage_cycle(baby_id)

    return success_response({
        **prediction,
        "size_usage_cycles": size_cycles
    }, "预测完成")


@router.get("/inventory-days/{baby_id}", summary="计算库存可用天数")
def get_inventory_days(
    baby_id: int,
    size: Optional[str] = None,
    db: Session = Depends(get_db)
):
    baby = db.query(Baby).filter(Baby.id == baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    target_size = size or baby.current_diaper_size

    predictor = DiaperPrediction(db)
    status = predictor.calculate_inventory_days(baby_id, target_size)

    return success_response({
        "baby_id": baby_id,
        "baby_name": baby.name,
        "size": target_size,
        "is_current_size": target_size == baby.current_diaper_size,
        **status
    }, "计算完成")


@router.get("/restocking/{baby_id}", summary="生成补货清单")
def get_restocking_list(
    baby_id: int,
    safety_days: Optional[int] = 7,
    db: Session = Depends(get_db)
):
    if safety_days is not None and safety_days <= 0:
        return bad_request_response("安全库存天数必须为正整数")

    baby = db.query(Baby).filter(Baby.id == baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    predictor = DiaperPrediction(db)
    restocking_list = predictor.generate_restocking_list(baby, safety_days=safety_days)

    total_recommendation = sum(item["recommended_quantity"] for item in restocking_list)
    priority_summary = {
        "critical": sum(1 for item in restocking_list if item["priority"] == "critical"),
        "high": sum(1 for item in restocking_list if item["priority"] == "high"),
        "medium": sum(1 for item in restocking_list if item["priority"] == "medium"),
        "low": sum(1 for item in restocking_list if item["priority"] == "low")
    }

    return success_response({
        "baby_id": baby_id,
        "baby_name": baby.name,
        "current_size": baby.current_diaper_size,
        "safety_days": safety_days,
        "priority_summary": priority_summary,
        "total_recommended_pieces": total_recommendation,
        "restocking_items": restocking_list
    }, "补货清单生成完成")


@router.get("/size-cycles/{baby_id}", summary="获取各尺码平均使用周期")
def get_size_cycles(
    baby_id: int,
    db: Session = Depends(get_db)
):
    baby = db.query(Baby).filter(Baby.id == baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    predictor = DiaperPrediction(db)
    cycles = predictor.calculate_size_usage_cycle(baby_id)

    return success_response({
        "baby_id": baby_id,
        "baby_name": baby.name,
        "size_cycles": cycles
    }, "获取成功")

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime

from ..database import get_db
from ..models import Baby
from ..schemas import BabyCreate, BabyUpdate, BabyResponse
from ..utils import success_response, not_found_response, bad_request_response
from ..alerts import AlertSystem

router = APIRouter(prefix="/api/babies", tags=["宝宝档案管理"])


@router.post("", summary="创建宝宝档案")
def create_baby(baby_data: BabyCreate, db: Session = Depends(get_db)):
    try:
        db_baby = Baby(
            name=baby_data.name,
            birth_date=baby_data.birth_date,
            current_age_months=baby_data.current_age_months,
            current_weight_kg=baby_data.current_weight_kg,
            current_diaper_size=baby_data.current_diaper_size,
            gender=baby_data.gender
        )
        db.add(db_baby)
        db.commit()
        db.refresh(db_baby)

        alert_system = AlertSystem(db)
        alerts = alert_system.check_and_create_alerts(db_baby)

        return success_response({
            "baby": BabyResponse.model_validate(db_baby).model_dump(),
            "generated_alerts": len(alerts)
        }, "宝宝档案创建成功")
    except Exception as e:
        return bad_request_response(f"创建失败: {str(e)}")


@router.get("", summary="获取宝宝列表")
def get_babies(db: Session = Depends(get_db)):
    babies = db.query(Baby).order_by(Baby.created_at.desc()).all()
    return success_response([
        BabyResponse.model_validate(baby).model_dump()
        for baby in babies
    ])


@router.get("/{baby_id}", summary="获取宝宝详情")
def get_baby(baby_id: int, db: Session = Depends(get_db)):
    baby = db.query(Baby).filter(Baby.id == baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    alert_system = AlertSystem(db)
    size_analysis = alert_system.analyze_size_change_need(baby)
    nighttime_risk = alert_system.get_nighttime_risk_summary(baby_id)
    alert_stats = alert_system.get_alert_statistics(baby_id)

    from ..prediction import DiaperPrediction
    predictor = DiaperPrediction(db)
    inventory_status = predictor.calculate_inventory_days(baby_id, baby.current_diaper_size)
    size_cycles = predictor.calculate_size_usage_cycle(baby_id)

    return success_response({
        "baby": BabyResponse.model_validate(baby).model_dump(),
        "current_status": {
            "inventory_status": inventory_status,
            "size_analysis": {
                "decision": size_analysis["decision"],
                "urgency": size_analysis["urgency"],
                "recommended_next_size": size_analysis["recommended_next_size"],
                "estimated_days_remaining": size_analysis["estimated_days_remaining_in_size"]
            },
            "nighttime_risk": nighttime_risk["risk_assessment"],
            "alert_statistics": alert_stats,
            "size_usage_cycles": size_cycles
        }
    })


@router.put("/{baby_id}", summary="更新宝宝档案")
def update_baby(baby_id: int, baby_data: BabyUpdate, db: Session = Depends(get_db)):
    baby = db.query(Baby).filter(Baby.id == baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    try:
        update_data = baby_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(baby, key, value)
        baby.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(baby)

        alert_system = AlertSystem(db)
        alerts = alert_system.check_and_create_alerts(baby)

        return success_response({
            "baby": BabyResponse.model_validate(baby).model_dump(),
            "generated_alerts": len(alerts)
        }, "更新成功")
    except Exception as e:
        return bad_request_response(f"更新失败: {str(e)}")


@router.delete("/{baby_id}", summary="删除宝宝档案")
def delete_baby(baby_id: int, db: Session = Depends(get_db)):
    baby = db.query(Baby).filter(Baby.id == baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    try:
        db.delete(baby)
        db.commit()
        return success_response(None, "删除成功")
    except Exception as e:
        return bad_request_response(f"删除失败: {str(e)}")

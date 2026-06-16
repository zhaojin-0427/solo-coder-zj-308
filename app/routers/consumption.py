from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import Optional

from ..database import get_db
from ..models import Baby, ConsumptionRecord
from ..schemas import ConsumptionRecordCreate
from ..utils import success_response, not_found_response, bad_request_response
from ..alerts import AlertSystem

router = APIRouter(prefix="/api/consumption", tags=["消耗记录管理"])


@router.post("", summary="上报每日消耗记录")
def create_consumption_record(record_data: ConsumptionRecordCreate, db: Session = Depends(get_db)):
    baby = db.query(Baby).filter(Baby.id == record_data.baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    try:
        db_record = ConsumptionRecord(
            baby_id=record_data.baby_id,
            record_date=record_data.record_date,
            diaper_size=record_data.diaper_size,
            daily_changes=record_data.daily_changes,
            nighttime_changes=record_data.nighttime_changes,
            nighttime_leaks=record_data.nighttime_leaks,
            weight_kg=record_data.weight_kg,
            notes=record_data.notes
        )
        db.add(db_record)

        if record_data.weight_kg:
            baby.current_weight_kg = record_data.weight_kg

        db.commit()
        db.refresh(db_record)

        alert_system = AlertSystem(db)
        alerts = alert_system.check_and_create_alerts(baby)

        return success_response({
            "record_id": db_record.id,
            "generated_alerts": len(alerts),
            "alerts": [
                {
                    "id": a.id,
                    "type": a.alert_type,
                    "level": a.alert_level,
                    "message": a.message
                }
                for a in alerts
            ]
        }, "消耗记录上报成功")
    except Exception as e:
        return bad_request_response(f"上报失败: {str(e)}")


@router.get("/baby/{baby_id}", summary="获取宝宝消耗记录列表")
def get_baby_consumption(
    baby_id: int,
    days: Optional[int] = 30,
    db: Session = Depends(get_db)
):
    from datetime import datetime, timedelta

    if days is not None and days <= 0:
        return bad_request_response("查询天数必须为正整数")

    baby = db.query(Baby).filter(Baby.id == baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    records = db.query(ConsumptionRecord).filter(
        ConsumptionRecord.baby_id == baby_id,
        ConsumptionRecord.record_date >= cutoff_date
    ).order_by(ConsumptionRecord.record_date.desc()).all()

    total_changes = sum(r.daily_changes for r in records)
    total_nightly = sum(r.nighttime_changes for r in records)
    total_leaks = sum(r.nighttime_leaks for r in records)
    data_points = len(records)

    return success_response({
        "baby_id": baby_id,
        "baby_name": baby.name,
        "query_period_days": days,
        "data_points": data_points,
        "summary": {
            "total_changes": total_changes,
            "average_daily_changes": round(total_changes / data_points, 1) if data_points > 0 else 0,
            "total_nightly_changes": total_nightly,
            "average_nightly_changes": round(total_nightly / data_points, 1) if data_points > 0 else 0,
            "total_leaks": total_leaks,
            "average_leaks_per_day": round(total_leaks / data_points, 2) if data_points > 0 else 0,
            "leak_days": sum(1 for r in records if r.nighttime_leaks > 0)
        },
        "records": [
            {
                "id": r.id,
                "record_date": r.record_date,
                "diaper_size": r.diaper_size,
                "daily_changes": r.daily_changes,
                "nighttime_changes": r.nighttime_changes,
                "nighttime_leaks": r.nighttime_leaks,
                "weight_kg": r.weight_kg,
                "notes": r.notes
            }
            for r in records
        ]
    })

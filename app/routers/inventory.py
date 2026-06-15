from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import Optional

from ..database import get_db
from ..models import Baby, InventoryRecord
from ..schemas import InventoryRecordCreate
from ..utils import success_response, not_found_response, bad_request_response
from ..prediction import DiaperPrediction
from ..alerts import AlertSystem

router = APIRouter(prefix="/api/inventory", tags=["库存管理"])


@router.post("", summary="上报库存")
def create_inventory_record(record_data: InventoryRecordCreate, db: Session = Depends(get_db)):
    baby = db.query(Baby).filter(Baby.id == record_data.baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    try:
        db_record = InventoryRecord(
            baby_id=record_data.baby_id,
            record_date=record_data.record_date,
            diaper_size=record_data.diaper_size,
            quantity=record_data.quantity,
            unit=record_data.unit,
            notes=record_data.notes
        )
        db.add(db_record)
        db.commit()
        db.refresh(db_record)

        alert_system = AlertSystem(db)
        alerts = alert_system.check_and_create_alerts(baby)

        predictor = DiaperPrediction(db)
        inventory_status = predictor.calculate_inventory_days(record_data.baby_id, record_data.diaper_size)

        return success_response({
            "record_id": db_record.id,
            "inventory_status": inventory_status,
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
        }, "库存上报成功")
    except Exception as e:
        return bad_request_response(f"上报失败: {str(e)}")


@router.get("/baby/{baby_id}", summary="获取宝宝库存状态")
def get_baby_inventory(
    baby_id: int,
    size: Optional[str] = None,
    db: Session = Depends(get_db)
):
    from datetime import datetime, timedelta

    baby = db.query(Baby).filter(Baby.id == baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    cutoff_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    query = db.query(InventoryRecord).filter(
        InventoryRecord.baby_id == baby_id,
        InventoryRecord.record_date >= cutoff_date
    )

    if size:
        query = query.filter(InventoryRecord.diaper_size == size)

    records = query.order_by(InventoryRecord.record_date.desc()).all()

    predictor = DiaperPrediction(db)

    if size:
        sizes_to_check = [size]
    else:
        sizes_to_check = ["NB", "S", "M", "L", "XL", "XXL"]

    inventory_statuses = []
    for s in sizes_to_check:
        status = predictor.calculate_inventory_days(baby_id, s)
        if status["current_inventory"] > 0 or s == baby.current_diaper_size:
            inventory_statuses.append({
                "size": s,
                "is_current_size": s == baby.current_diaper_size,
                **status
            })

    size_cycles = predictor.calculate_size_usage_cycle(baby_id)

    return success_response({
        "baby_id": baby_id,
        "baby_name": baby.name,
        "current_size": baby.current_diaper_size,
        "inventory_statuses": inventory_statuses,
        "size_usage_cycles": size_cycles,
        "recent_records": [
            {
                "id": r.id,
                "record_date": r.record_date,
                "diaper_size": r.diaper_size,
                "quantity": r.quantity,
                "unit": r.unit,
                "notes": r.notes
            }
            for r in records[:20]
        ]
    })


@router.get("/size-cycles/{baby_id}", summary="获取各尺码平均使用周期")
def get_size_cycles(baby_id: int, db: Session = Depends(get_db)):
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

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timedelta

from ..database import get_db
from ..models import Baby, AlertRecord
from ..schemas import AlertResolve
from ..utils import success_response, not_found_response, bad_request_response
from ..alerts import AlertSystem

router = APIRouter(prefix="/api/alerts", tags=["告警与提醒"])


@router.get("/size-change/{baby_id}", summary="获取换码建议")
def get_size_change_recommendation(baby_id: int, db: Session = Depends(get_db)):
    baby = db.query(Baby).filter(Baby.id == baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    alert_system = AlertSystem(db)
    analysis = alert_system.analyze_size_change_need(baby)

    return success_response(analysis, "获取成功")


@router.get("/nighttime-risk/{baby_id}", summary="获取夜间风险提醒")
def get_nighttime_risk(baby_id: int, db: Session = Depends(get_db)):
    baby = db.query(Baby).filter(Baby.id == baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    alert_system = AlertSystem(db)
    risk_summary = alert_system.get_nighttime_risk_summary(baby_id)
    leak_analysis = alert_system.analyze_leak_patterns(baby_id, days=14)
    alert_stats = alert_system.get_alert_statistics(baby_id)

    return success_response({
        **risk_summary,
        "detailed_leak_analysis": leak_analysis,
        "alert_statistics": alert_stats
    }, "获取成功")


@router.get("/baby/{baby_id}", summary="获取宝宝告警列表")
def get_baby_alerts(
    baby_id: int,
    resolved: Optional[bool] = None,
    days: Optional[int] = 30,
    db: Session = Depends(get_db)
):
    baby = db.query(Baby).filter(Baby.id == baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    cutoff = datetime.now() - timedelta(days=days)
    query = db.query(AlertRecord).filter(
        AlertRecord.baby_id == baby_id,
        AlertRecord.triggered_at >= cutoff
    )

    if resolved is not None:
        query = query.filter(AlertRecord.resolved == resolved)

    alerts = query.order_by(AlertRecord.triggered_at.desc()).all()

    alert_system = AlertSystem(db)
    stats = alert_system.get_alert_statistics(baby_id, days=days)

    return success_response({
        "baby_id": baby_id,
        "baby_name": baby.name,
        "statistics": stats,
        "alerts": [
            {
                "id": a.id,
                "alert_type": a.alert_type,
                "alert_level": a.alert_level,
                "message": a.message,
                "related_size": a.related_size,
                "triggered_at": a.triggered_at,
                "resolved": a.resolved,
                "resolved_at": a.resolved_at
            }
            for a in alerts
        ]
    }, "获取成功")


@router.get("/leak-analysis/{baby_id}", summary="获取漏尿模式分析")
def get_leak_analysis(
    baby_id: int,
    days: Optional[int] = 14,
    db: Session = Depends(get_db)
):
    baby = db.query(Baby).filter(Baby.id == baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    alert_system = AlertSystem(db)
    analysis = alert_system.analyze_leak_patterns(baby_id, days=days)

    return success_response({
        "baby_id": baby_id,
        "baby_name": baby.name,
        **analysis
    }, "分析完成")


@router.post("/check/{baby_id}", summary="主动检查并创建告警")
def check_and_create_alerts(baby_id: int, db: Session = Depends(get_db)):
    baby = db.query(Baby).filter(Baby.id == baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    alert_system = AlertSystem(db)
    alerts = alert_system.check_and_create_alerts(baby)

    return success_response({
        "baby_id": baby_id,
        "baby_name": baby.name,
        "new_alerts_count": len(alerts),
        "new_alerts": [
            {
                "id": a.id,
                "type": a.alert_type,
                "level": a.alert_level,
                "message": a.message,
                "related_size": a.related_size
            }
            for a in alerts
        ]
    }, "检查完成")


@router.put("/{alert_id}/resolve", summary="标记告警为已解决")
def resolve_alert(alert_id: int, resolve_data: AlertResolve, db: Session = Depends(get_db)):
    alert = db.query(AlertRecord).filter(AlertRecord.id == alert_id).first()
    if not alert:
        return not_found_response("告警不存在")

    try:
        alert.resolved = resolve_data.resolved
        if resolve_data.resolved:
            alert.resolved_at = datetime.utcnow()
        db.commit()
        db.refresh(alert)

        return success_response({
            "id": alert.id,
            "resolved": alert.resolved,
            "resolved_at": alert.resolved_at
        }, "操作成功")
    except Exception as e:
        return bad_request_response(f"操作失败: {str(e)}")


@router.get("/statistics/{baby_id}", summary="获取告警统计")
def get_alert_statistics(
    baby_id: int,
    days: Optional[int] = 30,
    db: Session = Depends(get_db)
):
    baby = db.query(Baby).filter(Baby.id == baby_id).first()
    if not baby:
        return not_found_response("宝宝不存在")

    alert_system = AlertSystem(db)
    stats = alert_system.get_alert_statistics(baby_id, days=days)

    return success_response({
        "baby_id": baby_id,
        "baby_name": baby.name,
        **stats
    }, "获取成功")

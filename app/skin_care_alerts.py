from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from .models import (
    Baby, SkinObservationRecord, CareProductArchive, ProductUsageLog,
    SkinCareAlert, ConsumptionRecord, InventoryRecord, HandoverItem, Shift
)
from .skin_risk_scoring import SkinRiskScoringService
from .allergy_attribution import AllergyAttributionService
from .care_recommendation import CareRecommendationService


class SkinCareAlertSystem:
    def __init__(self, db: Session):
        self.db = db
        self.risk_service = SkinRiskScoringService(db)
        self.allergy_service = AllergyAttributionService(db)
        self.recommendation_service = CareRecommendationService(db)

    def evaluate_diaper_rash_risk(self, baby_id: int) -> Dict:
        baby = self.db.query(Baby).filter(Baby.id == baby_id).first()
        if not baby:
            return {"error": "宝宝不存在"}

        risk_assessment = self.risk_service.calculate_rash_risk_score(baby_id, days=14)
        trend_analysis = self.risk_service.analyze_trend(baby_id, days=21)
        risk_factors = self.risk_service.identify_risk_factors(baby_id, days=14)
        allergens = self.allergy_service.identify_suspected_allergens(baby_id, days=30)
        recommendations = self.recommendation_service.generate_care_recommendations(baby_id)

        latest_record = self.db.query(SkinObservationRecord).filter(
            SkinObservationRecord.baby_id == baby_id
        ).order_by(SkinObservationRecord.observation_time.desc()).first()

        hist_consumption = self._get_historical_consumption(baby_id)
        inventory_status = self._get_inventory_status(baby_id)
        shift_info = self._get_recent_shift_info(baby_id)

        self._check_and_create_alerts(baby_id, risk_assessment, risk_factors, allergens)

        return {
            "baby_id": baby_id,
            "baby_name": baby.name,
            "assessment_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "overall_risk": {
                "risk_level": risk_assessment["risk_level"],
                "risk_score": risk_assessment["total_score"],
                "data_points": risk_assessment["data_points"]
            },
            "risk_score_breakdown": risk_assessment["score_breakdown"],
            "risk_factors": risk_factors,
            "trend_analysis": trend_analysis,
            "current_skin_status": self._format_skin_status(latest_record),
            "historical_context": {
                "consumption": hist_consumption,
                "inventory": inventory_status,
                "recent_shifts": shift_info
            },
            "suspected_allergens": allergens,
            "recommendations": recommendations
        }

    def _format_skin_status(self, record: Optional[SkinObservationRecord]) -> Dict:
        if not record:
            return {"status": "no_data", "message": "暂无皮肤观察记录"}

        from .schemas import RASH_GRADE_DESCRIPTIONS
        return {
            "status": "has_data",
            "observation_time": record.observation_time.strftime("%Y-%m-%d %H:%M:%S"),
            "rash_grade": record.rash_grade,
            "rash_grade_description": RASH_GRADE_DESCRIPTIONS.get(record.rash_grade, "未知"),
            "has_redness": record.has_redness,
            "has_breakdown": record.has_breakdown,
            "has_exudate": record.has_exudate,
            "skin_location": record.skin_location,
            "care_actions": record.care_actions,
            "change_frequency_24h": record.change_frequency_24h,
            "nighttime_leaks": record.nighttime_leaks,
            "diaper_brand": record.diaper_brand,
            "diaper_batch": record.diaper_batch
        }

    def _get_historical_consumption(self, baby_id: int, days: int = 14) -> Dict:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        records = self.db.query(ConsumptionRecord).filter(
            ConsumptionRecord.baby_id == baby_id,
            ConsumptionRecord.record_date >= cutoff
        ).order_by(ConsumptionRecord.record_date.desc()).all()

        if not records:
            return {"status": "no_data", "message": "暂无消耗记录"}

        total_changes = sum(r.daily_changes for r in records)
        avg_daily = total_changes / len(records)
        total_leaks = sum(r.nighttime_leaks for r in records)

        return {
            "status": "has_data",
            "period_days": days,
            "record_count": len(records),
            "avg_daily_changes": round(avg_daily, 1),
            "total_nighttime_leaks": total_leaks,
            "avg_nighttime_leaks_per_day": round(total_leaks / len(records), 2),
            "recent_records": [
                {
                    "date": r.record_date,
                    "diaper_size": r.diaper_size,
                    "daily_changes": r.daily_changes,
                    "nighttime_leaks": r.nighttime_leaks
                }
                for r in records[:7]
            ]
        }

    def _get_inventory_status(self, baby_id: int) -> Dict:
        baby = self.db.query(Baby).filter(Baby.id == baby_id).first()
        if not baby:
            return {"status": "no_data"}

        latest = self.db.query(InventoryRecord).filter(
            InventoryRecord.baby_id == baby_id
        ).order_by(InventoryRecord.record_date.desc()).first()

        if not latest:
            return {"status": "no_data", "message": "暂无库存记录"}

        size_match = latest.diaper_size == baby.current_diaper_size

        return {
            "status": "has_data",
            "current_size": baby.current_diaper_size,
            "inventory_size": latest.diaper_size,
            "size_match": size_match,
            "quantity": latest.quantity,
            "unit": latest.unit,
            "record_date": latest.record_date
        }

    def _get_recent_shift_info(self, baby_id: int, days: int = 7) -> Dict:
        cutoff = datetime.now() - timedelta(days=days)
        shifts = self.db.query(Shift).filter(
            Shift.baby_id == baby_id,
            Shift.shift_start >= cutoff
        ).order_by(Shift.shift_start.desc()).all()

        if not shifts:
            return {"status": "no_data", "message": "暂无班次记录"}

        handover_items = self.db.query(HandoverItem).filter(
            HandoverItem.baby_id == baby_id,
            HandoverItem.created_at >= cutoff
        ).all()

        skin_related = [h for h in handover_items if h.content and any(
            kw in h.content for kw in ["疹", "皮肤", "红", "过敏", "破皮", "渗液"]
        )]

        return {
            "status": "has_data",
            "period_days": days,
            "shift_count": len(shifts),
            "caregiver_count": len(set(s.caregiver_id for s in shifts)),
            "total_handover_items": len(handover_items),
            "skin_related_handover_count": len(skin_related),
            "unresolved_skin_issues": sum(1 for h in skin_related if not h.is_resolved),
            "recent_shifts": [
                {
                    "shift_id": s.id,
                    "caregiver_id": s.caregiver_id,
                    "shift_start": s.shift_start.strftime("%Y-%m-%d %H:%M:%S"),
                    "status": s.status
                }
                for s in shifts[:3]
            ]
        }

    def _check_and_create_alerts(
        self,
        baby_id: int,
        risk_assessment: Dict,
        risk_factors: List[Dict],
        allergens: List[Dict]
    ) -> List[SkinCareAlert]:
        alerts = []

        risk_level = risk_assessment["risk_level"]
        risk_score = risk_assessment["total_score"]

        if risk_level in ["critical", "high"]:
            existing = self.db.query(SkinCareAlert).filter(
                SkinCareAlert.baby_id == baby_id,
                SkinCareAlert.alert_type == "high_risk_score",
                SkinCareAlert.resolved == False
            ).first()

            if not existing:
                message = f"尿布疹风险{risk_level}，风险评分{risk_score}分，需要立即关注"
                alert = self._create_alert(
                    baby_id=baby_id,
                    alert_type="high_risk_score",
                    alert_level=risk_level,
                    risk_score=risk_score,
                    message=message
                )
                alerts.append(alert)

        for factor in risk_factors:
            if factor["severity"] in ["critical", "high"]:
                alert_type = f"risk_factor_{factor['type']}"
                existing = self.db.query(SkinCareAlert).filter(
                    SkinCareAlert.baby_id == baby_id,
                    SkinCareAlert.alert_type == alert_type,
                    SkinCareAlert.resolved == False
                ).first()

                if not existing:
                    alert = self._create_alert(
                        baby_id=baby_id,
                        alert_type=alert_type,
                        alert_level=factor["severity"],
                        risk_score=factor["contribution_score"],
                        message=factor["description"]
                    )
                    alerts.append(alert)

        for allergen in allergens[:2]:
            if allergen["correlation_score"] >= 0.7:
                alert_type = f"suspected_allergen_{allergen['product_id']}"
                existing = self.db.query(SkinCareAlert).filter(
                    SkinCareAlert.baby_id == baby_id,
                    SkinCareAlert.alert_type == alert_type,
                    SkinCareAlert.resolved == False
                ).first()

                if not existing:
                    message = f"疑似过敏：{allergen['brand']}{allergen['product_name']}，相关性{round(allergen['correlation_score'] * 100)}%"
                    alert = self._create_alert(
                        baby_id=baby_id,
                        alert_type=alert_type,
                        alert_level="high" if allergen["confidence"] == "high" else "medium",
                        risk_score=allergen["correlation_score"] * 100,
                        message=message,
                        related_product_id=allergen["product_id"]
                    )
                    alerts.append(alert)

        return alerts

    def _create_alert(
        self,
        baby_id: int,
        alert_type: str,
        alert_level: str,
        risk_score: float,
        message: str,
        related_record_id: Optional[int] = None,
        related_product_id: Optional[int] = None
    ) -> SkinCareAlert:
        alert = SkinCareAlert(
            baby_id=baby_id,
            alert_type=alert_type,
            alert_level=alert_level,
            risk_score=risk_score,
            message=message,
            related_record_id=related_record_id,
            related_product_id=related_product_id
        )
        self.db.add(alert)
        self.db.commit()
        self.db.refresh(alert)
        return alert

    def get_high_risk_alerts(self, baby_id: Optional[int] = None,
                             resolved: Optional[bool] = None,
                             severity: Optional[str] = None,
                             days: int = 30) -> List[Dict]:
        cutoff = datetime.now() - timedelta(days=days)
        query = self.db.query(SkinCareAlert).filter(
            SkinCareAlert.triggered_at >= cutoff
        )

        if baby_id:
            query = query.filter(SkinCareAlert.baby_id == baby_id)

        if resolved is not None:
            query = query.filter(SkinCareAlert.resolved == resolved)

        if severity:
            if severity not in ["critical", "high", "medium", "low"]:
                return []
            query = query.filter(SkinCareAlert.alert_level == severity)

        alerts = query.order_by(SkinCareAlert.triggered_at.desc()).all()

        result = []
        for alert in alerts:
            baby = self.db.query(Baby).filter(Baby.id == alert.baby_id).first()
            result.append({
                "id": alert.id,
                "baby_id": alert.baby_id,
                "baby_name": baby.name if baby else None,
                "alert_type": alert.alert_type,
                "alert_level": alert.alert_level,
                "risk_score": alert.risk_score,
                "message": alert.message,
                "related_record_id": alert.related_record_id,
                "related_product_id": alert.related_product_id,
                "triggered_at": alert.triggered_at,
                "resolved": alert.resolved,
                "resolved_at": alert.resolved_at,
                "resolution_notes": alert.resolution_notes
            })

        return result

    def get_alert_statistics(self, baby_id: Optional[int] = None, days: int = 30) -> Dict:
        cutoff = datetime.now() - timedelta(days=days)
        query = self.db.query(SkinCareAlert).filter(
            SkinCareAlert.triggered_at >= cutoff
        )

        if baby_id:
            query = query.filter(SkinCareAlert.baby_id == baby_id)

        alerts = query.all()

        total = len(alerts)
        unresolved = sum(1 for a in alerts if not a.resolved)

        level_distribution = {
            "critical": sum(1 for a in alerts if a.alert_level == "critical"),
            "high": sum(1 for a in alerts if a.alert_level == "high"),
            "medium": sum(1 for a in alerts if a.alert_level == "medium"),
            "low": sum(1 for a in alerts if a.alert_level == "low")
        }

        type_distribution = {}
        for a in alerts:
            type_distribution[a.alert_type] = type_distribution.get(a.alert_type, 0) + 1

        if baby_id:
            risk_assessment = self.risk_service.calculate_rash_risk_score(baby_id)
            current_risk = {
                "level": risk_assessment["risk_level"],
                "score": risk_assessment["total_score"]
            }
        else:
            current_risk = None

        return {
            "period_days": days,
            "baby_id": baby_id,
            "total_alerts": total,
            "unresolved_alerts": unresolved,
            "level_distribution": level_distribution,
            "type_distribution": type_distribution,
            "current_risk": current_risk
        }

    def resolve_alert(self, alert_id: int, resolved: bool = True,
                      resolution_notes: Optional[str] = None) -> Optional[SkinCareAlert]:
        alert = self.db.query(SkinCareAlert).filter(SkinCareAlert.id == alert_id).first()
        if not alert:
            return None

        alert.resolved = resolved
        if resolved:
            alert.resolved_at = datetime.utcnow()
        else:
            alert.resolved_at = None
        if resolution_notes:
            alert.resolution_notes = resolution_notes

        self.db.commit()
        self.db.refresh(alert)
        return alert

    def get_alert_summary(self, days: int = 7) -> Dict:
        cutoff = datetime.now() - timedelta(days=days)

        babies = self.db.query(Baby).all()
        summary = {
            "total_babies": len(babies),
            "critical_risk": [],
            "high_risk": [],
            "medium_risk": [],
            "low_risk": [],
            "unresolved_alerts": []
        }

        for baby in babies:
            risk = self.risk_service.calculate_rash_risk_score(baby.id, days=14)
            risk_level = risk["risk_level"]

            baby_info = {
                "baby_id": baby.id,
                "baby_name": baby.name,
                "risk_score": risk["total_score"],
                "risk_level": risk_level,
                "data_points": risk["data_points"]
            }

            if risk_level == "critical":
                summary["critical_risk"].append(baby_info)
            elif risk_level == "high":
                summary["high_risk"].append(baby_info)
            elif risk_level == "medium":
                summary["medium_risk"].append(baby_info)
            else:
                summary["low_risk"].append(baby_info)

        unresolved = self.get_high_risk_alerts(resolved=False, days=days)
        summary["unresolved_alerts"] = unresolved
        summary["unresolved_count"] = len(unresolved)
        summary["high_risk_count"] = len(summary["critical_risk"]) + len(summary["high_risk"])

        return summary

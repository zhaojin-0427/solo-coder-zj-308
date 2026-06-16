from datetime import datetime, timedelta
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from .models import (
    Baby, OutingPlan, OutingRiskAlert, OutingBagItem,
    ConsumptionRecord, SkinObservationRecord, DiaperSizeReference,
    InventoryRecord, Caregiver
)
from .prediction import DiaperPrediction


class OutingRiskAssessor:
    def __init__(self, db: Session):
        self.db = db
        self.predictor = DiaperPrediction(db)

    def _get_nighttime_leak_trend(self, baby_id: int, days: int = 14) -> Dict:
        records = self.db.query(ConsumptionRecord).filter(
            ConsumptionRecord.baby_id == baby_id,
            ConsumptionRecord.record_date >= (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        ).order_by(ConsumptionRecord.record_date.desc()).all()

        if not records:
            return {
                "trend": "stable",
                "average_leaks": 0,
                "risk_level": "low",
                "risk_score": 10,
                "data_points": 0
            }

        half = len(records) // 2
        recent = records[:half] if half > 0 else records
        older = records[half:] if half > 0 else []

        recent_avg = sum(r.nighttime_leaks for r in recent) / len(recent) if recent else 0
        older_avg = sum(r.nighttime_leaks for r in older) / len(older) if older else 0

        if older_avg > 0:
            change_pct = (recent_avg - older_avg) / older_avg * 100
        else:
            change_pct = 100 if recent_avg > 0 else 0

        if change_pct > 30:
            trend = "increasing"
            risk_level = "high"
            risk_score = 75
        elif change_pct > 10:
            trend = "slightly_increasing"
            risk_level = "medium"
            risk_score = 45
        elif change_pct < -20:
            trend = "decreasing"
            risk_level = "low"
            risk_score = 15
        else:
            trend = "stable"
            risk_level = "low"
            risk_score = 20

        return {
            "trend": trend,
            "average_leaks": round(recent_avg, 2),
            "previous_average": round(older_avg, 2),
            "change_pct": round(change_pct, 1),
            "risk_level": risk_level,
            "risk_score": risk_score,
            "data_points": len(records)
        }

    def _get_skin_risk(self, baby_id: int) -> Dict:
        recent_skin = self.db.query(SkinObservationRecord).filter(
            SkinObservationRecord.baby_id == baby_id
        ).order_by(SkinObservationRecord.observation_time.desc()).first()

        if not recent_skin:
            return {
                "rash_grade": 0,
                "risk_level": "low",
                "risk_score": 10,
                "has_rash": False,
                "has_redness": False,
                "has_breakdown": False,
                "has_exudate": False
            }

        rash_grade = recent_skin.rash_grade

        if rash_grade >= 3:
            risk_level = "critical"
            risk_score = 90
        elif rash_grade >= 2:
            risk_level = "high"
            risk_score = 70
        elif rash_grade >= 1:
            risk_level = "medium"
            risk_score = 45
        else:
            risk_level = "low"
            risk_score = 15

        return {
            "rash_grade": rash_grade,
            "risk_level": risk_level,
            "risk_score": risk_score,
            "has_rash": rash_grade > 0,
            "has_redness": recent_skin.has_redness,
            "has_breakdown": recent_skin.has_breakdown,
            "has_exudate": recent_skin.has_exudate,
            "last_observation": recent_skin.observation_time
        }

    def _calculate_supply_risk(self, outing_plan: OutingPlan, baby: Baby) -> Dict:
        inventory = self.predictor.calculate_inventory_days(baby.id, baby.current_diaper_size)

        duration_hours = outing_plan.estimated_duration_hours
        duration_days = duration_hours / 24

        bag_items = self.db.query(OutingBagItem).filter(
            OutingBagItem.outing_plan_id == outing_plan.id,
            OutingBagItem.item_type == "diaper"
        ).all()

        total_bag_diapers = sum(item.quantity for item in bag_items)

        size_ref = self.db.query(DiaperSizeReference).filter(
            DiaperSizeReference.size == baby.current_diaper_size
        ).first()

        daily_usage = size_ref.average_daily_usage if size_ref else 6
        hourly_usage = daily_usage / 24
        required_diapers = duration_hours * hourly_usage * 1.3

        if total_bag_diapers == 0:
            sufficiency_ratio = 0
        else:
            sufficiency_ratio = total_bag_diapers / required_diapers if required_diapers > 0 else 2

        restock_convenience = outing_plan.restock_convenience
        restock_score = {
            "easy": 10,
            "moderate": 30,
            "difficult": 60,
            "none": 90
        }.get(restock_convenience, 30)

        if sufficiency_ratio < 0.5:
            supply_score = 90
            supply_level = "critical"
        elif sufficiency_ratio < 0.8:
            supply_score = 70
            supply_level = "high"
        elif sufficiency_ratio < 1.0:
            supply_score = 45
            supply_level = "medium"
        else:
            supply_score = 20
            supply_level = "low"

        combined_score = min(100, supply_score * 0.6 + restock_score * 0.4)

        if combined_score >= 75:
            overall_level = "high"
        elif combined_score >= 40:
            overall_level = "medium"
        else:
            overall_level = "low"

        return {
            "supply_risk_score": round(combined_score, 1),
            "supply_risk_level": overall_level,
            "bag_diapers_count": total_bag_diapers,
            "estimated_required": int(required_diapers),
            "sufficiency_ratio": round(sufficiency_ratio, 2),
            "restock_convenience": restock_convenience,
            "restock_risk_score": restock_score,
            "home_inventory_days": inventory.get("available_days", 0),
            "home_inventory_status": inventory.get("status", "unknown")
        }

    def _calculate_weather_risk(self, outing_plan: OutingPlan) -> Dict:
        temp = outing_plan.weather_temperature

        if temp is None:
            return {
                "risk_score": 20,
                "risk_level": "low",
                "factors": ["温度未提供，按中等风险预估"]
            }

        factors = []
        risk_score = 10

        if temp > 30:
            risk_score += 30
            factors.append(f"高温{temp}℃，易出汗，尿布疹风险增加")
        elif temp < 10:
            risk_score += 15
            factors.append(f"低温{temp}℃，更换时需注意保暖")
        else:
            factors.append(f"温度{temp}℃适宜")

        if outing_plan.destination_type == "park" and temp > 25:
            risk_score += 15
            factors.append("户外活动+高温，皮肤风险增加")

        if risk_score >= 50:
            risk_level = "high"
        elif risk_score >= 30:
            risk_level = "medium"
        else:
            risk_level = "low"

        return {
            "risk_score": risk_score,
            "risk_level": risk_level,
            "temperature": temp,
            "factors": factors
        }

    def _calculate_transportation_risk(self, outing_plan: OutingPlan) -> Dict:
        transport = outing_plan.transportation

        risk_map = {
            "walking": {"score": 20, "level": "low", "note": "步行，灵活但距离有限"},
            "car": {"score": 15, "level": "low", "note": "自驾，可携带较多物品"},
            "public_transit": {"score": 45, "level": "medium", "note": "公共交通，空间有限，需精简物品"},
            "taxi": {"score": 25, "level": "low", "note": "出租车，相对便利"},
            "airplane": {"score": 60, "level": "high", "note": "飞机出行，安检和机舱空间限制"},
            "train": {"score": 40, "level": "medium", "note": "火车出行，有洗手间但空间有限"},
            "other": {"score": 30, "level": "medium", "note": "其他交通方式"}
        }

        info = risk_map.get(transport, risk_map["other"])

        if outing_plan.estimated_duration_hours > 8 and transport in ["airplane", "train"]:
            info["score"] += 20
            info["note"] += "，长途出行需额外准备"

        if info["score"] >= 60:
            level = "high"
        elif info["score"] >= 35:
            level = "medium"
        else:
            level = "low"

        return {
            "transportation": transport,
            "risk_score": info["score"],
            "risk_level": level,
            "note": info["note"]
        }

    def _calculate_caregiver_risk(self, outing_plan: OutingPlan, baby_id: int) -> Dict:
        from .models import OutingCaregiverAssignment

        assignments = self.db.query(OutingCaregiverAssignment).filter(
            OutingCaregiverAssignment.outing_plan_id == outing_plan.id
        ).all()

        caregiver_count = len(assignments)
        primary_count = sum(1 for a in assignments if a.is_primary)

        duration_hours = outing_plan.estimated_duration_hours

        if caregiver_count == 0:
            risk_score = 80
            risk_level = "high"
            note = "无同行照护人，需单独照护宝宝"
        elif caregiver_count == 1:
            if duration_hours > 8:
                risk_score = 55
                risk_level = "medium"
                note = "仅1名照护人，长途外出较辛苦"
            else:
                risk_score = 30
                risk_level = "low"
                note = "1名照护人可应对"
        elif primary_count >= 1:
            risk_score = 15
            risk_level = "low"
            note = f"{caregiver_count}名照护人同行，含主要照护人"
        else:
            risk_score = 25
            risk_level = "low"
            note = f"{caregiver_count}名照护人同行"

        active_caregivers = self.db.query(Caregiver).filter(
            Caregiver.baby_id == baby_id,
            Caregiver.is_active == True
        ).all()

        assigned_ids = [a.caregiver_id for a in assignments]
        valid_assignments = [a for a in assignments if a.caregiver_id in [c.id for c in active_caregivers]]

        if len(valid_assignments) != len(assignments):
            risk_score += 15
            note += "；部分照护人归属校验不通过"

        return {
            "caregiver_count": caregiver_count,
            "primary_caregiver_count": primary_count,
            "valid_caregivers": len(valid_assignments),
            "risk_score": risk_score,
            "risk_level": risk_level,
            "note": note
        }

    def calculate_overall_risk(self, outing_plan: OutingPlan, baby: Baby) -> Dict:
        leak_trend = self._get_nighttime_leak_trend(baby.id)
        skin_risk = self._get_skin_risk(baby.id)
        supply_risk = self._calculate_supply_risk(outing_plan, baby)
        weather_risk = self._calculate_weather_risk(outing_plan)
        transport_risk = self._calculate_transportation_risk(outing_plan)
        caregiver_risk = self._calculate_caregiver_risk(outing_plan, baby.id)

        weights = {
            "leak": 0.20,
            "skin": 0.25,
            "supply": 0.25,
            "weather": 0.10,
            "transport": 0.10,
            "caregiver": 0.10
        }

        overall_score = (
            leak_trend["risk_score"] * weights["leak"] +
            skin_risk["risk_score"] * weights["skin"] +
            supply_risk["supply_risk_score"] * weights["supply"] +
            weather_risk["risk_score"] * weights["weather"] +
            transport_risk["risk_score"] * weights["transport"] +
            caregiver_risk["risk_score"] * weights["caregiver"]
        )

        overall_score = round(min(100, max(0, overall_score)), 1)

        if overall_score >= 70:
            overall_level = "high"
        elif overall_score >= 40:
            overall_level = "medium"
        elif overall_score >= 20:
            overall_level = "low"
        else:
            overall_level = "none"

        risk_factors = []
        if leak_trend["risk_score"] >= 50:
            risk_factors.append({
                "type": "leak_trend",
                "level": leak_trend["risk_level"],
                "score": leak_trend["risk_score"],
                "description": f"夜间漏尿趋势{leak_trend['trend']}"
            })
        if skin_risk["risk_score"] >= 40:
            risk_factors.append({
                "type": "skin_condition",
                "level": skin_risk["risk_level"],
                "score": skin_risk["risk_score"],
                "description": f"皮肤红疹等级{skin_risk['rash_grade']}"
            })
        if supply_risk["supply_risk_score"] >= 50:
            risk_factors.append({
                "type": "supply_shortage",
                "level": supply_risk["supply_risk_level"],
                "score": supply_risk["supply_risk_score"],
                "description": "纸尿裤携带量可能不足"
            })
        if weather_risk["risk_score"] >= 40:
            risk_factors.append({
                "type": "weather",
                "level": weather_risk["risk_level"],
                "score": weather_risk["risk_score"],
                "description": "天气条件增加护理难度"
            })
        if transport_risk["risk_score"] >= 40:
            risk_factors.append({
                "type": "transportation",
                "level": transport_risk["risk_level"],
                "score": transport_risk["risk_score"],
                "description": f"{transport_risk['transportation']}出行限制"
            })
        if caregiver_risk["risk_score"] >= 40:
            risk_factors.append({
                "type": "caregiver",
                "level": caregiver_risk["risk_level"],
                "score": caregiver_risk["risk_score"],
                "description": "照护人力可能不足"
            })

        return {
            "overall_risk_score": overall_score,
            "overall_risk_level": overall_level,
            "risk_factors": risk_factors,
            "component_scores": {
                "leak_trend": leak_trend,
                "skin_risk": skin_risk,
                "supply_risk": supply_risk,
                "weather_risk": weather_risk,
                "transport_risk": transport_risk,
                "caregiver_risk": caregiver_risk
            }
        }

    def generate_risk_alerts(self, outing_plan: OutingPlan, baby: Baby) -> List[OutingRiskAlert]:
        existing = self.db.query(OutingRiskAlert).filter(
            OutingRiskAlert.outing_plan_id == outing_plan.id
        ).all()
        for alert in existing:
            self.db.delete(alert)

        risk_assessment = self.calculate_overall_risk(outing_plan, baby)
        alerts = []

        for factor in risk_assessment["risk_factors"]:
            alert = OutingRiskAlert(
                outing_plan_id=outing_plan.id,
                baby_id=baby.id,
                alert_type=factor["type"],
                risk_level=factor["level"],
                risk_score=factor["score"],
                message=factor["description"],
                related_item=factor["type"],
                triggered_at=datetime.utcnow(),
                resolved=False
            )
            self.db.add(alert)
            alerts.append(alert)

        self.db.commit()
        for alert in alerts:
            self.db.refresh(alert)

        return alerts

    def get_risk_alerts(self, outing_plan_id: int, resolved: Optional[bool] = None) -> List[OutingRiskAlert]:
        query = self.db.query(OutingRiskAlert).filter(
            OutingRiskAlert.outing_plan_id == outing_plan_id
        )

        if resolved is not None:
            query = query.filter(OutingRiskAlert.resolved == resolved)

        return query.order_by(OutingRiskAlert.risk_score.desc()).all()

    def resolve_risk_alert(self, alert_id: int, resolved: bool = True, notes: str = None) -> Optional[OutingRiskAlert]:
        alert = self.db.query(OutingRiskAlert).filter(
            OutingRiskAlert.id == alert_id
        ).first()

        if not alert:
            return None

        alert.resolved = resolved
        if resolved:
            alert.resolved_at = datetime.utcnow()
        else:
            alert.resolved_at = None
        alert.resolution_notes = notes

        self.db.commit()
        self.db.refresh(alert)

        return alert

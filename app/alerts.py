from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from sqlalchemy.orm import Session
from .models import Baby, ConsumptionRecord, DiaperSizeReference, AlertRecord, PlanReminder, GrowthPlan


class AlertSystem:
    def __init__(self, db: Session):
        self.db = db

    def _get_size_order(self) -> List[str]:
        return ["NB", "S", "M", "L", "XL", "XXL"]

    def _is_valid_size(self, size: str) -> bool:
        return size and size.upper() in self._get_size_order()

    def _get_next_size(self, current_size: str) -> Optional[str]:
        sizes = self._get_size_order()
        if current_size in sizes:
            idx = sizes.index(current_size)
            if idx < len(sizes) - 1:
                return sizes[idx + 1]
        return None

    def _get_previous_size(self, current_size: str) -> Optional[str]:
        sizes = self._get_size_order()
        if current_size in sizes:
            idx = sizes.index(current_size)
            if idx > 0:
                return sizes[idx - 1]
        return None

    def analyze_weight_for_size(self, baby: Baby) -> Dict:
        if not self._is_valid_size(baby.current_diaper_size):
            return {
                "current_size": baby.current_diaper_size,
                "weight": baby.current_weight_kg,
                "size_fit": "invalid",
                "recommendation": "invalid_size",
                "weight_range": None,
                "error": f"无效的纸尿裤尺码，必须是以下之一: {', '.join(self._get_size_order())}"
            }

        current_size_ref = self.db.query(DiaperSizeReference).filter(
            DiaperSizeReference.size == baby.current_diaper_size
        ).first()

        if not current_size_ref:
            return {
                "current_size": baby.current_diaper_size,
                "weight": baby.current_weight_kg,
                "size_fit": "unknown",
                "recommendation": "no_size_reference",
                "weight_range": None
            }

        weight = baby.current_weight_kg
        min_weight = current_size_ref.min_weight_kg
        max_weight = current_size_ref.max_weight_kg
        mid_weight = (min_weight + max_weight) / 2

        if weight < min_weight:
            fit_status = "too_large"
            weight_ratio = weight / min_weight
        elif weight > max_weight:
            fit_status = "too_small"
            weight_ratio = weight / max_weight
        else:
            fit_status = "good_fit"
            weight_ratio = weight / mid_weight

        recommendation = "stay"
        confidence = 0.5

        if fit_status == "too_small":
            if weight_ratio > 1.15:
                recommendation = "urgent_upgrade"
                confidence = 0.95
            elif weight_ratio > 1.1:
                recommendation = "recommend_upgrade"
                confidence = 0.85
            else:
                recommendation = "consider_upgrade"
                confidence = 0.7
        elif fit_status == "too_large":
            if weight_ratio < 0.8:
                recommendation = "consider_downgrade"
                confidence = 0.7
            else:
                recommendation = "stay_monitor"
                confidence = 0.6

        next_size = self._get_next_size(baby.current_diaper_size)
        prev_size = self._get_previous_size(baby.current_diaper_size)

        next_size_ref = None
        if next_size:
            next_size_ref = self.db.query(DiaperSizeReference).filter(
                DiaperSizeReference.size == next_size
            ).first()

        prev_size_ref = None
        if prev_size:
            prev_size_ref = self.db.query(DiaperSizeReference).filter(
                DiaperSizeReference.size == prev_size
            ).first()

        return {
            "current_size": baby.current_diaper_size,
            "weight": weight,
            "weight_range": f"{min_weight}-{max_weight}kg",
            "mid_weight": mid_weight,
            "weight_ratio_to_mid": round(weight_ratio, 2),
            "fit_status": fit_status,
            "recommendation": recommendation,
            "confidence": confidence,
            "next_size": {
                "size": next_size,
                "weight_range": f"{next_size_ref.min_weight_kg}-{next_size_ref.max_weight_kg}kg" if next_size_ref else None,
                "is_weight_eligible": weight >= next_size_ref.min_weight_kg if next_size_ref else False
            } if next_size else None,
            "previous_size": {
                "size": prev_size,
                "weight_range": f"{prev_size_ref.min_weight_kg}-{prev_size_ref.max_weight_kg}kg" if prev_size_ref else None
            } if prev_size else None
        }

    def analyze_leak_patterns(self, baby_id: int, days: int = 14) -> Dict:
        cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        records = self.db.query(ConsumptionRecord).filter(
            ConsumptionRecord.baby_id == baby_id,
            ConsumptionRecord.record_date >= cutoff_date
        ).order_by(ConsumptionRecord.record_date.desc()).all()

        if not records:
            return {
                "analysis_period_days": days,
                "data_points": 0,
                "total_leaks": 0,
                "leak_days": 0,
                "average_leaks_per_night": 0,
                "leak_rate_per_night_change": 0,
                "leak_frequency": "none",
                "risk_level": "low",
                "trend": "stable",
                "recommendations": [],
                "daily_leak_record": []
            }

        total_records = len(records)
        total_leaks = sum(r.nighttime_leaks for r in records)
        total_nightly_changes = sum(r.nighttime_changes for r in records)

        leak_days = sum(1 for r in records if r.nighttime_leaks > 0)
        avg_leaks_per_night = total_leaks / total_records if total_records > 0 else 0
        leak_rate_per_change = total_leaks / total_nightly_changes if total_nightly_changes > 0 else 0

        if total_leaks == 0:
            leak_frequency = "none"
            risk_level = "low"
        elif leak_days <= 1:
            leak_frequency = "rare"
            risk_level = "low"
        elif leak_days <= 3:
            leak_frequency = "occasional"
            risk_level = "medium"
        elif leak_days <= 7:
            leak_frequency = "frequent"
            risk_level = "high"
        else:
            leak_frequency = "very_frequent"
            risk_level = "critical"

        mid_point = total_records // 2
        if mid_point > 0:
            first_half_leaks = sum(r.nighttime_leaks for r in records[mid_point:])
            second_half_leaks = sum(r.nighttime_leaks for r in records[:mid_point])

            if first_half_leaks > 0:
                trend_ratio = second_half_leaks / first_half_leaks
                if trend_ratio > 1.5:
                    trend = "increasing"
                elif trend_ratio < 0.67:
                    trend = "decreasing"
                else:
                    trend = "stable"
            else:
                trend = "increasing" if second_half_leaks > 0 else "stable"
        else:
            trend = "insufficient_data"

        recommendations = []

        if risk_level in ["high", "critical"]:
            if leak_rate_per_change > 0.3:
                recommendations.append({
                    "type": "size_issue",
                    "priority": "high",
                    "message": "漏尿率较高，可能是尺码偏小或吸收量不足，建议检查尺码是否合适"
                })
            recommendations.append({
                "type": "nighttime_reminder",
                "priority": "high",
                "message": "夜间漏尿频繁，建议在睡前更换新的纸尿裤，或考虑使用夜用款"
            })
        elif risk_level == "medium":
            recommendations.append({
                "type": "monitor",
                "priority": "medium",
                "message": "偶尔出现漏尿，建议继续观察，如频率增加请考虑更换尺码"
            })

        if trend == "increasing":
            recommendations.append({
                "type": "trend_alert",
                "priority": "high",
                "message": "漏尿频率呈上升趋势，建议检查是否需要更换更大尺码"
            })

        return {
            "analysis_period_days": days,
            "data_points": total_records,
            "total_leaks": total_leaks,
            "leak_days": leak_days,
            "average_leaks_per_night": round(avg_leaks_per_night, 2),
            "leak_rate_per_night_change": round(leak_rate_per_change, 2),
            "leak_frequency": leak_frequency,
            "risk_level": risk_level,
            "trend": trend,
            "recommendations": recommendations,
            "daily_leak_record": [
                {
                    "date": r.record_date,
                    "nighttime_changes": r.nighttime_changes,
                    "leaks": r.nighttime_leaks
                }
                for r in records
            ]
        }

    def analyze_size_change_need(self, baby: Baby) -> Dict:
        if not self._is_valid_size(baby.current_diaper_size):
            valid_sizes = ", ".join(self._get_size_order())
            return {
                "baby_id": baby.id,
                "baby_name": baby.name,
                "current_size": baby.current_diaper_size,
                "decision": "invalid_size",
                "urgency": "high",
                "total_score": 0,
                "score_breakdown": {
                    "weight_fit_score": 0,
                    "leak_factor": 0
                },
                "weight_analysis": {
                    "error": f"无效的纸尿裤尺码 '{baby.current_diaper_size}'，必须是以下之一: {valid_sizes}"
                },
                "leak_analysis": self.analyze_leak_patterns(baby.id),
                "recommended_next_size": None,
                "estimated_days_remaining_in_size": 0,
                "suggested_action": {
                    "action": "fix_invalid_size",
                    "message": f"当前尺码 '{baby.current_diaper_size}' 无效，请更新为有效尺码: {valid_sizes}",
                    "timeline": "立即",
                    "valid_sizes": valid_sizes
                }
            }

        weight_analysis = self.analyze_weight_for_size(baby)
        leak_analysis = self.analyze_leak_patterns(baby.id)

        size_orders = self._get_size_order()
        current_idx = size_orders.index(baby.current_diaper_size) if baby.current_diaper_size in size_orders else -1

        change_scores = {
            "urgent_upgrade": 100,
            "recommend_upgrade": 75,
            "consider_upgrade": 50,
            "stay": 0,
            "stay_monitor": 10,
            "consider_downgrade": -50
        }

        base_score = change_scores.get(weight_analysis["recommendation"], 0)
        leak_factor = 0
        if leak_analysis["risk_level"] == "critical":
            leak_factor = 40
        elif leak_analysis["risk_level"] == "high":
            leak_factor = 30
        elif leak_analysis["risk_level"] == "medium":
            leak_factor = 15

        if leak_analysis["trend"] == "increasing":
            leak_factor += 15

        total_score = base_score + leak_factor

        if total_score >= 80:
            decision = "should_upgrade"
            urgency = "urgent"
        elif total_score >= 60:
            decision = "recommend_upgrade"
            urgency = "high"
        elif total_score >= 25:
            decision = "consider_upgrade"
            urgency = "medium"
        elif total_score >= -30:
            decision = "stay"
            urgency = "low"
        else:
            decision = "consider_downgrade"
            urgency = "medium"

        next_size = self._get_next_size(baby.current_diaper_size)
        expected_days_in_size = self._estimate_days_remaining_in_size(baby)

        return {
            "baby_id": baby.id,
            "baby_name": baby.name,
            "current_size": baby.current_diaper_size,
            "decision": decision,
            "urgency": urgency,
            "total_score": total_score,
            "score_breakdown": {
                "weight_fit_score": base_score,
                "leak_factor": leak_factor
            },
            "weight_analysis": weight_analysis,
            "leak_analysis": leak_analysis,
            "recommended_next_size": next_size if decision in ["should_upgrade", "recommend_upgrade", "consider_upgrade"] else None,
            "estimated_days_remaining_in_size": expected_days_in_size,
            "suggested_action": self._generate_size_suggestion(decision, baby, next_size, expected_days_in_size)
        }

    def _estimate_days_remaining_in_size(self, baby: Baby) -> int:
        if not self._is_valid_size(baby.current_diaper_size):
            return 0

        size_ref = self.db.query(DiaperSizeReference).filter(
            DiaperSizeReference.size == baby.current_diaper_size
        ).first()

        if not size_ref:
            return 30

        weight = baby.current_weight_kg
        max_weight = size_ref.max_weight_kg
        weight_gap = max_weight - weight

        if weight_gap <= 0:
            return 0

        age = baby.current_age_months
        if age < 3:
            monthly_gain = 1.0
        elif age < 6:
            monthly_gain = 0.8
        elif age < 12:
            monthly_gain = 0.5
        elif age < 24:
            monthly_gain = 0.3
        else:
            monthly_gain = 0.2

        daily_gain = monthly_gain / 30
        estimated_days = weight_gap / daily_gain if daily_gain > 0 else 999

        return min(int(estimated_days), 180)

    def _generate_size_suggestion(self, decision: str, baby: Baby, next_size: str, days_remaining: int) -> Dict:
        if decision == "should_upgrade":
            return {
                "action": "upgrade_immediately",
                "message": f"强烈建议立即升级到 {next_size} 码，当前尺码已偏小，可能导致漏尿和不适",
                "timeline": "立即",
                "next_size": next_size
            }
        elif decision == "recommend_upgrade":
            return {
                "action": "prepare_upgrade",
                "message": f"建议准备升级到 {next_size} 码，预计还可使用当前尺码约 {days_remaining} 天",
                "timeline": f"约 {days_remaining} 天内",
                "next_size": next_size
            }
        elif decision == "consider_upgrade":
            return {
                "action": "monitor_and_prepare",
                "message": f"可以开始留意 {next_size} 码的促销活动，预计还可使用当前尺码约 {days_remaining} 天",
                "timeline": f"约 {days_remaining} 天内",
                "next_size": next_size
            }
        elif decision == "consider_downgrade":
            prev_size = self._get_previous_size(baby.current_diaper_size)
            return {
                "action": "consider_downgrade",
                "message": f"当前尺码可能偏大，如持续漏尿可考虑使用 {prev_size} 码",
                "timeline": "按需",
                "previous_size": prev_size
            }
        else:
            return {
                "action": "continue_using",
                "message": f"当前尺码合适，预计还可使用约 {days_remaining} 天",
                "timeline": f"约 {days_remaining} 天",
                "next_size": next_size
            }

    def get_nighttime_risk_summary(self, baby_id: int) -> Dict:
        leak_analysis = self.analyze_leak_patterns(baby_id, days=14)
        baby = self.db.query(Baby).filter(Baby.id == baby_id).first()

        if baby and not self._is_valid_size(baby.current_diaper_size):
            valid_sizes = ", ".join(self._get_size_order())
            return {
                "baby_id": baby_id,
                "baby_name": baby.name if baby else "Unknown",
                "error": f"无效的纸尿裤尺码 '{baby.current_diaper_size}'，必须是以下之一: {valid_sizes}",
                "risk_assessment": {
                    "overall_risk": "invalid",
                    "active_alerts": 0,
                    "this_week_leaks": 0,
                    "last_week_leaks": 0,
                    "week_over_week_change_pct": 0,
                    "average_leaks_per_night": 0,
                    "trend": "stable"
                },
                "leak_statistics": {
                    "last_14_days_total": 0,
                    "leak_days": 0,
                    "frequency": "none"
                },
                "suggestions": [f"请先更新为有效的纸尿裤尺码: {valid_sizes}"]
            }

        alert_count = self.db.query(AlertRecord).filter(
            AlertRecord.baby_id == baby_id,
            AlertRecord.alert_type == "nighttime_leak",
            AlertRecord.resolved == False
        ).count()

        last_week_leaks = 0
        this_week_leaks = 0

        today = datetime.now()
        for record in leak_analysis.get("daily_leak_record", []):
            record_date = datetime.strptime(record["date"], "%Y-%m-%d")
            days_diff = (today - record_date).days
            if days_diff < 7:
                this_week_leaks += record["leaks"]
            elif days_diff < 14:
                last_week_leaks += record["leaks"]

        week_over_week_change = 0
        if last_week_leaks > 0:
            week_over_week_change = ((this_week_leaks - last_week_leaks) / last_week_leaks) * 100

        risk_assessment = {
            "overall_risk": leak_analysis["risk_level"],
            "active_alerts": alert_count,
            "this_week_leaks": this_week_leaks,
            "last_week_leaks": last_week_leaks,
            "week_over_week_change_pct": round(week_over_week_change, 1),
            "average_leaks_per_night": leak_analysis["average_leaks_per_night"],
            "trend": leak_analysis["trend"]
        }

        suggestions = []
        if leak_analysis["risk_level"] in ["high", "critical"]:
            suggestions.append("睡前更换新的纸尿裤")
            suggestions.append("考虑使用夜用款或吸收量更大的产品")
            suggestions.append("检查尺码是否合适，可能需要升级")
            suggestions.append("可以考虑夜间增加一次更换")
        elif leak_analysis["risk_level"] == "medium":
            suggestions.append("继续观察漏尿频率变化")
            suggestions.append("确保睡前更换纸尿裤")
        else:
            suggestions.append("继续保持当前护理习惯")

        return {
            "baby_id": baby_id,
            "baby_name": baby.name if baby else "Unknown",
            "risk_assessment": risk_assessment,
            "leak_statistics": {
                "last_14_days_total": leak_analysis["total_leaks"],
                "leak_days": leak_analysis["leak_days"],
                "frequency": leak_analysis["leak_frequency"]
            },
            "suggestions": suggestions
        }

    def create_alert(self, baby_id: int, alert_type: str, alert_level: str,
                     message: str, related_size: str = None) -> AlertRecord:
        alert = AlertRecord(
            baby_id=baby_id,
            alert_type=alert_type,
            alert_level=alert_level,
            message=message,
            related_size=related_size
        )
        self.db.add(alert)
        self.db.commit()
        self.db.refresh(alert)
        return alert

    def check_and_create_alerts(self, baby: Baby) -> List[AlertRecord]:
        alerts = []

        size_analysis = self.analyze_size_change_need(baby)
        if size_analysis["urgency"] in ["urgent", "high"]:
            existing_alert = self.db.query(AlertRecord).filter(
                AlertRecord.baby_id == baby.id,
                AlertRecord.alert_type == "size_change",
                AlertRecord.related_size == size_analysis["recommended_next_size"],
                AlertRecord.resolved == False
            ).first()

            if not existing_alert:
                alert = self.create_alert(
                    baby_id=baby.id,
                    alert_type="size_change",
                    alert_level=size_analysis["urgency"],
                    message=size_analysis["suggested_action"]["message"],
                    related_size=size_analysis["recommended_next_size"]
                )
                alerts.append(alert)

        leak_analysis = self.analyze_leak_patterns(baby.id)
        if leak_analysis["risk_level"] in ["high", "critical"]:
            existing_alert = self.db.query(AlertRecord).filter(
                AlertRecord.baby_id == baby.id,
                AlertRecord.alert_type == "nighttime_leak",
                AlertRecord.resolved == False
            ).first()

            if not existing_alert:
                alert = self.create_alert(
                    baby_id=baby.id,
                    alert_type="nighttime_leak",
                    alert_level=leak_analysis["risk_level"],
                    message=f"夜间漏尿风险{leak_analysis['risk_level']}，近14天漏尿{leak_analysis['total_leaks']}次，{leak_analysis['leak_days']}天出现漏尿",
                    related_size=baby.current_diaper_size
                )
                alerts.append(alert)

        from .prediction import DiaperPrediction
        predictor = DiaperPrediction(self.db)
        inventory = predictor.calculate_inventory_days(baby.id, baby.current_diaper_size)

        if inventory["status"] in ["critical", "low"]:
            existing_alert = self.db.query(AlertRecord).filter(
                AlertRecord.baby_id == baby.id,
                AlertRecord.alert_type == "low_inventory",
                AlertRecord.related_size == baby.current_diaper_size,
                AlertRecord.resolved == False
            ).first()

            if not existing_alert:
                alert = self.create_alert(
                    baby_id=baby.id,
                    alert_type="low_inventory",
                    alert_level="high" if inventory["status"] == "critical" else "medium",
                    message=f"{baby.current_diaper_size}码库存仅够用{inventory['available_days']}天，请及时补货",
                    related_size=baby.current_diaper_size
                )
                alerts.append(alert)

        return alerts

    def get_alert_statistics(self, baby_id: int, days: int = 30) -> Dict:
        cutoff = datetime.now() - timedelta(days=days)

        alerts = self.db.query(AlertRecord).filter(
            AlertRecord.baby_id == baby_id,
            AlertRecord.triggered_at >= cutoff
        ).all()

        total_alerts = len(alerts)
        nighttime_leak_alerts = sum(1 for a in alerts if a.alert_type == "nighttime_leak")
        size_change_alerts = sum(1 for a in alerts if a.alert_type == "size_change")
        inventory_alerts = sum(1 for a in alerts if a.alert_type == "low_inventory")

        unresolved_alerts = sum(1 for a in alerts if not a.resolved)

        return {
            "period_days": days,
            "total_alerts": total_alerts,
            "nighttime_leak_alerts": nighttime_leak_alerts,
            "size_change_alerts": size_change_alerts,
            "inventory_alerts": inventory_alerts,
            "unresolved_alerts": unresolved_alerts,
            "alert_level_distribution": {
                "critical": sum(1 for a in alerts if a.alert_level == "critical"),
                "high": sum(1 for a in alerts if a.alert_level == "high"),
                "medium": sum(1 for a in alerts if a.alert_level == "medium"),
                "low": sum(1 for a in alerts if a.alert_level == "low")
            }
        }


class PlanReminderSystem:
    def __init__(self, db: Session):
        self.db = db
        self.alert_system = AlertSystem(db)

    def _get_size_order(self) -> List[str]:
        return ["NB", "S", "M", "L", "XL", "XXL"]

    def _is_valid_size(self, size: str) -> bool:
        return size and size.upper() in self._get_size_order()

    def _get_growth_plan(self, baby_id: int) -> GrowthPlan:
        from .prediction import GrowthPlanning
        planner = GrowthPlanning(self.db)
        return planner._get_growth_plan(baby_id)

    def generate_plan_reminders(self, baby: Baby, planning_period_days: int = 30) -> List[Dict]:
        if not self._is_valid_size(baby.current_diaper_size):
            return []

        from .prediction import GrowthPlanning
        planner = GrowthPlanning(self.db)

        reminders = []

        overstock_risks = planner.assess_overstock_risk(baby, planning_period_days)
        for risk in overstock_risks:
            if risk["size_status"] == "current" and risk["risk_level"] in ["high", "medium"]:
                from .prediction import DiaperPrediction
                predictor = DiaperPrediction(self.db)
                inv = predictor.calculate_inventory_days(baby.id, risk["size"])
                safety_days = plan.safety_stock_days or 7
                if inv["available_days"] != 999 and inv["available_days"] < safety_days:
                    continue
                reminders.append({
                    "reminder_type": "overstock_warning",
                    "reminder_level": risk["risk_level"],
                    "reason_code": "OVERSTOCK_CURRENT_SIZE",
                    "message": f"当前{risk['size']}码库存过多，预计可用{risk['estimated_stock_duration_days']}天，超过预计使用周期，可能造成浪费",
                    "related_size": risk["size"],
                    "related_metric": risk["overstock_pieces"],
                    "threshold_value": risk["expected_usage_period_days"],
                    "action_suggestion": f"建议减少{risk['size']}码购买量，可考虑赠送或转让多余库存"
                })
            elif risk["size_status"] == "past" and risk["risk_level"] in ["high", "medium"]:
                reminders.append({
                    "reminder_type": "overstock_warning",
                    "reminder_level": risk["risk_level"],
                    "reason_code": "OVERSTOCK_CURRENT_SIZE",
                    "message": f"{risk['size']}码已过使用期，但仍有{risk['current_inventory']}片库存，浪费风险{risk['waste_risk_pct']}%",
                    "related_size": risk["size"],
                    "related_metric": risk["waste_risk_pct"],
                    "threshold_value": 30.0,
                    "action_suggestion": "建议尽快处理闲置库存，可考虑转让或捐赠"
                })

        next_size_readiness_list = planner.calculate_next_size_readiness(baby)
        for readiness in next_size_readiness_list:
            if readiness["readiness_level"] in ["imminent", "preparing"]:
                if readiness["current_inventory"] < readiness["recommended_pre_stock_pieces"] * 0.5:
                    shortage = readiness["recommended_pre_stock_pieces"] - readiness["current_inventory"]
                    level = "high" if readiness["readiness_level"] == "imminent" else "medium"
                    reminders.append({
                        "reminder_type": "understock_warning",
                        "reminder_level": level,
                        "reason_code": "NEXT_SIZE_UNDERSTOCK",
                        "message": f"{readiness['size']}码预计{readiness['estimated_days_to_start']}天后开始使用，但库存不足，建议提前备货",
                        "related_size": readiness["size"],
                        "related_metric": float(readiness["current_inventory"]),
                        "threshold_value": float(readiness["recommended_pre_stock_pieces"]),
                        "action_suggestion": f"建议购买至少{shortage}片{readiness['size']}码作为过渡备货"
                    })

        leak_analysis = self.alert_system.analyze_leak_patterns(baby.id, days=14)
        size_change_info = planner.estimate_size_change_date(baby)

        if leak_analysis["trend"] == "increasing" and leak_analysis["risk_level"] in ["high", "critical"]:
            leak_adjustment = size_change_info.get("leak_adjustment_days", 0)
            if leak_adjustment < 0:
                reminders.append({
                    "reminder_type": "size_transition_alert",
                    "reminder_level": "high" if leak_analysis["risk_level"] == "critical" else "medium",
                    "reason_code": "NIGHTTIME_LEAK_INCREASE",
                    "message": f"夜间漏尿频率上升，可能需要提前换码，预计换码日期提前{abs(leak_adjustment)}天",
                    "related_size": size_change_info.get("next_size"),
                    "related_metric": float(leak_analysis.get("total_leaks", 0)),
                    "threshold_value": 3.0,
                    "action_suggestion": f"建议提前准备{size_change_info.get('next_size')}码，或考虑使用吸收量更大的夜用款"
                })

        plan = self._get_growth_plan(baby.id)
        if plan.promo_stocking_preference == "aggressive":
            for risk in overstock_risks:
                if risk["size_status"] == "current" and risk["risk_level"] == "high":
                    reminders.append({
                        "reminder_type": "promo_stocking_risk",
                        "reminder_level": "high",
                        "reason_code": "PROMO_OVERSTOCK",
                        "message": f"促销囤货量过大，{risk['size']}码库存超过可消耗周期{risk['waste_risk_pct']}%，存在浪费风险",
                        "related_size": risk["size"],
                        "related_metric": risk["waste_risk_pct"],
                        "threshold_value": 30.0,
                        "action_suggestion": "建议调整囤货策略，控制促销购买量在合理使用范围内"
                    })
                    break

        if size_change_info.get("next_size") and size_change_info.get("days_remaining", 999) <= 30:
            level = "high" if size_change_info.get("days_remaining", 999) <= 14 else "medium"
            reminders.append({
                "reminder_type": "size_transition_alert",
                "reminder_level": level,
                "reason_code": "SIZE_TRANSITION_SOON",
                "message": f"预计{size_change_info['days_remaining']}天后换码到{size_change_info['next_size']}码，请做好准备",
                "related_size": size_change_info["next_size"],
                "related_metric": float(size_change_info["days_remaining"]),
                "threshold_value": 30.0,
                "action_suggestion": f"建议开始购买小包装{size_change_info['next_size']}码试用，确认合适后再大量采购"
            })

        from .prediction import DiaperPrediction
        predictor = DiaperPrediction(self.db)
        inventory = predictor.calculate_inventory_days(baby.id, baby.current_diaper_size)
        safety_days = plan.safety_stock_days or 7

        if inventory["available_days"] != 999 and inventory["available_days"] < safety_days:
            reminders.append({
                "reminder_type": "safety_stock_warning",
                "reminder_level": "high" if inventory["available_days"] < 3 else "medium",
                "reason_code": "SAFETY_STOCK_LOW",
                "message": f"{baby.current_diaper_size}码库存仅够用{inventory['available_days']}天，低于安全库存天数{safety_days}天",
                "related_size": baby.current_diaper_size,
                "related_metric": float(inventory["available_days"]),
                "threshold_value": float(safety_days),
                "action_suggestion": "建议尽快补货，确保库存达到安全水平"
            })

        if plan.growth_rate_kg_per_month and plan.growth_rate_kg_per_month > 0:
            default_rate = predictor._get_monthly_growth_rate(baby.current_age_months)
            actual_rate = plan.growth_rate_kg_per_month

            if actual_rate > default_rate * 1.3:
                reminders.append({
                    "reminder_type": "growth_rate_alert",
                    "reminder_level": "medium",
                    "reason_code": "GROWTH_FASTER_THAN_EXPECTED",
                    "message": f"宝宝成长速度快于预期（{actual_rate}kg/月 vs 平均{default_rate}kg/月），可能需要更早换码",
                    "related_size": size_change_info.get("next_size"),
                    "related_metric": round(actual_rate / default_rate * 100, 1),
                    "threshold_value": 130.0,
                    "action_suggestion": "建议增加下一尺码的备货量，提前做好换码准备"
                })
            elif actual_rate < default_rate * 0.7:
                reminders.append({
                    "reminder_type": "growth_rate_alert",
                    "reminder_level": "low",
                    "reason_code": "GROWTH_SLOWER_THAN_EXPECTED",
                    "message": f"宝宝成长速度慢于预期（{actual_rate}kg/月 vs 平均{default_rate}kg/月），当前尺码使用时间可能延长",
                    "related_size": baby.current_diaper_size,
                    "related_metric": round(actual_rate / default_rate * 100, 1),
                    "threshold_value": 70.0,
                    "action_suggestion": "可适当减少囤货量，避免因成长缓慢造成库存积压"
                })

        return reminders

    def create_plan_reminder(self, baby_id: int, reminder_type: str, reminder_level: str,
                             reason_code: str, message: str, related_size: str = None,
                             related_metric: float = None, threshold_value: float = None) -> PlanReminder:
        reminder = PlanReminder(
            baby_id=baby_id,
            reminder_type=reminder_type,
            reminder_level=reminder_level,
            reason_code=reason_code,
            message=message,
            related_size=related_size,
            related_metric=related_metric,
            threshold_value=threshold_value
        )
        self.db.add(reminder)
        self.db.commit()
        self.db.refresh(reminder)
        return reminder

    def check_and_create_plan_reminders(self, baby: Baby, planning_period_days: int = 30) -> List[PlanReminder]:
        reminders = []
        plan_reminders_data = self.generate_plan_reminders(baby, planning_period_days)

        for reminder_data in plan_reminders_data:
            existing = self.db.query(PlanReminder).filter(
                PlanReminder.baby_id == baby.id,
                PlanReminder.reason_code == reminder_data["reason_code"],
                PlanReminder.related_size == reminder_data.get("related_size"),
                PlanReminder.resolved == False
            ).first()

            if not existing:
                reminder = self.create_plan_reminder(
                    baby_id=baby.id,
                    reminder_type=reminder_data["reminder_type"],
                    reminder_level=reminder_data["reminder_level"],
                    reason_code=reminder_data["reason_code"],
                    message=reminder_data["message"],
                    related_size=reminder_data.get("related_size"),
                    related_metric=reminder_data.get("related_metric"),
                    threshold_value=reminder_data.get("threshold_value")
                )
                reminders.append(reminder)

        return reminders

    def get_plan_reminders(self, baby_id: int, resolved: bool = None, days: int = 30) -> List[Dict]:
        cutoff = datetime.now() - timedelta(days=days)
        query = self.db.query(PlanReminder).filter(
            PlanReminder.baby_id == baby_id,
            PlanReminder.triggered_at >= cutoff
        )

        if resolved is not None:
            query = query.filter(PlanReminder.resolved == resolved)

        reminders = query.order_by(PlanReminder.triggered_at.desc()).all()

        return [
            {
                "id": r.id,
                "reminder_type": r.reminder_type,
                "reminder_level": r.reminder_level,
                "reason_code": r.reason_code,
                "message": r.message,
                "related_size": r.related_size,
                "related_metric": r.related_metric,
                "threshold_value": r.threshold_value,
                "triggered_at": r.triggered_at,
                "resolved": r.resolved,
                "resolved_at": r.resolved_at
            }
            for r in reminders
        ]

    def resolve_plan_reminder(self, reminder_id: int, resolved: bool = True) -> Optional[PlanReminder]:
        reminder = self.db.query(PlanReminder).filter(PlanReminder.id == reminder_id).first()
        if not reminder:
            return None

        reminder.resolved = resolved
        if resolved:
            reminder.resolved_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(reminder)
        return reminder

    def get_plan_reminder_statistics(self, baby_id: int, days: int = 30) -> Dict:
        cutoff = datetime.now() - timedelta(days=days)
        reminders = self.db.query(PlanReminder).filter(
            PlanReminder.baby_id == baby_id,
            PlanReminder.triggered_at >= cutoff
        ).all()

        total = len(reminders)
        unresolved = sum(1 for r in reminders if not r.resolved)

        reason_code_counts = {}
        for r in reminders:
            code = r.reason_code
            reason_code_counts[code] = reason_code_counts.get(code, 0) + 1

        level_distribution = {
            "critical": sum(1 for r in reminders if r.reminder_level == "critical"),
            "high": sum(1 for r in reminders if r.reminder_level == "high"),
            "medium": sum(1 for r in reminders if r.reminder_level == "medium"),
            "low": sum(1 for r in reminders if r.reminder_level == "low")
        }

        return {
            "period_days": days,
            "total_reminders": total,
            "unresolved_reminders": unresolved,
            "reason_code_distribution": reason_code_counts,
            "level_distribution": level_distribution
        }

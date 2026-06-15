from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from sqlalchemy.orm import Session
from .models import Baby, ConsumptionRecord, DiaperSizeReference, AlertRecord


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
        estimated_days = weight_gap / daily_gain if daily_gain > 0 else float('inf')

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

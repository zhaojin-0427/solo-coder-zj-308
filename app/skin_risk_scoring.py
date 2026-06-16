from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from .models import (
    Baby, SkinObservationRecord, CareProductArchive, ProductUsageLog,
    ConsumptionRecord, InventoryRecord, Shift, HandoverItem
)


class SkinRiskScoringService:
    def __init__(self, db: Session):
        self.db = db

    def calculate_rash_risk_score(self, baby_id: int, days: int = 14) -> Dict:
        cutoff = datetime.now() - timedelta(days=days)
        records = self.db.query(SkinObservationRecord).filter(
            SkinObservationRecord.baby_id == baby_id,
            SkinObservationRecord.observation_time >= cutoff
        ).order_by(SkinObservationRecord.observation_time.desc()).all()

        if not records:
            return {
                "total_score": 0.0,
                "risk_level": "low",
                "score_breakdown": {},
                "data_points": 0
            }

        total_score = 0.0
        score_breakdown = {}

        avg_rash_grade = sum(r.rash_grade for r in records) / len(records)
        rash_grade_score = avg_rash_grade * 15
        score_breakdown["avg_rash_grade"] = round(avg_rash_grade, 2)
        score_breakdown["rash_grade_score"] = round(rash_grade_score, 2)
        total_score += rash_grade_score

        latest = records[0]
        if latest.rash_grade >= 3:
            severe_score = 25
        elif latest.rash_grade >= 2:
            severe_score = 15
        else:
            severe_score = 0
        score_breakdown["current_severity_score"] = severe_score
        total_score += severe_score

        if latest.has_breakdown:
            breakdown_score = 20
        elif latest.has_exudate:
            breakdown_score = 15
        elif latest.has_redness:
            breakdown_score = 5
        else:
            breakdown_score = 0
        score_breakdown["skin_breakdown_score"] = breakdown_score
        total_score += breakdown_score

        if len(records) >= 2:
            recent_records = records[:min(7, len(records))]
            older_records = records[min(7, len(records)):min(14, len(records))]

            if older_records:
                recent_avg = sum(r.rash_grade for r in recent_records) / len(recent_records)
                older_avg = sum(r.rash_grade for r in older_records) / len(older_records)
                trend_diff = recent_avg - older_avg

                if trend_diff > 0.5:
                    trend_score = 15
                elif trend_diff > 0:
                    trend_score = 5
                elif trend_diff < -0.5:
                    trend_score = -10
                else:
                    trend_score = 0

                score_breakdown["trend_diff"] = round(trend_diff, 2)
                score_breakdown["trend_score"] = trend_score
                total_score += trend_score

        avg_change_freq = sum(r.change_frequency_24h for r in records if r.change_frequency_24h > 0)
        freq_count = sum(1 for r in records if r.change_frequency_24h > 0)
        if freq_count > 0:
            avg_change_freq /= freq_count
            if avg_change_freq < 4:
                freq_score = 15
            elif avg_change_freq < 6:
                freq_score = 5
            else:
                freq_score = 0
            score_breakdown["avg_change_freq"] = round(avg_change_freq, 1)
            score_breakdown["change_freq_score"] = freq_score
            total_score += freq_score

        total_leaks = sum(r.nighttime_leaks for r in records)
        if total_leaks >= 7:
            leak_score = 15
        elif total_leaks >= 3:
            leak_score = 8
        elif total_leaks >= 1:
            leak_score = 3
        else:
            leak_score = 0
        score_breakdown["total_leaks"] = total_leaks
        score_breakdown["leak_score"] = leak_score
        total_score += leak_score

        consumption_cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        consumption_records = self.db.query(ConsumptionRecord).filter(
            ConsumptionRecord.baby_id == baby_id,
            ConsumptionRecord.record_date >= consumption_cutoff
        ).all()

        if consumption_records:
            consumption_leaks = sum(r.nighttime_leaks for r in consumption_records)
            if consumption_leaks >= 5:
                hist_leak_score = 5
            else:
                hist_leak_score = 0
            score_breakdown["historical_leak_score"] = hist_leak_score
            total_score += hist_leak_score

        handover_cutoff = datetime.now() - timedelta(days=days)
        handover_items = self.db.query(HandoverItem).filter(
            HandoverItem.baby_id == baby_id,
            HandoverItem.created_at >= handover_cutoff,
            HandoverItem.item_type == "anomaly",
            HandoverItem.content.like("%疹%") | HandoverItem.content.like("%皮肤%") | HandoverItem.content.like("%红%")
        ).all()

        if handover_items:
            unresolved = sum(1 for h in handover_items if not h.is_resolved)
            if unresolved >= 2:
                handover_score = 10
            elif unresolved >= 1:
                handover_score = 5
            else:
                handover_score = 0
            score_breakdown["unresolved_skin_issues"] = unresolved
            score_breakdown["handover_score"] = handover_score
            total_score += handover_score

        total_score = max(0.0, min(100.0, total_score))

        if total_score >= 70:
            risk_level = "critical"
        elif total_score >= 50:
            risk_level = "high"
        elif total_score >= 25:
            risk_level = "medium"
        else:
            risk_level = "low"

        return {
            "total_score": round(total_score, 2),
            "risk_level": risk_level,
            "score_breakdown": score_breakdown,
            "data_points": len(records)
        }

    def analyze_trend(self, baby_id: int, days: int = 21) -> Dict:
        cutoff = datetime.now() - timedelta(days=days)
        records = self.db.query(SkinObservationRecord).filter(
            SkinObservationRecord.baby_id == baby_id,
            SkinObservationRecord.observation_time >= cutoff
        ).order_by(SkinObservationRecord.observation_time).all()

        if len(records) < 3:
            return {
                "trend": "insufficient_data",
                "slope": 0.0,
                "weekly_averages": [],
                "prediction_next_week": None
            }

        daily_avg = {}
        for r in records:
            date_key = r.observation_time.strftime("%Y-%m-%d")
            if date_key not in daily_avg:
                daily_avg[date_key] = []
            daily_avg[date_key].append(r.rash_grade)

        sorted_dates = sorted(daily_avg.keys())
        daily_values = [(d, sum(grades) / len(grades)) for d, grades in daily_avg.items()]

        weeks = []
        current_week = []
        current_week_start = None

        for d, avg in daily_values:
            dt = datetime.strptime(d, "%Y-%m-%d")
            week_num = dt.isocalendar()[1]
            if current_week_start is None or week_num != current_week_start:
                if current_week:
                    weeks.append({
                        "week_start": current_week[0][0],
                        "week_end": current_week[-1][0],
                        "avg_rash_grade": round(sum(v for _, v in current_week) / len(current_week), 2),
                        "data_points": len(current_week)
                    })
                current_week = [(d, avg)]
                current_week_start = week_num
            else:
                current_week.append((d, avg))

        if current_week:
            weeks.append({
                "week_start": current_week[0][0],
                "week_end": current_week[-1][0],
                "avg_rash_grade": round(sum(v for _, v in current_week) / len(current_week), 2),
                "data_points": len(current_week)
            })

        n = len(daily_values)
        if n >= 2:
            x_mean = sum(range(n)) / n
            y_mean = sum(v for _, v in daily_values) / n
            numerator = sum((i - x_mean) * (v - y_mean) for i, (_, v) in enumerate(daily_values))
            denominator = sum((i - x_mean) ** 2 for i in range(n))
            slope = numerator / denominator if denominator != 0 else 0
        else:
            slope = 0

        if slope > 0.1:
            trend = "worsening"
        elif slope < -0.1:
            trend = "improving"
        else:
            trend = "stable"

        prediction = None
        if len(weeks) >= 2:
            recent_avg = weeks[-1]["avg_rash_grade"]
            prediction = round(recent_avg + slope * 7, 2)
            prediction = max(0.0, min(4.0, prediction))

        return {
            "trend": trend,
            "slope": round(slope, 4),
            "weekly_averages": weeks,
            "prediction_next_week": prediction,
            "daily_data": [{"date": d, "avg_grade": round(v, 2)} for d, v in daily_values]
        }

    def identify_risk_factors(self, baby_id: int, days: int = 14) -> List[Dict]:
        risk_factors = []

        scoring = self.calculate_rash_risk_score(baby_id, days)
        breakdown = scoring["score_breakdown"]

        if breakdown.get("avg_rash_grade", 0) >= 2:
            risk_factors.append({
                "type": "persistent_rash",
                "severity": "high",
                "description": f"持续红疹（平均等级{breakdown['avg_rash_grade']}）",
                "contribution_score": breakdown.get("rash_grade_score", 0)
            })

        if breakdown.get("current_severity_score", 0) >= 15:
            risk_factors.append({
                "type": "severe_current_condition",
                "severity": "high",
                "description": "当前皮肤状况严重",
                "contribution_score": breakdown["current_severity_score"]
            })

        if breakdown.get("skin_breakdown_score", 0) >= 15:
            risk_factors.append({
                "type": "skin_breakdown",
                "severity": "critical",
                "description": "皮肤破损/渗液，存在感染风险",
                "contribution_score": breakdown["skin_breakdown_score"]
            })

        if breakdown.get("trend_score", 0) > 0:
            risk_factors.append({
                "type": "worsening_trend",
                "severity": "high",
                "description": "红疹状况呈恶化趋势",
                "contribution_score": breakdown["trend_score"]
            })

        if breakdown.get("change_freq_score", 0) >= 5:
            risk_factors.append({
                "type": "insufficient_changing",
                "severity": "medium",
                "description": f"更换频率不足（平均{breakdown.get('avg_change_freq', 0)}次/天）",
                "contribution_score": breakdown["change_freq_score"]
            })

        if breakdown.get("leak_score", 0) >= 8:
            risk_factors.append({
                "type": "frequent_leaks",
                "severity": "medium",
                "description": f"夜间漏尿频繁（{breakdown['total_leaks']}次）",
                "contribution_score": breakdown["leak_score"]
            })

        if breakdown.get("unresolved_skin_issues", 0) >= 1:
            risk_factors.append({
                "type": "unresolved_issues",
                "severity": "medium",
                "description": f"存在{breakdown['unresolved_skin_issues']}项未解决的皮肤相关交接事项",
                "contribution_score": breakdown.get("handover_score", 0)
            })

        risk_factors.sort(key=lambda x: x["contribution_score"], reverse=True)
        return risk_factors

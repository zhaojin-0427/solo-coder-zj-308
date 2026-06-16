from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from .models import (
    Baby, SkinObservationRecord, CareProductArchive, ProductUsageLog,
    ConsumptionRecord, InventoryRecord, HandoverItem, Shift
)
from .skin_risk_scoring import SkinRiskScoringService
from .allergy_attribution import AllergyAttributionService


class CareRecommendationService:
    def __init__(self, db: Session):
        self.db = db
        self.risk_service = SkinRiskScoringService(db)
        self.allergy_service = AllergyAttributionService(db)

    def generate_care_recommendations(self, baby_id: int) -> List[Dict]:
        recommendations = []

        baby = self.db.query(Baby).filter(Baby.id == baby_id).first()
        if not baby:
            return [{"type": "error", "priority": "high", "message": "宝宝不存在"}]

        risk_assessment = self.risk_service.calculate_rash_risk_score(baby_id)
        risk_level = risk_assessment["risk_level"]
        risk_score = risk_assessment["total_score"]
        breakdown = risk_assessment["score_breakdown"]

        risk_factors = self.risk_service.identify_risk_factors(baby_id)
        trend_analysis = self.risk_service.analyze_trend(baby_id)
        allergens = self.allergy_service.identify_suspected_allergens(baby_id)

        latest_record = self.db.query(SkinObservationRecord).filter(
            SkinObservationRecord.baby_id == baby_id
        ).order_by(SkinObservationRecord.observation_time.desc()).first()

        if risk_level == "critical":
            recommendations.append({
                "type": "medical_attention",
                "priority": "critical",
                "message": "皮肤状况严重，建议立即就医或咨询儿科医生",
                "details": f"风险评分：{risk_score}，红疹等级：{latest_record.rash_grade if latest_record else '未知'}"
            })

        if latest_record and latest_record.rash_grade >= 3:
            recommendations.append({
                "type": "immediate_care",
                "priority": "critical",
                "message": "建议增加皮肤清洁和护理频率，每次更换纸尿裤时彻底清洁并风干",
                "details": "使用温水轻柔清洁，避免使用刺激性湿巾"
            })

        if latest_record and (latest_record.has_breakdown or latest_record.has_exudate):
            recommendations.append({
                "type": "skin_protection",
                "priority": "high",
                "message": "皮肤有破损/渗液，建议使用含有氧化锌的护臀膏形成保护层",
                "details": "如情况恶化或出现感染迹象（发热、流脓）请立即就医"
            })

        if breakdown.get("avg_change_freq", 0) > 0 and breakdown["avg_change_freq"] < 6:
            freq_rec = {
                "type": "change_frequency",
                "priority": "high",
                "message": f"建议增加更换频率至每天至少6次（当前平均{breakdown['avg_change_freq']}次）",
                "details": ""
            }
            if breakdown["avg_change_freq"] < 4:
                freq_rec["details"] = "更换频率严重不足，尿液和粪便长时间接触皮肤是尿布疹的主要诱因"
            else:
                freq_rec["details"] = "适当增加更换频率，尤其是在排便后立即更换"
            recommendations.append(freq_rec)

        if breakdown.get("leak_score", 0) >= 8:
            recommendations.append({
                "type": "leak_prevention",
                "priority": "high",
                "message": f"夜间漏尿频繁（{breakdown.get('total_leaks', 0)}次），建议检查尺码是否合适",
                "details": "漏尿会导致皮肤长时间处于潮湿环境，加重红疹症状。可考虑使用夜用款或吸收量更大的产品"
            })

        if allergens:
            high_risk = [a for a in allergens if a["correlation_score"] >= 0.7]
            medium_risk = [a for a in allergens if 0.5 <= a["correlation_score"] < 0.7]

            for allergen in high_risk[:2]:
                recommendations.append({
                    "type": "allergen_avoidance",
                    "priority": "high",
                    "message": f"疑似过敏：建议立即停用「{allergen['brand']}{allergen['product_name']}」",
                    "details": f"相关性达{round(allergen['correlation_score'] * 100)}%，证据：{'; '.join(allergen['evidence'][:2])}"
                })

            for allergen in medium_risk[:2]:
                recommendations.append({
                    "type": "allergen_monitoring",
                    "priority": "medium",
                    "message": f"建议观察「{allergen['brand']}{allergen['product_name']}」与皮肤状况的关联",
                    "details": f"相关性{round(allergen['correlation_score'] * 100)}%，{allergen['recommendation']}"
                })

        if trend_analysis["trend"] == "worsening":
            recommendations.append({
                "type": "trend_warning",
                "priority": "high",
                "message": "红疹状况呈恶化趋势，建议及时调整护理方案",
                "details": f"过去一周平均红疹等级上升，如无改善请就医"
            })
        elif trend_analysis["trend"] == "improving":
            recommendations.append({
                "type": "positive_feedback",
                "priority": "low",
                "message": "护理方案有效，皮肤状况正在改善，建议继续保持",
                "details": "继续当前护理措施，直至皮肤完全恢复正常"
            })

        inventory_info = self._check_inventory_suitability(baby_id)
        if inventory_info:
            recommendations.append(inventory_info)

        size_suggestion = self._check_size_suitability(baby)
        if size_suggestion:
            recommendations.append(size_suggestion)

        if latest_record and latest_record.rash_grade >= 1:
            recommendations.append({
                "type": "air_drying",
                "priority": "medium",
                "message": "建议每天安排10-15分钟的空气暴露时间，让皮肤自然风干",
                "details": "可在温暖的室内让宝宝光着屁股，有助于皮肤恢复"
            })

            recommendations.append({
                "type": "product_review",
                "priority": "medium",
                "message": "建议检查当前使用的护理用品成分，避免含有香料、酒精、防腐剂的产品",
                "details": "选择温和、无刺激、pH值平衡的清洁用品"
            })

        if risk_level == "low" and not latest_record or latest_record.rash_grade == 0:
            recommendations.append({
                "type": "preventive_care",
                "priority": "low",
                "message": "皮肤状况良好，建议继续保持良好的护理习惯",
                "details": "定期更换、彻底清洁、适当使用护臀膏预防"
            })

        for factor in risk_factors:
            if factor["type"] == "unresolved_issues":
                recommendations.append({
                    "type": "care_coordination",
                    "priority": "medium",
                    "message": f"存在{factor.get('unresolved_skin_issues', '未解决的')}项皮肤相关交接事项未处理",
                    "details": "建议照护团队及时沟通处理，确保护理的连续性"
                })

        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        recommendations.sort(key=lambda x: priority_order.get(x["priority"], 99))

        return recommendations

    def _check_inventory_suitability(self, baby_id: int) -> Optional[Dict]:
        latest_inventory = self.db.query(InventoryRecord).filter(
            InventoryRecord.baby_id == baby_id
        ).order_by(InventoryRecord.record_date.desc()).first()

        if not latest_inventory:
            return None

        baby = self.db.query(Baby).filter(Baby.id == baby_id).first()
        if not baby:
            return None

        if latest_inventory.diaper_size != baby.current_diaper_size:
            return {
                "type": "inventory_mismatch",
                "priority": "medium",
                "message": f"库存尺码（{latest_inventory.diaper_size}）与当前使用尺码（{baby.current_diaper_size}）不匹配",
                "details": "建议确认当前使用的尺码是否正确，或调整库存"
            }

        return None

    def _check_size_suitability(self, baby: Baby) -> Optional[Dict]:
        from .alerts import AlertSystem
        alert_system = AlertSystem(self.db)
        size_analysis = alert_system.analyze_weight_for_size(baby)

        if size_analysis.get("error"):
            return None

        fit_status = size_analysis.get("fit_status")
        recommendation = size_analysis.get("recommendation")

        if fit_status == "too_small":
            if recommendation == "urgent_upgrade":
                return {
                    "type": "size_upgrade",
                    "priority": "high",
                    "message": f"当前尺码{baby.current_diaper_size}偏小，强烈建议立即升级到{size_analysis['next_size']['size']}码",
                    "details": f"体重{baby.current_weight_kg}kg已超出{baby.current_diaper_size}码适用范围，可能导致漏尿和压痕"
                }
            elif recommendation == "recommend_upgrade":
                return {
                    "type": "size_upgrade",
                    "priority": "medium",
                    "message": f"建议准备升级到{size_analysis['next_size']['size']}码",
                    "details": f"当前体重接近{baby.current_diaper_size}码上限"
                }
        elif fit_status == "too_large":
            return {
                "type": "size_fit",
                "priority": "medium",
                "message": f"当前尺码{baby.current_diaper_size}可能偏大，如持续漏尿可考虑小一码",
                "details": "偏大的尺码可能导致侧漏和缝隙，增加皮肤刺激风险"
            }

        return None

    def review_care_effectiveness(self, baby_id: int, intervention_date: str) -> Dict:
        try:
            intervention_dt = datetime.strptime(intervention_date, "%Y-%m-%d")
        except ValueError:
            return {"error": "日期格式不正确，应为 YYYY-MM-DD"}

        before_cutoff = intervention_dt - timedelta(days=14)
        after_cutoff = intervention_dt + timedelta(days=14)
        now = datetime.now()

        before_records = self.db.query(SkinObservationRecord).filter(
            SkinObservationRecord.baby_id == baby_id,
            SkinObservationRecord.observation_time >= before_cutoff,
            SkinObservationRecord.observation_time < intervention_dt
        ).order_by(SkinObservationRecord.observation_time).all()

        after_records = self.db.query(SkinObservationRecord).filter(
            SkinObservationRecord.baby_id == baby_id,
            SkinObservationRecord.observation_time >= intervention_dt,
            SkinObservationRecord.observation_time <= min(after_cutoff, now)
        ).order_by(SkinObservationRecord.observation_time).all()

        if not before_records or not after_records:
            return {
                "error": "干预前后数据不足，无法进行效果评估",
                "before_count": len(before_records),
                "after_count": len(after_records)
            }

        avg_before = sum(r.rash_grade for r in before_records) / len(before_records)
        avg_after = sum(r.rash_grade for r in after_records) / len(after_records)

        if avg_before > 0:
            improvement_rate = ((avg_before - avg_after) / avg_before) * 100
        else:
            improvement_rate = 100 if avg_after == 0 else 0

        max_before = max(r.rash_grade for r in before_records)
        max_after = max(r.rash_grade for r in after_records)
        min_before = min(r.rash_grade for r in before_records)
        min_after = min(r.rash_grade for r in after_records)

        normal_days_before = sum(1 for r in before_records if r.rash_grade == 0)
        normal_days_after = sum(1 for r in after_records if r.rash_grade == 0)

        action_effectiveness = self._analyze_action_effectiveness(
            baby_id, intervention_dt, before_records, after_records)

        product_effectiveness = self._analyze_product_effectiveness(
            baby_id, intervention_dt, before_records, after_records)

        suggestions = []
        if improvement_rate >= 50:
            suggestions.append("护理干预效果显著，建议继续保持当前方案")
        elif improvement_rate >= 20:
            suggestions.append("护理干预有一定效果，建议继续观察或微调方案")
        elif improvement_rate >= 0:
            suggestions.append("护理干预效果有限，建议考虑调整护理方案")
        else:
            suggestions.append("皮肤状况有所恶化，建议重新评估护理方案并考虑就医")

        if max_after < max_before:
            suggestions.append("红疹严重程度峰值下降，说明控制措施有效")
        if normal_days_after > normal_days_before:
            suggestions.append(f"正常皮肤天数从{normal_days_before}天增加到{normal_days_after}天")

        return {
            "baby_id": baby_id,
            "intervention_date": intervention_date,
            "review_period": {
                "before_days": (intervention_dt - before_cutoff).days,
                "after_days": (min(after_cutoff, now) - intervention_dt).days
            },
            "before_metrics": {
                "average_rash_grade": round(avg_before, 2),
                "max_rash_grade": max_before,
                "min_rash_grade": min_before,
                "normal_skin_days": normal_days_before,
                "record_count": len(before_records)
            },
            "after_metrics": {
                "average_rash_grade": round(avg_after, 2),
                "max_rash_grade": max_after,
                "min_rash_grade": min_after,
                "normal_skin_days": normal_days_after,
                "record_count": len(after_records)
            },
            "improvement_rate": round(improvement_rate, 2),
            "effectiveness_level": "excellent" if improvement_rate >= 50 else "good" if improvement_rate >= 20 else "moderate" if improvement_rate >= 0 else "ineffective",
            "effective_care_actions": action_effectiveness["effective"],
            "ineffective_interventions": action_effectiveness["ineffective"],
            "effective_products": product_effectiveness["effective"],
            "ineffective_products": product_effectiveness["ineffective"],
            "suggestions": suggestions
        }

    def _analyze_action_effectiveness(
        self,
        baby_id: int,
        intervention_dt: datetime,
        before_records: List,
        after_records: List
    ) -> Dict:
        from .schemas import VALID_CARE_ACTIONS

        action_stats_before = {action: {"count": 0, "avg_grade": []} for action in VALID_CARE_ACTIONS}
        action_stats_after = {action: {"count": 0, "avg_grade": []} for action in VALID_CARE_ACTIONS}

        for record in before_records:
            if record.care_actions:
                actions = [a.strip() for a in record.care_actions.split(",")]
                for action in actions:
                    if action in action_stats_before:
                        action_stats_before[action]["count"] += 1
                        action_stats_before[action]["avg_grade"].append(record.rash_grade)

        for record in after_records:
            if record.care_actions:
                actions = [a.strip() for a in record.care_actions.split(",")]
                for action in actions:
                    if action in action_stats_after:
                        action_stats_after[action]["count"] += 1
                        action_stats_after[action]["avg_grade"].append(record.rash_grade)

        effective = []
        ineffective = []

        action_names = {
            "clean": "清洁",
            "air_dry": "风干",
            "apply_cream": "涂抹护臀膏",
            "change_diaper": "更换纸尿裤",
            "other": "其他"
        }

        for action in VALID_CARE_ACTIONS:
            before_stat = action_stats_before[action]
            after_stat = action_stats_after[action]

            if before_stat["count"] > 0 and after_stat["count"] > 0:
                avg_before = sum(before_stat["avg_grade"]) / len(before_stat["avg_grade"])
                avg_after = sum(after_stat["avg_grade"]) / len(after_stat["avg_grade"])
                improvement = avg_before - avg_after

                if improvement > 0.3:
                    effective.append({
                        "action": action,
                        "action_name": action_names.get(action, action),
                        "improvement": round(improvement, 2),
                        "usage_count": after_stat["count"]
                    })
                elif improvement < -0.2:
                    ineffective.append({
                        "action": action,
                        "action_name": action_names.get(action, action),
                        "deterioration": round(-improvement, 2),
                        "usage_count": after_stat["count"]
                    })

        return {"effective": effective, "ineffective": ineffective}

    def _analyze_product_effectiveness(
        self,
        baby_id: int,
        intervention_dt: datetime,
        before_records: List,
        after_records: List
    ) -> Dict:
        products = self.db.query(CareProductArchive).filter(
            CareProductArchive.baby_id == baby_id
        ).all()

        product_ids = [p.id for p in products]

        before_usage = self.db.query(ProductUsageLog).filter(
            ProductUsageLog.baby_id == baby_id,
            ProductUsageLog.product_id.in_(product_ids),
            ProductUsageLog.usage_time < intervention_dt,
            ProductUsageLog.usage_time >= intervention_dt - timedelta(days=14)
        ).all()

        after_usage = self.db.query(ProductUsageLog).filter(
            ProductUsageLog.baby_id == baby_id,
            ProductUsageLog.product_id.in_(product_ids),
            ProductUsageLog.usage_time >= intervention_dt,
            ProductUsageLog.usage_time <= intervention_dt + timedelta(days=14)
        ).all()

        def get_avg_grade_for_product(usage_logs, skin_records):
            product_grades = {}
            for log in usage_logs:
                log_day = log.usage_time.strftime("%Y-%m-%d")
                related_records = [
                    r for r in skin_records
                    if abs((r.observation_time - log.usage_time).total_seconds()) < 86400
                ]
                if related_records:
                    if log.product_id not in product_grades:
                        product_grades[log.product_id] = []
                    product_grades[log.product_id].extend([r.rash_grade for r in related_records])

            result = {}
            for pid, grades in product_grades.items():
                product = next((p for p in products if p.id == pid), None)
                if product and grades:
                    result[pid] = {
                        "product": product,
                        "avg_grade": sum(grades) / len(grades),
                        "usage_count": sum(1 for l in usage_logs if l.product_id == pid)
                    }
            return result

        before_avg = get_avg_grade_for_product(before_usage, before_records)
        after_avg = get_avg_grade_for_product(after_usage, after_records)

        effective = []
        ineffective = []

        for pid in set(before_avg.keys()) & set(after_avg.keys()):
            b = before_avg[pid]
            a = after_avg[pid]
            improvement = b["avg_grade"] - a["avg_grade"]

            product = b["product"]
            if improvement > 0.3:
                effective.append({
                    "product_id": pid,
                    "product_name": product.product_name or product.product_type,
                    "brand": product.brand,
                    "product_type": product.product_type,
                    "improvement": round(improvement, 2),
                    "usage_count": a["usage_count"]
                })
            elif improvement < -0.2:
                ineffective.append({
                    "product_id": pid,
                    "product_name": product.product_name or product.product_type,
                    "brand": product.brand,
                    "product_type": product.product_type,
                    "deterioration": round(-improvement, 2),
                    "usage_count": a["usage_count"]
                })

        return {"effective": effective, "ineffective": ineffective}

    def generate_care_plan(self, baby_id: int) -> Dict:
        baby = self.db.query(Baby).filter(Baby.id == baby_id).first()
        if not baby:
            return {"error": "宝宝不存在"}

        recommendations = self.generate_care_recommendations(baby_id)
        risk_assessment = self.risk_service.calculate_rash_risk_score(baby_id)
        allergens = self.allergy_service.identify_suspected_allergens(baby_id)

        high_priority = [r for r in recommendations if r["priority"] == "critical"]
        medium_priority = [r for r in recommendations if r["priority"] == "high"]
        low_priority = [r for r in recommendations if r["priority"] in ["medium", "low"]]

        daily_routine = []
        daily_routine.append("每次排便后立即更换纸尿裤")
        daily_routine.append("每次更换时用温水轻柔清洁尿布区")
        daily_routine.append("清洁后用柔软毛巾轻轻拍干或自然风干")
        daily_routine.append("根据皮肤状况涂抹适量护臀膏")

        if risk_assessment["risk_level"] in ["high", "critical"]:
            daily_routine.append("每天安排2-3次空气暴露，每次10-15分钟")
            daily_routine.append("增加夜间检查次数，及时更换湿尿裤")

        products_to_avoid = []
        for allergen in allergens[:3]:
            products_to_avoid.append({
                "product": f"{allergen['brand']}{allergen['product_name']}",
                "reason": f"相关性{round(allergen['correlation_score'] * 100)}%"
            })

        return {
            "baby_id": baby_id,
            "baby_name": baby.name,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "risk_summary": {
                "risk_level": risk_assessment["risk_level"],
                "risk_score": risk_assessment["total_score"],
                "data_points": risk_assessment["data_points"]
            },
            "immediate_actions": high_priority + medium_priority,
            "daily_care_routine": daily_routine,
            "products_to_avoid": products_to_avoid,
            "general_suggestions": low_priority,
            "follow_up": {
                "next_assessment": (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d"),
                "reassessment_condition": "如红疹加重或出现发热、渗液增多等情况请立即就医"
            }
        }

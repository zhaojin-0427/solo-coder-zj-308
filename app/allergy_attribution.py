from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from .models import (
    Baby, SkinObservationRecord, CareProductArchive, ProductUsageLog
)


class AllergyAttributionService:
    def __init__(self, db: Session):
        self.db = db

    def identify_suspected_allergens(self, baby_id: int, days: int = 30) -> List[Dict]:
        cutoff = datetime.now() - timedelta(days=days)

        skin_records = self.db.query(SkinObservationRecord).filter(
            SkinObservationRecord.baby_id == baby_id,
            SkinObservationRecord.observation_time >= cutoff
        ).order_by(SkinObservationRecord.observation_time).all()

        if len(skin_records) < 5:
            return []

        products = self.db.query(CareProductArchive).filter(
            CareProductArchive.baby_id == baby_id
        ).all()

        if not products:
            return []

        usage_logs = self.db.query(ProductUsageLog).filter(
            ProductUsageLog.baby_id == baby_id,
            ProductUsageLog.usage_time >= cutoff
        ).order_by(ProductUsageLog.usage_time).all()

        product_timelines = self._build_product_timelines(products, usage_logs)
        rash_timeline = self._build_rash_timeline(skin_records)

        candidates = []

        for product in products:
            product_id = product.id
            timeline = product_timelines.get(product_id, [])

            if len(timeline) < 3:
                continue

            correlation = self._calculate_product_rash_correlation(timeline, rash_timeline)
            temporal_evidence = self._analyze_temporal_pattern(timeline, rash_timeline)
            severity_evidence = self._analyze_severity_correlation(timeline, skin_records, product_id)

            total_score = (
                correlation * 0.4 + temporal_evidence["score"] * 0.3 + severity_evidence["score"] * 0.3)

            if total_score > 0.3:
                evidence = []
                if correlation > 0.5:
                    evidence.append(f"使用与红疹发作相关性达{round(correlation * 100)}%")
                if temporal_evidence.get("rash_after_use_count", 0) > 0:
                    count = temporal_evidence['rash_after_use_count']
                    evidence.append(
                        f"{count}次红疹发生在使用后24小时内")
                if severity_evidence.get("avg_grade_with_product"):
                    diff = severity_evidence['avg_grade_with_product'] - severity_evidence['avg_grade_without_product']
                    evidence.append(f"使用期间平均红疹等级高出{round(diff, 2)}级")

                if correlation >= 0.7:
                    confidence = "high"
                elif correlation >= 0.5:
                    confidence = "medium"
                else:
                    confidence = "low"

                if total_score >= 0.7:
                    recommendation = f"强烈建议停用{product.brand}{product.product_name or product.product_type}，考虑更换品牌或就医排查"
                elif total_score >= 0.5:
                    recommendation = f"建议暂停使用{product.brand}{product.product_name or product.product_type}，观察皮肤状况变化"
                else:
                    recommendation = f"建议继续观察{product.brand}{product.product_name or product.product_type}与皮肤状况的关联"

                candidates.append({
                    "product_id": product.id,
                    "product_name": product.product_name or product.product_type,
                    "product_type": product.product_type,
                    "brand": product.brand,
                    "correlation_score": round(total_score, 4),
                    "confidence": confidence,
                    "evidence": evidence,
                    "recommendation": recommendation,
                    "details": {
                        "correlation": round(correlation, 4),
                        "temporal_score": round(temporal_evidence["score"], 4),
                        "severity_score": round(severity_evidence["score"], 4),
                        "usage_count": len(timeline),
                        "rash_after_use": temporal_evidence.get("rash_after_use_count", 0),
                        "avg_grade_with": round(severity_evidence.get("avg_grade_with_product", 0), 2),
                        "avg_grade_without": round(severity_evidence.get("avg_grade_without_product", 0), 2)
                    }
                })

        candidates.sort(key=lambda x: x["correlation_score"], reverse=True)
        return candidates

    def _build_product_timelines(self, products: List, usage_logs: List) -> Dict[int, List[datetime]]:
        timelines = {}
        for product in products:
            timelines[product.id] = []

        for log in usage_logs:
            if log.product_id in timelines:
                timelines[log.product_id].append(log.usage_time)

        return timelines

    def _build_rash_timeline(self, skin_records: List) -> List[Tuple[datetime, int]]:
        return [(r.observation_time, r.rash_grade) for r in skin_records if r.rash_grade >= 1]

    def _calculate_product_rash_correlation(
        self,
        product_usage: List[datetime],
        rash_events: List[Tuple[datetime, int]]
    ) -> float:
        if not product_usage or not rash_events:
            return 0.0

        rash_after_use = 0
        total_rash_events = len(rash_events)

        for rash_time, _ in rash_events:
            for use_time in product_usage:
                time_diff = (rash_time - use_time).total_seconds() / 3600
                if 0 <= time_diff <= 24:
                    rash_after_use += 1
                    break

        if total_rash_events > 0:
            return rash_after_use / total_rash_events
        return 0.0

    def _analyze_temporal_pattern(
        self,
        product_usage: List[datetime],
        rash_events: List[Tuple[datetime, int]]
    ) -> Dict:
        if not product_usage or not rash_events:
            return {"score": 0.0, "rash_after_use_count": 0}

        rash_after_use_count = 0
        avg_time_to_rash = []

        for rash_time, _ in rash_events:
            min_diff = None
            for use_time in product_usage:
                time_diff = (rash_time - use_time).total_seconds() / 3600
                if 0 <= time_diff <= 48:
                    if min_diff is None or time_diff < min_diff:
                        min_diff = time_diff
            if min_diff is not None:
                rash_after_use_count += 1
                avg_time_to_rash.append(min_diff)

        if rash_after_use_count > 0:
            avg_time = sum(avg_time_to_rash) / len(avg_time_to_rash)
            time_score = max(0, 1 - avg_time / 24)
            frequency_score = min(1.0, rash_after_use_count / len(product_usage))
            score = time_score * 0.5 + frequency_score * 0.5
        else:
            score = 0.0

        return {
            "score": score,
            "rash_after_use_count": rash_after_use_count,
            "avg_hours_to_rash": round(sum(avg_time_to_rash) / len(avg_time_to_rash), 2) if avg_time_to_rash else None
        }

    def _analyze_severity_correlation(
        self,
        product_usage: List[datetime],
        skin_records: List,
        product_id: int
    ) -> Dict:
        usage_set = set()
        for t in product_usage:
            usage_set.add(t.strftime("%Y-%m-%d"))

        usage_days = set()
        for use_time in product_usage:
            for i in range(3):
                day = (use_time + timedelta(days=i)).strftime("%Y-%m-%d")
                usage_days.add(day)

        with_product = [r for r in skin_records if r.observation_time.strftime("%Y-%m-%d") in usage_days]
        without_product = [r for r in skin_records if r.observation_time.strftime("%Y-%m-%d") not in usage_days and r.observation_time.strftime("%Y-%m-%d") not in usage_set]

        if with_product and without_product:
            avg_with = sum(r.rash_grade for r in with_product) / len(with_product)
            avg_without = sum(r.rash_grade for r in without_product) / len(without_product)

            if avg_without > 0:
                ratio = avg_with / avg_without
                score = min(1.0, max(0, (ratio - 1) * 2))
            else:
                score = 1.0 if avg_with > 0 else 0.0
        elif with_product:
            avg_with = sum(r.rash_grade for r in with_product) / len(with_product)
            avg_without = 0
            score = min(1.0, avg_with / 4)
        else:
            avg_with = 0
            avg_without = 0
            score = 0.0

        return {
            "score": score,
            "avg_grade_with_product": avg_with,
            "avg_grade_without_product": avg_without,
            "records_with_product": len(with_product),
            "records_without_product": len(without_product)
        }

    def get_product_usage_history(self, baby_id: int, product_id: int, days: int = 30) -> Dict:
        cutoff = datetime.now() - timedelta(days=days)

        product = self.db.query(CareProductArchive).filter(
            CareProductArchive.id == product_id,
            CareProductArchive.baby_id == baby_id
        ).first()

        if not product:
            return {"error": "产品不存在"}

        usage_logs = self.db.query(ProductUsageLog).filter(
            ProductUsageLog.product_id == product_id,
            ProductUsageLog.usage_time >= cutoff
        ).order_by(ProductUsageLog.usage_time).all()

        skin_records = self.db.query(SkinObservationRecord).filter(
            SkinObservationRecord.baby_id == baby_id,
            SkinObservationRecord.observation_time >= cutoff
        ).order_by(SkinObservationRecord).all()

        usage_dates = set(log.usage_time.strftime("%Y-%m-%d") for log in usage_logs)

        rash_after_usage = []
        for record in skin_records:
            record_date = record.observation_time.strftime("%Y-%m-%d")
            if record_date in usage_dates or (record.observation_time - timedelta(days=1)).strftime("%Y-%m-%d") in usage_dates:
                rash_after_usage.append(record)

        return {
            "product_id": product.id,
            "product_name": product.product_name or product.product_type,
            "brand": product.brand,
            "product_type": product.product_type,
            "usage_count": len(usage_logs),
            "usage_dates": sorted(list(usage_dates)),
            "skin_records_after_usage": [
                {
                    "date": r.observation_time.strftime("%Y-%m-%d"),
                    "rash_grade": r.rash_grade,
                    "has_redness": r.has_redness,
                    "has_breakdown": r.has_breakdown
                }
                for r in rash_after_usage
            ],
            "avg_rash_grade": round(sum(r.rash_grade for r in rash_after_usage) / max(1, len(rash_after_usage)), 2),
            "total_usage_amount": sum(log.usage_amount for log in usage_logs)
        }

    def analyze_brand_sensitivity(self, baby_id: int, days: int = 60) -> List[Dict]:
        cutoff = datetime.now() - timedelta(days=days)

        products = self.db.query(CareProductArchive).filter(
            CareProductArchive.baby_id == baby_id
        ).all()

        if not products:
            return []

        brand_stats = {}
        for product in products:
            key = (product.brand, product.product_type)
            if key not in brand_stats:
                brand_stats[key] = {
                    "brand": product.brand,
                    "product_type": product.product_type,
                    "usage_count": 0,
                    "rash_count": 0,
                    "avg_rash_grade": [],
                    "product_ids": []
                }
            brand_stats[key]["product_ids"].append(product.id)

        usage_logs = self.db.query(ProductUsageLog).filter(
            ProductUsageLog.baby_id == baby_id,
            ProductUsageLog.usage_time >= cutoff
        ).all()

        skin_records = self.db.query(SkinObservationRecord).filter(
            SkinObservationRecord.baby_id == baby_id,
            SkinObservationRecord.observation_time >= cutoff
        ).all()

        for log in usage_logs:
            product = next((p for p in products if p.id == log.product_id), None)
            if product:
                key = (product.brand, product.product_type)
                if key in brand_stats:
                    brand_stats[key]["usage_count"] += 1

        usage_days_by_brand = {}
        for log in usage_logs:
            product = next((p for p in products if p.id == log.product_id), None)
            if product:
                key = (product.brand, product.product_type)
                day = log.usage_time.strftime("%Y-%m-%d")
                if key not in usage_days_by_brand:
                    usage_days_by_brand[key] = set()
                for i in range(2):
                    d = (log.usage_time + timedelta(days=i)).strftime("%Y-%m-%d")
                    usage_days_by_brand[key].add(d)

        for record in skin_records:
            record_day = record.observation_time.strftime("%Y-%m-%d")
            for key, days_set in usage_days_by_brand.items():
                if record_day in days_set and record.rash_grade >= 1:
                    brand_stats[key]["rash_count"] += 1
                    brand_stats[key]["avg_rash_grade"].append(record.rash_grade)

        results = []
        for key, stats in brand_stats.items():
            if stats["usage_count"] > 0:
                rash_rate = stats["rash_count"] / stats["usage_count"] if stats["usage_count"] > 0 else 0
                avg_grade = sum(stats["avg_rash_grade"]) / max(1, len(stats["avg_rash_grade"])) if stats["avg_rash_grade"] else 0

                sensitivity_score = rash_rate * 0.6 + (avg_grade / 4) * 0.4

                results.append({
                    "brand": stats["brand"],
                    "product_type": stats["product_type"],
                    "usage_count": stats["usage_count"],
                    "rash_count": stats["rash_count"],
                    "rash_rate": round(rash_rate, 4),
                    "avg_rash_grade": round(avg_grade, 2),
                    "sensitivity_score": round(sensitivity_score, 4),
                    "risk_level": "high" if sensitivity_score > 0.5 else "medium" if sensitivity_score > 0.3 else "low",
                    "product_ids": stats["product_ids"]
                })

        results.sort(key=lambda x: x["sensitivity_score"], reverse=True)
        return results

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from .models import Baby, ConsumptionRecord, InventoryRecord, DiaperSizeReference, GrowthPlan, PackageSpec


class DiaperPrediction:
    def __init__(self, db: Session):
        self.db = db

    def _get_size_order(self) -> List[str]:
        return ["NB", "S", "M", "L", "XL", "XXL"]

    def _is_valid_size(self, size: str) -> bool:
        return size and size.upper() in self._get_size_order()

    def _get_monthly_growth_rate(self, age_months: int) -> float:
        if age_months < 3:
            return 1.0
        elif age_months < 6:
            return 0.85
        elif age_months < 12:
            return 0.7
        elif age_months < 24:
            return 0.5
        else:
            return 0.3

    def _calculate_age_factor(self, age_months: int) -> float:
        if age_months < 1:
            return 1.4
        elif age_months < 3:
            return 1.3
        elif age_months < 6:
            return 1.2
        elif age_months < 9:
            return 1.1
        elif age_months < 12:
            return 1.0
        elif age_months < 18:
            return 0.95
        elif age_months < 24:
            return 0.9
        else:
            return 0.85

    def _calculate_weight_factor(self, weight_kg: float, size_ref: DiaperSizeReference) -> float:
        mid_weight = (size_ref.min_weight_kg + size_ref.max_weight_kg) / 2
        weight_ratio = weight_kg / mid_weight

        if weight_ratio < 0.8:
            return 0.9
        elif weight_ratio < 0.95:
            return 0.95
        elif weight_ratio < 1.05:
            return 1.0
        elif weight_ratio < 1.15:
            return 1.05
        else:
            return 1.1

    def get_historical_consumption(self, baby_id: int, days: int = 30) -> List[ConsumptionRecord]:
        cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        return self.db.query(ConsumptionRecord).filter(
            ConsumptionRecord.baby_id == baby_id,
            ConsumptionRecord.record_date >= cutoff_date
        ).order_by(ConsumptionRecord.record_date.desc()).all()

    def calculate_average_daily_usage(self, baby_id: int, size: str = None, days: int = 30) -> Dict:
        records = self.get_historical_consumption(baby_id, days)

        if not records:
            size_ref = self.db.query(DiaperSizeReference).filter(
                DiaperSizeReference.size == size
            ).first()
            return {
                "average_daily": size_ref.average_daily_usage if size_ref else 6,
                "nightly_average": 1,
                "data_points": 0,
                "source": "reference"
            }

        if size:
            records = [r for r in records if r.diaper_size == size]

        if not records:
            return {
                "average_daily": 0,
                "nightly_average": 0,
                "data_points": 0,
                "source": "none"
            }

        total_changes = sum(r.daily_changes for r in records)
        total_nightly = sum(r.nighttime_changes for r in records)
        data_points = len(records)

        return {
            "average_daily": round(total_changes / data_points, 1),
            "nightly_average": round(total_nightly / data_points, 1),
            "data_points": data_points,
            "source": "historical"
        }

    def predict_daily_usage(self, baby: Baby, target_days: int = 7) -> List[Dict]:
        if not self._is_valid_size(baby.current_diaper_size):
            return [{
                "error": f"无效的纸尿裤尺码 '{baby.current_diaper_size}'，必须是以下之一: {', '.join(self._get_size_order())}",
                "date": None,
                "day_of_week": None,
                "predicted_usage": 0,
                "confidence": 0
            }]

        predictions = []
        size_ref = self.db.query(DiaperSizeReference).filter(
            DiaperSizeReference.size == baby.current_diaper_size
        ).first()

        historical = self.calculate_average_daily_usage(
            baby.id, baby.current_diaper_size, days=30
        )

        age_factor = self._calculate_age_factor(baby.current_age_months)
        weight_factor = self._calculate_weight_factor(baby.current_weight_kg, size_ref) if size_ref else 1.0

        base_usage = historical["average_daily"] if historical["data_points"] > 0 else (
            size_ref.average_daily_usage if size_ref else 6
        )

        growth_rate = self._get_monthly_growth_rate(baby.current_age_months)

        for day in range(target_days):
            day_factor = 1 + (day * growth_rate * 0.01)
            predicted_usage = base_usage * age_factor * weight_factor * day_factor

            weekend_factor = 1.05 if (datetime.now() + timedelta(days=day)).weekday() >= 5 else 1.0
            predicted_usage *= weekend_factor

            predictions.append({
                "date": (datetime.now() + timedelta(days=day)).strftime("%Y-%m-%d"),
                "day_of_week": (datetime.now() + timedelta(days=day)).strftime("%A"),
                "predicted_usage": round(predicted_usage, 1),
                "confidence": max(0.5, min(0.95, 0.5 + historical["data_points"] * 0.015))
            })

        return predictions

    def calculate_inventory_days(self, baby_id: int, size: str) -> Dict:
        if not self._is_valid_size(size):
            return {
                "current_inventory": 0,
                "daily_usage": 0,
                "available_days": 0,
                "status": "invalid_size",
                "error": f"无效的纸尿裤尺码 '{size}'，必须是以下之一: {', '.join(self._get_size_order())}"
            }

        latest_inventory = self.db.query(InventoryRecord).filter(
            InventoryRecord.baby_id == baby_id,
            InventoryRecord.diaper_size == size
        ).order_by(InventoryRecord.record_date.desc(), InventoryRecord.id.desc()).first()

        if not latest_inventory:
            return {
                "current_inventory": 0,
                "daily_usage": 0,
                "available_days": 0,
                "status": "no_data"
            }

        usage = self.calculate_average_daily_usage(baby_id, size, days=30)
        daily_usage = usage["average_daily"]

        if daily_usage == 0:
            return {
                "current_inventory": latest_inventory.quantity,
                "daily_usage": 0,
                "available_days": float('inf'),
                "status": "unknown"
            }

        available_days = latest_inventory.quantity / daily_usage

        if available_days < 3:
            status = "critical"
        elif available_days < 7:
            status = "low"
        elif available_days < 14:
            status = "moderate"
        else:
            status = "sufficient"

        return {
            "current_inventory": latest_inventory.quantity,
            "daily_usage": daily_usage,
            "available_days": round(available_days, 1),
            "status": status,
            "last_updated": latest_inventory.record_date
        }

    def calculate_size_usage_cycle(self, baby_id: int) -> List[Dict]:
        records = self.get_historical_consumption(baby_id, days=180)

        if not records:
            return []

        size_groups = {}
        for record in records:
            size = record.diaper_size
            if size not in size_groups:
                size_groups[size] = []
            size_groups[size].append(record)

        result = []
        for size, size_records in size_groups.items():
            size_ref = self.db.query(DiaperSizeReference).filter(
                DiaperSizeReference.size == size
            ).first()

            total_usage = sum(r.daily_changes for r in size_records)
            days_used = len(size_records)
            avg_daily = total_usage / days_used if days_used > 0 else 0

            total_pieces_per_pack = 80
            if size_ref:
                if size == "NB":
                    total_pieces_per_pack = 120
                elif size == "S":
                    total_pieces_per_pack = 100
                elif size == "M":
                    total_pieces_per_pack = 80
                elif size == "L":
                    total_pieces_per_pack = 60
                else:
                    total_pieces_per_pack = 50

            packs_used = total_usage / total_pieces_per_pack
            cycle_days = total_pieces_per_pack / avg_daily if avg_daily > 0 else 0

            result.append({
                "size": size,
                "total_days_used": days_used,
                "total_pieces_used": total_usage,
                "average_daily_usage": round(avg_daily, 1),
                "pieces_per_pack": total_pieces_per_pack,
                "packs_used_estimated": round(packs_used, 1),
                "average_cycle_days_per_pack": round(cycle_days, 1),
                "weight_range": f"{size_ref.min_weight_kg}-{size_ref.max_weight_kg}kg" if size_ref else "N/A"
            })

        return sorted(result, key=lambda x: ["NB", "S", "M", "L", "XL", "XXL"].index(x["size"]) if x["size"] in ["NB", "S", "M", "L", "XL", "XXL"] else 99)

    def predict_future_consumption(self, baby: Baby, days: int = 30) -> Dict:
        if not self._is_valid_size(baby.current_diaper_size):
            valid_sizes = ", ".join(self._get_size_order())
            return {
                "baby_id": baby.id,
                "baby_name": baby.name,
                "current_size": baby.current_diaper_size,
                "prediction_period_days": days,
                "error": f"无效的纸尿裤尺码 '{baby.current_diaper_size}'，必须是以下之一: {valid_sizes}",
                "daily_predictions": [],
                "total_predicted_usage": 0,
                "inventory_status": {
                    "error": "无效的纸尿裤尺码，无法进行预测"
                },
                "expected_run_out_date": None,
                "historical_average": None
            }

        daily_predictions = self.predict_daily_usage(baby, days)
        inventory_status = self.calculate_inventory_days(baby.id, baby.current_diaper_size)

        total_predicted = sum(p["predicted_usage"] for p in daily_predictions)

        run_out_date = None
        if inventory_status["available_days"] != float('inf') and inventory_status["available_days"] > 0:
            run_out_date = (datetime.now() + timedelta(days=inventory_status["available_days"])).strftime("%Y-%m-%d")

        return {
            "baby_id": baby.id,
            "baby_name": baby.name,
            "current_size": baby.current_diaper_size,
            "prediction_period_days": days,
            "daily_predictions": daily_predictions,
            "total_predicted_usage": round(total_predicted, 1),
            "inventory_status": inventory_status,
            "expected_run_out_date": run_out_date,
            "historical_average": self.calculate_average_daily_usage(baby.id, baby.current_diaper_size)
        }

    def generate_restocking_list(self, baby: Baby, safety_days: int = 7) -> List[Dict]:
        if not self._is_valid_size(baby.current_diaper_size):
            valid_sizes = ", ".join(self._get_size_order())
            return [{
                "size": baby.current_diaper_size,
                "is_current_size": True,
                "is_next_size": False,
                "current_inventory": 0,
                "daily_usage_rate": 0,
                "available_days": 0,
                "recommended_quantity": 0,
                "packs_needed": 0,
                "priority": "critical",
                "priority_score": 100,
                "inventory_status": "invalid_size",
                "error": f"无效的纸尿裤尺码 '{baby.current_diaper_size}'，必须是以下之一: {valid_sizes}"
            }]

        sizes = ["NB", "S", "M", "L", "XL", "XXL"]
        restocking_items = []

        current_size_idx = sizes.index(baby.current_diaper_size) if baby.current_diaper_size in sizes else 2
        relevant_sizes = sizes[max(0, current_size_idx - 1): min(len(sizes), current_size_idx + 2)]

        for size in relevant_sizes:
            inventory = self.calculate_inventory_days(baby.id, size)
            usage = self.calculate_average_daily_usage(baby.id, size)

            if size == baby.current_diaper_size:
                usage_rate = usage["average_daily"] if usage["average_daily"] > 0 else 6
            elif sizes.index(size) < current_size_idx:
                usage_rate = usage["average_daily"] * 0.3
            else:
                usage_rate = usage["average_daily"] if usage["average_daily"] > 0 else 5

            needed_days = safety_days + 14
            needed_qty = usage_rate * needed_days

            current_qty = inventory["current_inventory"]
            shortage = max(0, needed_qty - current_qty)

            if size == baby.current_diaper_size:
                priority_score = (safety_days - inventory["available_days"]) if inventory["available_days"] != float('inf') else -10
                if inventory["available_days"] < 3:
                    priority = "critical"
                elif inventory["available_days"] < 7:
                    priority = "high"
                elif inventory["available_days"] < 14:
                    priority = "medium"
                else:
                    priority = "low"
            elif sizes.index(size) > current_size_idx:
                priority_score = 5
                priority = "medium" if shortage > 0 else "low"
            else:
                priority_score = -5
                priority = "low" if shortage > 0 else "none"

            if shortage > 0 or priority in ["critical", "high"]:
                restocking_items.append({
                    "size": size,
                    "is_current_size": size == baby.current_diaper_size,
                    "is_next_size": sizes.index(size) > current_size_idx if size in sizes else False,
                    "current_inventory": current_qty,
                    "daily_usage_rate": round(usage_rate, 1),
                    "available_days": inventory["available_days"],
                    "recommended_quantity": round(shortage, 0),
                    "packs_needed": round(shortage / 80, 1),
                    "priority": priority,
                    "priority_score": priority_score,
                    "inventory_status": inventory["status"]
                })

        return sorted(restocking_items, key=lambda x: x["priority_score"], reverse=True)


class GrowthPlanning:
    def __init__(self, db: Session):
        self.db = db
        self.predictor = DiaperPrediction(db)

    def _get_size_order(self) -> List[str]:
        return ["NB", "S", "M", "L", "XL", "XXL"]

    def _is_valid_size(self, size: str) -> bool:
        return size and size.upper() in self._get_size_order()

    def _get_growth_plan(self, baby_id: int) -> GrowthPlan:
        plan = self.db.query(GrowthPlan).filter(GrowthPlan.baby_id == baby_id).first()
        if not plan:
            plan = GrowthPlan(
                baby_id=baby_id,
                promo_stocking_preference="moderate",
                safety_stock_days=7,
                planning_horizon_days=90
            )
        return plan

    def _get_active_package_spec(self, baby_id: int, size: str) -> Optional[PackageSpec]:
        return self.db.query(PackageSpec).filter(
            PackageSpec.baby_id == baby_id,
            PackageSpec.size == size,
            PackageSpec.is_active == True
        ).first()

    def _get_pieces_per_pack(self, baby_id: int, size: str) -> int:
        spec = self._get_active_package_spec(baby_id, size)
        if spec:
            return spec.pieces_per_pack
        default_pieces = {
            "NB": 120, "S": 100, "M": 80, "L": 60, "XL": 50, "XXL": 40
        }
        return default_pieces.get(size, 60)

    def _calculate_growth_rate(self, baby: Baby, plan: GrowthPlan) -> float:
        if plan.growth_rate_kg_per_month is not None and plan.growth_rate_kg_per_month > 0:
            return plan.growth_rate_kg_per_month
        return self.predictor._get_monthly_growth_rate(baby.current_age_months)

    def _estimate_days_to_weight(self, baby: Baby, target_weight_kg: float, plan: GrowthPlan) -> int:
        weight_gap = max(0, target_weight_kg - baby.current_weight_kg)
        if weight_gap <= 0:
            return 0
        monthly_gain = self._calculate_growth_rate(baby, plan)
        if monthly_gain <= 0:
            return 999
        daily_gain = monthly_gain / 30
        days = weight_gap / daily_gain
        return min(int(days), 365)

    def calculate_size_transition_windows(self, baby: Baby, planning_period_days: int = 30) -> List[Dict]:
        if not self._is_valid_size(baby.current_diaper_size):
            return []

        sizes = self._get_size_order()
        current_idx = sizes.index(baby.current_diaper_size)
        plan = self._get_growth_plan(baby.id)
        today = datetime.now()

        windows = []

        start_idx = max(0, current_idx - 1)
        end_idx = min(len(sizes) - 1, current_idx + 2)

        for i in range(start_idx, end_idx + 1):
            size = sizes[i]
            size_ref = self.db.query(DiaperSizeReference).filter(
                DiaperSizeReference.size == size
            ).first()

            if not size_ref:
                continue

            if i < current_idx:
                days_ago_start = self._estimate_days_to_weight(
                    Baby(current_weight_kg=baby.current_weight_kg - 2, current_age_months=baby.current_age_months),
                    size_ref.min_weight_kg, plan
                )
                start_date = (today - timedelta(days=max(30, days_ago_start))).strftime("%Y-%m-%d")
                end_date = (today - timedelta(days=7)).strftime("%Y-%m-%d")
                peak_date = (today - timedelta(days=20)).strftime("%Y-%m-%d")
                confidence = 0.9
                transition_type = "past"
                duration_days = max(1, (datetime.strptime(end_date, "%Y-%m-%d") - datetime.strptime(start_date, "%Y-%m-%d")).days)

            elif i == current_idx:
                days_to_max = self._estimate_days_to_weight(baby, size_ref.max_weight_kg, plan)
                start_date = (today - timedelta(days=7)).strftime("%Y-%m-%d")
                end_date = (today + timedelta(days=days_to_max)).strftime("%Y-%m-%d")
                mid_weight = (size_ref.min_weight_kg + size_ref.max_weight_kg) / 2
                days_to_mid = self._estimate_days_to_weight(baby, mid_weight, plan)
                peak_date = (today + timedelta(days=days_to_mid)).strftime("%Y-%m-%d")
                confidence = 0.85
                transition_type = "current"
                duration_days = days_to_max + 7

            else:
                days_to_min = self._estimate_days_to_weight(baby, size_ref.min_weight_kg, plan)
                days_to_max = self._estimate_days_to_weight(baby, size_ref.max_weight_kg, plan)
                start_date = (today + timedelta(days=days_to_min)).strftime("%Y-%m-%d")
                end_date = (today + timedelta(days=days_to_max)).strftime("%Y-%m-%d")
                mid_weight = (size_ref.min_weight_kg + size_ref.max_weight_kg) / 2
                days_to_mid = self._estimate_days_to_weight(baby, mid_weight, plan)
                peak_date = (today + timedelta(days=days_to_mid)).strftime("%Y-%m-%d")
                confidence = 0.7 if days_to_min > 60 else 0.6
                transition_type = "future"
                duration_days = days_to_max - days_to_min

            if planning_period_days > 0:
                period_end = today + timedelta(days=planning_period_days)
                window_end = datetime.strptime(end_date, "%Y-%m-%d")
                window_start = datetime.strptime(start_date, "%Y-%m-%d")

                if window_start > period_end and transition_type == "future":
                    visible_ratio = 0
                elif window_end < today and transition_type == "past":
                    visible_ratio = 0
                else:
                    overlap_start = max(today, window_start)
                    overlap_end = min(period_end, window_end)
                    overlap_days = max(0, (overlap_end - overlap_start).days)
                    visible_ratio = min(1.0, overlap_days / planning_period_days)

                if visible_ratio <= 0 and transition_type != "current":
                    continue

            windows.append({
                "size": size,
                "start_date": start_date,
                "end_date": end_date,
                "peak_date": peak_date,
                "duration_days": max(1, duration_days),
                "confidence": round(confidence, 2),
                "transition_type": transition_type
            })

        return windows

    def estimate_size_change_date(self, baby: Baby) -> Dict:
        if not self._is_valid_size(baby.current_diaper_size):
            return {
                "current_size": baby.current_diaper_size,
                "next_size": None,
                "estimated_change_date": None,
                "days_remaining": 0,
                "confidence": 0.0,
                "error": "无效的纸尿裤尺码"
            }

        sizes = self._get_size_order()
        current_idx = sizes.index(baby.current_diaper_size)

        if current_idx >= len(sizes) - 1:
            return {
                "current_size": baby.current_diaper_size,
                "next_size": None,
                "estimated_change_date": None,
                "days_remaining": 0,
                "confidence": 1.0,
                "is_largest_size": True
            }

        next_size = sizes[current_idx + 1]
        next_size_ref = self.db.query(DiaperSizeReference).filter(
            DiaperSizeReference.size == next_size
        ).first()

        plan = self._get_growth_plan(baby.id)
        today = datetime.now()

        if next_size_ref:
            days_to_min = self._estimate_days_to_weight(baby, next_size_ref.min_weight_kg, plan)
            change_date = (today + timedelta(days=days_to_min)).strftime("%Y-%m-%d")
            confidence = 0.8 if days_to_min < 30 else (0.6 if days_to_min < 60 else 0.4)
        else:
            days_to_min = 30
            change_date = (today + timedelta(days=days_to_min)).strftime("%Y-%m-%d")
            confidence = 0.5

        from .alerts import AlertSystem
        alert_system = AlertSystem(self.db)
        leak_analysis = alert_system.analyze_leak_patterns(baby.id, days=14)

        leak_adjustment = 0
        if leak_analysis["risk_level"] == "critical":
            leak_adjustment = -7
        elif leak_analysis["risk_level"] == "high":
            leak_adjustment = -3
        elif leak_analysis["trend"] == "increasing":
            leak_adjustment = -2

        adjusted_days = max(0, days_to_min + leak_adjustment)
        adjusted_date = (today + timedelta(days=adjusted_days)).strftime("%Y-%m-%d")

        return {
            "current_size": baby.current_diaper_size,
            "next_size": next_size,
            "estimated_change_date": adjusted_date,
            "original_estimated_date": change_date,
            "days_remaining": adjusted_days,
            "original_days_remaining": days_to_min,
            "confidence": round(confidence, 2),
            "leak_adjustment_days": leak_adjustment,
            "is_largest_size": False
        }

    def calculate_recommended_purchase_by_size(self, baby: Baby, planning_period_days: int = 30) -> List[Dict]:
        if not self._is_valid_size(baby.current_diaper_size):
            return []

        sizes = self._get_size_order()
        current_idx = sizes.index(baby.current_diaper_size)
        plan = self._get_growth_plan(baby.id)
        safety_days = plan.safety_stock_days or 7

        relevant_sizes = sizes[max(0, current_idx - 1): min(len(sizes), current_idx + 2)]
        recommendations = []

        size_change_info = self.estimate_size_change_date(baby)

        for size in relevant_sizes:
            inventory = self.predictor.calculate_inventory_days(baby.id, size)
            usage = self.predictor.calculate_average_daily_usage(baby.id, size)

            is_current = size == baby.current_diaper_size
            is_next = sizes.index(size) > current_idx if size in sizes else False
            is_prev = sizes.index(size) < current_idx if size in sizes else False

            if is_current:
                usage_rate = usage["average_daily"] if usage["average_daily"] > 0 else 6
                days_until_change = size_change_info.get("days_remaining", 30)
                usage_during_period = min(planning_period_days, days_until_change)
                total_needed = usage_rate * (usage_during_period + safety_days)
                current_stock = inventory["current_inventory"]
                shortage = max(0, total_needed - current_stock)

                if shortage <= 0:
                    priority = "none"
                    priority_score = -10
                elif inventory["available_days"] < 3:
                    priority = "critical"
                    priority_score = 100
                elif inventory["available_days"] < 7:
                    priority = "high"
                    priority_score = 75
                elif inventory["available_days"] < safety_days:
                    priority = "medium"
                    priority_score = 50
                else:
                    priority = "low"
                    priority_score = 25

                pieces_per_pack = self._get_pieces_per_pack(baby.id, size)
                estimated_days_coverage = inventory["available_days"] if inventory["available_days"] != float('inf') else 999

                recommendations.append({
                    "size": size,
                    "recommended_pieces": int(round(shortage, 0)),
                    "recommended_packs": round(shortage / pieces_per_pack, 1),
                    "current_inventory": current_stock,
                    "daily_usage_rate": round(usage_rate, 1),
                    "estimated_days_coverage": round(estimated_days_coverage, 1),
                    "purchase_priority": priority,
                    "priority_score": priority_score,
                    "is_current_size": True,
                    "is_next_size": False,
                    "expected_usage_days": usage_during_period
                })

            elif is_next:
                next_size_readiness = self._calculate_next_size_readiness_internal(baby, size)
                usage_rate = usage["average_daily"] if usage["average_daily"] > 0 else 5
                current_stock = inventory["current_inventory"]

                pre_stock_days = max(0, safety_days - 3)
                pre_stock_qty = usage_rate * pre_stock_days
                shortage = max(0, pre_stock_qty - current_stock)

                if next_size_readiness["readiness_level"] == "imminent":
                    priority = "high"
                    priority_score = 80
                elif next_size_readiness["readiness_level"] == "preparing":
                    priority = "medium"
                    priority_score = 50
                elif next_size_readiness["readiness_level"] == "monitoring":
                    priority = "low"
                    priority_score = 20
                else:
                    priority = "none"
                    priority_score = 0
                    shortage = 0

                pieces_per_pack = self._get_pieces_per_pack(baby.id, size)
                days_coverage = current_stock / usage_rate if usage_rate > 0 else float('inf')

                recommendations.append({
                    "size": size,
                    "recommended_pieces": int(round(shortage, 0)),
                    "recommended_packs": round(shortage / pieces_per_pack, 1) if shortage > 0 else 0,
                    "current_inventory": current_stock,
                    "daily_usage_rate": round(usage_rate, 1),
                    "estimated_days_coverage": round(days_coverage, 1) if days_coverage != float('inf') else 999,
                    "purchase_priority": priority,
                    "priority_score": priority_score,
                    "is_current_size": False,
                    "is_next_size": True,
                    "days_to_start": next_size_readiness["estimated_days_to_start"]
                })

            elif is_prev:
                usage_rate = usage["average_daily"] * 0.1 if usage["average_daily"] > 0 else 0.5
                current_stock = inventory["current_inventory"]
                pieces_per_pack = self._get_pieces_per_pack(baby.id, size)
                days_coverage = current_stock / usage_rate if usage_rate > 0 else float('inf')

                recommendations.append({
                    "size": size,
                    "recommended_pieces": 0,
                    "recommended_packs": 0,
                    "current_inventory": current_stock,
                    "daily_usage_rate": round(usage_rate, 1),
                    "estimated_days_coverage": round(days_coverage, 1) if days_coverage != float('inf') else 999,
                    "purchase_priority": "none",
                    "priority_score": -20,
                    "is_current_size": False,
                    "is_next_size": False,
                    "note": "已过尺码，不建议购买"
                })

        return sorted(recommendations, key=lambda x: x["priority_score"], reverse=True)

    def _calculate_next_size_readiness_internal(self, baby: Baby, size: str) -> Dict:
        sizes = self._get_size_order()
        if size not in sizes:
            return {
                "size": size,
                "readiness_score": 0,
                "readiness_level": "unknown",
                "estimated_days_to_start": 999,
                "estimated_start_date": None,
                "current_inventory": 0,
                "recommended_pre_stock_pieces": 0,
                "weight_progress_pct": 0
            }

        size_ref = self.db.query(DiaperSizeReference).filter(
            DiaperSizeReference.size == size
        ).first()

        plan = self._get_growth_plan(baby.id)
        today = datetime.now()

        if not size_ref:
            return {
                "size": size,
                "readiness_score": 30,
                "readiness_level": "monitoring",
                "estimated_days_to_start": 60,
                "estimated_start_date": (today + timedelta(days=60)).strftime("%Y-%m-%d"),
                "current_inventory": 0,
                "recommended_pre_stock_pieces": 0,
                "weight_progress_pct": 0
            }

        current_weight = baby.current_weight_kg
        min_weight = size_ref.min_weight_kg
        weight_gap = min_weight - current_weight

        current_size_ref = self.db.query(DiaperSizeReference).filter(
            DiaperSizeReference.size == baby.current_diaper_size
        ).first()

        prev_size_max = current_size_ref.max_weight_kg if current_size_ref else (min_weight - 2)
        weight_range = min_weight - prev_size_max
        weight_progress_pct = max(0, min(100, ((current_weight - prev_size_max) / weight_range * 100))) if weight_range > 0 else 50

        days_to_start = self._estimate_days_to_weight(baby, min_weight, plan)
        start_date = (today + timedelta(days=days_to_start)).strftime("%Y-%m-%d")

        if days_to_start <= 7:
            readiness_level = "imminent"
            readiness_score = 90
        elif days_to_start <= 14:
            readiness_level = "preparing"
            readiness_score = 70
        elif days_to_start <= 30:
            readiness_level = "monitoring"
            readiness_score = 40
        else:
            readiness_level = "distant"
            readiness_score = 15

        inventory = self.predictor.calculate_inventory_days(baby.id, size)
        current_inventory = inventory["current_inventory"]

        usage = self.predictor.calculate_average_daily_usage(baby.id, size)
        usage_rate = usage["average_daily"] if usage["average_daily"] > 0 else 5
        pre_stock_days = plan.safety_stock_days or 7
        recommended_pre_stock = int(usage_rate * pre_stock_days)

        return {
            "size": size,
            "readiness_score": readiness_score,
            "readiness_level": readiness_level,
            "estimated_days_to_start": days_to_start,
            "estimated_start_date": start_date,
            "current_inventory": current_inventory,
            "recommended_pre_stock_pieces": recommended_pre_stock,
            "weight_progress_pct": round(weight_progress_pct, 1)
        }

    def calculate_next_size_readiness(self, baby: Baby) -> List[Dict]:
        if not self._is_valid_size(baby.current_diaper_size):
            return []

        sizes = self._get_size_order()
        current_idx = sizes.index(baby.current_diaper_size)
        next_sizes = sizes[current_idx + 1: min(len(sizes), current_idx + 3)]

        readiness_list = []
        for size in next_sizes:
            readiness = self._calculate_next_size_readiness_internal(baby, size)
            readiness_list.append(readiness)

        return readiness_list

    def assess_overstock_risk(self, baby: Baby, planning_period_days: int = 30) -> List[Dict]:
        if not self._is_valid_size(baby.current_diaper_size):
            return []

        sizes = self._get_size_order()
        current_idx = sizes.index(baby.current_diaper_size)
        plan = self._get_growth_plan(baby.id)

        risk_items = []
        size_change_info = self.estimate_size_change_date(baby)

        for i in range(max(0, current_idx - 1), min(len(sizes), current_idx + 2)):
            size = sizes[i]
            inventory = self.predictor.calculate_inventory_days(baby.id, size)
            usage = self.predictor.calculate_average_daily_usage(baby.id, size)

            current_stock = inventory["current_inventory"]
            if current_stock <= 0:
                continue

            is_current = i == current_idx
            is_next = i > current_idx
            is_prev = i < current_idx

            if is_current:
                usage_rate = usage["average_daily"] if usage["average_daily"] > 0 else 6
                days_until_change = size_change_info.get("days_remaining", 90)
                expected_usage_days = min(planning_period_days, days_until_change)
                expected_usage = usage_rate * expected_usage_days
            elif is_next:
                usage_rate = usage["average_daily"] if usage["average_daily"] > 0 else 5
                days_to_start = self._estimate_days_to_weight(baby,
                    self.db.query(DiaperSizeReference).filter(DiaperSizeReference.size == size).first().min_weight_kg
                    if self.db.query(DiaperSizeReference).filter(DiaperSizeReference.size == size).first() else 5,
                    plan
                )
                days_used_in_period = max(0, planning_period_days - days_to_start)
                expected_usage_days = days_used_in_period
                expected_usage = usage_rate * days_used_in_period
            else:
                usage_rate = usage["average_daily"] * 0.1 if usage["average_daily"] > 0 else 0.5
                expected_usage_days = 7
                expected_usage = usage_rate * expected_usage_days

            stock_duration_days = current_stock / usage_rate if usage_rate > 0 else float('inf')
            overstock_pieces = max(0, current_stock - expected_usage)
            pieces_per_pack = self._get_pieces_per_pack(baby.id, size)
            overstock_packs = round(overstock_pieces / pieces_per_pack, 1) if overstock_pieces > 0 else 0

            waste_risk_pct = (overstock_pieces / current_stock * 100) if current_stock > 0 else 0

            if is_prev:
                if overstock_pieces > 10:
                    risk_level = "high"
                elif overstock_pieces > 0:
                    risk_level = "medium"
                else:
                    risk_level = "low"
            elif is_current:
                days_until_change = size_change_info.get("days_remaining", 30)
                if stock_duration_days != float('inf') and stock_duration_days > days_until_change * 1.5:
                    risk_level = "high"
                elif stock_duration_days != float('inf') and stock_duration_days > days_until_change:
                    risk_level = "medium"
                elif overstock_pieces > 0:
                    risk_level = "low"
                else:
                    risk_level = "none"
            else:
                if stock_duration_days != float('inf') and stock_duration_days > planning_period_days * 2:
                    risk_level = "high"
                elif stock_duration_days != float('inf') and stock_duration_days > planning_period_days:
                    risk_level = "medium"
                elif overstock_pieces > 0:
                    risk_level = "low"
                else:
                    risk_level = "none"

            if overstock_pieces > 0 or risk_level in ["low", "medium", "high"]:
                risk_items.append({
                    "size": size,
                    "current_inventory": current_stock,
                    "daily_usage_rate": round(usage_rate, 1),
                    "estimated_stock_duration_days": round(stock_duration_days, 1) if stock_duration_days != float('inf') else 999,
                    "expected_usage_period_days": round(expected_usage_days, 1),
                    "overstock_pieces": int(overstock_pieces),
                    "overstock_packs": overstock_packs,
                    "risk_level": risk_level,
                    "waste_risk_pct": round(waste_risk_pct, 1),
                    "size_status": "past" if is_prev else ("current" if is_current else "future")
                })

        return sorted(risk_items, key=lambda x: x["waste_risk_pct"], reverse=True)

    def calculate_purchase_priority(self, baby: Baby, planning_period_days: int = 30) -> List[Dict]:
        recommendations = self.calculate_recommended_purchase_by_size(baby, planning_period_days)
        overstock_risks = self.assess_overstock_risk(baby, planning_period_days)
        next_readiness = self.calculate_next_size_readiness(baby)

        priority_list = []
        for rec in recommendations:
            size = rec["size"]

            overstock_risk = next((r for r in overstock_risks if r["size"] == size), None)
            readiness = next((r for r in next_readiness if r["size"] == size), None)

            base_score = rec["priority_score"]

            overstock_penalty = 0
            if overstock_risk and overstock_risk["risk_level"] == "high":
                overstock_penalty = -30
            elif overstock_risk and overstock_risk["risk_level"] == "medium":
                overstock_penalty = -15

            readiness_bonus = 0
            if readiness and readiness["readiness_level"] == "imminent":
                readiness_bonus = 15
            elif readiness and readiness["readiness_level"] == "preparing":
                readiness_bonus = 5

            final_score = max(0, min(100, base_score + overstock_penalty + readiness_bonus))

            if final_score >= 80:
                priority = "critical"
            elif final_score >= 60:
                priority = "high"
            elif final_score >= 30:
                priority = "medium"
            elif final_score > 0:
                priority = "low"
            else:
                priority = "none"

            priority_list.append({
                "size": size,
                "purchase_priority": priority,
                "priority_score": round(final_score, 1),
                "base_score": base_score,
                "overstock_penalty": overstock_penalty,
                "readiness_bonus": readiness_bonus,
                "recommended_pieces": rec["recommended_pieces"],
                "recommended_packs": rec["recommended_packs"],
                "is_current_size": rec["is_current_size"],
                "is_next_size": rec["is_next_size"]
            })

        return sorted(priority_list, key=lambda x: x["priority_score"], reverse=True)

    def get_comprehensive_planning(self, baby: Baby, planning_period_days: int = 30) -> Dict:
        plan = self._get_growth_plan(baby.id)

        size_transition_windows = self.calculate_size_transition_windows(baby, planning_period_days)
        recommended_purchase = self.calculate_recommended_purchase_by_size(baby, planning_period_days)
        overstock_risks = self.assess_overstock_risk(baby, planning_period_days)
        next_size_readiness = self.calculate_next_size_readiness(baby)
        size_change_info = self.estimate_size_change_date(baby)
        purchase_priorities = self.calculate_purchase_priority(baby, planning_period_days)

        return {
            "baby_id": baby.id,
            "baby_name": baby.name,
            "planning_period_days": planning_period_days,
            "current_size": baby.current_diaper_size,
            "current_weight_kg": baby.current_weight_kg,
            "current_age_months": baby.current_age_months,
            "growth_plan": {
                "target_weight_kg": plan.target_weight_kg,
                "target_date": plan.target_date,
                "growth_rate_kg_per_month": plan.growth_rate_kg_per_month,
                "promo_stocking_preference": plan.promo_stocking_preference,
                "safety_stock_days": plan.safety_stock_days
            },
            "size_transition_windows": size_transition_windows,
            "recommended_purchase_by_size": recommended_purchase,
            "overstock_risk_items": overstock_risks,
            "next_size_readiness": next_size_readiness,
            "estimated_size_change_date": size_change_info,
            "purchase_priority": purchase_priorities
        }

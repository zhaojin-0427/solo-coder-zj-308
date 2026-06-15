from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from .models import Baby, ConsumptionRecord, InventoryRecord, DiaperSizeReference


class DiaperPrediction:
    def __init__(self, db: Session):
        self.db = db

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
        latest_inventory = self.db.query(InventoryRecord).filter(
            InventoryRecord.baby_id == baby_id,
            InventoryRecord.diaper_size == size
        ).order_by(InventoryRecord.record_date.desc()).first()

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

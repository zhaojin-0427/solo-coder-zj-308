from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from .models import (
    Baby, OutingPlan, OutingBagItem, OutingChangeSchedule,
    ConsumptionRecord, InventoryRecord, SkinObservationRecord,
    DiaperSizeReference, Caregiver
)
from .prediction import DiaperPrediction


class OutingPackingCalculator:
    def __init__(self, db: Session):
        self.db = db
        self.predictor = DiaperPrediction(db)

    def _get_size_order(self) -> List[str]:
        return ["NB", "S", "M", "L", "XL", "XXL"]

    def _calculate_base_diaper_count(self, baby: Baby, duration_hours: float, leak_pref: str) -> Dict:
        size_ref = self.db.query(DiaperSizeReference).filter(
            DiaperSizeReference.size == baby.current_diaper_size
        ).first()

        historical = self.predictor.calculate_average_daily_usage(
            baby.id, baby.current_diaper_size, days=14
        )

        base_daily = historical["average_daily"] if historical["data_points"] > 0 else (
            size_ref.average_daily_usage if size_ref else 6
        )

        hourly_rate = base_daily / 24
        base_count = max(1, int(duration_hours * hourly_rate))

        leak_multipliers = {"minimal": 1.0, "moderate": 1.3, "maximum": 1.6}
        leak_multiplier = leak_multipliers.get(leak_pref, 1.3)

        safety_margin = 1.2
        total_count = int(base_count * leak_multiplier * safety_margin)

        return {
            "base_count": base_count,
            "leak_adjusted": int(base_count * leak_multiplier),
            "safety_count": total_count,
            "hourly_rate": round(hourly_rate, 2),
            "source": historical["source"]
        }

    def _get_next_size_info(self, baby: Baby) -> Dict:
        sizes = self._get_size_order()
        current_idx = sizes.index(baby.current_diaper_size) if baby.current_diaper_size in sizes else 2

        if current_idx >= len(sizes) - 1:
            return {"has_next_size": False, "next_size": None, "suggested_count": 0}

        next_size = sizes[current_idx + 1]
        next_size_ref = self.db.query(DiaperSizeReference).filter(
            DiaperSizeReference.size == next_size
        ).first()

        weight_progress = 0
        current_size_ref = self.db.query(DiaperSizeReference).filter(
            DiaperSizeReference.size == baby.current_diaper_size
        ).first()

        if current_size_ref and next_size_ref:
            weight_range = next_size_ref.min_weight_kg - current_size_ref.max_weight_kg
            weight_gap = baby.current_weight_kg - current_size_ref.max_weight_kg
            if weight_range > 0:
                weight_progress = max(0, min(1, weight_gap / weight_range))

        if weight_progress > 0.7:
            suggested = 3
        elif weight_progress > 0.4:
            suggested = 2
        elif weight_progress > 0.1:
            suggested = 1
        else:
            suggested = 0

        return {
            "has_next_size": True,
            "next_size": next_size,
            "suggested_count": suggested,
            "weight_progress": round(weight_progress, 2)
        }

    def _calculate_skin_care_items(self, baby: Baby, duration_hours: float, skin_pref: str) -> List[Dict]:
        items = []

        recent_skin = self.db.query(SkinObservationRecord).filter(
            SkinObservationRecord.baby_id == baby.id
        ).order_by(SkinObservationRecord.observation_time.desc()).first()

        rash_grade = recent_skin.rash_grade if recent_skin else 0
        has_risk = rash_grade >= 1

        items.append({
            "item_type": "wipe",
            "item_name": "婴儿湿纸巾",
            "quantity": max(10, int(duration_hours * 1.5)),
            "unit": "pieces",
            "priority": "high",
            "is_essential": True,
            "notes": "每次更换使用"
        })

        if has_risk or skin_pref in ["moderate", "high"]:
            items.append({
                "item_type": "rash_cream",
                "item_name": "护臀膏",
                "quantity": 1,
                "unit": "tube",
                "priority": "high" if has_risk else "normal",
                "is_essential": has_risk,
                "notes": "红疹护理，每次更换涂抹" if has_risk else "备用防护"
            })

        items.append({
            "item_type": "change_pad",
            "item_name": "隔尿垫",
            "quantity": max(2, int(duration_hours / 4)),
            "unit": "pieces",
            "priority": "normal",
            "is_essential": True,
            "notes": "外出更换尿布使用"
        })

        if duration_hours > 4:
            items.append({
                "item_type": "extra_clothes",
                "item_name": "备用衣物",
                "quantity": 1 if duration_hours <= 8 else 2,
                "unit": "set",
                "priority": "normal",
                "is_essential": False,
                "notes": "漏尿或弄脏时更换"
            })

        return items

    def _calculate_change_schedule(self, baby: Baby, outing_plan: OutingPlan) -> List[Dict]:
        schedules = []
        departure = outing_plan.departure_time
        return_time = outing_plan.return_time
        duration_hours = outing_plan.estimated_duration_hours

        historical = self.predictor.calculate_average_daily_usage(
            baby.id, baby.current_diaper_size, days=14
        )
        size_ref = self.db.query(DiaperSizeReference).filter(
            DiaperSizeReference.size == baby.current_diaper_size
        ).first()

        base_daily = historical["average_daily"] if historical["data_points"] > 0 else (
            size_ref.average_daily_usage if size_ref else 6
        )
        hourly_rate = base_daily / 24

        interval_hours = max(1.5, 24 / base_daily * 0.9)

        current_time = departure
        change_count = 0

        while current_time < return_time:
            if current_time > departure:
                is_nighttime = 22 <= current_time.hour or current_time.hour < 6

                if is_nighttime:
                    change_type = "nighttime"
                    location = "夜间更换"
                else:
                    change_type = "regular"
                    location = ""

                schedules.append({
                    "scheduled_time": current_time,
                    "location_hint": location,
                    "change_type": change_type,
                    "diaper_size": baby.current_diaper_size,
                    "is_nighttime": is_nighttime,
                    "notes": f"第{change_count}次更换"
                })

            current_time += timedelta(hours=interval_hours)
            change_count += 1

        if outing_plan.restock_convenience == "difficult":
            midpoint = departure + (return_time - departure) / 2
            schedules.append({
                "scheduled_time": midpoint,
                "location_hint": "预防更换",
                "change_type": "preventive",
                "diaper_size": baby.current_diaper_size,
                "is_nighttime": False,
                "notes": "补货困难，增加预防性更换"
            })

        schedules.sort(key=lambda x: x["scheduled_time"])

        for i, s in enumerate(schedules):
            s["notes"] = f"第{i + 1}次更换"

        return schedules

    def _assess_restock_risk(self, outing_plan: OutingPlan, packing_list: List[Dict]) -> Dict:
        total_diapers = sum(
            item["quantity"] for item in packing_list
            if item["item_type"] == "diaper"
        )

        duration_hours = outing_plan.estimated_duration_hours
        hourly_usage = total_diapers / duration_hours if duration_hours > 0 else 0

        restock_factor = {
            "easy": 1.0,
            "moderate": 0.6,
            "difficult": 0.2,
            "none": 0.0
        }.get(outing_plan.restock_convenience, 0.6)

        buffer_hours = total_diapers * restock_factor / hourly_usage if hourly_usage > 0 else 0

        if outing_plan.restock_convenience == "none" and total_diapers < duration_hours / 2:
            risk_level = "critical"
            risk_score = 90
        elif buffer_hours < 2:
            risk_level = "high"
            risk_score = 70
        elif buffer_hours < 4:
            risk_level = "medium"
            risk_score = 40
        else:
            risk_level = "low"
            risk_score = 15

        return {
            "restock_convenience": outing_plan.restock_convenience,
            "buffer_hours": round(buffer_hours, 1),
            "total_diapers": total_diapers,
            "hourly_usage_rate": round(hourly_usage, 2),
            "risk_level": risk_level,
            "risk_score": risk_score
        }

    def generate_packing_list(self, outing_plan: OutingPlan, baby: Baby) -> List[Dict]:
        packing_items = []

        diaper_calc = self._calculate_base_diaper_count(
            baby, outing_plan.estimated_duration_hours, outing_plan.leak_risk_preference
        )

        packing_items.append({
            "item_type": "diaper",
            "item_name": f"{baby.current_diaper_size}码纸尿裤",
            "diaper_size": baby.current_diaper_size,
            "quantity": diaper_calc["safety_count"],
            "unit": "pieces",
            "priority": "high",
            "is_essential": True,
            "notes": f"基础{diaper_calc['base_count']}片，含漏尿和安全余量"
        })

        next_size_info = self._get_next_size_info(baby)
        if next_size_info["has_next_size"] and next_size_info["suggested_count"] > 0:
            packing_items.append({
                "item_type": "diaper",
                "item_name": f"{next_size_info['next_size']}码纸尿裤(备用)",
                "diaper_size": next_size_info["next_size"],
                "quantity": next_size_info["suggested_count"],
                "unit": "pieces",
                "priority": "normal",
                "is_essential": False,
                "notes": f"备用尺码，体重进度{next_size_info['weight_progress']*100:.0f}%"
            })

        skin_care_items = self._calculate_skin_care_items(
            baby, outing_plan.estimated_duration_hours, outing_plan.skin_risk_preference
        )
        packing_items.extend(skin_care_items)

        if outing_plan.carry_capacity_limit > 0:
            total_diapers = sum(i["quantity"] for i in packing_items if i["item_type"] == "diaper")
            if total_diapers > outing_plan.carry_capacity_limit:
                non_essential = [i for i in packing_items if not i["is_essential"]]
                for item in non_essential:
                    if item["item_type"] == "diaper":
                        packing_items.remove(item)

        return packing_items

    def save_packing_list(self, outing_plan_id: int, packing_items: List[Dict]) -> List[OutingBagItem]:
        existing = self.db.query(OutingBagItem).filter(
            OutingBagItem.outing_plan_id == outing_plan_id
        ).all()
        for item in existing:
            self.db.delete(item)

        saved_items = []
        for item_data in packing_items:
            db_item = OutingBagItem(
                outing_plan_id=outing_plan_id,
                item_type=item_data["item_type"],
                item_name=item_data["item_name"],
                diaper_size=item_data.get("diaper_size"),
                quantity=item_data["quantity"],
                unit=item_data.get("unit", "pieces"),
                priority=item_data.get("priority", "normal"),
                is_essential=item_data.get("is_essential", True),
                notes=item_data.get("notes")
            )
            self.db.add(db_item)
            saved_items.append(db_item)

        self.db.commit()
        for item in saved_items:
            self.db.refresh(item)

        return saved_items

    def save_change_schedule(self, outing_plan_id: int, schedules: List[Dict]) -> List[OutingChangeSchedule]:
        existing = self.db.query(OutingChangeSchedule).filter(
            OutingChangeSchedule.outing_plan_id == outing_plan_id
        ).all()
        for s in existing:
            self.db.delete(s)

        saved_schedules = []
        for sched_data in schedules:
            db_sched = OutingChangeSchedule(
                outing_plan_id=outing_plan_id,
                scheduled_time=sched_data["scheduled_time"],
                location_hint=sched_data.get("location_hint"),
                change_type=sched_data.get("change_type", "regular"),
                diaper_size=sched_data.get("diaper_size"),
                is_nighttime=sched_data.get("is_nighttime", False),
                notes=sched_data.get("notes")
            )
            self.db.add(db_sched)
            saved_schedules.append(db_sched)

        self.db.commit()
        for sched in saved_schedules:
            self.db.refresh(sched)

        return saved_schedules

    def generate_full_packing_plan(self, outing_plan: OutingPlan, baby: Baby) -> Dict:
        packing_items = self.generate_packing_list(outing_plan, baby)
        change_schedules = self._calculate_change_schedule(baby, outing_plan)
        restock_risk = self._assess_restock_risk(outing_plan, packing_items)
        next_size_info = self._get_next_size_info(baby)

        self.save_packing_list(outing_plan.id, packing_items)
        self.save_change_schedule(outing_plan.id, change_schedules)

        diaper_items = [i for i in packing_items if i["item_type"] == "diaper"]
        total_diapers = sum(i["quantity"] for i in diaper_items)

        size_breakdown = {}
        for item in diaper_items:
            size = item.get("diaper_size", "unknown")
            size_breakdown[size] = size_breakdown.get(size, 0) + item["quantity"]

        capacity_sufficient = True
        capacity_usage_pct = 0.0
        if outing_plan.carry_capacity_limit > 0:
            capacity_usage_pct = round(total_diapers / outing_plan.carry_capacity_limit * 100, 1)
            capacity_sufficient = total_diapers <= outing_plan.carry_capacity_limit

        weight_estimate = total_diapers * 0.03 + len([i for i in packing_items if i["item_type"] != "diaper"]) * 0.1

        daytime_changes = sum(1 for s in change_schedules if not s["is_nighttime"])
        nighttime_changes = sum(1 for s in change_schedules if s["is_nighttime"])

        essential_items = [i for i in packing_items if i["is_essential"]]
        optional_items = [i for i in packing_items if not i["is_essential"]]

        return {
            "outing_plan_id": outing_plan.id,
            "baby_id": baby.id,
            "total_items_count": len(packing_items),
            "total_diapers_count": total_diapers,
            "essential_items": essential_items,
            "optional_items": optional_items,
            "size_breakdown": size_breakdown,
            "weight_estimate_kg": round(weight_estimate, 2),
            "carry_capacity_sufficient": capacity_sufficient,
            "capacity_limit": outing_plan.carry_capacity_limit,
            "capacity_usage_pct": capacity_usage_pct,
            "change_schedule": {
                "total_changes": len(change_schedules),
                "daytime_changes": daytime_changes,
                "nighttime_changes": nighttime_changes,
                "schedules": change_schedules
            },
            "restock_risk": restock_risk,
            "next_size_suggestion": next_size_info
        }

    def calculate_inventory_writeback(self, outing_plan: OutingPlan, baby: Baby, actual_items: List[Dict]) -> List[Dict]:
        suggestions = []
        current_inventory = {}

        inventory_records = self.db.query(InventoryRecord).filter(
            InventoryRecord.baby_id == baby.id
        ).order_by(InventoryRecord.record_date.desc()).all()

        for record in inventory_records:
            if record.diaper_size not in current_inventory:
                current_inventory[record.diaper_size] = record.quantity

        for actual_item in actual_items:
            if actual_item["item_type"] == "diaper":
                size = actual_item.get("diaper_size", baby.current_diaper_size)
                actual_qty = actual_item.get("actual_quantity", 0)
                planned_qty = actual_item.get("planned_quantity", 0)
                variance = actual_qty - planned_qty

                current_qty = current_inventory.get(size, 0)
                new_qty = max(0, current_qty - actual_qty)

                suggestions.append({
                    "item_type": "diaper",
                    "diaper_size": size,
                    "current_inventory": current_qty,
                    "actual_consumption": actual_qty,
                    "planned_consumption": planned_qty,
                    "variance": variance,
                    "variance_pct": round(variance / planned_qty * 100, 1) if planned_qty > 0 else 0,
                    "estimated_remaining": new_qty,
                    "action": "reduce_inventory",
                    "suggestion": f"建议将{size}码库存从{current_qty}更新为{new_qty}片"
                })

        non_diaper_items = [i for i in actual_items if i["item_type"] != "diaper"]
        for item in non_diaper_items:
            suggestions.append({
                "item_type": item["item_type"],
                "item_name": item["item_name"],
                "actual_consumption": item.get("actual_quantity", 0),
                "planned_consumption": item.get("planned_quantity", 0),
                "action": "note_consumption",
                "suggestion": f"{item['item_name']}实际使用{item.get('actual_quantity', 0)}{item.get('unit', '个')}"
            })

        return suggestions

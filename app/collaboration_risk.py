import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from .models import (
    Baby, Caregiver, Shift, HandoverItem, TodoTask,
    ConsumptionRecord, InventoryRecord, AlertRecord, PlanReminder
)


class CollaborationRiskDetector:
    def __init__(self, db: Session):
        self.db = db

    def _parse_datetime(self, v: str) -> Optional[datetime]:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M"):
            try:
                return datetime.strptime(v, fmt)
            except (ValueError, TypeError):
                continue
        return None

    def _get_shifts_in_range(self, baby_id: int, start: datetime, end: datetime) -> List[Shift]:
        return self.db.query(Shift).filter(
            Shift.baby_id == baby_id,
            Shift.shift_start >= start,
            Shift.shift_start <= end
        ).order_by(Shift.shift_start).all()

    def _get_unresolved_reminders(self, baby_id: int) -> List[PlanReminder]:
        return self.db.query(PlanReminder).filter(
            PlanReminder.baby_id == baby_id,
            PlanReminder.resolved == False
        ).all()

    def detect_inventory_sync_risk(self, baby_id: int, shifts: List[Shift]) -> List[Dict]:
        risks = []
        for i in range(1, len(shifts)):
            prev_shift = shifts[i - 1]
            curr_shift = shifts[i]
            if prev_shift.inventory_snapshot and curr_shift.inventory_snapshot:
                try:
                    prev_inv = json.loads(prev_shift.inventory_snapshot)
                    curr_inv = json.loads(curr_shift.inventory_snapshot)
                except (json.JSONDecodeError, TypeError):
                    continue

                for size, prev_qty in prev_inv.items():
                    curr_qty = curr_inv.get(size)
                    if curr_qty is not None and prev_qty is not None:
                        records = self.db.query(ConsumptionRecord).filter(
                            ConsumptionRecord.baby_id == baby_id,
                            ConsumptionRecord.diaper_size == size
                        ).order_by(ConsumptionRecord.record_date.desc()).limit(7).all()

                        avg_daily = (
                            sum(r.daily_changes for r in records) / len(records)
                            if records else 0
                        )

                        shift_duration_hours = 0
                        if prev_shift.shift_end:
                            shift_duration_hours = max(
                                0,
                                (prev_shift.shift_end - prev_shift.shift_start).total_seconds() / 3600
                            )

                        expected_consumption = int(avg_daily * shift_duration_hours / 24)
                        expected_remaining = prev_qty - expected_consumption
                        diff = abs(curr_qty - expected_remaining)

                        if diff > max(3, expected_consumption * 2):
                            risks.append({
                                "risk_type": "inventory_not_synced",
                                "severity": "high" if diff > 10 else "medium",
                                "shift_id": curr_shift.id,
                                "caregiver_id": curr_shift.caregiver_id,
                                "size": size,
                                "previous_shift_quantity": prev_qty,
                                "current_shift_quantity": curr_qty,
                                "expected_remaining": expected_remaining,
                                "discrepancy": diff,
                                "message": f"尺码{size}库存未同步: 上一班{prev_qty}片，当前班{curr_qty}片，预计应剩余{expected_remaining}片，差异{diff}片"
                            })
        return risks

    def detect_continuous_leak_risk(self, baby_id: int, shifts: List[Shift]) -> List[Dict]:
        risks = []
        if not shifts:
            return risks

        earliest = min(s.shift_start for s in shifts)
        cutoff = earliest - timedelta(days=3)

        records = self.db.query(ConsumptionRecord).filter(
            ConsumptionRecord.baby_id == baby_id,
            ConsumptionRecord.nighttime_leaks > 0
        ).order_by(ConsumptionRecord.record_date.desc()).all()

        recent_leak_records = [
            r for r in records
            if datetime.strptime(r.record_date, "%Y-%m-%d") >= cutoff
        ]

        if len(recent_leak_records) >= 2:
            consecutive_leak_days = 0
            max_consecutive = 0
            leak_dates = sorted(set(r.record_date for r in recent_leak_records))

            for i in range(1, len(leak_dates)):
                prev_d = datetime.strptime(leak_dates[i - 1], "%Y-%m-%d")
                curr_d = datetime.strptime(leak_dates[i], "%Y-%m-%d")
                if (curr_d - prev_d).days == 1:
                    consecutive_leak_days += 1
                    max_consecutive = max(max_consecutive, consecutive_leak_days + 1)
                else:
                    consecutive_leak_days = 0

            if max_consecutive >= 2:
                total_leaks = sum(r.nighttime_leaks for r in recent_leak_records)
                active_shifts = [s for s in shifts if s.status == "active"]

                risks.append({
                    "risk_type": "continuous_leak_unhandled",
                    "severity": "high" if max_consecutive >= 3 else "medium",
                    "consecutive_leak_days": max_consecutive,
                    "total_leaks": total_leaks,
                    "affected_shift_ids": [s.id for s in active_shifts],
                    "message": f"连续{max_consecutive}天夜间漏尿未处理，共{total_leaks}次漏尿，请检查尺码或增加夜间更换频率"
                })
        return risks

    def detect_restock_reminder_unconfirmed(self, baby_id: int, shifts: List[Shift]) -> List[Dict]:
        risks = []
        unresolved = self._get_unresolved_reminders(baby_id)

        restock_reminders = [
            r for r in unresolved
            if r.reason_code in ("SAFETY_STOCK_LOW", "NEXT_SIZE_UNDERSTOCK")
        ]

        if not restock_reminders or not shifts:
            return risks

        for reminder in restock_reminders:
            shift_items = self.db.query(HandoverItem).filter(
                HandoverItem.baby_id == baby_id,
                HandoverItem.item_type == "reminder",
                HandoverItem.is_resolved == True
            ).all()

            reminder_handled = any(
                item.content and str(reminder.id) in item.content
                for item in shift_items
            )

            if not reminder_handled:
                hours_since = (datetime.now() - reminder.triggered_at).total_seconds() / 3600
                risks.append({
                    "risk_type": "restock_reminder_unconfirmed",
                    "severity": "high" if hours_since > 48 else "medium",
                    "reminder_id": reminder.id,
                    "reminder_type": reminder.reason_code,
                    "reminder_message": reminder.message,
                    "hours_since_triggered": round(hours_since, 1),
                    "message": f"补货提醒无人确认: {reminder.message}，已超过{round(hours_since, 0)}小时"
                })
        return risks

    def detect_duplicate_reporting(self, baby_id: int, shifts: List[Shift]) -> List[Dict]:
        risks = []
        items = self.db.query(HandoverItem).filter(
            HandoverItem.baby_id == baby_id
        ).order_by(HandoverItem.created_at.desc()).limit(100).all()

        content_map: Dict[str, List[HandoverItem]] = {}
        for item in items:
            key = f"{item.item_type}:{item.content[:50]}"
            if key not in content_map:
                content_map[key] = []
            content_map[key].append(item)

        for key, grouped in content_map.items():
            if len(grouped) < 2:
                continue

            time_sorted = sorted(grouped, key=lambda x: x.created_at)
            for i in range(1, len(time_sorted)):
                time_diff = (time_sorted[i].created_at - time_sorted[i - 1].created_at).total_seconds()
                if time_diff < 3600 and time_sorted[i].caregiver_id != time_sorted[i - 1].caregiver_id:
                    risks.append({
                        "risk_type": "duplicate_reporting",
                        "severity": "low",
                        "item_ids": [time_sorted[i - 1].id, time_sorted[i].id],
                        "item_type": time_sorted[i].item_type,
                        "content_preview": time_sorted[i].content[:100],
                        "caregiver_ids": [time_sorted[i - 1].caregiver_id, time_sorted[i].caregiver_id],
                        "time_diff_seconds": int(time_diff),
                        "message": f"同一时段不同照护人重复上报: '{time_sorted[i].content[:50]}'，间隔{int(time_diff)}秒"
                    })
        return risks

    def detect_task_omission(self, baby_id: int, shifts: List[Shift]) -> List[Dict]:
        risks = []
        active_shifts = [s for s in shifts if s.status == "active"]

        for shift in active_shifts:
            tasks = self.db.query(TodoTask).filter(
                TodoTask.shift_id == shift.id,
                TodoTask.baby_id == baby_id
            ).all()

            if not tasks:
                continue

            incomplete_tasks = [t for t in tasks if not t.is_completed]
            overdue_tasks = [
                t for t in incomplete_tasks
                if t.due_time and t.due_time < datetime.now()
            ]

            if overdue_tasks:
                risks.append({
                    "risk_type": "task_omission",
                    "severity": "high",
                    "shift_id": shift.id,
                    "caregiver_id": shift.caregiver_id,
                    "overdue_task_count": len(overdue_tasks),
                    "overdue_tasks": [
                        {
                            "task_id": t.id,
                            "task_type": t.task_type,
                            "description": t.description,
                            "due_time": t.due_time.isoformat() if t.due_time else None
                        }
                        for t in overdue_tasks
                    ],
                    "message": f"班次{shift.id}有{len(overdue_tasks)}项护理任务已超时未完成"
                })
            elif len(incomplete_tasks) > len(tasks) * 0.5 and len(tasks) >= 3:
                risks.append({
                    "risk_type": "task_omission_risk",
                    "severity": "medium",
                    "shift_id": shift.id,
                    "caregiver_id": shift.caregiver_id,
                    "incomplete_task_count": len(incomplete_tasks),
                    "total_task_count": len(tasks),
                    "message": f"班次{shift.id}有{len(incomplete_tasks)}/{len(tasks)}项任务未完成，完成率低于50%"
                })
        return risks

    def detect_all_risks(self, baby_id: int) -> List[Dict]:
        end = datetime.now()
        start = end - timedelta(days=7)
        shifts = self._get_shifts_in_range(baby_id, start, end)

        all_risks = []
        all_risks.extend(self.detect_inventory_sync_risk(baby_id, shifts))
        all_risks.extend(self.detect_continuous_leak_risk(baby_id, shifts))
        all_risks.extend(self.detect_restock_reminder_unconfirmed(baby_id, shifts))
        all_risks.extend(self.detect_duplicate_reporting(baby_id, shifts))
        all_risks.extend(self.detect_task_omission(baby_id, shifts))

        severity_order = {"high": 0, "medium": 1, "low": 2}
        all_risks.sort(key=lambda x: severity_order.get(x.get("severity", "low"), 3))
        return all_risks


class HandoverSummaryGenerator:
    def __init__(self, db: Session):
        self.db = db

    def generate_summary(self, baby_id: int, shift_id: Optional[int] = None) -> Dict:
        baby = self.db.query(Baby).filter(Baby.id == baby_id).first()
        if not baby:
            return {"error": "宝宝不存在"}

        if shift_id:
            shift = self.db.query(Shift).filter(Shift.id == shift_id, Shift.baby_id == baby_id).first()
            if not shift:
                return {"error": "班次不存在"}
            shifts = [shift]
        else:
            shifts = self.db.query(Shift).filter(
                Shift.baby_id == baby_id
            ).order_by(Shift.shift_start.desc()).limit(5).all()

        consumption_records = self.db.query(ConsumptionRecord).filter(
            ConsumptionRecord.baby_id == baby_id
        ).order_by(ConsumptionRecord.record_date.desc()).limit(7).all()

        inventory_records = self.db.query(InventoryRecord).filter(
            InventoryRecord.baby_id == baby_id
        ).order_by(InventoryRecord.record_date.desc()).limit(5).all()

        recent_leaks = [
            r for r in consumption_records
            if r.nighttime_leaks and r.nighttime_leaks > 0
        ]

        unresolved_reminders = self.db.query(PlanReminder).filter(
            PlanReminder.baby_id == baby_id,
            PlanReminder.resolved == False
        ).order_by(PlanReminder.triggered_at.desc()).all()

        shift_summaries = []
        for s in shifts:
            items = self.db.query(HandoverItem).filter(
                HandoverItem.shift_id == s.id
            ).order_by(HandoverItem.created_at).all()

            tasks = self.db.query(TodoTask).filter(
                TodoTask.shift_id == s.id
            ).all()

            caregiver = self.db.query(Caregiver).filter(Caregiver.id == s.caregiver_id).first()

            completed_tasks = [t for t in tasks if t.is_completed]
            incomplete_tasks = [t for t in tasks if not t.is_completed]
            anomaly_items = [i for i in items if i.item_type == "anomaly"]
            unresolved_items = [i for i in items if not i.is_resolved]

            shift_summaries.append({
                "shift_id": s.id,
                "caregiver_name": caregiver.name if caregiver else "未知",
                "caregiver_role": caregiver.role if caregiver else None,
                "shift_start": s.shift_start.isoformat() if s.shift_start else None,
                "shift_end": s.shift_end.isoformat() if s.shift_end else None,
                "status": s.status,
                "inventory_snapshot": s.inventory_snapshot,
                "previous_shift_anomalies": s.previous_shift_anomalies,
                "handover_summary": {
                    "total_items": len(items),
                    "unresolved_items": len(unresolved_items),
                    "anomaly_items": len(anomaly_items),
                    "anomalies": [
                        {"content": a.content, "priority": a.priority, "is_resolved": a.is_resolved}
                        for a in anomaly_items
                    ],
                    "unresolved_reminders": [
                        {"content": i.content, "priority": i.priority}
                        for i in unresolved_items if i.item_type == "reminder"
                    ],
                    "completed_care_actions": [
                        {"content": i.content}
                        for i in items if i.item_type == "completed_care"
                    ]
                },
                "task_summary": {
                    "total_tasks": len(tasks),
                    "completed_tasks": len(completed_tasks),
                    "incomplete_tasks": len(incomplete_tasks),
                    "completion_rate": round(len(completed_tasks) / len(tasks) * 100, 1) if tasks else 0,
                    "overdue_tasks": len([
                        t for t in incomplete_tasks
                        if t.due_time and t.due_time < datetime.now()
                    ])
                }
            })

        risk_detector = CollaborationRiskDetector(self.db)
        risks = risk_detector.detect_all_risks(baby_id)

        return {
            "baby_id": baby_id,
            "baby_name": baby.name,
            "current_size": baby.current_diaper_size,
            "generated_at": datetime.now().isoformat(),
            "recent_consumption": {
                "total_changes": sum(r.daily_changes for r in consumption_records),
                "total_nighttime_changes": sum(r.nighttime_changes for r in consumption_records),
                "total_nighttime_leaks": sum(r.nighttime_leaks for r in consumption_records),
                "data_points": len(consumption_records),
                "recent_leak_dates": [
                    {"date": r.record_date, "leaks": r.nighttime_leaks}
                    for r in recent_leaks
                ]
            },
            "current_inventory": [
                {
                    "date": r.record_date,
                    "size": r.diaper_size,
                    "quantity": r.quantity
                }
                for r in inventory_records
            ],
            "unresolved_plan_reminders": [
                {
                    "id": r.id,
                    "type": r.reminder_type,
                    "level": r.reminder_level,
                    "message": r.message,
                    "triggered_at": r.triggered_at.isoformat()
                }
                for r in unresolved_reminders
            ],
            "shift_summaries": shift_summaries,
            "collaboration_risks": risks,
            "risk_summary": {
                "total_risks": len(risks),
                "high_risks": sum(1 for r in risks if r.get("severity") == "high"),
                "medium_risks": sum(1 for r in risks if r.get("severity") == "medium"),
                "low_risks": sum(1 for r in risks if r.get("severity") == "low")
            }
        }


class WorkloadStatistics:
    def __init__(self, db: Session):
        self.db = db

    def get_caregiver_workload(self, baby_id: int, days: int = 30) -> Dict:
        end = datetime.now()
        start = end - timedelta(days=days)

        caregivers = self.db.query(Caregiver).filter(
            Caregiver.baby_id == baby_id,
            Caregiver.is_active == True
        ).all()

        if not caregivers:
            return {
                "baby_id": baby_id,
                "period_days": days,
                "caregivers": [],
                "summary": {
                    "total_shifts": 0,
                    "total_tasks": 0,
                    "total_handover_items": 0
                }
            }

        caregiver_stats = []
        total_shifts = 0
        total_tasks = 0
        total_items = 0

        for cg in caregivers:
            shifts = self.db.query(Shift).filter(
                Shift.baby_id == baby_id,
                Shift.caregiver_id == cg.id,
                Shift.shift_start >= start
            ).all()

            shift_ids = [s.id for s in shifts]
            shift_count = len(shifts)

            total_hours = 0.0
            for s in shifts:
                if s.shift_end and s.shift_start:
                    total_hours += max(0, (s.shift_end - s.shift_start).total_seconds() / 3600)

            tasks = self.db.query(TodoTask).filter(
                TodoTask.shift_id.in_(shift_ids),
                TodoTask.baby_id == baby_id
            ).all() if shift_ids else []

            completed_tasks = [t for t in tasks if t.is_completed]
            overdue_tasks = [
                t for t in tasks
                if not t.is_completed and t.due_time and t.due_time < datetime.now()
            ]

            items = self.db.query(HandoverItem).filter(
                HandoverItem.shift_id.in_(shift_ids),
                HandoverItem.baby_id == baby_id
            ).all() if shift_ids else []

            anomaly_count = sum(1 for i in items if i.item_type == "anomaly")
            resolved_anomalies = sum(1 for i in items if i.item_type == "anomaly" and i.is_resolved)

            task_count = len(tasks)
            item_count = len(items)
            total_shifts += shift_count
            total_tasks += task_count
            total_items += item_count

            caregiver_stats.append({
                "caregiver_id": cg.id,
                "caregiver_name": cg.name,
                "role": cg.role,
                "shifts": shift_count,
                "total_hours": round(total_hours, 1),
                "tasks": {
                    "total": task_count,
                    "completed": len(completed_tasks),
                    "overdue": len(overdue_tasks),
                    "completion_rate": round(len(completed_tasks) / task_count * 100, 1) if task_count > 0 else 0
                },
                "handover_items": {
                    "total": item_count,
                    "anomalies": anomaly_count,
                    "resolved_anomalies": resolved_anomalies
                }
            })

        caregiver_stats.sort(key=lambda x: x["shifts"], reverse=True)

        return {
            "baby_id": baby_id,
            "period_days": days,
            "caregivers": caregiver_stats,
            "summary": {
                "total_shifts": total_shifts,
                "total_tasks": total_tasks,
                "total_handover_items": total_items,
                "active_caregiver_count": len(caregivers)
            }
        }

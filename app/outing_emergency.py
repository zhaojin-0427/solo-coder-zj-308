from datetime import datetime, timedelta
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from .models import (
    Baby, OutingPlan, OutingEmergencyPlan, OutingCaregiverTask,
    OutingCaregiverAssignment, SkinObservationRecord, Caregiver
)
from .outing_risk import OutingRiskAssessor
from .outing_packing import OutingPackingCalculator


class OutingEmergencyPlanner:
    def __init__(self, db: Session):
        self.db = db
        self.risk_assessor = OutingRiskAssessor(db)
        self.packing_calculator = OutingPackingCalculator(db)

    def _generate_leak_emergency_steps(self, outing_plan: OutingPlan, baby: Baby, risk_assessment: Dict) -> List[str]:
        steps = [
            "立即更换湿脏的纸尿裤和衣物",
            "用湿纸巾清洁宝宝皮肤，保持干燥",
            "检查是否有红屁屁现象，如有涂抹护臀膏"
        ]

        if outing_plan.restock_convenience in ["difficult", "none"]:
            steps.append("清点剩余纸尿裤数量，估算可支撑时长")
            steps.append("如库存不足，优先保证核心更换需求")
            steps.append("联系附近亲友或寻找最近的母婴店补货")

        leak_trend = risk_assessment["component_scores"]["leak_trend"]
        if leak_trend["risk_level"] in ["high", "critical"]:
            steps.insert(0, "发现漏尿时立即处理，避免皮肤长时间接触尿液")
            steps.append("下次更换时检查纸尿裤尺码是否合适")
            steps.append("如频繁漏尿，考虑使用大一号的纸尿裤")

        if outing_plan.transportation in ["airplane", "train", "public_transit"]:
            steps.append("在交通工具上提前寻找卫生间位置")
            steps.append("准备便携更换垫，方便随时更换")

        return steps

    def _generate_rash_emergency_steps(self, outing_plan: OutingPlan, baby: Baby, risk_assessment: Dict) -> List[str]:
        skin_risk = risk_assessment["component_scores"]["skin_risk"]

        steps = []

        if skin_risk["rash_grade"] >= 2:
            steps.extend([
                "发现红疹加重时，立即清洁并干燥皮肤",
                "让皮肤暴露在空气中5-10分钟，保持通风干燥",
                "涂抹护臀膏或湿疹药膏",
                "增加更换频率，减少尿液粪便刺激"
            ])
        else:
            steps.extend([
                "保持皮肤清洁干燥，每次更换后彻底清洁",
                "如有轻微发红，涂抹防护型护臀膏",
                "注意观察皮肤状况变化"
            ])

        if skin_risk["has_exudate"] or skin_risk["has_breakdown"]:
            steps.append("如皮肤有破皮渗液，使用无菌纱布轻轻按压")
            steps.append("避免摩擦和刺激皮肤，动作要轻柔")
            steps.append("如情况严重或持续加重，及时就医")

        weather_risk = risk_assessment["component_scores"]["weather_risk"]
        if weather_risk["risk_level"] == "high":
            steps.append("高温天气注意降温，避免宝宝过热出汗")
            steps.append("选择透气吸汗的衣物和纸尿裤")

        steps.append("回家后详细记录皮肤状况，必要时咨询医生")

        return steps

    def _generate_supply_shortage_steps(self, outing_plan: OutingPlan, baby: Baby, risk_assessment: Dict) -> List[str]:
        steps = []

        supply_risk = risk_assessment["component_scores"]["supply_risk"]

        if supply_risk["supply_risk_level"] in ["high", "critical"]:
            steps.extend([
                "立即清点剩余纸尿裤和用品数量",
                "计算预计可使用时长",
                "优先保证必要更换，减少预防性更换"
            ])
        else:
            steps.extend([
                "定期检查剩余用品数量",
                "合理安排更换频率，避免浪费"
            ])

        restock_convenience = outing_plan.restock_convenience
        if restock_convenience == "easy":
            steps.append("周边购物方便，可随时补充")
        elif restock_convenience == "moderate":
            steps.append("附近有商店，预留补货时间")
        elif restock_convenience == "difficult":
            steps.append("补货较困难，节省使用，寻找替代方案")
            steps.append("可询问当地亲友是否有备用")
        else:
            steps.append("无法补货，严格控制使用量")
            steps.append("提前结束行程或寻找替代住宿")

        steps.append("如遇严重短缺，联系家人送补给或叫外卖配送")

        return steps

    def _generate_nearest_facilities(self, outing_plan: OutingPlan) -> List[Dict]:
        facilities = []

        dest_type = outing_plan.destination_type

        facility_map = {
            "park": [
                {"type": "public_toilet", "name": "公园公共卫生间", "note": "通常有母婴室或无障碍卫生间"},
                {"type": "convenience_store", "name": "周边便利店", "note": "可购买纸尿裤和湿巾"}
            ],
            "shopping_mall": [
                {"type": "mother_baby_room", "name": "商场母婴室", "note": "配备尿布台和哺乳设施"},
                {"type": "pharmacy", "name": "药店", "note": "可购买护理用品和药品"},
                {"type": "supermarket", "name": "超市/母婴店", "note": "纸尿裤规格齐全"}
            ],
            "restaurant": [
                {"type": "restaurant_toilet", "name": "餐厅卫生间", "note": "部分餐厅有婴儿护理台"},
                {"type": "convenience_store", "name": "附近便利店", "note": "紧急补充用品"}
            ],
            "hospital": [
                {"type": "pediatrics", "name": "医院儿科", "note": "如有紧急情况可直接就诊"},
                {"type": "pharmacy", "name": "医院药房", "note": "可购买药品和护理用品"}
            ],
            "home_visit": [
                {"type": "home", "name": "亲友家", "note": "可借用或请求帮助"},
                {"type": "nearby_store", "name": "附近商店", "note": "社区周边通常有便利店"}
            ],
            "travel": [
                {"type": "service_station", "name": "服务区/休息站", "note": "长途出行注意补给点"},
                {"type": "pharmacy", "name": "沿途药店", "note": "提前查询沿途药店位置"}
            ],
            "other": [
                {"type": "convenience_store", "name": "便利店", "note": "24小时便利店通常有售基础用品"}
            ]
        }

        facilities = facility_map.get(dest_type, facility_map["other"])

        if outing_plan.transportation in ["airplane", "train"]:
            facilities.append({
                "type": "transport_facility",
                "name": "交通工具卫生间",
                "note": "空间有限，提前准备便携用品"
            })

        return facilities

    def _generate_emergency_contacts(self, outing_plan: OutingPlan, baby_id: int) -> List[Dict]:
        contacts = []

        from .models import OutingCaregiverAssignment

        assignments = self.db.query(OutingCaregiverAssignment).filter(
            OutingCaregiverAssignment.outing_plan_id == outing_plan.id
        ).all()

        for assignment in assignments:
            caregiver = assignment.caregiver
            if caregiver and caregiver.phone:
                contacts.append({
                    "name": caregiver.name,
                    "role": assignment.role_in_outing,
                    "phone": caregiver.phone,
                    "is_primary": assignment.is_primary,
                    "type": "caregiver"
                })

        active_caregivers = self.db.query(Caregiver).filter(
            Caregiver.baby_id == baby_id,
            Caregiver.is_active == True
        ).all()

        assigned_ids = [a.caregiver_id for a in assignments]
        for caregiver in active_caregivers:
            if caregiver.id not in assigned_ids and caregiver.phone:
                contacts.append({
                    "name": caregiver.name,
                    "role": caregiver.role,
                    "phone": caregiver.phone,
                    "is_primary": False,
                    "type": "backup_caregiver",
                    "note": "可联系送补给或支援"
                })

        contacts.append({
            "name": "急救中心",
            "phone": "120",
            "type": "emergency",
            "note": "紧急医疗求助"
        })

        return contacts

    def _generate_recommendations(self, risk_assessment: Dict) -> List[str]:
        recommendations = []

        overall_level = risk_assessment["overall_risk_level"]
        if overall_level == "high":
            recommendations.append("整体风险较高，建议做好充分准备")
            recommendations.append("考虑缩短外出时间或增加照护人手")
        elif overall_level == "medium":
            recommendations.append("有一定风险，注意观察宝宝状况")
            recommendations.append("准备好应急用品，保持通讯畅通")
        else:
            recommendations.append("风险较低，正常准备即可")

        supply_risk = risk_assessment["component_scores"]["supply_risk"]
        if supply_risk["supply_risk_level"] in ["high", "critical"]:
            recommendations.append("建议额外多带2-3片纸尿裤备用")
            recommendations.append("提前查询目的地周边母婴店位置")

        skin_risk = risk_assessment["component_scores"]["skin_risk"]
        if skin_risk["risk_level"] in ["high", "critical"]:
            recommendations.append("注意皮肤护理，增加更换频率")
            recommendations.append("携带护臀膏和保湿霜")

        leak_trend = risk_assessment["component_scores"]["leak_trend"]
        if leak_trend["risk_level"] in ["high", "critical"]:
            recommendations.append("近期漏尿增多，建议带备用衣物")
            recommendations.append("检查纸尿裤尺码是否合适")

        caregiver_risk = risk_assessment["component_scores"]["caregiver_risk"]
        if caregiver_risk["risk_level"] in ["high", "medium"]:
            recommendations.append("照护人力有限，合理安排休息")
            recommendations.append("确保紧急联系人信息准确")

        return recommendations

    def generate_emergency_plan(self, outing_plan: OutingPlan, baby: Baby) -> Dict:
        risk_assessment = self.risk_assessor.calculate_overall_risk(outing_plan, baby)

        leak_steps = self._generate_leak_emergency_steps(outing_plan, baby, risk_assessment)
        rash_steps = self._generate_rash_emergency_steps(outing_plan, baby, risk_assessment)
        supply_steps = self._generate_supply_shortage_steps(outing_plan, baby, risk_assessment)
        facilities = self._generate_nearest_facilities(outing_plan)
        contacts = self._generate_emergency_contacts(outing_plan, baby.id)
        recommendations = self._generate_recommendations(risk_assessment)

        risk_factors = risk_assessment.get("risk_factors", [])

        return {
            "overall_risk_level": risk_assessment["overall_risk_level"],
            "overall_risk_score": risk_assessment["overall_risk_score"],
            "leak_emergency_steps": leak_steps,
            "rash_emergency_steps": rash_steps,
            "supply_shortage_steps": supply_steps,
            "nearest_facilities": facilities,
            "emergency_contacts": contacts,
            "risk_factors": risk_factors,
            "recommendations": recommendations
        }

    def save_emergency_plan(self, outing_plan_id: int, emergency_data: Dict) -> OutingEmergencyPlan:
        existing = self.db.query(OutingEmergencyPlan).filter(
            OutingEmergencyPlan.outing_plan_id == outing_plan_id
        ).first()

        if existing:
            plan = existing
        else:
            plan = OutingEmergencyPlan(outing_plan_id=outing_plan_id)
            self.db.add(plan)

        import json

        plan.leak_emergency_steps = json.dumps(emergency_data.get("leak_emergency_steps", []), ensure_ascii=False)
        plan.rash_emergency_steps = json.dumps(emergency_data.get("rash_emergency_steps", []), ensure_ascii=False)
        plan.supply_shortage_steps = json.dumps(emergency_data.get("supply_shortage_steps", []), ensure_ascii=False)
        plan.nearest_facilities = json.dumps(emergency_data.get("nearest_facilities", []), ensure_ascii=False)
        plan.emergency_contacts = json.dumps(emergency_data.get("emergency_contacts", []), ensure_ascii=False)
        plan.overall_risk_level = emergency_data.get("overall_risk_level", "low")
        plan.overall_risk_score = emergency_data.get("overall_risk_score", 0.0)
        plan.risk_factors = json.dumps(emergency_data.get("risk_factors", []), ensure_ascii=False)
        plan.recommendations = json.dumps(emergency_data.get("recommendations", []), ensure_ascii=False)

        self.db.commit()
        self.db.refresh(plan)

        return plan

    def generate_caregiver_tasks(self, outing_plan: OutingPlan, baby: Baby) -> List[Dict]:
        tasks = []

        from .models import OutingCaregiverAssignment

        assignments = self.db.query(OutingCaregiverAssignment).filter(
            OutingCaregiverAssignment.outing_plan_id == outing_plan.id
        ).all()

        primary_caregiver = next((a for a in assignments if a.is_primary), None)
        other_caregivers = [a for a in assignments if not a.is_primary]

        if not assignments:
            return tasks

        if primary_caregiver:
            tasks.extend([
                {
                    "caregiver_id": primary_caregiver.caregiver_id,
                    "task_type": "carry_supplies",
                    "task_description": "负责携带主要护理用品",
                    "item_category": "main_supplies",
                    "quantity": 1,
                    "priority": "high",
                    "due_time": outing_plan.departure_time - timedelta(hours=1),
                    "notes": "出发前整理好尿布包"
                },
                {
                    "task_type": "change_diaper",
                    "task_description": "负责主要的尿布更换工作",
                    "item_category": "diaper_change",
                    "quantity": 0,
                    "priority": "high",
                    "due_time": None,
                    "notes": "按更换时间表执行"
                },
                {
                    "task_type": "monitor_skin",
                    "task_description": "观察宝宝皮肤状况",
                    "item_category": "skin_care",
                    "quantity": 0,
                    "priority": "medium",
                    "due_time": None,
                    "notes": "每次更换时检查皮肤"
                },
                {
                    "caregiver_id": primary_caregiver.caregiver_id,
                    "task_type": "handle_emergency",
                    "task_description": "处理突发状况",
                    "item_category": "emergency",
                    "quantity": 0,
                    "priority": "high",
                    "due_time": None,
                    "notes": "熟悉应急预案步骤"
                }
            ])

        for i, caregiver in enumerate(other_caregivers):
            tasks.extend([
                {
                    "caregiver_id": caregiver.caregiver_id,
                    "task_type": "carry_supplies",
                    "task_description": "协助携带备用物品",
                    "item_category": "backup_supplies",
                    "quantity": 1,
                    "priority": "normal",
                    "due_time": outing_plan.departure_time - timedelta(hours=1),
                    "notes": "携带备用衣物和湿巾"
                },
                {
                    "caregiver_id": caregiver.caregiver_id,
                    "task_type": "reminder",
                    "task_description": "提醒更换时间",
                    "item_category": "schedule",
                    "quantity": 0,
                    "priority": "normal",
                    "due_time": None,
                    "notes": "关注更换时间表"
                }
            ])

        if len(assignments) >= 2:
            tasks.append({
                "caregiver_id": assignments[0].caregiver_id,
                "task_type": "other",
                "task_description": "照顾宝宝（轮换）",
                "item_category": "care_rotation",
                "quantity": 0,
                "priority": "normal",
                "due_time": None,
                "notes": "每2小时轮换休息"
            })

        return tasks

    def save_caregiver_tasks(self, outing_plan_id: int, tasks: List[Dict]) -> List[OutingCaregiverTask]:
        existing = self.db.query(OutingCaregiverTask).filter(
            OutingCaregiverTask.outing_plan_id == outing_plan_id
        ).all()
        for task in existing:
            self.db.delete(task)

        saved_tasks = []
        for task_data in tasks:
            db_task = OutingCaregiverTask(
                outing_plan_id=outing_plan_id,
                caregiver_id=task_data.get("caregiver_id"),
                task_type=task_data.get("task_type", "other"),
                task_description=task_data.get("task_description", ""),
                item_category=task_data.get("item_category"),
                quantity=task_data.get("quantity", 0),
                priority=task_data.get("priority", "normal"),
                due_time=task_data.get("due_time"),
                notes=task_data.get("notes")
            )
            self.db.add(db_task)
            saved_tasks.append(db_task)

        self.db.commit()
        for task in saved_tasks:
            self.db.refresh(task)

        return saved_tasks

    def generate_full_emergency_and_tasks(self, outing_plan: OutingPlan, baby: Baby) -> Dict:
        emergency_data = self.generate_emergency_plan(outing_plan, baby)
        self.save_emergency_plan(outing_plan.id, emergency_data)

        tasks = self.generate_caregiver_tasks(outing_plan, baby)
        self.save_caregiver_tasks(outing_plan.id, tasks)

        return {
            "emergency_plan": emergency_data,
            "caregiver_tasks": tasks,
            "task_count": len(tasks)
        }

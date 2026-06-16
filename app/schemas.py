from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, List, Dict, Any
from datetime import datetime

VALID_DIAPER_SIZES = ["NB", "S", "M", "L", "XL", "XXL"]


def validate_diaper_size(v: str) -> str:
    if v and v.upper() not in VALID_DIAPER_SIZES:
        raise ValueError(f"纸尿裤尺码必须是以下之一: {', '.join(VALID_DIAPER_SIZES)}")
    return v.upper() if v else v


class ApiResponse(BaseModel):
    code: int = Field(default=200, description="响应码")
    message: str = Field(default="success", description="响应消息")
    data: Optional[Any] = Field(default=None, description="响应数据")


class BabyCreate(BaseModel):
    name: str = Field(..., description="宝宝姓名")
    birth_date: str = Field(..., description="出生日期 YYYY-MM-DD")
    current_age_months: int = Field(..., ge=0, description="当前月龄")
    current_weight_kg: float = Field(..., gt=0, description="当前体重(kg)")
    current_diaper_size: str = Field(..., description="当前纸尿裤尺码 NB/S/M/L/XL/XXL")
    gender: Optional[str] = Field(default=None, description="性别")

    @field_validator("birth_date")
    @classmethod
    def check_birth_date(cls, v: str) -> str:
        return validate_date_format(v)

    @field_validator("current_diaper_size")
    @classmethod
    def check_diaper_size(cls, v: str) -> str:
        return validate_diaper_size(v)


class BabyUpdate(BaseModel):
    name: Optional[str] = None
    birth_date: Optional[str] = None
    current_age_months: Optional[int] = Field(default=None, ge=0)
    current_weight_kg: Optional[float] = Field(default=None, gt=0)
    current_diaper_size: Optional[str] = None
    gender: Optional[str] = None

    @field_validator("birth_date")
    @classmethod
    def check_birth_date(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validate_date_format(v)
        return v

    @field_validator("current_diaper_size")
    @classmethod
    def check_diaper_size(cls, v: Optional[str]) -> Optional[str]:
        return validate_diaper_size(v) if v is not None else v


class BabyResponse(BaseModel):
    id: int
    name: str
    birth_date: str
    current_age_months: int
    current_weight_kg: float
    current_diaper_size: str
    gender: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ConsumptionRecordCreate(BaseModel):
    baby_id: int = Field(..., description="宝宝ID")
    record_date: str = Field(..., description="记录日期 YYYY-MM-DD")
    diaper_size: str = Field(..., description="纸尿裤尺码")
    daily_changes: int = Field(..., ge=0, description="当日更换次数")
    nighttime_changes: Optional[int] = Field(default=0, ge=0, description="夜间更换次数")
    nighttime_leaks: Optional[int] = Field(default=0, ge=0, description="夜间漏尿次数")
    weight_kg: Optional[float] = Field(default=None, gt=0, description="当日体重")
    notes: Optional[str] = Field(default=None, description="备注")

    @field_validator("record_date")
    @classmethod
    def check_record_date(cls, v: str) -> str:
        return validate_date_format(v)

    @field_validator("diaper_size")
    @classmethod
    def check_diaper_size(cls, v: str) -> str:
        return validate_diaper_size(v)


class InventoryRecordCreate(BaseModel):
    baby_id: int = Field(..., description="宝宝ID")
    record_date: str = Field(..., description="记录日期 YYYY-MM-DD")
    diaper_size: str = Field(..., description="纸尿裤尺码")
    quantity: int = Field(..., ge=0, description="库存数量")
    unit: Optional[str] = Field(default="pieces", description="单位")
    notes: Optional[str] = Field(default=None, description="备注")

    @field_validator("record_date")
    @classmethod
    def check_record_date(cls, v: str) -> str:
        return validate_date_format(v)

    @field_validator("diaper_size")
    @classmethod
    def check_diaper_size(cls, v: str) -> str:
        return validate_diaper_size(v)


class AlertResolve(BaseModel):
    resolved: bool = Field(default=True, description="是否已解决")


VALID_PROMO_PREFERENCES = ["minimal", "moderate", "aggressive"]
VALID_PLANNING_PERIODS = [30, 60, 90]
VALID_REASON_CODES = [
    "OVERSTOCK_CURRENT_SIZE",
    "NEXT_SIZE_UNDERSTOCK",
    "NIGHTTIME_LEAK_INCREASE",
    "PROMO_OVERSTOCK",
    "SIZE_TRANSITION_SOON",
    "SAFETY_STOCK_LOW",
    "GROWTH_FASTER_THAN_EXPECTED",
    "GROWTH_SLOWER_THAN_EXPECTED"
]


def validate_date_format(v: str) -> str:
    from datetime import datetime
    try:
        datetime.strptime(v, "%Y-%m-%d")
        return v
    except ValueError:
        raise ValueError("日期格式必须为 YYYY-MM-DD")


def validate_planning_period(v: int) -> int:
    if v not in VALID_PLANNING_PERIODS:
        raise ValueError(f"计划周期必须为以下之一: {', '.join(map(str, VALID_PLANNING_PERIODS))}")
    return v


class GrowthPlanCreate(BaseModel):
    baby_id: int = Field(..., description="宝宝ID")
    target_weight_kg: Optional[float] = Field(default=None, ge=0, description="目标体重(kg)")
    target_date: Optional[str] = Field(default=None, description="目标日期 YYYY-MM-DD")
    growth_rate_kg_per_month: Optional[float] = Field(default=None, ge=0, description="预计月增长体重(kg)")
    promo_stocking_preference: Optional[str] = Field(default="moderate", description="促销囤货偏好 minimal/moderate/aggressive")
    preferred_brand: Optional[str] = Field(default=None, description="常用品牌")
    safety_stock_days: Optional[int] = Field(default=7, ge=0, description="期望安全库存天数")
    planning_horizon_days: Optional[int] = Field(default=90, ge=1, le=365, description="计划展望天数")

    @field_validator("target_date")
    @classmethod
    def check_target_date(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validate_date_format(v)
        return v

    @field_validator("promo_stocking_preference")
    @classmethod
    def check_promo_pref(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_PROMO_PREFERENCES:
            raise ValueError(f"促销囤货偏好必须为以下之一: {', '.join(VALID_PROMO_PREFERENCES)}")
        return v


class GrowthPlanUpdate(BaseModel):
    target_weight_kg: Optional[float] = Field(default=None, ge=0)
    target_date: Optional[str] = None
    growth_rate_kg_per_month: Optional[float] = Field(default=None, ge=0)
    promo_stocking_preference: Optional[str] = None
    preferred_brand: Optional[str] = None
    safety_stock_days: Optional[int] = Field(default=None, ge=0)
    planning_horizon_days: Optional[int] = Field(default=None, ge=1, le=365)

    @field_validator("target_date")
    @classmethod
    def check_target_date(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validate_date_format(v)
        return v

    @field_validator("promo_stocking_preference")
    @classmethod
    def check_promo_pref(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_PROMO_PREFERENCES:
            raise ValueError(f"促销囤货偏好必须为以下之一: {', '.join(VALID_PROMO_PREFERENCES)}")
        return v


class GrowthPlanResponse(BaseModel):
    id: int
    baby_id: int
    target_weight_kg: Optional[float]
    target_date: Optional[str]
    growth_rate_kg_per_month: Optional[float]
    promo_stocking_preference: str
    preferred_brand: Optional[str]
    safety_stock_days: int
    planning_horizon_days: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PackageSpecCreate(BaseModel):
    baby_id: int = Field(..., description="宝宝ID")
    brand: str = Field(..., description="品牌名称")
    size: str = Field(..., description="纸尿裤尺码")
    pieces_per_pack: int = Field(..., ge=1, description="每包片数")
    packs_per_box: Optional[int] = Field(default=1, ge=1, description="每箱包数")
    price_per_pack: Optional[float] = Field(default=None, ge=0, description="每包价格")
    is_active: Optional[bool] = Field(default=True, description="是否启用")
    notes: Optional[str] = Field(default=None, description="备注")

    @field_validator("size")
    @classmethod
    def check_size(cls, v: str) -> str:
        return validate_diaper_size(v)


class PackageSpecUpdate(BaseModel):
    brand: Optional[str] = None
    size: Optional[str] = None
    pieces_per_pack: Optional[int] = Field(default=None, ge=1)
    packs_per_box: Optional[int] = Field(default=None, ge=1)
    price_per_pack: Optional[float] = Field(default=None, ge=0)
    is_active: Optional[bool] = None
    notes: Optional[str] = None

    @field_validator("size")
    @classmethod
    def check_size(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validate_diaper_size(v)
        return v


class PackageSpecResponse(BaseModel):
    id: int
    baby_id: int
    brand: str
    size: str
    pieces_per_pack: int
    packs_per_box: int
    price_per_pack: Optional[float]
    is_active: bool
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PlanReminderResponse(BaseModel):
    id: int
    baby_id: int
    reminder_type: str
    reminder_level: str
    reason_code: str
    message: str
    related_size: Optional[str]
    related_metric: Optional[float]
    threshold_value: Optional[float]
    triggered_at: datetime
    resolved: bool
    resolved_at: Optional[datetime]

    class Config:
        from_attributes = True


class PlanningQueryParams(BaseModel):
    baby_id: int
    planning_period_days: int = Field(default=30, ge=1, le=365, description="计划周期天数")

    @field_validator("planning_period_days")
    @classmethod
    def check_period(cls, v: int) -> int:
        return validate_planning_period(v)


class SizeTransitionWindow(BaseModel):
    size: str
    start_date: str
    end_date: str
    peak_date: str
    duration_days: int
    confidence: float
    transition_type: str


class RecommendedPurchaseItem(BaseModel):
    size: str
    recommended_pieces: int
    recommended_packs: float
    current_inventory: int
    daily_usage_rate: float
    estimated_days_coverage: float
    purchase_priority: str
    priority_score: float
    is_current_size: bool
    is_next_size: bool


class OverstockRiskItem(BaseModel):
    size: str
    current_inventory: int
    daily_usage_rate: float
    estimated_stock_duration_days: float
    expected_usage_period_days: float
    overstock_pieces: int
    overstock_packs: float
    risk_level: str
    waste_risk_pct: float


class NextSizeReadiness(BaseModel):
    size: str
    readiness_score: float
    readiness_level: str
    estimated_days_to_start: int
    estimated_start_date: str
    current_inventory: int
    recommended_pre_stock_pieces: int
    weight_progress_pct: float


class PlanReminderItem(BaseModel):
    reminder_type: str
    reminder_level: str
    reason_code: str
    message: str
    related_size: Optional[str]
    related_metric: Optional[float]
    threshold_value: Optional[float]
    action_suggestion: str


VALID_CAREGIVER_ROLES = ["parent", "grandparent", "nanny", "temp"]
VALID_HANDOVER_ITEM_TYPES = ["anomaly", "reminder", "completed_care", "note"]
VALID_HANDOVER_PRIORITIES = ["urgent", "high", "normal", "low"]
VALID_TODO_TASK_TYPES = ["diaper_change", "feeding", "medication", "bath", "sleep", "other"]
VALID_SHIFT_STATUSES = ["active", "ended"]


def validate_datetime_format(v: str) -> str:
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M"):
        try:
            datetime.strptime(v, fmt)
            return v
        except ValueError:
            continue
    raise ValueError("日期时间格式必须为 YYYY-MM-DDTHH:MM:SS 或 YYYY-MM-DD HH:MM:SS")


def validate_caregiver_role(v: str) -> str:
    if v not in VALID_CAREGIVER_ROLES:
        raise ValueError(f"照护人角色必须是以下之一: {', '.join(VALID_CAREGIVER_ROLES)}")
    return v


def validate_handover_item_type(v: str) -> str:
    if v not in VALID_HANDOVER_ITEM_TYPES:
        raise ValueError(f"交接事项类型必须是以下之一: {', '.join(VALID_HANDOVER_ITEM_TYPES)}")
    return v


def validate_handover_priority(v: str) -> str:
    if v not in VALID_HANDOVER_PRIORITIES:
        raise ValueError(f"优先级必须是以下之一: {', '.join(VALID_HANDOVER_PRIORITIES)}")
    return v


def validate_todo_task_type(v: str) -> str:
    if v not in VALID_TODO_TASK_TYPES:
        raise ValueError(f"任务类型必须是以下之一: {', '.join(VALID_TODO_TASK_TYPES)}")
    return v


def validate_shift_status(v: str) -> str:
    if v not in VALID_SHIFT_STATUSES:
        raise ValueError(f"班次状态必须是以下之一: {', '.join(VALID_SHIFT_STATUSES)}")
    return v


class CaregiverCreate(BaseModel):
    baby_id: int = Field(..., description="宝宝ID")
    name: str = Field(..., min_length=1, max_length=100, description="照护人姓名")
    role: str = Field(..., description="角色 parent/grandparent/nanny/temp")
    phone: Optional[str] = Field(default=None, max_length=30, description="联系电话")
    notes: Optional[str] = Field(default=None, max_length=500, description="备注")

    @field_validator("role")
    @classmethod
    def check_role(cls, v: str) -> str:
        return validate_caregiver_role(v)


class CaregiverUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    role: Optional[str] = None
    phone: Optional[str] = Field(default=None, max_length=30)
    notes: Optional[str] = Field(default=None, max_length=500)
    is_active: Optional[bool] = None

    @field_validator("role")
    @classmethod
    def check_role(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validate_caregiver_role(v)
        return v


class CaregiverResponse(BaseModel):
    id: int
    baby_id: int
    name: str
    role: str
    phone: Optional[str]
    notes: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ShiftCreate(BaseModel):
    baby_id: int = Field(..., description="宝宝ID")
    caregiver_id: int = Field(..., description="照护人ID")
    shift_start: str = Field(..., description="班次开始时间")
    inventory_snapshot: Optional[str] = Field(default=None, description="接班库存快照JSON")
    previous_shift_anomalies: Optional[str] = Field(default=None, description="上一班异常事项")
    notes: Optional[str] = Field(default=None, max_length=1000, description="备注")

    @field_validator("shift_start")
    @classmethod
    def check_shift_start(cls, v: str) -> str:
        return validate_datetime_format(v)


class ShiftEnd(BaseModel):
    shift_end: str = Field(..., description="班次结束时间")
    inventory_snapshot: Optional[str] = Field(default=None, description="交班库存快照JSON")
    notes: Optional[str] = Field(default=None, max_length=1000, description="备注")

    @field_validator("shift_end")
    @classmethod
    def check_shift_end(cls, v: str) -> str:
        return validate_datetime_format(v)


class ShiftResponse(BaseModel):
    id: int
    baby_id: int
    caregiver_id: int
    shift_start: datetime
    shift_end: Optional[datetime]
    inventory_snapshot: Optional[str]
    previous_shift_anomalies: Optional[str]
    notes: Optional[str]
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class HandoverItemCreate(BaseModel):
    shift_id: int = Field(..., description="班次ID")
    baby_id: int = Field(..., description="宝宝ID")
    caregiver_id: int = Field(..., description="照护人ID")
    item_type: str = Field(..., description="交接事项类型 anomaly/reminder/completed_care/note")
    content: str = Field(..., min_length=1, max_length=1000, description="事项内容")
    priority: Optional[str] = Field(default="normal", description="优先级 urgent/high/normal/low")

    @field_validator("item_type")
    @classmethod
    def check_item_type(cls, v: str) -> str:
        return validate_handover_item_type(v)

    @field_validator("priority")
    @classmethod
    def check_priority(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validate_handover_priority(v)
        return v


class HandoverItemUpdate(BaseModel):
    content: Optional[str] = Field(default=None, min_length=1, max_length=1000)
    priority: Optional[str] = None
    is_resolved: Optional[bool] = None

    @field_validator("priority")
    @classmethod
    def check_priority(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validate_handover_priority(v)
        return v


class HandoverItemResponse(BaseModel):
    id: int
    shift_id: int
    baby_id: int
    caregiver_id: int
    item_type: str
    content: str
    priority: str
    is_resolved: bool
    resolved_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class TodoTaskCreate(BaseModel):
    shift_id: int = Field(..., description="班次ID")
    baby_id: int = Field(..., description="宝宝ID")
    caregiver_id: int = Field(..., description="照护人ID")
    task_type: str = Field(..., description="任务类型 diaper_change/feeding/medication/bath/sleep/other")
    description: str = Field(..., min_length=1, max_length=500, description="任务描述")
    due_time: Optional[str] = Field(default=None, description="截止时间")
    notes: Optional[str] = Field(default=None, max_length=500, description="备注")

    @field_validator("task_type")
    @classmethod
    def check_task_type(cls, v: str) -> str:
        return validate_todo_task_type(v)

    @field_validator("due_time")
    @classmethod
    def check_due_time(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validate_datetime_format(v)
        return v


class TodoTaskComplete(BaseModel):
    is_completed: bool = Field(default=True, description="是否已完成")
    completed_by_caregiver_id: int = Field(..., description="完成人照护人ID")
    notes: Optional[str] = Field(default=None, max_length=500, description="备注")


class TodoTaskResponse(BaseModel):
    id: int
    shift_id: int
    baby_id: int
    caregiver_id: int
    task_type: str
    description: str
    due_time: Optional[datetime]
    is_completed: bool
    completed_at: Optional[datetime]
    completed_by_caregiver_id: Optional[int]
    notes: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


CAREGIVER_ROLE_PERMISSIONS = {
    "parent": {
        "name": "父母",
        "description": "拥有全部权限，可管理照护人、查看所有数据、执行所有操作",
        "permissions": [
            "manage_caregivers",
            "view_all_records",
            "create_shifts",
            "end_shifts",
            "create_handover_items",
            "manage_todo_tasks",
            "view_summary",
            "view_risks",
            "view_statistics"
        ]
    },
    "grandparent": {
        "name": "祖辈",
        "description": "可执行日常照护、查看班次和交接事项",
        "permissions": [
            "view_all_records",
            "create_shifts",
            "end_shifts",
            "create_handover_items",
            "manage_todo_tasks",
            "view_summary",
            "view_risks"
        ]
    },
    "nanny": {
        "name": "保姆",
        "description": "可执行日常照护、记录交接事项和完成任务",
        "permissions": [
            "create_shifts",
            "end_shifts",
            "create_handover_items",
            "manage_todo_tasks",
            "view_summary"
        ]
    },
    "temp": {
        "name": "临时照护人",
        "description": "仅可查看自己的班次和待办任务",
        "permissions": [
            "create_handover_items",
            "manage_todo_tasks"
        ]
    }
}


class RolePermissionResponse(BaseModel):
    role: str
    name: str
    description: str
    permissions: List[str]


class ShiftDetailResponse(BaseModel):
    id: int
    baby_id: int
    caregiver_id: int
    caregiver_name: Optional[str] = None
    caregiver_role: Optional[str] = None
    shift_start: datetime
    shift_end: Optional[datetime]
    inventory_snapshot: Optional[str]
    previous_shift_anomalies: Optional[str]
    notes: Optional[str]
    status: str
    handover_item_count: int = 0
    todo_task_count: int = 0
    completed_task_count: int = 0
    created_at: datetime
    updated_at: datetime


class HandoverSummaryResponse(BaseModel):
    baby_id: int
    baby_name: str
    current_size: str
    generated_at: str
    recent_consumption: Dict[str, Any]
    current_inventory: List[Dict[str, Any]]
    unresolved_plan_reminders: List[Dict[str, Any]]
    shift_summaries: List[Dict[str, Any]]
    collaboration_risks: List[Dict[str, Any]]
    risk_summary: Dict[str, int]


class CollaborationRiskResponse(BaseModel):
    risk_type: str
    severity: str
    message: str
    details: Dict[str, Any]


class RiskListResponse(BaseModel):
    baby_id: int
    total_count: int
    high_count: int
    medium_count: int
    low_count: int
    risks: List[Dict[str, Any]]


class CaregiverWorkloadResponse(BaseModel):
    baby_id: int
    period_days: int
    caregivers: List[Dict[str, Any]]
    summary: Dict[str, Any]


VALID_RASH_GRADES = [0, 1, 2, 3, 4]
VALID_CARE_ACTIONS = ["clean", "air_dry", "apply_cream", "change_diaper", "other"]
VALID_PRODUCT_TYPES = ["diaper", "wipe", "rash_cream", "cleanser", "other"]
RASH_GRADE_DESCRIPTIONS = {
    0: "正常皮肤，无红疹",
    1: "轻度：皮肤微红，无破损",
    2: "中度：明显红疹，局部肿胀",
    3: "重度：广泛红疹，有破皮",
    4: "严重：破皮渗液，可能感染"
}


def validate_rash_grade(v: int) -> int:
    if v not in VALID_RASH_GRADES:
        raise ValueError(f"红疹等级必须是以下之一: {', '.join(map(str, VALID_RASH_GRADES))}")
    return v


def validate_care_action(v: str) -> str:
    if v and v.lower() not in VALID_CARE_ACTIONS:
        raise ValueError(f"护理动作类型必须是以下之一: {', '.join(VALID_CARE_ACTIONS)}")
    return v.lower() if v else v


def validate_care_actions_list(v: str) -> str:
    if not v:
        return v
    actions = [a.strip().lower() for a in v.split(",")]
    for action in actions:
        if action and action not in VALID_CARE_ACTIONS:
            raise ValueError(f"护理动作 '{action}' 无效，必须是以下之一: {', '.join(VALID_CARE_ACTIONS)}")
    return ",".join(actions)


def validate_product_type(v: str) -> str:
    if v and v.lower() not in VALID_PRODUCT_TYPES:
        raise ValueError(f"用品类型必须是以下之一: {', '.join(VALID_PRODUCT_TYPES)}")
    return v.lower() if v else v


def validate_non_negative(v: float) -> float:
    if v is not None and v < 0:
        raise ValueError("数值不能为负数")
    return v


class SkinObservationCreate(BaseModel):
    baby_id: int = Field(..., description="宝宝ID")
    caregiver_id: int = Field(..., description="照护人ID")
    observation_time: str = Field(..., description="观察时间 YYYY-MM-DDTHH:MM:SS")
    rash_grade: int = Field(..., description="红疹等级 0-4")
    has_redness: Optional[bool] = Field(default=False, description="是否有发红")
    has_breakdown: Optional[bool] = Field(default=False, description="是否有破皮")
    has_exudate: Optional[bool] = Field(default=False, description="是否有渗液")
    skin_location: Optional[str] = Field(default=None, max_length=100, description="皮肤部位")
    care_actions: Optional[str] = Field(default=None, max_length=200, description="护理动作，多个用逗号分隔")
    notes: Optional[str] = Field(default=None, max_length=1000, description="备注")
    change_frequency_24h: Optional[int] = Field(default=0, ge=0, description="近24小时更换频率")
    nighttime_leaks: Optional[int] = Field(default=0, ge=0, description="夜间漏尿次数")
    diaper_brand: Optional[str] = Field(default=None, max_length=100, description="纸尿裤品牌")
    diaper_batch: Optional[str] = Field(default=None, max_length=100, description="纸尿裤批次")

    @field_validator("observation_time")
    @classmethod
    def check_observation_time(cls, v: str) -> str:
        return validate_datetime_format(v)

    @field_validator("rash_grade")
    @classmethod
    def check_rash_grade(cls, v: int) -> int:
        return validate_rash_grade(v)

    @field_validator("care_actions")
    @classmethod
    def check_care_actions(cls, v: Optional[str]) -> Optional[str]:
        return validate_care_actions_list(v) if v is not None else v

    @field_validator("change_frequency_24h", "nighttime_leaks")
    @classmethod
    def check_non_negative_int(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("数值不能为负数")
        return v


class SkinObservationUpdate(BaseModel):
    rash_grade: Optional[int] = None
    has_redness: Optional[bool] = None
    has_breakdown: Optional[bool] = None
    has_exudate: Optional[bool] = None
    skin_location: Optional[str] = Field(default=None, max_length=100)
    care_actions: Optional[str] = Field(default=None, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=1000)
    change_frequency_24h: Optional[int] = Field(default=None, ge=0)
    nighttime_leaks: Optional[int] = Field(default=None, ge=0)
    diaper_brand: Optional[str] = Field(default=None, max_length=100)
    diaper_batch: Optional[str] = Field(default=None, max_length=100)

    @field_validator("rash_grade")
    @classmethod
    def check_rash_grade(cls, v: Optional[int]) -> Optional[int]:
        return validate_rash_grade(v) if v is not None else v

    @field_validator("care_actions")
    @classmethod
    def check_care_actions(cls, v: Optional[str]) -> Optional[str]:
        return validate_care_actions_list(v) if v is not None else v

    @field_validator("change_frequency_24h", "nighttime_leaks")
    @classmethod
    def check_non_negative_int(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("数值不能为负数")
        return v


class SkinObservationResponse(BaseModel):
    id: int
    baby_id: int
    caregiver_id: int
    observation_time: datetime
    rash_grade: int
    rash_grade_description: Optional[str] = None
    has_redness: bool
    has_breakdown: bool
    has_exudate: bool
    skin_location: Optional[str]
    care_actions: Optional[str]
    notes: Optional[str]
    change_frequency_24h: int
    nighttime_leaks: int
    diaper_brand: Optional[str]
    diaper_batch: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CareProductCreate(BaseModel):
    baby_id: int = Field(..., description="宝宝ID")
    product_type: str = Field(..., description="用品类型 diaper/wipe/rash_cream/cleanser/other")
    brand: str = Field(..., min_length=1, max_length=100, description="品牌")
    product_name: Optional[str] = Field(default=None, max_length=200, description="产品名称")
    batch_number: Optional[str] = Field(default=None, max_length=100, description="批次号")
    size: Optional[str] = Field(default=None, max_length=50, description="尺码/规格")
    start_date: Optional[str] = Field(default=None, description="开始使用日期 YYYY-MM-DD")
    end_date: Optional[str] = Field(default=None, description="停止使用日期 YYYY-MM-DD")
    is_active: Optional[bool] = Field(default=True, description="是否正在使用")
    ingredients: Optional[str] = Field(default=None, description="成分说明")
    notes: Optional[str] = Field(default=None, max_length=1000, description="备注")

    @field_validator("product_type")
    @classmethod
    def check_product_type(cls, v: str) -> str:
        return validate_product_type(v)

    @field_validator("start_date", "end_date")
    @classmethod
    def check_date_format(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validate_date_format(v)
        return v


class CareProductUpdate(BaseModel):
    product_type: Optional[str] = None
    brand: Optional[str] = Field(default=None, min_length=1, max_length=100)
    product_name: Optional[str] = Field(default=None, max_length=200)
    batch_number: Optional[str] = Field(default=None, max_length=100)
    size: Optional[str] = Field(default=None, max_length=50)
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    is_active: Optional[bool] = None
    ingredients: Optional[str] = None
    notes: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("product_type")
    @classmethod
    def check_product_type(cls, v: Optional[str]) -> Optional[str]:
        return validate_product_type(v) if v is not None else v

    @field_validator("start_date", "end_date")
    @classmethod
    def check_date_format(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validate_date_format(v)
        return v


class CareProductResponse(BaseModel):
    id: int
    baby_id: int
    product_type: str
    brand: str
    product_name: Optional[str]
    batch_number: Optional[str]
    size: Optional[str]
    start_date: Optional[str]
    end_date: Optional[str]
    is_active: bool
    ingredients: Optional[str]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProductUsageCreate(BaseModel):
    baby_id: int = Field(..., description="宝宝ID")
    product_id: int = Field(..., description="用品档案ID")
    skin_record_id: Optional[int] = Field(default=None, description="关联皮肤观察记录ID")
    caregiver_id: int = Field(..., description="照护人ID")
    usage_time: str = Field(..., description="使用时间 YYYY-MM-DDTHH:MM:SS")
    usage_amount: Optional[float] = Field(default=1.0, description="使用量")
    usage_notes: Optional[str] = Field(default=None, max_length=500, description="使用备注")

    @field_validator("usage_time")
    @classmethod
    def check_usage_time(cls, v: str) -> str:
        return validate_datetime_format(v)

    @field_validator("usage_amount")
    @classmethod
    def check_usage_amount(cls, v: Optional[float]) -> Optional[float]:
        return validate_non_negative(v) if v is not None else v


class ProductUsageResponse(BaseModel):
    id: int
    baby_id: int
    product_id: int
    product_name: Optional[str] = None
    product_brand: Optional[str] = None
    product_type: Optional[str] = None
    skin_record_id: Optional[int]
    caregiver_id: int
    caregiver_name: Optional[str] = None
    usage_time: datetime
    usage_amount: float
    usage_notes: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class RashRiskAssessment(BaseModel):
    baby_id: int
    assessment_time: str
    overall_risk_level: str
    overall_risk_score: float
    risk_factors: List[Dict[str, Any]]
    trend_analysis: Dict[str, Any]
    recommendations: List[Dict[str, Any]]


class AllergenCandidate(BaseModel):
    product_id: int
    product_name: str
    product_type: str
    brand: str
    correlation_score: float
    confidence: float
    evidence: List[str]
    recommendation: str


class CareEffectReview(BaseModel):
    baby_id: int
    review_period_days: int
    average_rash_grade_before: float
    average_rash_grade_after: float
    improvement_rate: float
    effective_care_actions: List[Dict[str, Any]]
    effective_products: List[Dict[str, Any]]
    ineffective_interventions: List[Dict[str, Any]]
    suggestions: List[str]


class SkinCareAlertResponse(BaseModel):
    id: int
    baby_id: int
    alert_type: str
    alert_level: str
    risk_score: float
    message: str
    related_record_id: Optional[int]
    related_product_id: Optional[int]
    triggered_at: datetime
    resolved: bool
    resolved_at: Optional[datetime]
    resolution_notes: Optional[str]

    class Config:
        from_attributes = True

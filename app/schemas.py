from pydantic import BaseModel, Field, field_validator
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

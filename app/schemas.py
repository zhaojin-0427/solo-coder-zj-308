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

    @field_validator("diaper_size")
    @classmethod
    def check_diaper_size(cls, v: str) -> str:
        return validate_diaper_size(v)


class AlertResolve(BaseModel):
    resolved: bool = Field(default=True, description="是否已解决")

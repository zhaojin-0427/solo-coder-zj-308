from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class ApiResponse(BaseModel):
    code: int = Field(default=200, description="响应码")
    message: str = Field(default="success", description="响应消息")
    data: Optional[Any] = Field(default=None, description="响应数据")


class BabyCreate(BaseModel):
    name: str = Field(..., description="宝宝姓名")
    birth_date: str = Field(..., description="出生日期 YYYY-MM-DD")
    current_age_months: int = Field(..., description="当前月龄")
    current_weight_kg: float = Field(..., description="当前体重(kg)")
    current_diaper_size: str = Field(..., description="当前纸尿裤尺码 NB/S/M/L/XL/XXL")
    gender: Optional[str] = Field(default=None, description="性别")


class BabyUpdate(BaseModel):
    name: Optional[str] = None
    birth_date: Optional[str] = None
    current_age_months: Optional[int] = None
    current_weight_kg: Optional[float] = None
    current_diaper_size: Optional[str] = None
    gender: Optional[str] = None


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
    daily_changes: int = Field(..., description="当日更换次数")
    nighttime_changes: Optional[int] = Field(default=0, description="夜间更换次数")
    nighttime_leaks: Optional[int] = Field(default=0, description="夜间漏尿次数")
    weight_kg: Optional[float] = Field(default=None, description="当日体重")
    notes: Optional[str] = Field(default=None, description="备注")


class InventoryRecordCreate(BaseModel):
    baby_id: int = Field(..., description="宝宝ID")
    record_date: str = Field(..., description="记录日期 YYYY-MM-DD")
    diaper_size: str = Field(..., description="纸尿裤尺码")
    quantity: int = Field(..., description="库存数量")
    unit: Optional[str] = Field(default="pieces", description="单位")
    notes: Optional[str] = Field(default=None, description="备注")


class AlertResolve(BaseModel):
    resolved: bool = Field(default=True, description="是否已解决")

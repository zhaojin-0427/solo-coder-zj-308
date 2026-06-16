from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base


class Baby(Base):
    __tablename__ = "babies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    birth_date = Column(String(20), nullable=False)
    current_age_months = Column(Integer, nullable=False)
    current_weight_kg = Column(Float, nullable=False)
    current_diaper_size = Column(String(20), nullable=False)
    gender = Column(String(10))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    consumption_records = relationship("ConsumptionRecord", back_populates="baby")
    inventory_records = relationship("InventoryRecord", back_populates="baby")
    alerts = relationship("AlertRecord", back_populates="baby")
    growth_plan = relationship("GrowthPlan", back_populates="baby", uselist=False)
    package_specs = relationship("PackageSpec", back_populates="baby")
    plan_reminders = relationship("PlanReminder", back_populates="baby")


class DiaperSizeReference(Base):
    __tablename__ = "diaper_size_references"

    id = Column(Integer, primary_key=True, index=True)
    size = Column(String(20), unique=True, nullable=False)
    min_weight_kg = Column(Float, nullable=False)
    max_weight_kg = Column(Float, nullable=False)
    min_age_months = Column(Integer)
    max_age_months = Column(Integer)
    average_daily_usage = Column(Integer, default=6)
    description = Column(String(200))


class ConsumptionRecord(Base):
    __tablename__ = "consumption_records"

    id = Column(Integer, primary_key=True, index=True)
    baby_id = Column(Integer, ForeignKey("babies.id"), nullable=False)
    record_date = Column(String(20), nullable=False)
    diaper_size = Column(String(20), nullable=False)
    daily_changes = Column(Integer, nullable=False)
    nighttime_changes = Column(Integer, default=0)
    nighttime_leaks = Column(Integer, default=0)
    weight_kg = Column(Float)
    notes = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)

    baby = relationship("Baby", back_populates="consumption_records")


class InventoryRecord(Base):
    __tablename__ = "inventory_records"

    id = Column(Integer, primary_key=True, index=True)
    baby_id = Column(Integer, ForeignKey("babies.id"), nullable=False)
    record_date = Column(String(20), nullable=False)
    diaper_size = Column(String(20), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit = Column(String(20), default="pieces")
    notes = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)

    baby = relationship("Baby", back_populates="inventory_records")


class AlertRecord(Base):
    __tablename__ = "alert_records"

    id = Column(Integer, primary_key=True, index=True)
    baby_id = Column(Integer, ForeignKey("babies.id"), nullable=False)
    alert_type = Column(String(50), nullable=False)
    alert_level = Column(String(20), nullable=False)
    message = Column(String(500), nullable=False)
    related_size = Column(String(20))
    triggered_at = Column(DateTime, default=datetime.utcnow)
    resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime)

    baby = relationship("Baby", back_populates="alerts")


class GrowthPlan(Base):
    __tablename__ = "growth_plans"

    id = Column(Integer, primary_key=True, index=True)
    baby_id = Column(Integer, ForeignKey("babies.id"), nullable=False)
    target_weight_kg = Column(Float, nullable=True)
    target_date = Column(String(20), nullable=True)
    growth_rate_kg_per_month = Column(Float, nullable=True)
    promo_stocking_preference = Column(String(20), default="moderate")
    preferred_brand = Column(String(100), nullable=True)
    safety_stock_days = Column(Integer, default=7)
    planning_horizon_days = Column(Integer, default=90)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    baby = relationship("Baby", back_populates="growth_plan")


class PackageSpec(Base):
    __tablename__ = "package_specs"

    id = Column(Integer, primary_key=True, index=True)
    baby_id = Column(Integer, ForeignKey("babies.id"), nullable=False)
    brand = Column(String(100), nullable=False)
    size = Column(String(20), nullable=False)
    pieces_per_pack = Column(Integer, nullable=False)
    packs_per_box = Column(Integer, default=1)
    price_per_pack = Column(Float, nullable=True)
    is_active = Column(Boolean, default=True)
    notes = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    baby = relationship("Baby", back_populates="package_specs")


class PlanReminder(Base):
    __tablename__ = "plan_reminders"

    id = Column(Integer, primary_key=True, index=True)
    baby_id = Column(Integer, ForeignKey("babies.id"), nullable=False)
    reminder_type = Column(String(50), nullable=False)
    reminder_level = Column(String(20), nullable=False)
    reason_code = Column(String(50), nullable=False)
    message = Column(String(500), nullable=False)
    related_size = Column(String(20))
    related_metric = Column(Float, nullable=True)
    threshold_value = Column(Float, nullable=True)
    triggered_at = Column(DateTime, default=datetime.utcnow)
    resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime)

    baby = relationship("Baby", back_populates="plan_reminders")

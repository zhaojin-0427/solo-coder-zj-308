from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base


VALID_CAREGIVER_ROLES = ["parent", "grandparent", "nanny", "temp"]


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
    caregivers = relationship("Caregiver", back_populates="baby", cascade="all, delete-orphan")
    shifts = relationship("Shift", back_populates="baby", cascade="all, delete-orphan")


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


class Caregiver(Base):
    __tablename__ = "caregivers"

    id = Column(Integer, primary_key=True, index=True)
    baby_id = Column(Integer, ForeignKey("babies.id"), nullable=False)
    name = Column(String(100), nullable=False)
    role = Column(String(20), nullable=False)
    phone = Column(String(30))
    notes = Column(String(500))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    baby = relationship("Baby", back_populates="caregivers")
    shifts = relationship("Shift", back_populates="caregiver")
    handover_items = relationship("HandoverItem", back_populates="caregiver")
    todo_tasks = relationship("TodoTask", back_populates="caregiver", foreign_keys="TodoTask.caregiver_id")
    completed_tasks = relationship("TodoTask", back_populates="completed_by", foreign_keys="TodoTask.completed_by_caregiver_id")


class Shift(Base):
    __tablename__ = "shifts"

    id = Column(Integer, primary_key=True, index=True)
    baby_id = Column(Integer, ForeignKey("babies.id"), nullable=False)
    caregiver_id = Column(Integer, ForeignKey("caregivers.id"), nullable=False)
    shift_start = Column(DateTime, nullable=False)
    shift_end = Column(DateTime)
    inventory_snapshot = Column(Text)
    previous_shift_anomalies = Column(Text)
    notes = Column(String(1000))
    status = Column(String(20), default="active")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    baby = relationship("Baby", back_populates="shifts")
    caregiver = relationship("Caregiver", back_populates="shifts")
    handover_items = relationship("HandoverItem", back_populates="shift")
    todo_tasks = relationship("TodoTask", back_populates="shift")


class HandoverItem(Base):
    __tablename__ = "handover_items"

    id = Column(Integer, primary_key=True, index=True)
    shift_id = Column(Integer, ForeignKey("shifts.id"), nullable=False)
    baby_id = Column(Integer, ForeignKey("babies.id"), nullable=False)
    caregiver_id = Column(Integer, ForeignKey("caregivers.id"), nullable=False)
    item_type = Column(String(50), nullable=False)
    content = Column(String(1000), nullable=False)
    priority = Column(String(20), default="normal")
    is_resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    shift = relationship("Shift", back_populates="handover_items")
    baby = relationship("Baby")
    caregiver = relationship("Caregiver", back_populates="handover_items")


class TodoTask(Base):
    __tablename__ = "todo_tasks"

    id = Column(Integer, primary_key=True, index=True)
    shift_id = Column(Integer, ForeignKey("shifts.id"), nullable=False)
    baby_id = Column(Integer, ForeignKey("babies.id"), nullable=False)
    caregiver_id = Column(Integer, ForeignKey("caregivers.id"), nullable=False)
    task_type = Column(String(50), nullable=False)
    description = Column(String(500), nullable=False)
    due_time = Column(DateTime)
    is_completed = Column(Boolean, default=False)
    completed_at = Column(DateTime)
    completed_by_caregiver_id = Column(Integer, ForeignKey("caregivers.id"))
    notes = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)

    shift = relationship("Shift", back_populates="todo_tasks")
    baby = relationship("Baby")
    caregiver = relationship("Caregiver", back_populates="todo_tasks", foreign_keys=[caregiver_id])
    completed_by = relationship("Caregiver", back_populates="completed_tasks", foreign_keys=[completed_by_caregiver_id])


VALID_RASH_GRADES = [0, 1, 2, 3, 4]
VALID_CARE_ACTIONS = ["clean", "air_dry", "apply_cream", "change_diaper", "other"]
VALID_PRODUCT_TYPES = ["diaper", "wipe", "rash_cream", "cleanser", "other"]


class SkinObservationRecord(Base):
    __tablename__ = "skin_observation_records"

    id = Column(Integer, primary_key=True, index=True)
    baby_id = Column(Integer, ForeignKey("babies.id"), nullable=False)
    caregiver_id = Column(Integer, ForeignKey("caregivers.id"), nullable=False)
    observation_time = Column(DateTime, nullable=False)
    rash_grade = Column(Integer, nullable=False)
    has_redness = Column(Boolean, default=False)
    has_breakdown = Column(Boolean, default=False)
    has_exudate = Column(Boolean, default=False)
    skin_location = Column(String(100))
    care_actions = Column(String(200))
    notes = Column(String(1000))
    change_frequency_24h = Column(Integer, default=0)
    nighttime_leaks = Column(Integer, default=0)
    diaper_brand = Column(String(100))
    diaper_batch = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    baby = relationship("Baby")
    caregiver = relationship("Caregiver", foreign_keys=[caregiver_id])
    product_usage = relationship("ProductUsageLog", back_populates="skin_record", cascade="all, delete-orphan")


class CareProductArchive(Base):
    __tablename__ = "care_product_archives"

    id = Column(Integer, primary_key=True, index=True)
    baby_id = Column(Integer, ForeignKey("babies.id"), nullable=False)
    product_type = Column(String(50), nullable=False)
    brand = Column(String(100), nullable=False)
    product_name = Column(String(200))
    batch_number = Column(String(100))
    size = Column(String(50))
    start_date = Column(String(20))
    end_date = Column(String(20))
    is_active = Column(Boolean, default=True)
    ingredients = Column(Text)
    notes = Column(String(1000))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    baby = relationship("Baby")
    usage_logs = relationship("ProductUsageLog", back_populates="product")


class ProductUsageLog(Base):
    __tablename__ = "product_usage_logs"

    id = Column(Integer, primary_key=True, index=True)
    baby_id = Column(Integer, ForeignKey("babies.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("care_product_archives.id"), nullable=False)
    skin_record_id = Column(Integer, ForeignKey("skin_observation_records.id"))
    caregiver_id = Column(Integer, ForeignKey("caregivers.id"), nullable=False)
    usage_time = Column(DateTime, nullable=False)
    usage_amount = Column(Float, default=1.0)
    usage_notes = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)

    baby = relationship("Baby")
    product = relationship("CareProductArchive", back_populates="usage_logs")
    skin_record = relationship("SkinObservationRecord", back_populates="product_usage")
    caregiver = relationship("Caregiver", foreign_keys=[caregiver_id])


class SkinCareAlert(Base):
    __tablename__ = "skin_care_alerts"

    id = Column(Integer, primary_key=True, index=True)
    baby_id = Column(Integer, ForeignKey("babies.id"), nullable=False)
    alert_type = Column(String(50), nullable=False)
    alert_level = Column(String(20), nullable=False)
    risk_score = Column(Float, default=0.0)
    message = Column(String(500), nullable=False)
    related_record_id = Column(Integer)
    related_product_id = Column(Integer)
    triggered_at = Column(DateTime, default=datetime.utcnow)
    resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime)
    resolution_notes = Column(String(500))

    baby = relationship("Baby")

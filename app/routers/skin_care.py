from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List, Optional, Dict
from datetime import datetime, timedelta

from ..database import get_db
from ..models import (
    Baby, Caregiver, SkinObservationRecord, CareProductArchive, ProductUsageLog
)
from ..schemas import (
    SkinObservationCreate, SkinObservationUpdate, SkinObservationResponse,
    CareProductCreate, CareProductUpdate, CareProductResponse,
    ProductUsageCreate, ProductUsageResponse,
    RashRiskAssessment, AllergenCandidate, CareEffectReview,
    SkinCareAlertResponse, RASH_GRADE_DESCRIPTIONS,
    VALID_RASH_GRADES, VALID_CARE_ACTIONS, VALID_PRODUCT_TYPES,
    validate_datetime_format
)
from ..utils import success_response, not_found_response, bad_request_response
from ..skin_risk_scoring import SkinRiskScoringService
from ..allergy_attribution import AllergyAttributionService
from ..care_recommendation import CareRecommendationService
from ..skin_care_alerts import SkinCareAlertSystem


router = APIRouter(prefix="/api/skin-care", tags=["尿布区皮肤护理与过敏风险追踪"])


def _parse_datetime(v: str) -> Optional[datetime]:
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(v, fmt)
        except (ValueError, TypeError):
            continue
    return None


def _check_baby_exists(db: Session, baby_id: int) -> Optional[Baby]:
    return db.query(Baby).filter(Baby.id == baby_id).first()


def _check_caregiver_exists(db: Session, caregiver_id: int, baby_id: Optional[int] = None) -> Optional[Caregiver]:
    query = db.query(Caregiver).filter(Caregiver.id == caregiver_id)
    if baby_id is not None:
        query = query.filter(Caregiver.baby_id == baby_id)
    return query.first()


def _check_skin_record_exists(db: Session, record_id: int, baby_id: Optional[int] = None) -> Optional[SkinObservationRecord]:
    query = db.query(SkinObservationRecord).filter(SkinObservationRecord.id == record_id)
    if baby_id is not None:
        query = query.filter(SkinObservationRecord.baby_id == baby_id)
    return query.first()


def _check_product_exists(db: Session, product_id: int, baby_id: Optional[int] = None) -> Optional[CareProductArchive]:
    query = db.query(CareProductArchive).filter(CareProductArchive.id == product_id)
    if baby_id is not None:
        query = query.filter(CareProductArchive.baby_id == baby_id)
    return query.first()


# ==================== 枚举类型接口 ====================

@router.get("/rash-grades", summary="获取红疹等级说明")
def get_rash_grades():
    grades = []
    for grade in VALID_RASH_GRADES:
        grades.append({
            "grade": grade,
            "description": RASH_GRADE_DESCRIPTIONS.get(grade, "")
        })
    return success_response(grades)


@router.get("/care-actions", summary="获取护理动作类型列表")
def get_care_actions():
    action_names = {
        "clean": "清洁",
        "air_dry": "风干",
        "apply_cream": "涂抹护臀膏",
        "change_diaper": "更换纸尿裤",
        "other": "其他"
    }
    actions = []
    for action in VALID_CARE_ACTIONS:
        actions.append({
            "type": action,
            "name": action_names.get(action, action)
        })
    return success_response(actions)


@router.get("/product-types", summary="获取护理用品类型列表")
def get_product_types():
    type_names = {
        "diaper": "纸尿裤",
        "wipe": "湿巾",
        "rash_cream": "护臀膏",
        "cleanser": "清洁用品",
        "other": "其他"
    }
    types = []
    for ptype in VALID_PRODUCT_TYPES:
        types.append({
            "type": ptype,
            "name": type_names.get(ptype, ptype)
        })
    return success_response(types)


# ==================== 皮肤观察记录接口 ====================

@router.post("/observations", summary="新增皮肤观察记录")
def create_skin_observation(
    observation_data: SkinObservationCreate,
    db: Session = Depends(get_db)
):
    baby = _check_baby_exists(db, observation_data.baby_id)
    if not baby:
        return not_found_response("宝宝不存在")

    caregiver = _check_caregiver_exists(db, observation_data.caregiver_id, observation_data.baby_id)
    if not caregiver:
        return not_found_response("照护人不存在或不属于该宝宝")

    observation_time = _parse_datetime(observation_data.observation_time)
    if not observation_time:
        return bad_request_response("观察时间格式不正确")

    try:
        db_record = SkinObservationRecord(
            baby_id=observation_data.baby_id,
            caregiver_id=observation_data.caregiver_id,
            observation_time=observation_time,
            rash_grade=observation_data.rash_grade,
            has_redness=observation_data.has_redness or False,
            has_breakdown=observation_data.has_breakdown or False,
            has_exudate=observation_data.has_exudate or False,
            skin_location=observation_data.skin_location,
            care_actions=observation_data.care_actions,
            notes=observation_data.notes,
            change_frequency_24h=observation_data.change_frequency_24h or 0,
            nighttime_leaks=observation_data.nighttime_leaks or 0,
            diaper_brand=observation_data.diaper_brand,
            diaper_batch=observation_data.diaper_batch
        )
        db.add(db_record)
        db.commit()
        db.refresh(db_record)

        alert_system = SkinCareAlertSystem(db)
        risk_assessment = alert_system.evaluate_diaper_rash_risk(observation_data.baby_id)

        response_data = SkinObservationResponse.model_validate(db_record).model_dump()
        response_data["rash_grade_description"] = RASH_GRADE_DESCRIPTIONS.get(db_record.rash_grade, "")

        return success_response({
            "record": response_data,
            "risk_assessment": {
                "risk_level": risk_assessment["overall_risk"]["risk_level"],
                "risk_score": risk_assessment["overall_risk"]["risk_score"]
            }
        }, "皮肤观察记录创建成功")
    except Exception as e:
        db.rollback()
        return bad_request_response(f"创建失败: {str(e)}")


@router.get("/observations", summary="获取皮肤观察记录列表")
def get_skin_observations(
    baby_id: int = Query(..., description="宝宝ID"),
    rash_grade: Optional[int] = Query(default=None, description="红疹等级筛选"),
    start_date: Optional[str] = Query(default=None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(default=None, description="结束日期 YYYY-MM-DD"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db)
):
    baby = _check_baby_exists(db, baby_id)
    if not baby:
        return not_found_response("宝宝不存在")

    query = db.query(SkinObservationRecord).filter(SkinObservationRecord.baby_id == baby_id)

    if rash_grade is not None:
        if rash_grade not in VALID_RASH_GRADES:
            return bad_request_response(f"红疹等级必须是以下之一: {', '.join(map(str, VALID_RASH_GRADES))}")
        query = query.filter(SkinObservationRecord.rash_grade == rash_grade)

    if start_date:
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            query = query.filter(SkinObservationRecord.observation_time >= start_dt)
        except ValueError:
            return bad_request_response("开始日期格式不正确，应为 YYYY-MM-DD")

    if end_date:
        try:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(SkinObservationRecord.observation_time < end_dt)
        except ValueError:
            return bad_request_response("结束日期格式不正确，应为 YYYY-MM-DD")

    total = query.count()
    records = query.order_by(SkinObservationRecord.observation_time.desc()).offset(
        (page - 1) * page_size).limit(page_size).all()

    caregiver_map = {}
    for r in records:
        if r.caregiver_id not in caregiver_map:
            cg = db.query(Caregiver).filter(Caregiver.id == r.caregiver_id).first()
            caregiver_map[r.caregiver_id] = cg

    record_list = []
    for r in records:
        cg = caregiver_map.get(r.caregiver_id)
        record_dict = SkinObservationResponse.model_validate(r).model_dump()
        record_dict["rash_grade_description"] = RASH_GRADE_DESCRIPTIONS.get(r.rash_grade, "")
        record_dict["caregiver_name"] = cg.name if cg else None
        record_list.append(record_dict)

    return success_response({
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": record_list
    })


@router.get("/observations/{record_id}", summary="获取皮肤观察记录详情")
def get_skin_observation(
    record_id: int,
    db: Session = Depends(get_db)
):
    record = _check_skin_record_exists(db, record_id)
    if not record:
        return not_found_response("皮肤观察记录不存在")

    caregiver = _check_caregiver_exists(db, record.caregiver_id)

    record_dict = SkinObservationResponse.model_validate(record).model_dump()
    record_dict["rash_grade_description"] = RASH_GRADE_DESCRIPTIONS.get(record.rash_grade, "")
    record_dict["caregiver_name"] = caregiver.name if caregiver else None

    product_usage = db.query(ProductUsageLog).filter(
        ProductUsageLog.skin_record_id == record_id
    ).all()

    record_dict["product_usage"] = [
        {
            "id": pu.id,
            "product_id": pu.product_id,
            "usage_time": pu.usage_time,
            "usage_amount": pu.usage_amount
        }
        for pu in product_usage
    ]

    return success_response(record_dict)


@router.put("/observations/{record_id}", summary="更新皮肤观察记录")
def update_skin_observation(
    record_id: int,
    update_data: SkinObservationUpdate,
    db: Session = Depends(get_db)
):
    record = _check_skin_record_exists(db, record_id)
    if not record:
        return not_found_response("皮肤观察记录不存在")

    try:
        update_dict = update_data.model_dump(exclude_unset=True)
        for key, value in update_dict.items():
            setattr(record, key, value)
        record.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(record)

        response_data = SkinObservationResponse.model_validate(record).model_dump()
        response_data["rash_grade_description"] = RASH_GRADE_DESCRIPTIONS.get(record.rash_grade, "")

        return success_response(response_data, "更新成功")
    except Exception as e:
        db.rollback()
        return bad_request_response(f"更新失败: {str(e)}")


@router.delete("/observations/{record_id}", summary="删除皮肤观察记录")
def delete_skin_observation(
    record_id: int,
    db: Session = Depends(get_db)
):
    record = _check_skin_record_exists(db, record_id)
    if not record:
        return not_found_response("皮肤观察记录不存在")

    try:
        db.delete(record)
        db.commit()
        return success_response(None, "删除成功")
    except Exception as e:
        db.rollback()
        return bad_request_response(f"删除失败: {str(e)}")


# ==================== 护理用品档案接口 ====================

@router.post("/products", summary="新增护理用品档案")
def create_care_product(
    product_data: CareProductCreate,
    db: Session = Depends(get_db)
):
    baby = _check_baby_exists(db, product_data.baby_id)
    if not baby:
        return not_found_response("宝宝不存在")

    try:
        db_product = CareProductArchive(
            baby_id=product_data.baby_id,
            product_type=product_data.product_type,
            brand=product_data.brand,
            product_name=product_data.product_name,
            batch_number=product_data.batch_number,
            size=product_data.size,
            start_date=product_data.start_date,
            end_date=product_data.end_date,
            is_active=product_data.is_active if product_data.is_active is not None else True,
            ingredients=product_data.ingredients,
            notes=product_data.notes
        )
        db.add(db_product)
        db.commit()
        db.refresh(db_product)

        return success_response(
            CareProductResponse.model_validate(db_product).model_dump(),
            "护理用品档案创建成功"
        )
    except Exception as e:
        db.rollback()
        return bad_request_response(f"创建失败: {str(e)}")


@router.get("/products", summary="获取护理用品档案列表")
def get_care_products(
    baby_id: int = Query(..., description="宝宝ID"),
    product_type: Optional[str] = Query(default=None, description="用品类型筛选"),
    is_active: Optional[bool] = Query(default=None, description="是否仅显示正在使用的"),
    brand: Optional[str] = Query(default=None, description="品牌筛选"),
    db: Session = Depends(get_db)
):
    baby = _check_baby_exists(db, baby_id)
    if not baby:
        return not_found_response("宝宝不存在")

    query = db.query(CareProductArchive).filter(CareProductArchive.baby_id == baby_id)

    if product_type:
        if product_type not in VALID_PRODUCT_TYPES:
            return bad_request_response(f"用品类型必须是以下之一: {', '.join(VALID_PRODUCT_TYPES)}")
        query = query.filter(CareProductArchive.product_type == product_type)

    if is_active is not None:
        query = query.filter(CareProductArchive.is_active == is_active)

    if brand:
        query = query.filter(CareProductArchive.brand.like(f"%{brand}%"))

    products = query.order_by(CareProductArchive.created_at.desc()).all()

    return success_response([
        CareProductResponse.model_validate(p).model_dump()
        for p in products
    ])


@router.get("/products/{product_id}", summary="获取护理用品档案详情")
def get_care_product(
    product_id: int,
    db: Session = Depends(get_db)
):
    product = _check_product_exists(db, product_id)
    if not product:
        return not_found_response("护理用品档案不存在")

    product_dict = CareProductResponse.model_validate(product).model_dump()

    usage_count = db.query(ProductUsageLog).filter(
        ProductUsageLog.product_id == product_id
    ).count()

    product_dict["usage_count"] = usage_count

    return success_response(product_dict)


@router.put("/products/{product_id}", summary="更新护理用品档案")
def update_care_product(
    product_id: int,
    update_data: CareProductUpdate,
    db: Session = Depends(get_db)
):
    product = _check_product_exists(db, product_id)
    if not product:
        return not_found_response("护理用品档案不存在")

    try:
        update_dict = update_data.model_dump(exclude_unset=True)
        for key, value in update_dict.items():
            setattr(product, key, value)
        product.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(product)

        return success_response(
            CareProductResponse.model_validate(product).model_dump(),
            "更新成功"
        )
    except Exception as e:
        db.rollback()
        return bad_request_response(f"更新失败: {str(e)}")


@router.delete("/products/{product_id}", summary="删除护理用品档案")
def delete_care_product(
    product_id: int,
    db: Session = Depends(get_db)
):
    product = _check_product_exists(db, product_id)
    if not product:
        return not_found_response("护理用品档案不存在")

    usage_count = db.query(ProductUsageLog).filter(
        ProductUsageLog.product_id == product_id
    ).count()

    if usage_count > 0:
        return bad_request_response(f"该用品已有{usage_count}条使用记录，无法删除，请先停用")

    try:
        db.delete(product)
        db.commit()
        return success_response(None, "删除成功")
    except Exception as e:
        db.rollback()
        return bad_request_response(f"删除失败: {str(e)}")


# ==================== 产品使用日志接口 ====================

@router.post("/product-usage", summary="新增产品使用日志")
def create_product_usage(
    usage_data: ProductUsageCreate,
    db: Session = Depends(get_db)
):
    baby = _check_baby_exists(db, usage_data.baby_id)
    if not baby:
        return not_found_response("宝宝不存在")

    product = _check_product_exists(db, usage_data.product_id, usage_data.baby_id)
    if not product:
        return not_found_response("护理用品不存在或不属于该宝宝")

    caregiver = _check_caregiver_exists(db, usage_data.caregiver_id, usage_data.baby_id)
    if not caregiver:
        return not_found_response("照护人不存在或不属于该宝宝")

    if usage_data.skin_record_id:
        skin_record = _check_skin_record_exists(db, usage_data.skin_record_id, usage_data.baby_id)
        if not skin_record:
            return not_found_response("皮肤观察记录不存在或不属于该宝宝")

    usage_time = _parse_datetime(usage_data.usage_time)
    if not usage_time:
        return bad_request_response("使用时间格式不正确")

    try:
        db_usage = ProductUsageLog(
            baby_id=usage_data.baby_id,
            product_id=usage_data.product_id,
            skin_record_id=usage_data.skin_record_id,
            caregiver_id=usage_data.caregiver_id,
            usage_time=usage_time,
            usage_amount=usage_data.usage_amount or 1.0,
            usage_notes=usage_data.usage_notes
        )
        db.add(db_usage)
        db.commit()
        db.refresh(db_usage)

        response_data = ProductUsageResponse.model_validate(db_usage).model_dump()
        response_data["product_name"] = product.product_name or product.product_type
        response_data["product_brand"] = product.brand
        response_data["product_type"] = product.product_type
        response_data["caregiver_name"] = caregiver.name

        return success_response(response_data, "产品使用日志创建成功")
    except Exception as e:
        db.rollback()
        return bad_request_response(f"创建失败: {str(e)}")


@router.get("/product-usage", summary="获取产品使用日志列表")
def get_product_usage(
    baby_id: int = Query(..., description="宝宝ID"),
    product_id: Optional[int] = Query(default=None, description="用品ID筛选"),
    skin_record_id: Optional[int] = Query(default=None, description="关联皮肤记录ID筛选"),
    start_date: Optional[str] = Query(default=None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(default=None, description="结束日期 YYYY-MM-DD"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db)
):
    baby = _check_baby_exists(db, baby_id)
    if not baby:
        return not_found_response("宝宝不存在")

    query = db.query(ProductUsageLog).filter(ProductUsageLog.baby_id == baby_id)

    if product_id:
        product = _check_product_exists(db, product_id, baby_id)
        if not product:
            return not_found_response("护理用品不存在或不属于该宝宝")
        query = query.filter(ProductUsageLog.product_id == product_id)

    if skin_record_id:
        record = _check_skin_record_exists(db, skin_record_id, baby_id)
        if not record:
            return not_found_response("皮肤观察记录不存在或不属于该宝宝")
        query = query.filter(ProductUsageLog.skin_record_id == skin_record_id)

    if start_date:
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            query = query.filter(ProductUsageLog.usage_time >= start_dt)
        except ValueError:
            return bad_request_response("开始日期格式不正确，应为 YYYY-MM-DD")

    if end_date:
        try:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(ProductUsageLog.usage_time < end_dt)
        except ValueError:
            return bad_request_response("结束日期格式不正确，应为 YYYY-MM-DD")

    total = query.count()
    logs = query.order_by(ProductUsageLog.usage_time.desc()).offset(
        (page - 1) * page_size).limit(page_size).all()

    product_map = {}
    caregiver_map = {}

    log_list = []
    for log in logs:
        if log.product_id not in product_map:
            product_map[log.product_id] = _check_product_exists(db, log.product_id)
        if log.caregiver_id not in caregiver_map:
            caregiver_map[log.caregiver_id] = _check_caregiver_exists(db, log.caregiver_id)

        product = product_map.get(log.product_id)
        caregiver = caregiver_map.get(log.caregiver_id)

        log_dict = ProductUsageResponse.model_validate(log).model_dump()
        log_dict["product_name"] = product.product_name or product.product_type if product else None
        log_dict["product_brand"] = product.brand if product else None
        log_dict["product_type"] = product.product_type if product else None
        log_dict["caregiver_name"] = caregiver.name if caregiver else None
        log_list.append(log_dict)

    return success_response({
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": log_list
    })


# ==================== 尿布疹风险评估接口 ====================

@router.get("/risk-assessment/{baby_id}", summary="尿布疹风险评估")
def get_rash_risk_assessment(
    baby_id: int,
    db: Session = Depends(get_db)
):
    baby = _check_baby_exists(db, baby_id)
    if not baby:
        return not_found_response("宝宝不存在")

    try:
        alert_system = SkinCareAlertSystem(db)
        assessment = alert_system.evaluate_diaper_rash_risk(baby_id)

        if "error" in assessment:
            return bad_request_response(assessment["error"])

        return success_response(assessment)
    except Exception as e:
        return bad_request_response(f"风险评估失败: {str(e)}")


# ==================== 疑似过敏源排序接口 ====================

@router.get("/allergens/{baby_id}", summary="疑似过敏源排序")
def get_suspected_allergens(
    baby_id: int,
    days: int = Query(default=30, ge=7, le=180, description="分析天数"),
    db: Session = Depends(get_db)
):
    baby = _check_baby_exists(db, baby_id)
    if not baby:
        return not_found_response("宝宝不存在")

    try:
        allergy_service = AllergyAttributionService(db)
        allergens = allergy_service.identify_suspected_allergens(baby_id, days=days)

        brand_sensitivity = allergy_service.analyze_brand_sensitivity(baby_id, days=days)

        return success_response({
            "baby_id": baby_id,
            "analysis_days": days,
            "suspected_allergens": allergens,
            "brand_sensitivity": brand_sensitivity
        })
    except Exception as e:
        return bad_request_response(f"过敏源分析失败: {str(e)}")


# ==================== 护理建议生成接口 ====================

@router.get("/recommendations/{baby_id}", summary="护理建议生成")
def get_care_recommendations(
    baby_id: int,
    db: Session = Depends(get_db)
):
    baby = _check_baby_exists(db, baby_id)
    if not baby:
        return not_found_response("宝宝不存在")

    try:
        recommendation_service = CareRecommendationService(db)
        recommendations = recommendation_service.generate_care_recommendations(baby_id)
        care_plan = recommendation_service.generate_care_plan(baby_id)

        return success_response({
            "baby_id": baby_id,
            "baby_name": baby.name,
            "recommendations": recommendations,
            "care_plan": care_plan
        })
    except Exception as e:
        return bad_request_response(f"生成护理建议失败: {str(e)}")


# ==================== 护理效果复盘接口 ====================

@router.get("/effect-review/{baby_id}", summary="护理效果复盘")
def get_care_effect_review(
    baby_id: int,
    intervention_date: str = Query(..., description="干预开始日期 YYYY-MM-DD"),
    db: Session = Depends(get_db)
):
    baby = _check_baby_exists(db, baby_id)
    if not baby:
        return not_found_response("宝宝不存在")

    try:
        datetime.strptime(intervention_date, "%Y-%m-%d")
    except ValueError:
        return bad_request_response("日期格式不正确，应为 YYYY-MM-DD")

    try:
        recommendation_service = CareRecommendationService(db)
        review = recommendation_service.review_care_effectiveness(baby_id, intervention_date)

        if "error" in review:
            return bad_request_response(review["error"])

        return success_response(review)
    except Exception as e:
        return bad_request_response(f"效果复盘失败: {str(e)}")


# ==================== 高风险提醒列表接口 ====================

@router.get("/alerts", summary="获取高风险提醒列表")
def get_high_risk_alerts(
    baby_id: Optional[int] = Query(default=None, description="宝宝ID（可选，不传则返回所有宝宝）"),
    resolved: Optional[bool] = Query(default=None, description="是否已解决"),
    severity: Optional[str] = Query(default=None, description="风险级别 critical/high/medium/low"),
    days: int = Query(default=30, ge=1, le=365, description="查询天数"),
    db: Session = Depends(get_db)
):
    if baby_id:
        baby = _check_baby_exists(db, baby_id)
        if not baby:
            return not_found_response("宝宝不存在")

    if severity and severity not in ["critical", "high", "medium", "low"]:
        return bad_request_response(f"风险级别必须是以下之一: critical, high, medium, low")

    try:
        alert_system = SkinCareAlertSystem(db)
        alerts = alert_system.get_high_risk_alerts(
            baby_id=baby_id,
            resolved=resolved,
            severity=severity,
            days=days
        )

        statistics = alert_system.get_alert_statistics(baby_id=baby_id, days=days)

        return success_response({
            "alerts": alerts,
            "statistics": statistics
        })
    except Exception as e:
        return bad_request_response(f"获取提醒列表失败: {str(e)}")


@router.get("/alerts/summary", summary="获取高风险提醒汇总")
def get_alert_summary(
    days: int = Query(default=7, ge=1, le=30, description="汇总天数"),
    db: Session = Depends(get_db)
):
    try:
        alert_system = SkinCareAlertSystem(db)
        summary = alert_system.get_alert_summary(days=days)
        return success_response(summary)
    except Exception as e:
        return bad_request_response(f"获取汇总信息失败: {str(e)}")


@router.put("/alerts/{alert_id}/resolve", summary="标记提醒为已解决")
def resolve_alert(
    alert_id: int,
    resolution_notes: Optional[str] = Query(default=None, description="处理说明"),
    db: Session = Depends(get_db)
):
    try:
        alert_system = SkinCareAlertSystem(db)
        alert = alert_system.resolve_alert(alert_id, resolved=True, resolution_notes=resolution_notes)

        if not alert:
            return not_found_response("提醒不存在")

        return success_response(
            SkinCareAlertResponse.model_validate(alert).model_dump(),
            "已标记为已解决"
        )
    except Exception as e:
        return bad_request_response(f"操作失败: {str(e)}")

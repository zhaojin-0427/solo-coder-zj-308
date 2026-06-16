from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from contextlib import asynccontextmanager

from app.database import engine, Base, SessionLocal
from app.models import (
    Baby, DiaperSizeReference, ConsumptionRecord, InventoryRecord, AlertRecord,
    GrowthPlan, PackageSpec, PlanReminder
)
from app.utils import init_size_references, success_response, error_response
from app.schemas import ApiResponse

from app.routers import babies, consumption, inventory, prediction, alerts, planning


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        init_size_references(db)
    finally:
        db.close()

    yield


app = FastAPI(
    title="宝宝尿布消耗预测与夜间补货提醒 API",
    description="基于 FastAPI 的宝宝尿布消耗预测服务，提供消耗预测、换码建议、夜间风险提醒和补货清单等功能",
    version="1.0.0",
    lifespan=lifespan
)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    resp = ApiResponse(code=exc.status_code, message=str(exc.detail), data=None)
    return JSONResponse(status_code=exc.status_code, content=resp.model_dump())


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for err in exc.errors():
        errors.append({
            "loc": err.get("loc", []),
            "msg": err.get("msg", ""),
            "type": err.get("type", "")
        })
    resp = ApiResponse(code=422, message="请求参数校验失败", data=errors)
    return JSONResponse(status_code=422, content=resp.model_dump())

app.include_router(babies.router)
app.include_router(consumption.router)
app.include_router(inventory.router)
app.include_router(prediction.router)
app.include_router(alerts.router)
app.include_router(planning.router)


@app.get("/", summary="健康检查", tags=["系统"])
def root():
    return success_response({
        "service": "宝宝尿布消耗预测与夜间补货提醒 API",
        "version": "1.0.0",
        "status": "running",
        "port": 9360
    })


@app.get("/api/health", summary="健康检查", tags=["系统"])
def health_check():
    return success_response({
        "status": "healthy",
        "timestamp": __import__("datetime").datetime.now().isoformat()
    })


@app.get("/api/size-reference", summary="获取尺码参考表", tags=["系统"])
def get_size_reference():
    db = SessionLocal()
    try:
        sizes = db.query(DiaperSizeReference).order_by(DiaperSizeReference.id).all()
        return success_response([
            {
                "size": s.size,
                "weight_range": f"{s.min_weight_kg}-{s.max_weight_kg}kg",
                "age_range": f"{s.min_age_months}-{s.max_age_months}个月" if s.min_age_months is not None else None,
                "average_daily_usage": s.average_daily_usage,
                "description": s.description
            }
            for s in sizes
        ])
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=9360,
        reload=True
    )

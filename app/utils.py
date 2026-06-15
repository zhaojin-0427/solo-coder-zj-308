from typing import Any, Dict, Optional
from .schemas import ApiResponse


def success_response(data: Any = None, message: str = "success") -> Dict:
    return ApiResponse(
        code=200,
        message=message,
        data=data
    ).model_dump()


def error_response(code: int, message: str, data: Any = None) -> Dict:
    return ApiResponse(
        code=code,
        message=message,
        data=data
    ).model_dump()


def not_found_response(message: str = "Resource not found") -> Dict:
    return error_response(404, message)


def bad_request_response(message: str = "Bad request") -> Dict:
    return error_response(400, message)


def server_error_response(message: str = "Internal server error") -> Dict:
    return error_response(500, message)


def calculate_age_months(birth_date_str: str, current_date_str: str = None) -> int:
    from datetime import datetime
    try:
        birth_date = datetime.strptime(birth_date_str, "%Y-%m-%d")
        if current_date_str:
            current_date = datetime.strptime(current_date_str, "%Y-%m-%d")
        else:
            current_date = datetime.now()

        age_months = (current_date.year - birth_date.year) * 12 + (current_date.month - birth_date.month)
        return max(0, age_months)
    except Exception:
        return 0


def init_size_references(db):
    from .models import DiaperSizeReference

    sizes = [
        {
            "size": "NB",
            "min_weight_kg": 0.0,
            "max_weight_kg": 5.0,
            "min_age_months": 0,
            "max_age_months": 1,
            "average_daily_usage": 10,
            "description": "新生儿（初生-5kg）"
        },
        {
            "size": "S",
            "min_weight_kg": 4.0,
            "max_weight_kg": 8.0,
            "min_age_months": 1,
            "max_age_months": 3,
            "average_daily_usage": 8,
            "description": "小号（4-8kg）"
        },
        {
            "size": "M",
            "min_weight_kg": 6.0,
            "max_weight_kg": 11.0,
            "min_age_months": 3,
            "max_age_months": 9,
            "average_daily_usage": 6,
            "description": "中号（6-11kg）"
        },
        {
            "size": "L",
            "min_weight_kg": 9.0,
            "max_weight_kg": 14.0,
            "min_age_months": 9,
            "max_age_months": 18,
            "average_daily_usage": 5,
            "description": "大号（9-14kg）"
        },
        {
            "size": "XL",
            "min_weight_kg": 12.0,
            "max_weight_kg": 17.0,
            "min_age_months": 18,
            "max_age_months": 36,
            "average_daily_usage": 4,
            "description": "加大号（12-17kg）"
        },
        {
            "size": "XXL",
            "min_weight_kg": 15.0,
            "max_weight_kg": 25.0,
            "min_age_months": 36,
            "max_age_months": 72,
            "average_daily_usage": 4,
            "description": "特大号（15kg以上）"
        }
    ]

    for size_data in sizes:
        existing = db.query(DiaperSizeReference).filter(
            DiaperSizeReference.size == size_data["size"]
        ).first()
        if not existing:
            db_size = DiaperSizeReference(**size_data)
            db.add(db_size)

    db.commit()

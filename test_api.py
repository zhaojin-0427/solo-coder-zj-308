import requests
import json
from datetime import datetime, timedelta

BASE_URL = "http://localhost:9360"

def print_response(label, response):
    print(f"\n{'='*60}")
    print(f"{label}")
    print(f"{'='*60}")
    print(json.dumps(response.json(), indent=2, ensure_ascii=False))

print("=== 测试开始 ===")

baby_data = {
    "name": "小明",
    "birth_date": "2025-09-15",
    "current_age_months": 9,
    "current_weight_kg": 9.5,
    "current_diaper_size": "M",
    "gender": "男"
}
response = requests.post(f"{BASE_URL}/api/babies", json=baby_data)
print_response("1. 创建宝宝档案", response)
baby_id = response.json()["data"]["baby"]["id"]

print("\n=== 上报历史消耗记录 ===")
today = datetime.now()
for i in range(14):
    record_date = (today - timedelta(days=i)).strftime("%Y-%m-%d")
    nighttime_leaks = 2 if i < 3 else (1 if i < 7 else 0)
    consumption_data = {
        "baby_id": baby_id,
        "record_date": record_date,
        "diaper_size": "M",
        "daily_changes": 6 + (i % 3),
        "nighttime_changes": 1 + (i % 2),
        "nighttime_leaks": nighttime_leaks,
        "weight_kg": 9.5 + (i * 0.02)
    }
    requests.post(f"{BASE_URL}/api/consumption", json=consumption_data)
print(f"已上报 14 天的消耗记录")

inventory_data = {
    "baby_id": baby_id,
    "record_date": today.strftime("%Y-%m-%d"),
    "diaper_size": "M",
    "quantity": 30,
    "unit": "pieces"
}
response = requests.post(f"{BASE_URL}/api/inventory", json=inventory_data)
print_response("2. 上报 M 码库存 30 片", response)

response = requests.get(f"{BASE_URL}/api/babies/{baby_id}")
print_response("3. 获取宝宝详情（含状态分析）", response)

response = requests.get(f"{BASE_URL}/api/prediction/{baby_id}?days=7")
print_response("4. 获取 7 天消耗预测", response)

response = requests.get(f"{BASE_URL}/api/prediction/restocking/{baby_id}?safety_days=7")
print_response("5. 获取补货清单", response)

response = requests.get(f"{BASE_URL}/api/alerts/size-change/{baby_id}")
print_response("6. 获取换码建议", response)

response = requests.get(f"{BASE_URL}/api/alerts/nighttime-risk/{baby_id}")
print_response("7. 获取夜间风险提醒", response)

response = requests.get(f"{BASE_URL}/api/alerts/leak-analysis/{baby_id}?days=14")
print_response("8. 获取漏尿模式分析", response)

response = requests.get(f"{BASE_URL}/api/inventory/size-cycles/{baby_id}")
print_response("9. 获取各尺码平均使用周期", response)

response = requests.post(f"{BASE_URL}/api/alerts/check/{baby_id}")
print_response("10. 主动检查并创建告警", response)

response = requests.get(f"{BASE_URL}/api/alerts/baby/{baby_id}")
print_response("11. 获取宝宝告警列表", response)

response = requests.get(f"{BASE_URL}/api/alerts/statistics/{baby_id}")
print_response("12. 获取告警统计", response)

print("\n=== 测试完成 ===")

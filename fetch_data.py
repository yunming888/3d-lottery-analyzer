"""
福彩3D历史数据抓取
数据源: 500.com / 中彩网公开数据
"""
import requests
import json
import time
import os
from datetime import datetime

DATA_FILE = "data/3d_history.json"

def fetch_lottery_data():
    """从500.com抓取福彩3D历史开奖数据"""
    url = "https://datachart.500.com/pls/history/newinc/history.php"
    params = {
        "start": "20001",
        "end": str(10000 + int(datetime.now().strftime("%y"))),
        "type": "pls",
        "limit": "5000"
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://datachart.500.com/"
    }

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        resp.encoding = "utf-8"
        data = resp.json()
        return data
    except Exception as e:
        print(f"网络抓取失败: {e}")
        return None

def parse_and_save(raw_data):
    """解析原始数据并保存为结构化JSON"""
    if not raw_data or "data" not in raw_data:
        print("无有效数据")
        return []

    records = []
    for item in raw_data["data"]:
        try:
            qihao = item.get("qihao", "")
            nums = item.get("num", "").split(",") if item.get("num") else item.get("newcode", "").split(",")
            if len(nums) != 3:
                continue

            records.append({
                "qihao": qihao,
                "date": str(item.get("opendate", qihao)),
                "bai": int(nums[0]),
                "shi": int(nums[1]),
                "ge": int(nums[2]),
                "nums": [int(n) for n in nums],
                "sum_val": sum(int(n) for n in nums),
                "type": classify_type(int(nums[0]), int(nums[1]), int(nums[2]))
            })
        except (ValueError, IndexError):
            continue

    os.makedirs("data", exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print(f"已保存 {len(records)} 条数据到 {DATA_FILE}")
    return records

def classify_type(b, s, g):
    """判断形态: 豹子/组三/组六"""
    if b == s == g:
        return "豹子"
    if b == s or s == g or b == g:
        return "组三"
    return "组六"

if __name__ == "__main__":
    print("正在抓取福彩3D历史数据...")
    raw = fetch_lottery_data()
    if raw:
        records = parse_and_save(raw)
        if records:
            latest = records[0]
            print(f"最新一期: {latest['qihao']} | {''.join(map(str, latest['nums']))} | {latest['type']}")
            print(f"数据范围: {records[-1]['qihao']} ~ {records[0]['qihao']}")

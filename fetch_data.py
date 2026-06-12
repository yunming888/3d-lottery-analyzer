"""
福彩3D历史数据抓取
数据源: 东方财富 caipiao.eastmoney.com
策略: 每次抓取5期(页面只展示5期带号码), 追加到本地库
"""
import requests
import json
import os
import re
from datetime import datetime

DATA_FILE = "data/3d_history.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://caipiao.eastmoney.com/",
}

def fetch_latest():
    """抓取东方财富最新5期开奖（页面只展示5期详情）"""
    url = "https://caipiao.eastmoney.com/Result/Category/fc3d"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        html = resp.text
    except Exception as e:
        print(f"抓取失败: {e}")
        return []

    # 页面结构: 只有5个tab-panel带详细号码
    # <strong>2026152期</strong> ... red">2</span> ... red">2</span> ... red">0</span>
    pattern = r'<strong>(\d{7})期</strong>.*?red">(\d)</span>.*?red">(\d)</span>.*?red">(\d)</span>'
    matches = re.findall(pattern, html, re.DOTALL)

    records = []
    for m in matches:
        qihao, bai, shi, ge = m[0], int(m[1]), int(m[2]), int(m[3])
        nums = [bai, shi, ge]
        lot_type = "组六"
        if bai == shi == ge:
            lot_type = "豹子"
        elif bai == shi or shi == ge or bai == ge:
            lot_type = "组三"

        # 尝试从页面提取日期
        date = ""
        date_match = re.search(rf'{qihao}期</strong>.*?开奖日期：(\d{{4}}-\d{{2}}-\d{{2}})', html, re.DOTALL)
        if date_match:
            date = date_match.group(1)

        records.append({
            "qihao": qihao,
            "date": date,
            "bai": bai, "shi": shi, "ge": ge,
            "nums": nums,
            "sum_val": sum(nums),
            "span": max(nums) - min(nums),
            "type": lot_type
        })

    return records

def merge_and_save(new_records):
    """合并新数据到本地库，去重只保留最新"""
    if not new_records:
        return load_data()

    existing = load_data()
    existing_map = {r["qihao"]: r for r in existing}

    for r in new_records:
        existing_map[r["qihao"]] = r

    merged = sorted(existing_map.values(), key=lambda x: x["qihao"], reverse=True)
    os.makedirs("data", exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    return merged

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def load_or_fetch():
    new_records = fetch_latest()
    if new_records:
        records = merge_and_save(new_records)
        print(f"东方财富: {len(new_records)} 期新数据, 本地共 {len(records)} 期")
        return records
    else:
        records = load_data()
        if records:
            print(f"使用本地缓存: {len(records)} 期")
        return records

if __name__ == "__main__":
    records = load_or_fetch()
    if records:
        latest = records[0]
        print(f"最新: {latest['qihao']}期 | {' '.join(map(str, latest['nums']))} | {latest['type']}")
        print(f"范围: {records[-1]['qihao']} ~ {records[0]['qihao']}")

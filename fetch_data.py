"""

福彩3D历史数据抓取 v2

数据源: 东方财富 caipiao.eastmoney.com (主) + 500.com (补缺)

策略: 每次抓取5期东财, 检测gap自动从500.com补全

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

def fetch_eastmoney():

    """抓取东方财富最新5期开奖"""

    url = "https://caipiao.eastmoney.com/Result/Category/fc3d"

    try:

        resp = requests.get(url, headers=HEADERS, timeout=15)

        resp.encoding = "utf-8"

        html = resp.text

    except Exception as e:

        print(f"  东财抓取失败: {e}")

        return []

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

def fetch_500com(qihao):

    """从500.com抓取单个期号（用于补缺）"""

    url = f"https://sports.163.com/caipiao/lottery/fc3d/{qihao}"

    try:

        resp = requests.get(url, headers=HEADERS, timeout=15)

        resp.encoding = "utf-8"

        html = resp.text

    except Exception:

        # 备用: 500.com

        try:

            url = f"https://kaijiang.500.com/shtml/sd/{qihao}.shtml"

            resp = requests.get(url, headers=HEADERS, timeout=15)

            resp.encoding = "utf-8"

            html = resp.text

        except Exception as e:

            print(f"  补缺{qihao}失败: {e}")

            return None

    # 500.com 页面: 开奖号码: - N - N - N, 号码类型：组X

    # 163.com 页面: 开奖号码\nN\nN\nN

    nums_match = re.findall(r'开奖号码[：:]?\s*</h\d>?\s*<[^>]*>\s*(\d)\s*</[^>]*>\s*<[^>]*>\s*(\d)\s*</[^>]*>\s*<[^>]*>\s*(\d)', html, re.DOTALL | re.IGNORECASE)

    if not nums_match:

        # 500.com format: <div class="ball_red">N</div>

        nums_match = re.findall(r'ball_red[^>]*>\s*(\d)\s*<', html)

        if len(nums_match) >= 3:

            nums_match = [(nums_match[0], nums_match[1], nums_match[2])]

        else:

            # Try other formats

            nums_match = re.findall(r'red[^>]*>\s*(\d)\s*<[^>]*>\s*<[^>]*>\s*(\d)\s*<[^>]*>\s*<[^>]*>\s*(\d)', html, re.DOTALL)

    if not nums_match:

        print(f"  补缺{qihao}: 无法解析号码")

        return None

    m = nums_match[0]

    bai, shi, ge = int(m[0]), int(m[1]), int(m[2])

    nums = [bai, shi, ge]

    lot_type = "组六"

    if bai == shi == ge:

        lot_type = "豹子"

    elif bai == shi or shi == ge or bai == ge:

        lot_type = "组三"

    # Extract date

    date = ""

    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', html)

    if date_match:

        date = date_match.group(1)

    return {

        "qihao": str(qihao),

        "date": date,

        "bai": bai, "shi": shi, "ge": ge,

        "nums": nums,

        "sum_val": sum(nums),

        "span": max(nums) - min(nums),

        "type": lot_type,

        "_source": "500.com补缺"

    }

def detect_gaps(records):

    """检测本地数据中的期号缺口"""

    if len(records) < 2:

        return []

    qihaos = sorted([int(r["qihao"]) for r in records])

    gaps = []

    for i in range(len(qihaos) - 1):

        curr = qihaos[i]

        next_qh = qihaos[i + 1]

        if next_qh - curr > 1:

            for missing in range(curr + 1, next_qh):

                gaps.append(str(missing))

    return gaps

def fill_gaps(records):

    """检测缺口并从500.com补全"""

    gaps = detect_gaps(records)

    if not gaps:

        return records, 0

    # 跳过大缺口 (超过50期, 可能是数据源切换导致的不连续)

    if len(gaps) > 50:

        print(f"  ⚠️ 检测到{len(gaps)}个缺口, 数量过多, 跳过补全")

        return records, 0

    print(f"  🔍 检测到{len(gaps)}个缺口: {', '.join(gaps)}")

    filled = 0

    existing_map = {r["qihao"]: r for r in records}

    for qihao in gaps:

        print(f"  补缺 {qihao}...", end=" ")

        record = fetch_500com(qihao)

        if record:

            existing_map[qihao] = record

            filled += 1

            print(f"✅ {''.join(map(str, record['nums']))} {record['type']}")

        else:

            print("❌")

    if filled > 0:

        merged = sorted(existing_map.values(), key=lambda x: x["qihao"], reverse=True)

        os.makedirs("data", exist_ok=True)

        with open(DATA_FILE, "w", encoding="utf-8") as f:

            json.dump(merged, f, ensure_ascii=False, indent=2)

        print(f"  缺口补全: {filled}/{len(gaps)}")

        return merged, filled

    return records, 0

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

    # Step 1: 东财抓最新5期

    new_records = fetch_eastmoney()

    if new_records:

        records = merge_and_save(new_records)

        print(f"东方财富: {len(new_records)} 期新数据, 本地共 {len(records)} 期")

    else:

        records = load_data()

        if records:

            print(f"使用本地缓存: {len(records)} 期")

    # Step 2: 检测并补全缺口

    records, filled = fill_gaps(records)

    return records

if __name__ == "__main__":

    records = load_or_fetch()

    if records:

        latest = records[0]

        print(f"最新: {latest['qihao']}期 | {' '.join(map(str, latest['nums']))} | {latest['type']}")

        print(f"范围: {records[-1]['qihao']} ~ {records[0]['qihao']}")

        print(f"总计: {len(records)} 期")


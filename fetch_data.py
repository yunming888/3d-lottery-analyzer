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

        # 2026-11-23 实测：500 页面 3D 球号 class 为 ball_orange（旧正则 ball_red 永不匹配，补缺静默失败）
        nums_match = re.findall(r'ball_(?:red|orange)[^>]*>\s*(\d)\s*<', html)

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

def fetch_huiniao(limit=30):
    """
    主数据源: api.huiniao.top (中福彩官方数据镜像, 免鉴权, 约5分钟同步)
    返回最近 limit 期福彩3D开奖, JSON 结构: data.list[].{code,day,one,two,three}
    """
    url = f"http://api.huiniao.top/interface/home/lotteryHistory?type=fcsd&page=1&limit={limit}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        j = resp.json()
        if j.get("code") != 1:
            print(f"  huiniao 返回异常: {j.get('info')}")
            return []
        records = []
        # 结构: data.data.list (data 内含 last 与 data.list 两层)
        for it in j.get("data", {}).get("data", {}).get("list", []):
            bai, shi, ge = int(it["one"]), int(it["two"]), int(it["three"])
            nums = [bai, shi, ge]
            if bai == shi == ge:
                lot_type = "豹子"
            elif bai == shi or shi == ge or bai == ge:
                lot_type = "组三"
            else:
                lot_type = "组六"
            records.append({
                "qihao": str(it["code"]),
                "date": it["day"],
                "bai": bai, "shi": shi, "ge": ge,
                "nums": nums,
                "sum_val": sum(nums),
                "span": max(nums) - min(nums),
                "type": lot_type,
                "_source": "huiniao",
            })
        return records
    except Exception as e:
        print(f"  huiniao 抓取失败: {e}")
        return []


def fetch_cwl(limit=25):
    """
    兜底数据源（2026-11-23 云明授权方案B）：中福彩官方开奖 API findDrawNotice。
    背景：huiniao 镜像可能停更（HTTP 200 但期号落后），旧 fill_gaps 只查内部缺口、
    检测不到"尾部缺口"。本函数返回官方一手数据，解析成 3D record 格式。
    需带 Referer（否则 403）。
    """
    url = ("https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice"
           "?name=3d&issueCount=%d" % limit)
    try:
        resp = requests.get(url, headers={**HEADERS, "Referer": "https://www.cwl.gov.cn/ygkj/wqkjgg/3d/",
                                          "Accept": "application/json"}, timeout=15)
        resp.encoding = "utf-8"
        j = resp.json()
        if j.get("state") != 0:
            print(f"  cwl官方 返回异常: state={j.get('state')}")
            return []
        records = []
        for it in j.get("result", []):
            m = re.match(r"(\d{4}-\d{2}-\d{2})", str(it.get("date", "")))
            date = m.group(1) if m else ""
            nums = [int(x) for x in str(it.get("red", "")).split(",") if x.strip() != ""]
            if len(nums) != 3:
                continue
            bai, shi, ge = nums
            if bai == shi == ge:
                lot_type = "豹子"
            elif bai == shi or shi == ge or bai == ge:
                lot_type = "组三"
            else:
                lot_type = "组六"
            records.append({
                "qihao": str(it.get("code")), "date": date,
                "bai": bai, "shi": shi, "ge": ge, "nums": nums,
                "sum_val": sum(nums), "span": max(nums) - min(nums),
                "type": lot_type, "_source": "cwl官方",
            })
        return records
    except Exception as e:
        print(f"  cwl官方 抓取失败: {e}")
        return []


def official_backfill(records):
    """
    尾部缺口兜底（2026-11-24 修复）：无条件查中福彩官方 API，只要官方有比本地新的期号就补齐。

    背景（静默 0 注根因）：旧版用「本地最新日期 vs 昨日交易日」的日差 >= 2 才触发；
    当本地恰好落后 1 天（如本地 11-22、昨日 11-23）时不补，但官方其实已有该期
    （2026313=346）。同时出号层 daily_review 用「期号差 > 1」判数据滞后 → 暂停出号，
    新鲜度层 data_freshness 又因日差=1 报 OK 不告警 —— 三层口径错配导致连续多日静默 0 注。

    新逻辑与 qlc/fetcher._cwl_backfill 保持一致：每次拉官方、按期号差补，
    不再依赖脆弱的日差阈值。只补数据，不触碰选号/结算/成本/台账结构。
    """
    try:
        if not records:
            return records
        local_latest = records[0]
        local_int = int(local_latest["qihao"])
        official = fetch_cwl(limit=25)
        if not official:
            return records  # 官方无数据/临时故障：静默保持现状，数据新鲜度层仍会告警
        official_map = {r["qihao"]: r for r in official}
        to_add = [official_map[q] for q in sorted(official_map.keys(), key=int)
                  if int(q) > local_int]
        if not to_add:
            return records
        print(f"  🔍 huiniao 停更/尾部缺口: 本地 {local_latest['qihao']} → 官方有 {[r['qihao'] for r in to_add]}")
        merged = merge_and_save(to_add)
        print(f"  ✅ 官方兜底补 {len(to_add)} 期")
        return merged
    except Exception as e:
        print(f"  ⚠️ 尾部缺口兜底异常(不影响主链路): {e}")
        return records


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

        from atomic_io import save_json_locked
        save_json_locked(DATA_FILE, merged)

        print(f"  缺口补全: {filled}/{len(gaps)}")

        return merged, filled

    return records, 0

def merge_and_save(new_records):

    """合并新数据到本地库，去重只保留最新（带锁+原子写，审计 A1）"""

    if not new_records:

        return load_data()

    existing = load_data()

    existing_map = {r["qihao"]: r for r in existing}

    for r in new_records:

        existing_map[r["qihao"]] = r

    merged = sorted(existing_map.values(), key=lambda x: x["qihao"], reverse=True)

    os.makedirs("data", exist_ok=True)

    from atomic_io import save_json_locked
    save_json_locked(DATA_FILE, merged)

    return merged

def load_data():

    if os.path.exists(DATA_FILE):

        with open(DATA_FILE, "r", encoding="utf-8") as f:

            return json.load(f)

    return []

def load_or_fetch():
    # Step 1: 主源 = 中福彩官方 API findDrawNotice（一手权威数据, 2026-11-24 换源）
    #   背景: huiniao 镜像自 11-14 停更 10 天 (HTTP 200 但期号冻结), 改官方为主源。
    #   官方实测: 免鉴权(带 Referer), 100期覆盖~3个月, 与本地历史库100期零差异。
    new_records = fetch_cwl(limit=100)
    if new_records:
        records = merge_and_save(new_records)
        print(f"中福彩官方: {len(new_records)} 期新数据, 本地共 {len(records)} 期")
    else:
        # Step 1b: 官方 API 故障 → 回退 huiniao 镜像
        print("  ⚠️ 官方 API 无数据, 回退 huiniao 镜像")
        new_records = fetch_huiniao(limit=100)
        if new_records:
            records = merge_and_save(new_records)
            print(f"huiniao(备用): {len(new_records)} 期新数据, 本地共 {len(records)} 期")
        else:
            # Step 1c: 再回退东方财富 / 本地缓存
            new_records = fetch_eastmoney()
            if new_records:
                records = merge_and_save(new_records)
                print(f"东方财富(备用): {len(new_records)} 期新数据, 本地共 {len(records)} 期")
            else:
                records = load_data()
                if records:
                    print(f"使用本地缓存: {len(records)} 期")

    # Step 2: 检测并补全内部缺口 (官方数据若有断档则尝试 500.com)
    records, filled = fill_gaps(records)

    return records

if __name__ == "__main__":

    records = load_or_fetch()

    if records:

        latest = records[0]

        print(f"最新: {latest['qihao']}期 | {' '.join(map(str, latest['nums']))} | {latest['type']}")

        print(f"范围: {records[-1]['qihao']} ~ {records[0]['qihao']}")

        print(f"总计: {len(records)} 期")


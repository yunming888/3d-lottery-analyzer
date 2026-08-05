# -*- coding: utf-8 -*-
"""
数据抓取与整合模块
------------------
从 500彩票网 历史数据接口检索双色球/大乐透等开奖结果，解析为统一结构并本地缓存。

统一数据结构（每期）:
    {
        "issue": "26089",      # 期号（字符串，5位）
        "date":  "2026-08-02",  # 开奖日期
        "reds":  [5, 18, 23, 24, 27, 33],  # 前区/红球（整数升序）
        "blues": [3],                         # 后区/蓝球
    }

说明：
- 接口为 server-render 的 HTML 表格，需正则解析；注意表格首列含注释伪节点 `<!--<td>2</td>-->` 需剔除。
- 为「整合各类彩票」预留：SOURCE_500 按彩种映射，新增数据源只需实现对应解析器。
"""

import os
import re
import json
import urllib.request
from datetime import datetime, date

from . import config

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def _http_get(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    # 500 历史页为 GBK/GB18030 编码
    for enc in ("utf-8", "gb18030", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore")


def _parse_500(html: str, spec: config.LotterySpec):
    """解析 500彩票网历史表格 -> 统一结构的 list（最新在前）。"""
    m = re.search(r'id="tdata">(.*?)</tbody>', html, re.S)
    if not m:
        return []
    body = m.group(1)
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)  # 剔除注释伪节点
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S)
    draws = []
    for row in rows:
        tds = [t.strip() for t in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(tds) < 1 + spec.red_count + spec.blue_count:
            continue
        issue = tds[0]
        if not re.fullmatch(r"\d{5}", issue):
            continue
        try:
            reds = [int(tds[1 + i]) for i in range(spec.red_count)]
            blues = [int(tds[1 + spec.red_count + i]) for i in range(spec.blue_count)]
        except ValueError:
            continue
        # 开奖日期：表格最后一列
        draw_date = tds[-1] if re.fullmatch(r"\d{4}-\d{2}-\d{2}", tds[-1]) else ""
        draws.append({
            "issue": issue,
            "date": draw_date,
            "reds": sorted(reds),
            "blues": sorted(blues),
        })
    return draws


def fetch_history(game: str, window: int = config.DEFAULT_WINDOW,
                  use_cache: bool = True, cache_dir: str = None,
                  force_refresh: bool = False):
    """
    获取指定彩种最近 window 期历史数据。

    说明：500彩票网期号为 YYNNN（每年从 001 重置）。直接 latest-window 会因跨年
    越界而被接口截断，故以"当前年份"估算起点，向前取足够年数（≥2 年）确保覆盖
    window 期，再截取最新 window 期，从而得到真正的近期窗口。
    """
    spec = config.get_spec(game)
    cache_dir = cache_dir or os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, f"{game}_history.json")

    # 尝试读缓存（当天抓取且非空即视为有效）
    if use_cache and not force_refresh and os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            fetched_day = cached.get("meta", {}).get("fetched_at", "")[:10]
            if fetched_day == date.today().isoformat() and cached.get("draws"):
                draws = cached["draws"][:window]
                meta = dict(cached["meta"])
                meta["window"] = window
                meta["from_cache"] = True
                return draws, meta
        except Exception:
            pass

    # 计算抓取起点：以当前年份估算，向前取足够年数确保覆盖 window 期
    now_year = datetime.now().year % 100
    years_back = max(2, (window + 149) // 150)
    start_issue = max(101, (now_year - years_back) * 1000 + 1)
    url = f"{config.SOURCE_500[game]}?start={start_issue:05d}&end=99999"
    html = _http_get(url)
    draws = _parse_500(html, spec)
    if not draws:
        raise RuntimeError(f"解析 {spec.name} 历史数据失败")

    # 按数值期号排序（最新在前）并截取最新 window 期
    draws.sort(key=lambda d: int(d["issue"]), reverse=True)
    latest = int(draws[0]["issue"]) if draws else 0
    draws = draws[:window]

    meta = {
        "source": "500彩票网",
        "game": game,
        "name": spec.name,
        "latest_issue": str(latest),
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "count": len(draws),
        "window": window,
        "from_cache": False,
    }
    # 写缓存
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"meta": meta, "draws": draws}, f,
                      ensure_ascii=False, indent=2)
    except Exception:
        pass
    return draws, meta

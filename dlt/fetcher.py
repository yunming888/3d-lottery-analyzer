# -*- coding: utf-8 -*-
"""
大乐透 数据抓取模块
-------------------
从 500彩票网 历史接口获取大乐透开奖结果，解析为统一结构并本地缓存。
统一结构（每期）:
    {"issue": "26089", "date": "2026-08-02",
     "reds": [5, 18, 23, 24, 27], "blues": [3, 9]}

容错：网络/解析失败时回退本地缓存 data/dlt_history.json，并在 meta 中标注
from_cache / fallback，绝不因抓取失败而误判或中断选号。
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
    for enc in ("utf-8", "gb18030", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore")


def _parse(html: str) -> list:
    """解析 500彩票网 大乐透历史表格 -> 统一结构 list（最新在前）。"""
    m = re.search(r'id="tdata">(.*?)</tbody>', html, re.S)
    if not m:
        return []
    body = m.group(1)
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)  # 剔除注释伪节点
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S)
    draws = []
    for row in rows:
        tds = [t.strip() for t in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(tds) < 1 + config.RED_COUNT + config.BLUE_COUNT:
            continue
        issue = tds[0]
        if not re.fullmatch(r"\d{5}", issue):
            continue
        try:
            reds = [int(tds[1 + i]) for i in range(config.RED_COUNT)]
            blues = [int(tds[1 + config.RED_COUNT + i]) for i in range(config.BLUE_COUNT)]
        except ValueError:
            continue
        draw_date = tds[-1] if re.fullmatch(r"\d{4}-\d{2}-\d{2}", tds[-1]) else ""
        draws.append({
            "issue": issue,
            "date": draw_date,
            "reds": sorted(reds),
            "blues": sorted(blues),
        })
    return draws


def fetch_history(window: int = config.WINDOW, force_refresh: bool = False):
    """
    获取大乐透最近 window 期历史。
    返回 (draws, meta)。draws 最新在前，仅取最近 window 期。
    """
    cache_path = config.HISTORY_FILE
    meta = {"source": "500彩票网", "game": "dlt", "name": "大乐透",
            "fetched_at": datetime.now().isoformat(timespec="seconds"), "window": window}

    # 1) 尝试读当天缓存（非强制刷新时）
    if not force_refresh and os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            fetched_day = cached.get("meta", {}).get("fetched_at", "")[:10]
            if fetched_day == date.today().isoformat() and cached.get("draws"):
                draws = cached["draws"][:window]
                meta.update({"latest_issue": draws[0]["issue"], "count": len(draws),
                             "from_cache": True, "fallback": False})
                return draws, meta
        except Exception:
            pass

    # 2) 实时抓取（覆盖足够年数确保窗口，再截最近 window 期）
    try:
        now_year = datetime.now().year % 100
        years_back = max(2, (window + 149) // 150)
        start_issue = max(101, (now_year - years_back) * 1000 + 1)
        url = f"{config.SOURCE_500}?start={start_issue:05d}&end=99999"
        html = _http_get(url)
        draws = _parse(html)
        if not draws:
            raise RuntimeError("解析大乐透历史数据为空")
        draws.sort(key=lambda d: int(d["issue"]), reverse=True)
        draws = draws[:window]
        meta.update({"latest_issue": draws[0]["issue"], "count": len(draws),
                     "from_cache": False, "fallback": False})
        # 写缓存
        try:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({"meta": meta, "draws": draws}, f,
                          ensure_ascii=False, indent=2)
        except Exception:
            pass
        return draws, meta
    except Exception as e:
        # 3) 抓取失败 → 回退本地缓存（若存在）
        if os.path.exists(cache_path):
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            draws = cached.get("draws", [])[:window]
            if draws:
                meta.update({"latest_issue": draws[0]["issue"], "count": len(draws),
                             "from_cache": True, "fallback": True, "error": str(e)})
                return draws, meta
        meta.update({"from_cache": False, "fallback": True, "error": str(e), "count": 0})
        return [], meta


def load_cache(path: str = config.HISTORY_FILE) -> list:
    """仅读本地缓存（无网络时用）。"""
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f).get("draws", [])

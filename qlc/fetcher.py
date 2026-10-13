# -*- coding: utf-8 -*-
"""
七乐彩 数据抓取模块
-------------------
从 huiniao 官方镜像获取七乐彩开奖结果，解析为统一结构并本地缓存。
统一结构（每期）:
    {"issue": "2026117", "date": "2026-10-12",
     "reds": [1, 8, 12, 14, 17, 25, 27],   # 基本号码（7个，01-30）
     "blues": [23]}                        # 特别号码（1个）

⚠️ 字段沿用 reds/blues 命名以便与 dlt/ssq 的结算、轮换、均衡统计逻辑复用；
   语义为 reds=基本号码(7)、blues=特别号码(1)。

容错：网络/解析失败时回退本地缓存 data/qlc_history.json，并在 meta 中标注
from_cache / fallback，绝不因抓取失败而误判或中断选号。
"""
import os
import json
import urllib.request
from datetime import datetime, date

from . import config

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
_BASIC_KEYS = ("one", "two", "three", "four", "five", "six", "seven")


def _http_get_json(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    for enc in ("utf-8", "gb18030"):
        try:
            return json.loads(raw.decode(enc))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return json.loads(raw.decode("utf-8", "ignore"))


def _parse(j: dict) -> list:
    """解析 huiniao 七乐彩响应 -> 统一结构 list（最新在前）。"""
    try:
        lst = j["data"]["data"]["list"]
    except (KeyError, TypeError):
        return []
    draws = []
    for r in lst:
        try:
            basic = [int(r[k]) for k in _BASIC_KEYS]
            special = int(r["eight"])
        except (KeyError, ValueError, TypeError):
            continue
        # 合法性校验：7 个互不重复、均在 01-30；特别号不与基本号重复
        if len(set(basic)) != config.BASIC_COUNT:
            continue
        if not all(config.BASIC_MIN <= x <= config.BASIC_MAX for x in basic):
            continue
        if not (config.SPECIAL_MIN <= special <= config.SPECIAL_MAX) or special in basic:
            continue
        issue = str(r.get("code", ""))
        if len(issue) != 7 or not issue.isdigit():
            continue
        draws.append({
            "issue": issue,
            "date": str(r.get("day", "")),
            "reds": sorted(basic),
            "blues": [special],
        })
    draws.sort(key=lambda d: int(d["issue"]), reverse=True)
    return draws


def fetch_history(window: int = config.WINDOW, force_refresh: bool = False):
    """
    获取七乐彩最近 window 期历史。
    返回 (draws, meta)。draws 最新在前，仅取最近 window 期。
    """
    cache_path = config.HISTORY_FILE
    meta = {"source": "huiniao镜像", "game": "qlc", "name": "七乐彩",
            "fetched_at": datetime.now().isoformat(timespec="seconds"), "window": window}

    # 1) 尝试读当天缓存（非强制刷新时）—— 数据源约 5 分钟同步，同日缓存足够新
    if not force_refresh and os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            fetched_day = str(cached.get("meta", {}).get("fetched_at", ""))[:10]
            if fetched_day == date.today().isoformat() and cached.get("draws"):
                draws = cached["draws"][:window]
                meta.update({"latest_issue": draws[0]["issue"], "count": len(draws),
                             "from_cache": True, "fallback": False})
                return draws, meta
        except Exception:
            pass

    # 2) 实时抓取
    try:
        url = f"{config.SOURCE_HUINIAO}?type=qlc&page=1&limit={max(window, 100)}"
        draws = _parse(_http_get_json(url))
        if not draws:
            raise RuntimeError("解析七乐彩历史数据为空")
        draws = draws[:window]
        meta.update({"latest_issue": draws[0]["issue"], "count": len(draws),
                     "from_cache": False, "fallback": False})
        try:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            from atomic_io import save_json_atomic
            save_json_atomic(cache_path, {"meta": meta, "draws": draws})
        except Exception as _e:
            from alerts import ALERTS
            ALERTS.add("WARN", "七乐彩", "缓存写盘失败：%s" % _e)
        return draws, meta
    except Exception as e:
        # 3) 抓取失败 → 回退本地缓存（若存在）
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                draws = cached.get("draws", [])[:window]
                if draws:
                    meta.update({"latest_issue": draws[0]["issue"], "count": len(draws),
                                 "from_cache": True, "fallback": True, "error": str(e)})
                    return draws, meta
            except Exception:
                pass
        meta.update({"from_cache": False, "fallback": True, "error": str(e), "count": 0})
        return [], meta


def load_cache(path: str = config.HISTORY_FILE) -> list:
    """仅读本地缓存（无网络时用）。"""
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f).get("draws", [])

# -*- coding: utf-8 -*-
"""
彩票配置中心
-----------
定义支持的彩种及其规则（红球/蓝球取值范围、个数、奖级表）。
新增彩种只需在此处登记，fetcher/analyzer/recommender/backtester 均按规则驱动，
无需改动核心算法，实现「整合各类彩票」的可扩展目标。
"""

from dataclasses import dataclass, field


@dataclass
class LotterySpec:
    key: str                 # 内部键，如 'ssq'
    name: str                # 中文名
    source: str              # 数据源标识（500 = 500彩票网）
    red_min: int             # 前区/红球 最小值
    red_max: int             # 前区/红球 最大值
    red_count: int           # 每注前区/红球个数
    blue_min: int            # 后区/蓝球 最小值
    blue_max: int            # 后区/蓝球 最大值
    blue_count: int          # 每注后区/蓝球个数
    cost_per_note: int       # 每注金额（元）
    # 奖级表：tier -> (名称, 固定奖金)。tier 1/2 通常为浮动奖池，标记为 None
    prize_table: dict = field(default_factory=dict)

    @property
    def red_pool(self):
        return list(range(self.red_min, self.red_max + 1))

    @property
    def blue_pool(self):
        return list(range(self.blue_min, self.blue_max + 1))


# ---- 标准奖级固定奖金（基本投注，单位：元）----
# tier 1/2 为浮动奖池，不在此列（回测时按「浮动奖，金额不定」统计注数）。

SSQ_PRIZE = {
    1: ("一等奖", None),
    2: ("二等奖", None),
    3: ("三等奖", 3000),
    4: ("四等奖", 200),
    5: ("五等奖", 10),
    6: ("六等奖", 5),
}

DLT_PRIZE = {
    1: ("一等奖", None),
    2: ("二等奖", None),
    3: ("三等奖", 10000),
    4: ("四等奖", 2000),
    5: ("五等奖", 300),
    6: ("六等奖", 200),
    7: ("七等奖", 100),
    8: ("八等奖", 15),
    9: ("九等奖", 5),
}


def _ssq_tier(red_match, blue_match):
    """双色球奖级判定：传入(命中红球数, 命中蓝球数)。"""
    if red_match == 6 and blue_match == 1:
        return 1
    if red_match == 6 and blue_match == 0:
        return 2
    if red_match == 5 and blue_match == 1:
        return 3
    if (red_match == 5 and blue_match == 0) or (red_match == 4 and blue_match == 1):
        return 4
    if (red_match == 4 and blue_match == 0) or (red_match == 3 and blue_match == 1):
        return 5
    if (red_match in (0, 1, 2) and blue_match == 1):
        return 6
    return 0


def _dlt_tier(red_match, blue_match):
    """大乐透奖级判定：传入(命中前区数, 命中后区数)。"""
    if red_match == 5 and blue_match == 2:
        return 1
    if red_match == 5 and blue_match == 1:
        return 2
    if red_match == 5 and blue_match == 0:
        return 3
    if red_match == 4 and blue_match == 2:
        return 4
    if red_match == 4 and blue_match == 1:
        return 5
    if red_match == 3 and blue_match == 2:
        return 6
    if red_match == 4 and blue_match == 0:
        return 7
    if (red_match == 3 and blue_match == 1) or (red_match == 2 and blue_match == 2):
        return 8
    if (red_match == 3 and blue_match == 0) or (red_match == 2 and blue_match == 1) \
            or (red_match == 1 and blue_match == 2) or (red_match == 0 and blue_match == 2):
        return 9
    return 0


# 彩种注册表
LOTTERIES = {
    "ssq": LotterySpec(
        key="ssq", name="双色球", source="500",
        red_min=1, red_max=33, red_count=6,
        blue_min=1, blue_max=16, blue_count=1,
        cost_per_note=2, prize_table=SSQ_PRIZE,
    ),
    "dlt": LotterySpec(
        key="dlt", name="大乐透", source="500",
        red_min=1, red_max=35, red_count=5,
        blue_min=1, blue_max=12, blue_count=2,
        cost_per_note=2, prize_table=DLT_PRIZE,
    ),
}

# 奖级判定函数（按 key 索引）
TIER_FUNC = {
    "ssq": _ssq_tier,
    "dlt": _dlt_tier,
}

# 数据源配置（500彩票网历史数据接口）
SOURCE_500 = {
    "ssq": "https://datachart.500.com/ssq/history/newinc/history.php",
    "dlt": "https://datachart.500.com/dlt/history/newinc/history.php",
}

# 默认分析窗口（最近 N 期，用于频率/冷热/遗漏统计）
DEFAULT_WINDOW = 300


def get_spec(key: str) -> LotterySpec:
    if key not in LOTTERIES:
        raise ValueError(f"不支持的彩种: {key}，可选: {list(LOTTERIES.keys())}")
    return LOTTERIES[key]

# -*- coding: utf-8 -*-
"""
中奖号码比对与奖级判定
----------------------
复用 specs.TIER_FUNC（与 lottery-strategy-analyzer 一致的奖级表逻辑）：
传入(命中红球数, 命中蓝球数) 得到奖级 tier，再查 prize_table 取奖金。
"""
from typing import List, Tuple, Dict, Optional
from .specs import LotterySpec, TIER_FUNC, get_spec
from .draw import DrawResult


def match_counts(draw: DrawResult, ticket_red: List[int], ticket_blue: List[int]) -> Tuple[int, int]:
    """返回 (命中红球数, 命中蓝球数)。"""
    red_hit = len(set(draw.red) & set(ticket_red))
    blue_hit = len(set(draw.blue) & set(ticket_blue))
    return red_hit, blue_hit


def check_winning(draw: DrawResult, ticket_red: List[int], ticket_blue: List[int],
                  spec: Optional[LotterySpec] = None) -> Dict:
    """比对一注投注号码与开奖结果，输出命中详情与奖级。"""
    red_hit, blue_hit = match_counts(draw, ticket_red, ticket_blue)
    tier_func = TIER_FUNC.get(draw.spec_key)
    tier = tier_func(red_hit, blue_hit) if tier_func else 0

    spec = spec or get_spec(draw.spec_key)
    tier_name, fixed = spec.prize_table.get(tier, (None, None))
    return {
        "red_hit": red_hit,
        "blue_hit": blue_hit,
        "tier": tier,
        "tier_name": tier_name,        # None 表示未中奖
        "fixed_prize": fixed,          # None 表示浮动奖池（一/二等奖）
        "is_win": tier > 0,
        "spec_key": draw.spec_key,
    }

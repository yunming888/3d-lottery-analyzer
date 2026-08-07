# -*- coding: utf-8 -*-
"""
随机抽奖生成器
--------------
按 LotterySpec 对红球/蓝球独立无放回抽样，生成一注合法号码。
支持随机种子以便复现（便于测试与演示）。
"""
import random
from dataclasses import dataclass
from typing import List, Optional

from .specs import LotterySpec


@dataclass
class DrawResult:
    """一注开奖/模拟结果"""
    spec_key: str
    red: List[int]
    blue: List[int]
    note: str = ""

    def __str__(self) -> str:
        red_s = " ".join(f"{n:02d}" for n in self.red)
        blue_s = " ".join(f"{n:02d}" for n in self.blue)
        return f"红球: {red_s}    蓝球: {blue_s}"

    def to_dict(self) -> dict:
        return {"spec_key": self.spec_key, "red": self.red, "blue": self.blue, "note": self.note}


def draw_one(spec: LotterySpec, rng: Optional[random.Random] = None) -> DrawResult:
    """按 spec 生成一注：红球无放回抽 red_count 个，蓝球无放回抽 blue_count 个。"""
    r = rng or random
    red = sorted(r.sample(spec.red_pool, spec.red_count))
    blue = sorted(r.sample(spec.blue_pool, spec.blue_count))
    return DrawResult(spec_key=spec.key, red=red, blue=blue)


def simulate(spec: LotterySpec, count: int = 1, seed: Optional[int] = None) -> List[DrawResult]:
    """生成 count 注（可指定随机种子以便复现）。"""
    rng = random.Random(seed)
    return [draw_one(spec, rng) for _ in range(max(1, count))]

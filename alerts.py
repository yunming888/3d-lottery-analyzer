# -*- coding: utf-8 -*-
"""
alerts —— 全局运行告警单例（2026-10-13 审计修复 A2/A5）

背景：dlt/ssq settle、hot_core、unified_review 中存在大量 `except: pass` 静默路径
（状态损坏、核心号校验异常、数据源回退等），外部表现只有"0注"或空数据，无法区分
「真休市」「数据滞后」「代码故障」三种语义完全不同的状态。

本模块提供进程内全局告警收集器，由 unified_review 在【微信推送摘要】末尾统一渲染。
独立成模块是为了避免 daily_review / dlt.settle / ssq.settle / unified_review
之间循环导入。
"""
import datetime


class _Alerts:
    def __init__(self):
        self.items = []          # [(sev, scope, msg, ts)]

    def add(self, sev, scope, msg):
        """sev: ERROR / WARN / INFO"""
        self.items.append((sev, scope, msg,
                           datetime.datetime.now().strftime("%H:%M:%S")))

    def has_error(self):
        return any(sev == "ERROR" for sev, *_ in self.items)

    def render(self):
        """渲染为微信摘要行；无告警返回 []。"""
        if not self.items:
            return []
        n_err = sum(1 for sev, *_ in self.items if sev == "ERROR")
        n_warn = len(self.items) - n_err
        out = ["", "━━ ⚠️ 运行告警 %d 条（ERROR %d / WARN %d）━━" % (
            len(self.items), n_err, n_warn)]
        for sev, scope, msg, ts in self.items:
            out.append("  [%s %s] %s：%s" % (sev, ts, scope, msg))
        out.append("  ⚠️ 以上异常可能导致数据不完整，号码与盈亏不可作为完整依据。")
        return out

    def clear(self):
        self.items = []


ALERTS = _Alerts()

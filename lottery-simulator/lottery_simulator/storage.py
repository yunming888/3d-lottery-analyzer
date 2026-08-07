# -*- coding: utf-8 -*-
"""
历史记录保存与读取（JSON 文件）
-------------------------------
默认存到包外 data/history.json；后续可替换为数据库而无需改动调用方。
"""
import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional

from .draw import DrawResult


DEFAULT_HISTORY_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "history.json"
)


def save_draw(draw: DrawResult, history_file: str = DEFAULT_HISTORY_FILE,
              ticket: Optional[Dict[str, Any]] = None) -> Dict:
    """追加一注到历史文件，返回写入的记录。"""
    os.makedirs(os.path.dirname(history_file), exist_ok=True)
    record = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "draw": draw.to_dict(),
    }
    if ticket:
        record["ticket"] = ticket
    records = load_history(history_file)
    records.append(record)
    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    return record


def load_history(history_file: str = DEFAULT_HISTORY_FILE) -> List[Dict]:
    """读取全部历史记录；文件不存在返回空列表。"""
    if not os.path.exists(history_file):
        return []
    with open(history_file, "r", encoding="utf-8") as f:
        return json.load(f)

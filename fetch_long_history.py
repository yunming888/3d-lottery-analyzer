# -*- coding: utf-8 -*-
"""
拉取福彩3D长历史用于回测（只读远端，写入独立的 data/backtest_3d_long.json）
不污染每日链路使用的 data/3d_history.json。
"""
import json
import os
import time
import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "data", "backtest_3d_long.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


def fetch_page(page, limit=100):
    url = ("http://api.huiniao.top/interface/home/lotteryHistory"
           "?type=fcsd&page=%d&limit=%d" % (page, limit))
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            j = resp.json()
            if j.get("code") != 1:
                print("  page%d 异常: %s" % (page, j.get("info")))
                return []
            lst = j.get("data", {}).get("data", {}).get("list", [])
            out = []
            for it in lst:
                bai, shi, ge = int(it["one"]), int(it["two"]), int(it["three"])
                nums = [bai, shi, ge]
                if bai == shi == ge:
                    t = "豹子"
                elif bai == shi or shi == ge or bai == ge:
                    t = "组三"
                else:
                    t = "组六"
                out.append({
                    "qihao": str(it["code"]),
                    "date": it["day"],
                    "bai": bai, "shi": shi, "ge": ge,
                    "nums": nums,
                    "sum_val": sum(nums),
                    "span": max(nums) - min(nums),
                    "type": t,
                    "_source": "huiniao",
                })
            return out
        except Exception as e:
            print("  page%d 失败(%d): %s" % (page, attempt + 1, e))
            time.sleep(2)
    return []


def main(pages=12):
    seen = {}
    for p in range(1, pages + 1):
        recs = fetch_page(p)
        if not recs:
            print("page%d 无数据，停止" % p)
            break
        for r in recs:
            seen[r["qihao"]] = r
        print("page%d: %d 条，累计去重 %d 期" % (p, len(recs), len(seen)))
        time.sleep(0.4)
    merged = sorted(seen.values(), key=lambda x: x["qihao"], reverse=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    if merged:
        qs = [int(x["qihao"]) for x in merged]
        gaps = []
        for i in range(len(qs) - 1):
            if qs[i] - qs[i + 1] != 1:
                gaps.append((qs[i], qs[i + 1]))
        print("\n✅ 写入 %s" % OUT)
        print("   共 %d 期，范围 %s ~ %s（%s ~ %s）"
              % (len(merged), merged[-1]["qihao"], merged[0]["qihao"],
                 merged[-1]["date"], merged[0]["date"]))
        if gaps:
            print("   ⚠️ 期号不连续区间数：%d，示例：%s" % (len(gaps), gaps[:5]))
    else:
        print("❌ 未拉到数据")


if __name__ == "__main__":
    main()

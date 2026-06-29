"""
福彩3D 可视化图表
生成频率热力图、遗漏趋势图、和值分布图
"""
import json
import os
from datetime import datetime

DATA_FILE = "data/3d_history.json"
OUTPUT_DIR = "data/charts"

def load_data():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def generate_html_report(records):
    """生成一个独立的HTML分析看板"""
    total = len(records)
    recent = records[:200]

    freq = {i: 0 for i in range(10)}
    pos_freq = {"bai": {i: 0 for i in range(10)}, "shi": {i: 0 for i in range(10)}, "ge": {i: 0 for i in range(10)}}
    sum_freq = {i: 0 for i in range(28)}
    span_freq = {i: 0 for i in range(10)}
    type_freq = {"豹子": 0, "组三": 0, "组六": 0}

    for r in recent:
        for n in r["nums"]:
            freq[n] += 1
        pos_freq["bai"][r["bai"]] += 1
        pos_freq["shi"][r["shi"]] += 1
        pos_freq["ge"][r["ge"]] += 1
        sum_freq[r["sum_val"]] += 1
        span_freq[max(r["nums"]) - min(r["nums"])] += 1
        type_freq[r["type"]] += 1

    max_f = max(freq.values()) if max(freq.values()) > 0 else 1

    rows_html = ""
    for n in range(10):
        count = freq[n]
        pct = count / max_f * 100
        color = "rgba(59,130,246,0.85)" if pct > 60 else "rgba(59,130,246,0.4)"
        rows_html += f"""
        <tr>
          <td style="font-weight:500;width:40px">{n}</td>
          <td style="width:100%"><div style="height:18px;width:{pct}%;background:{color};border-radius:4px;transition:width 0.3s"></div></td>
          <td style="width:50px;text-align:right;font-variant-numeric:tabular-nums">{count}</td>
        </tr>"""

    pos_html = ""
    for pos_name, pos_label in [("bai", "百位"), ("shi", "十位"), ("ge", "个位")]:
        pf = pos_freq[pos_name]
        sorted_nums = sorted(pf.items(), key=lambda x: x[1], reverse=True)
        pos_html += f"<div style='flex:1;min-width:140px'><h3 style='font-size:14px;margin-bottom:8px'>{pos_label}</h3>"
        for n, c in sorted_nums[:3]:
            pos_html += f"<div style='margin-bottom:4px'><span style='font-weight:500'>{n}</span>: {c}次</div>"
        pos_html += "</div>"

    type_html = ""
    type_colors = {"豹子": "#ef4444", "组三": "#f59e0b", "组六": "#22c55e"}
    for t, c in type_freq.items():
        pct = c / 200 * 100
        type_html += f"""<div style="margin-bottom:6px">
          <span style="font-weight:500">{t}</span> {c}次 ({pct:.0f}%)
          <div style="height:6px;width:{pct}%;background:{type_colors[t]};border-radius:3px;margin-top:2px"></div>
        </div>"""

    latest_20 = records[:20]
    trend_html = "<table style='width:100%;font-size:12px;border-collapse:collapse'>"
    trend_html += "<tr style='border-bottom:1px solid #e5e7eb'><th style='padding:4px 8px;text-align:left'>期号</th><th style='padding:4px 8px'>开奖号</th><th style='padding:4px 8px'>和值</th><th style='padding:4px 8px'>跨度</th><th style='padding:4px 8px'>形态</th></tr>"
    for r in latest_20:
        nums_str = " ".join(map(str, r["nums"]))
        span = max(r["nums"]) - min(r["nums"])
        trend_html += f"<tr style='border-bottom:1px solid #f3f4f6'><td style='padding:4px 8px'>{r['qihao']}</td><td style='padding:4px 8px;font-weight:500;font-size:14px'>{nums_str}</td><td style='padding:4px 8px'>{r['sum_val']}</td><td style='padding:4px 8px'>{span}</td><td style='padding:4px 8px'>{r['type']}</td></tr>"
    trend_html += "</table>"

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>福彩3D 数据看板</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box }}
  body {{ font-family: -apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC',sans-serif; background:#f8fafc; color:#1e293b; padding:24px; line-height:1.6 }}
  .container {{ max-width:900px; margin:0 auto }}
  h1 {{ font-size:22px; font-weight:600; margin-bottom:4px }}
  .subtitle {{ color:#64748b; font-size:13px; margin-bottom:24px }}
  .card {{ background:#fff; border-radius:12px; padding:20px; margin-bottom:16px; box-shadow:0 1px 3px rgba(0,0,0,0.06) }}
  .card h2 {{ font-size:15px; font-weight:600; margin-bottom:12px; color:#334155 }}
  .grid-3 {{ display:flex; gap:16px; flex-wrap:wrap }}
  .badge {{ display:inline-block; padding:2px 10px; border-radius:12px; font-size:12px; font-weight:500 }}
  .badge-danger {{ background:#fef2f2; color:#dc2626 }}
  .badge-warning {{ background:#fffbeb; color:#d97706 }}
  .badge-success {{ background:#f0fdf4; color:#16a34a }}
  .disclaimer {{ background:#fefce8; border:1px solid #fde68a; border-radius:10px; padding:16px; margin-top:24px; font-size:12px; color:#854d0e }}
</style>
</head>
<body>
<div class="container">
  <h1>福彩3D 数据分析看板</h1>
  <p class="subtitle">数据范围: 近{len(recent)}期 | 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')} | 总数据: {total}期</p>

  <div class="card">
    <h2>号码频率分布 (近{len(recent)}期)</h2>
    <table style="width:100%">{rows_html}</table>
  </div>

  <div class="card">
    <h2>各位热号 Top3</h2>
    <div class="grid-3">{pos_html}</div>
  </div>

  <div class="card">
    <h2>形态分布</h2>
    {type_html}
  </div>

  <div class="card">
    <h2>最近20期开奖</h2>
    {trend_html}
  </div>

  <div class="disclaimer">
    此工具仅提供历史数据统计，不构成任何投注建议。彩票有风险，理性购彩。
  </div>
</div>
</body>
</html>"""

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, "dashboard.html")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"可视化看板已生成: {filepath}")
    return filepath

if __name__ == "__main__":
    records = load_data()
    generate_html_report(records)

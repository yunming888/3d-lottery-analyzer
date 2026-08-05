# 3D彩票分析器 - 项目记忆

## 熔断规则版本
- v7 (2026-07-06): Rule1组三高频熔断已禁用, 靠Rule2(和值极端)/Rule3(连续同形态)管
- v6 (2026-07-06): Rule1 改为近30期组三>=10次 (已废弃, 仍太敏感)
- 覆盖规则: Rule4(3连同形态→强推)/Rule6(组三2连→推组六)/Rule7(组六11连→警戒) 不熔断
- 用户只推组六, 不推组三

## 技术备忘
- git push: 统一用 `git pull --rebase` + `git push origin master`; Python API 兜底已废弃(token 失效)
- 微信推送(automation push_to_wechat): 自动化回复禁止调用 present_files(微信不渲染文件卡片→空白), 改为纯文本自包含输出
- 数据源: **已切换为 huiniao 官方镜像** `http://api.huiniao.top/interface/home/lotteryHistory?type=fcsd&page=1&limit=30` (fetch_data.py `fetch_huiniao`, 免鉴权, ~5分钟同步, 含 200+, 返回 `data.data.list[].{code,day,one,two,three}`)。东方财富兜底仍保留但已过期卡在 2026199。huiniao 实测最新 2026204(2026-08-02), 2026205 每晚21:15开。
- 每日7点自动执行 (automation-1782775804842)

## 休市判断 (2026-08-03 重构)
- 福彩3D **天天开奖、全年无休**, 周末照常开; 仅财政部公告的官方休市期停开: 春节(2026-02-14~02-23, 10天)、国庆(2026-10-01~10-04, 4天)。
- ❌ 旧逻辑(已废弃): `is_suspension = (last_draw_qihao == current_latest)` —— 期号没变就判休市, 在「抓取源过期/早晨未开奖/抓取失败」时全误判。
- ✅ 新逻辑: `trading_day.is_trading_day(date)` 按日历判定真休市; 交易日但本地数据期号落后预期(`expected_qihao_for_date` 推算)→ 标记「数据滞后」, **绝不误判休市**, 也不编造待开奖记录。
- 休市日列表: `data/holidays.json`(每年需按官方公告更新)。
- 07-31 那3注曾因数据过期误记 target=2026200(=07-29已开), 已修正为真实下一期 **2026202(2026-07-31开, 988 组三)**; 命中0/盈亏-6 不变(推组六 vs 组三必输)。结算逻辑现已按期号精确匹配, 数据新鲜时 target=latest+1 正确。

## 追踪期
- 2026-06-13 ~ 2026-08-31
- profit_loss.json end_date = 2026-08-31

## 子项目: lottery-strategy-analyzer (2026-08-05 新建)
- 位置: 本仓库 `lottery-strategy-analyzer/` —— 通用彩票策略分析程序（双色球/大乐透），与 3D 项目独立。
- 结构: `lottery_analyzer/` 包(config/fetcher/analyzer/recommender/backtester/visualizer/report) + `run.py`(CLI)。
- 数据源: 500彩票网历史接口 `datachart.500.com/{game}/history/newinc/history.php`(server-render HTML, 需剔 `<!--<td>2</td>-->` 注释伪节点; 期号 YYNNN 跨年, 抓取起点按当前年份回退≥2年取窗口)。
- 统计: 频率/冷热三分位/当前+最大遗漏/区间/奇偶和值; 三策略(hot/cold/balanced)选号+回测(组合数学理论中奖率对照)。
- 输出: `output/{game}_analysis.json` / `_report.md` / `_report.html`(图表 base64 内嵌) + 4张 PNG。
- 依赖 matplotlib(已装项目 venv)；运行需 `--refresh` 重新抓取。
- 新增彩种只需在 `config.py` 的 LOTTERIES/SOURCE_500/TIER_FUNC 注册, 核心算法不动。

# 3D彩票分析器 - 项目记忆

## 熔断规则版本
- v7 (2026-07-06): Rule1组三高频熔断已禁用, 靠Rule2(和值极端)/Rule3(连续同形态)管
- v6 (2026-07-06): Rule1 改为近30期组三>=10次 (已废弃, 仍太敏感)
- 覆盖规则: Rule4(3连同形态→强推)/Rule6(组三2连→推组六)/Rule7(组六11连→警戒) 不熔断
- 用户只推组六, 不推组三

## 技术备忘
- git push 经常因网络问题失败, 用 GitHub API (Python requests) 推送替代
- GitHub token 存在 daily_review.py 的自动化任务指令中
- 微信推送(automation push_to_wechat): 自动化回复禁止调用 present_files(微信不渲染文件卡片→空白), 改为纯文本自包含输出
- 数据源: 东方财富, 抓取脚本 fetch_data.py
- 每日7点自动执行 (automation-1782775804842)

## 追踪期
- 2026-06-13 ~ 2026-07-31
- profit_loss.json end_date = 2026-07-31

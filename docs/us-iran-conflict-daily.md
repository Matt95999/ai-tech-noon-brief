# 美国-伊朗冲突每日简报接入说明

## 主题

- 主题：美国与伊朗冲突每日新闻
- 目标：每天汇总过去 24 小时真实可靠、影响力大的高置信动态
- 验收：邮件按时送达，正文只保留高影响事实，低信号日允许发“无重大新增”

## 复用骨架

- 发现层：`rss`
- 成稿层：`deepseek_chat`
- 调度：GitHub Actions
- 投递：SMTP 邮件
- 代码入口：`python3 scripts/run_profile.py --profile us-iran-conflict-daily`

## 新增文件

- `profiles/us-iran-conflict-daily.json`
- `templates/us_iran_conflict_daily_template.md`
- `.github/workflows/us-iran-conflict-daily.yml`

## 运行策略

- 时区：`Asia/Shanghai`
- 时间窗：过去 `24` 小时
- 定时：每天北京时间 `06:30`
- 低信号策略：允许发送“无重大新增”

## 信源和门槛

- 优先信源：官方机构、IEA、IAEA、IMF、央行与监管机构
- 次级高质量媒体：Reuters、AP、FT、Bloomberg、WSJ、CNBC、Nikkei Asia
- 影响关键词：停火、霍尔木兹、油气、制裁、空袭、导弹、核设施、航运、通胀、央行路径
- 门槛：`min_high_confidence_items = 1`

## 本地验证

```bash
python3 -m unittest discover -s tests
python3 scripts/run_profile.py --profile us-iran-conflict-daily --dry-run
python3 scripts/run_profile.py --profile us-iran-conflict-daily --skip-delivery
python3 scripts/send_email_report.py --check-config
```

## 上线检查

- GitHub Secrets 复用现有 `DEEPSEEK_*` 和 `SMTP_*`
- 手动触发 `.github/workflows/us-iran-conflict-daily.yml`
- 确认 `Generate daily brief`
- 确认 `Validate report structure`
- 确认 `Send email`
- 确认邮箱收到 `美国-伊朗冲突每日简报（YYYY-MM-DD）`

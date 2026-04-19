# 集成电路先进封装每日简报接入说明

## 主题

- 主题：集成电路先进封装行业最新进展
- 目标：每天汇总过去 24 小时真实可靠、影响力大的先进封装新增，覆盖国内外龙头公司和上下游完整产业链
- 受众：管理层、投资研究、业务拓展与产业链合作团队
- 验收：飞书卡片按时送达，正文只保留高影响事实，低信号日允许发“无重大新增”

## 复用骨架

- 发现层：`rss`
- 成稿层：`deepseek_chat`
- 调度：GitHub Actions
- 投递：飞书自定义机器人 Webhook 卡片
- 代码入口：`python3 scripts/run_profile.py --profile advanced-packaging-daily`

## 新增文件

- `profiles/advanced-packaging-daily.json`
- `templates/advanced_packaging_daily_template.md`
- `.github/workflows/advanced-packaging-daily.yml`

## 运行策略

- 时区：`Asia/Shanghai`
- 时间窗：过去 `24` 小时
- 定时：每天北京时间 `08:30`
- 低信号策略：允许发送“无重大新增”

## 主题覆盖

- 国际龙头：`TSMC`、`Intel Foundry`、`Samsung Foundry`、`ASE`、`Amkor`
- 中国龙头：`长电科技`、`通富微电`、`华天科技`、`深南电路`
- 需求牵引：`NVIDIA`、`AMD`、`Broadcom`、`Marvell`、`Huawei`
- 关键链条：`HBM`、`Chiplet`、`CoWoS`、`SoIC`、`Foveros`、`I-Cube`、`X-Cube`、`ABF substrate`、`FCBGA`、`fan-out`、`hybrid bonding`、`CPO`

## 信源和门槛

- 优先信源：公司官网、IR、技术活动页、官方新闻稿、交易所公告、`UCIe Consortium`、`SEMI`、`SEMICON`、`IEDM`、`ECTC`
- 次级高质量媒体：`Reuters`、`Bloomberg`、`Financial Times`、`Nikkei Asia`、`CNBC`、`EE Times`、`Semiconductor Engineering`、`DigiTimes`、`TrendForce`
- 低置信规则：`unclassified` 只进入观察候选，不能单独支撑高影响结论；低质 publisher 与营销/股价噪音会进入 source audit 排除统计
- 影响关键词：先进封装、`CoWoS`、`HBM`、`Chiplet`、`Foveros`、`EMIB`、`FOCoS`、`XDFOI`、`ABF`、混合键合、硅光、`CPO`
- 门槛：`min_high_confidence_items = 1`

## 建模依据

- `2025-04-29`：Intel 在 `Foundry Direct Connect 2025` 强调先进封装、测试与系统代工能力。
- `2025-05-28`：ASE 发布 `FOCoS-Bridge with TSV`，继续强化 AI/HPC 封装平台。
- `2025-06-03`：AT&S 启用欧洲 `IC substrate` 与 advanced packaging 研发产线。
- `2025-10-06`：Amkor 宣布亚利桑那先进封装与测试园区扩产至 `70 亿美元` 级别。
- `2026-03-16`：Micron 宣布面向 `NVIDIA Vera Rubin` 的 `HBM4` 进入大规模量产。
- `2026-03-31`：NVIDIA 与 Marvell 宣布通过 `NVLink Fusion` 与硅光合作扩展 AI 基础设施生态。

## 本地验证

```bash
python3 -m unittest discover -s tests
python3 scripts/run_profile.py --profile advanced-packaging-daily --dry-run
python3 scripts/run_profile.py --profile advanced-packaging-daily --skip-delivery
python3 scripts/send_feishu_report.py --check-feishu
```

## 上线检查

- GitHub Secrets 配置 `DEEPSEEK_*` 与 `FEISHU_WEBHOOK_URL`
- 如飞书机器人开启签名校验，额外配置 `FEISHU_SIGN_SECRET`
- Webhook 只能写入 GitHub Secret，不应写入代码、profile、日志或 PR 描述
- 手动触发 `.github/workflows/advanced-packaging-daily.yml`
- 确认 `Generate daily brief`
- 确认 `Validate report structure`
- 确认 `Send Feishu card`
- 确认飞书群收到 `集成电路先进封装每日简报（YYYY-MM-DD）` 卡片

# Research Automation Hub

这个仓库现在同时承担两类职责：

- 通用的“资料搜索 + 简报生成”母版能力
- GitHub 托管的 `ai-evening-brief` 晚报生产链路

本机正式晨报发送仍由 `/Users/chrome/ai-daily-brief` 独立负责。

## 目标

- 抓取过去 24 小时 AI / 科技行业高信噪比公开动态
- 聚焦行业新闻、公司动作、技术发布、资本市场影响与后续观察点
- 生成中文研究简报 Markdown
- 通过 GitHub Actions 做 dry-run 校验、模板回归和晚报正式发送
- 内建自审产物，方便后续升级到 Claude / Codex / Gemini 多角色协作

## 仓库结构

- `profiles/`：每个自动化需求一份 profile 配置
- `collectors/`：资料抓取模块，如 OpenAI 搜索、RSS、DeepSeek 整理
- `delivery/`：发送通道，如邮件
- `scripts/`：主流程脚本、邮件发送、自审生成
- `templates/`：简报模板与任务模板
- `prompts/`：Claude / Codex / Reviewer 提示词
- `docs/`：SOP 与新 profile 清单
- `reports/`：最终报告输出
- `artifacts/`：研究底稿、API 原始响应、运行元数据
- `reviews/`：自动生成的自审记录
- `plans/`、`summaries/`：后续多代理协作预留目录
- `.github/workflows/`：GitHub Actions 定时任务

## 运行方式

### 1. 本地手动执行

先准备环境变量：

```bash
cp .env.example .env
cp config.example.json config.json
```

然后执行默认 profile：

```bash
./run_brief.sh
```

### 2. 本地 dry-run

dry-run 不依赖外部 API 或 SMTP，适合验证整条链路和目录输出：

```bash
./run_brief.sh --dry-run
```

也可以显式指定 profile：

```bash
python3 scripts/run_profile.py --profile ai-tech-daily --dry-run
```

晚报 dry-run：

```bash
python3 scripts/run_profile.py --profile ai-evening-brief --dry-run
```

模型配置预检：

```bash
python3 scripts/run_profile.py --profile ai-evening-brief --check-deepseek
```

```bash
python3 scripts/run_profile.py --profile ai-frontier-daily --check-openai
```

### 3. 单独测试邮件模块

```bash
python3 scripts/send_email_report.py reports/2026-03-27.md --dry-run
```

### 4. 单独测试飞书模块

```bash
python3 scripts/send_feishu_report.py --check-feishu
python3 scripts/send_feishu_report.py reports/2026-03-27.md --dry-run
```

## GitHub Actions

工作流分三条：

- `.github/workflows/ai-tech-noon-brief.yml`
  - 每天 `12:00` 北京时间执行 dry-run 校验，对应 `04:00 UTC`
  - 默认运行 profile：`ai-frontier-daily`
  - 用于模板回归和结构验证
- `.github/workflows/ai-evening-brief.yml`
  - 每天 `20:00` 北京时间正式运行，对应 `12:00 UTC`
  - 固定运行 profile：`ai-evening-brief`
  - 顺序：单测 -> 生成报告 -> 结构校验 -> 发送邮件 -> 上传 artifacts
- `.github/workflows/model-dev-github-daily.yml`
  - 每天 `09:10` 北京时间正式运行，对应 `01:10 UTC`
  - 固定运行 profile：`model-dev-github-daily`
  - 数据来自 GitHub 官方 REST API，覆盖 Codex、Claude Code、Gemini 与国内外主流模型开发生态
- `.github/workflows/advanced-packaging-daily.yml`
  - 每天 `08:30` 北京时间正式运行，对应 `00:30 UTC`
  - 固定运行 profile：`advanced-packaging-daily`
  - 投递到飞书自定义机器人 Webhook；完整 Markdown 和 source audit 仍上传到 artifacts

### 需要配置的 Secrets

- `DEEPSEEK_API_URL`
- `DEEPSEEK_API_KEY`
- `DEEPSEEK_MODEL`
- `FEISHU_WEBHOOK_URL`
- `FEISHU_SIGN_SECRET`（可选，仅飞书机器人启用签名校验时需要）
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_USE_SSL`
- `SMTP_USE_TLS`
- `EMAIL_FROM`
- `EMAIL_TO`

有效配置规则：

- `DEEPSEEK_API_URL` 支持填写 base URL 或完整聊天接口 URL。
- 例如 `https://api.deepseek.com` 会自动补全成 `https://api.deepseek.com/chat/completions`，`https://api.deepseek.com/v1` 会自动补全成 `https://api.deepseek.com/v1/chat/completions`
- 如果 `DEEPSEEK_API_URL` 指向明显错误的路径，系统会直接失败，不再静默降级。
- `DEEPSEEK_MODEL` 默认可用 `deepseek-chat`
- `OPENAI_API_KEY` 只对 `openai_search` 类 profile 生效
- `GITHUB_TOKEN` 只对 `github_search` 类 profile 生效；GitHub Actions 默认使用 `github.token`
- `FEISHU_WEBHOOK_URL` 只通过 GitHub Secret 注入，不应提交到仓库、profile 或日志
- `FEISHU_SIGN_SECRET` 可选；配置后飞书 payload 会自动加签
- 如果 `OPENAI_API_KEY` 缺失，`openai_search` profile 会回退到 RSS，不会得到 OpenAI 深度检索结果
- `SMTP_PORT` 必须是有效端口；`SMTP_USE_SSL=true` 不应搭配 `587`，`SMTP_USE_TLS=true` 不应搭配 `465`
- `DEEPSEEK_API_KEY`、`DEEPSEEK_API_URL`、`SMTP` 或 `FEISHU` 配置会在对应 live workflow 生成前先做预检；配置错误会直接失败，不再因为低信号日被掩盖

### 可选 Variables

- `REPORT_TIMEZONE`
- `LOOKBACK_HOURS`
- `BRIEF_DEFAULT_PROFILE`：覆盖 GitHub Actions 与本地脚本默认 profile

## Profile 化配置

- 运行时环境变量：模型与邮件认证
- `profiles/<slug>.json`：主题、数据源、关键词、模板、发送方式、信源规则、影响力门槛

优先级：

1. 命令行参数
2. 环境变量
3. `profiles/<slug>.json`
4. 代码默认值

## 新需求接入

新增一个自动化需求时，不需要重写整套代码：

1. 复制 `templates/profile.example.json`
2. 生成 `profiles/<你的主题>.json`
3. 调整关键词、公司名单、模板和发送策略
4. 运行 `python3 scripts/run_profile.py --profile <你的主题> --dry-run`
5. 若需要正式发送，再配置 DeepSeek / SMTP secrets 并上线到 GitHub Actions

SOP 见：

- `docs/SOP.md`：仓库接入与运行说明
- `docs/news-automation-sop.md`：面向“新主题新闻自动化复用”的标准 SOP
- `docs/new-profile-checklist.md`：新主题接入检查单

## 自审机制

每次运行会额外生成一个 `reviews/<date>-self-review.md`，内容包括：

- 本次目标、范围、验证方式、非目标
- 数据量与降级情况
- 正确性 / 回归 / 边界条件 / 配置安全性检查项
- 后续可改进建议

这套格式与 `prompts/`、`templates/task-brief.md` 配合，可以直接升级到：

- Claude：规划
- Codex：实现
- Reviewer / Gemini：独立审查

## 测试

```bash
python3 -m unittest discover -s tests
```

## 注意事项

- `reports/`、`artifacts/`、`logs/` 默认不提交运行产物
- 如果没有足够高置信新闻，报告会明确输出“无重大新增”
- 邮件失败不会删除已生成的报告与 artifacts，便于补发和排查
- `ai-evening-brief` 默认采用“主信源优先 + 二线高质量媒体补充 + 影响力关键词过滤”的规则
- 新主题新闻自动化默认复用 `deepseek_chat + rss + GitHub Actions + SMTP` 这条链路

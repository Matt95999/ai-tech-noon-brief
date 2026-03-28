# Research Automation Hub

这个仓库现在是一个“资料搜索 + 简报生成 + 邮件发送”的通用自动化母版，当前内置了 `ai-tech-daily` 这个 profile。

## 目标

- 抓取过去 24 小时 AI / 科技行业高信噪比公开动态
- 聚焦行业新闻、公司动作、技术发布、资本市场影响与后续观察点
- 生成中文研究简报 Markdown
- 通过 GitHub Actions 云端定时运行
- 内建自审产物，方便后续升级到 Claude / Codex / Gemini 多角色协作

## 仓库结构

- `profiles/`：每个自动化需求一份 profile 配置
- `collectors/`：资料抓取模块，如 OpenAI 搜索、RSS 等
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

### 3. 单独测试邮件模块

```bash
python3 scripts/send_email_report.py reports/2026-03-27.md --dry-run
```

## GitHub Actions

工作流文件：`.github/workflows/ai-tech-noon-brief.yml`

- 定时：每天 `12:00` 北京时间，对应 `04:00 UTC`
- 默认运行 profile：`ai-frontier-daily`
- 也支持手动触发 `workflow_dispatch`

### 需要配置的 Secrets

- `OPENAI_API_KEY`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `EMAIL_FROM`
- `EMAIL_TO`

### 可选 Variables

- `OPENAI_MODEL`
- `REPORT_TIMEZONE`
- `LOOKBACK_HOURS`
- `BRIEF_DEFAULT_PROFILE`：覆盖 GitHub Actions 与本地脚本默认 profile

## Profile 化配置

- 运行时环境变量：模型与邮件认证
- `profiles/<slug>.json`：主题、数据源、关键词、模板、发送方式

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
5. 验证后再上线到 GitHub Actions

SOP 见：`docs/SOP.md`

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

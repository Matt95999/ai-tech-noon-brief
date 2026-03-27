# AI / 科技行业中午简报

这个仓库用于“每天北京时间中午自动抓取 AI / 科技行业与重点公司公开动态，生成中文研究简报，并通过邮件发送”。

## 目标

- 抓取过去 24 小时 AI / 科技行业高信噪比公开动态
- 聚焦行业新闻、公司动作、技术发布、资本市场影响与后续观察点
- 生成中文研究简报 Markdown
- 通过 GitHub Actions 云端定时运行
- 内建自审产物，方便后续升级到 Claude / Codex / Gemini 多角色协作

## 仓库结构

- `scripts/`：主流程脚本、邮件发送、自审生成
- `templates/`：简报模板与任务模板
- `prompts/`：Claude / Codex / Reviewer 提示词
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

然后执行：

```bash
./run_brief.sh
```

### 2. 本地 dry-run

dry-run 不依赖外部 API 或 SMTP，适合验证整条链路和目录输出：

```bash
./run_brief.sh --dry-run
```

### 3. 单独测试邮件模块

```bash
python3 scripts/send_email_report.py reports/2026-03-27.md --dry-run
```

## GitHub Actions

工作流文件：`.github/workflows/ai-tech-noon-brief.yml`

- 定时：每天 `12:00` 北京时间，对应 `04:00 UTC`
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

## 统一配置

- 运行时环境变量：模型与邮件认证
- `config.json`：主题、关注公司、关键词、报告风格、保留策略

优先级：

1. 命令行参数
2. 环境变量
3. `config.json`
4. 代码默认值

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


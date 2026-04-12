# Agent / Codex / Claude Code GitHub 日报接入说明

## 主题

- 主题：每天获取 GitHub 上与通用 Agent、Codex 生态、Claude Code 生态相关的高 Star 新玩法和重点仓库动态，并保留指定观察项目如 Hermes Agent、OpenScreen
- 目标：把“每天自己翻 GitHub”变成一条自动化日报链路
- 受众：个人开发者、独立产品开发、AI 工程效率工作流
- 验收：每天按时生成一份 Markdown 日报；如果 SMTP 已配置则同步发邮件；低信号日也不断档

## 推荐落地方案

- 发现层：`github_search`
- 成稿层：规则化摘要，不依赖大模型
- 调度：`GitHub Actions` 每天北京时间 `09:10`
- 投递：SMTP 邮件，可复用仓库现有发送链路

## 为什么这样设计

- 稳定：核心数据来自 GitHub 官方 REST API，不依赖网页抓取
- 成本低：即使不配模型 API，也能每天稳定产出
- 可扩展：后续如果你想把“玩法点评”写得更像研究简报，再叠加 `openai_search` 或 `deepseek_chat`
- 抗偏科：通过 focus map 和分组选择逻辑，日报不会长期只剩单一生态

## 新增文件

- `collectors/github_search.py`
- `profiles/agent-codex-claude-github-daily.json`
- `templates/agent_codex_claude_github_daily_template.md`
- `.github/workflows/agent-codex-claude-github-daily.yml`

## 运行策略

- 时间窗：过去 `24` 小时的活跃仓库 + 过去 `14` 天的新建高 Star 仓库
- Star 门槛：默认 `80`
- 覆盖生态：
  - `通用 Agent`
  - `Codex`
  - `Claude Code`
  - `Hermes Agent`
  - `OpenHands`
  - `OpenScreen`
- 输出重点：
  - 今天最值得先看哪几个仓库
  - 每个仓库具体在做什么，属于哪类玩法主题
  - 每个仓库有哪些可玩点，适不适合拿来做你自己的玩法参考
  - 哪些属于官方仓库更新，哪些属于社区新玩法

## 环境变量

- 必填：无
- 推荐：`GITHUB_TOKEN`
  - 本地可不填，仍可跑公开仓库
  - GitHub Actions 默认复用 `github.token`
- 邮件发送仍复用现有 `SMTP_*` 和 `EMAIL_*`

## 本地验证

```bash
python3 -m unittest discover -s tests
python3 scripts/run_profile.py --profile agent-codex-claude-github-daily --dry-run
python3 scripts/run_profile.py --profile agent-codex-claude-github-daily --skip-delivery
```

## 上线检查

- 确认 workflow `agent-codex-claude-github-daily.yml` 已启用
- 手动触发一次 workflow
- 确认 `reports/` 生成当日 Markdown
- 确认 `artifacts/` 写入 research notes 和 API 元数据
- 若配置了 SMTP，确认邮箱收到 `Agent / Codex / Claude Code GitHub 日报（YYYY-MM-DD）`

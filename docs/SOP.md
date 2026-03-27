# SOP：资料搜索与邮件自动化

## 目标

把“搜索资料 -> 生成简报 -> 发送通知”做成可复用的 GitHub 自动化流程。

## 新需求接入步骤

1. 复制 `templates/profile.example.json` 到 `profiles/<slug>.json`
2. 填写主题、关键词、公司名单、时间窗口和发送方式
3. 选择 collector：
   - `openai_search`
   - `rss`
4. 指定报告模板 `template_path`
5. 本地执行：
   - `python3 scripts/run_profile.py --profile <slug> --dry-run`
6. 验证 dry-run 后执行真实链路：
   - `python3 scripts/run_profile.py --profile <slug>`
7. 如果需要定时运行，在 `.github/workflows/ai-tech-noon-brief.yml` 中新增或调整 profile 参数

## 默认流程

- 优先使用高质量搜索
- 无模型 key 时自动回退到 RSS
- 生成报告后写入 artifacts、reviews、summaries
- 发送失败不删除报告，便于补发

## 标准检查项

- profile 是否完整
- collector 是否与需求匹配
- 模板是否符合输出风格
- secrets 是否已配置
- dry-run 是否通过
- 真实发送是否成功

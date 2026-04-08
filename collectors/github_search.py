from __future__ import annotations

import base64
import json
import os
import re
import ssl
from datetime import datetime, timedelta, timezone
from urllib import error, parse, request

from scripts.brief_utils import BriefGenerationError, USER_AGENT

GITHUB_API_ROOT = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
DEFAULT_GITHUB_CREATED_DAYS = 14
DEFAULT_GITHUB_MIN_STARS = 80
DEFAULT_GITHUB_MAX_CANDIDATES = 6


def build_github_headers(token: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def request_github_json(url: str, token: str | None = None, allow_404: bool = False) -> dict | None:
    req = request.Request(url, headers=build_github_headers(token), method="GET")
    try:
        with request.urlopen(req, timeout=90) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        if allow_404 and exc.code == 404:
            return None
        details = exc.read().decode("utf-8", errors="ignore")
        if exc.code == 403 and "rate limit" in details.lower():
            raise BriefGenerationError(
                "GitHub API rate limit exceeded. Set GITHUB_TOKEN for higher limits, "
                "or rely on GitHub Actions where github.token is injected automatically."
            ) from exc
        raise BriefGenerationError(f"GitHub API request failed: {exc.code} {details}") from exc
    except error.URLError as exc:
        if isinstance(exc.reason, ssl.SSLCertVerificationError):
            insecure_context = ssl._create_unverified_context()
            try:
                with request.urlopen(req, timeout=90, context=insecure_context) as response:
                    return json.loads(response.read().decode("utf-8"))
            except error.HTTPError as insecure_http_error:
                if allow_404 and insecure_http_error.code == 404:
                    return None
                details = insecure_http_error.read().decode("utf-8", errors="ignore")
                raise BriefGenerationError(
                    f"GitHub API request failed: {insecure_http_error.code} {details}"
                ) from insecure_http_error
        raise BriefGenerationError(f"GitHub API request failed: {exc}") from exc


def parse_github_datetime(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def normalize_github_text(value: str) -> str:
    lowered = value.lower().strip()
    return re.sub(r"[\W_]+", " ", lowered, flags=re.UNICODE).strip()


def extract_readme_excerpt(markdown_text: str, max_chars: int = 220) -> str:
    def clean_inline_markdown(line: str) -> str:
        text = re.sub(r"`([^`]+)`", r"\1", line)
        text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        text = re.sub(r"\*([^*]+)\*", r"\1", text)
        text = re.sub(r"^>\s*", "", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip(" -")

    selected: list[str] = []
    in_code_block = False
    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block or not line or line.startswith("#"):
            continue
        if "shields.io" in line or line.startswith("[![") or line.startswith("!["):
            continue
        cleaned = clean_inline_markdown(line)
        if len(cleaned) < 30:
            continue
        selected.append(cleaned)
        if len(" ".join(selected)) >= max_chars:
            break
    excerpt = " ".join(selected).strip()
    if len(excerpt) > max_chars:
        excerpt = excerpt[: max_chars - 1].rstrip() + "..."
    return excerpt


def normalize_search_item(raw_item: dict, bucket: str, matched_query: str) -> dict:
    return {
        "full_name": raw_item["full_name"],
        "name": raw_item["name"],
        "html_url": raw_item["html_url"],
        "description": raw_item.get("description") or "",
        "stars": int(raw_item.get("stargazers_count", 0)),
        "forks": int(raw_item.get("forks_count", 0)),
        "language": raw_item.get("language") or "",
        "topics": list(raw_item.get("topics", []) or []),
        "created_at": parse_github_datetime(raw_item["created_at"]),
        "updated_at": parse_github_datetime(raw_item["updated_at"]),
        "pushed_at": parse_github_datetime(raw_item["pushed_at"]),
        "bucket": bucket,
        "matched_query": matched_query,
        "watchlisted": False,
        "readme_excerpt": "",
        "latest_release": None,
        "focus_labels": [],
        "score": 0.0,
        "relevance_score": 0,
    }


def resolve_focus_map(config: dict) -> dict[str, list[str]]:
    focus_map = dict(config.get("github_focus_map", {}))
    normalized: dict[str, list[str]] = {}
    for label, aliases in focus_map.items():
        label_text = str(label).strip()
        alias_items = aliases if isinstance(aliases, list) else [aliases]
        merged = [label_text]
        for alias in alias_items:
            alias_text = str(alias).strip()
            if alias_text:
                merged.append(alias_text)
        if label_text:
            normalized[label_text] = list(dict.fromkeys(merged))
    return normalized


def extract_focus_labels(repo: dict, config: dict) -> list[str]:
    haystack = normalize_github_text(
        " ".join(
            [
                repo.get("full_name", ""),
                repo.get("description", ""),
                " ".join(repo.get("topics", [])),
                repo.get("matched_query", ""),
                repo.get("readme_excerpt", ""),
            ]
        )
    )
    labels: list[str] = []
    for label, aliases in resolve_focus_map(config).items():
        for alias in aliases:
            token = normalize_github_text(alias)
            if token and token in haystack:
                labels.append(label)
                break
    return list(dict.fromkeys(labels))


def compute_relevance_score(repo: dict, config: dict) -> int:
    haystack = normalize_github_text(
        " ".join(
            [
                repo.get("full_name", ""),
                repo.get("description", ""),
                " ".join(repo.get("topics", [])),
                repo.get("matched_query", ""),
                repo.get("readme_excerpt", ""),
            ]
        )
    )
    score = 0
    for _, aliases in resolve_focus_map(config).items():
        for alias in aliases:
            token = normalize_github_text(alias)
            if token and token in haystack:
                score += 3
                break
    if any(term in haystack for term in ("agent", "workflow", "cli", "tool", "coding", "developer", "github action")):
        score += 1
    return score


def build_search_specs(now_local: datetime, config: dict) -> list[dict]:
    base_queries = list(dict.fromkeys(config.get("github_queries", [])))
    created_cutoff = (
        now_local - timedelta(days=int(config.get("github_created_days", DEFAULT_GITHUB_CREATED_DAYS)))
    ).astimezone(timezone.utc).strftime("%Y-%m-%d")
    pushed_value = (
        now_local - timedelta(hours=int(config["lookback_hours"]))
    ).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    search_specs: list[dict] = []
    for query in base_queries[:6]:
        base = f"{query} archived:false is:public"
        search_specs.append({"bucket": "fresh", "sort": "stars", "query": f"{base} created:>={created_cutoff}"})
        search_specs.append({"bucket": "active", "sort": "updated", "query": f"{base} pushed:>={pushed_value}"})
    return search_specs


def search_repositories(now_local: datetime, config: dict, token: str | None = None) -> list[dict]:
    results: list[dict] = []
    for spec in build_search_specs(now_local, config):
        params = parse.urlencode({"q": spec["query"], "sort": spec["sort"], "order": "desc", "per_page": "10"})
        payload = request_github_json(f"{GITHUB_API_ROOT}/search/repositories?{params}", token=token) or {}
        for item in payload.get("items", []):
            results.append(normalize_search_item(item, spec["bucket"], spec["query"]))
    return results


def fetch_repository(full_name: str, token: str | None = None) -> dict:
    payload = request_github_json(f"{GITHUB_API_ROOT}/repos/{parse.quote(full_name, safe='')}", token=token, allow_404=True)
    if not payload:
        raise BriefGenerationError(f"Repository not found or inaccessible: {full_name}")
    repo = normalize_search_item(payload, "watch", full_name)
    repo["watchlisted"] = True
    return repo


def fetch_latest_release(full_name: str, token: str | None = None) -> dict | None:
    payload = request_github_json(
        f"{GITHUB_API_ROOT}/repos/{parse.quote(full_name, safe='')}/releases/latest",
        token=token,
        allow_404=True,
    )
    if not payload:
        return None
    return {
        "name": payload.get("name") or payload.get("tag_name") or "",
        "tag_name": payload.get("tag_name") or "",
        "html_url": payload.get("html_url") or "",
        "published_at": parse_github_datetime(payload["published_at"]) if payload.get("published_at") else None,
    }


def fetch_readme_excerpt(full_name: str, token: str | None = None, max_chars: int = 220) -> str:
    payload = request_github_json(
        f"{GITHUB_API_ROOT}/repos/{parse.quote(full_name, safe='')}/readme",
        token=token,
        allow_404=True,
    )
    if not payload:
        return ""
    content = payload.get("content") or ""
    if payload.get("encoding") != "base64" or not content:
        return ""
    decoded = base64.b64decode(content).decode("utf-8", errors="ignore")
    return extract_readme_excerpt(decoded, max_chars=max_chars)


def compute_repo_score(repo: dict, now_local: datetime, config: dict) -> float:
    fresh_cutoff = now_local - timedelta(days=int(config.get("github_created_days", DEFAULT_GITHUB_CREATED_DAYS)))
    score = min(repo.get("stars", 0), 5000) / 40
    pushed_at = repo.get("pushed_at")
    if pushed_at:
        hours_since_push = max((now_local - pushed_at.astimezone(now_local.tzinfo or timezone.utc)).total_seconds() / 3600, 0)
        score += max(0, 36 - min(hours_since_push, 36)) / 3
    if repo.get("created_at") and repo["created_at"].astimezone(now_local.tzinfo or timezone.utc) >= fresh_cutoff:
        score += 12
    if repo.get("bucket") == "fresh":
        score += 8
    if repo.get("watchlisted"):
        score += 16
    release = repo.get("latest_release")
    published_at = release.get("published_at") if isinstance(release, dict) else None
    if published_at and published_at.astimezone(now_local.tzinfo or timezone.utc) >= now_local - timedelta(days=7):
        score += 10
    return round(score, 2)


def build_watch_repositories(config: dict, token: str | None = None) -> list[dict]:
    watched: list[dict] = []
    for full_name in list(dict.fromkeys(config.get("github_watch_repos", [])))[:8]:
        try:
            watched.append(fetch_repository(full_name, token=token))
        except BriefGenerationError:
            continue
    return watched


def select_top_repositories(
    items: list[dict],
    now_local: datetime,
    config: dict,
    token: str | None = None,
    enrich: bool = True,
) -> list[dict]:
    selected: dict[str, dict] = {}
    for item in items:
        if not item.get("watchlisted") and int(item.get("stars", 0)) < int(config.get("github_min_stars", DEFAULT_GITHUB_MIN_STARS)):
            continue
        existing = selected.get(item["full_name"])
        if existing is None or item.get("stars", 0) > existing.get("stars", 0):
            selected[item["full_name"]] = dict(item)

    ranked = list(selected.values())
    ranked.sort(key=lambda repo: (repo.get("watchlisted", False), repo.get("stars", 0)), reverse=True)
    candidates = ranked[: int(config.get("github_max_candidates", DEFAULT_GITHUB_MAX_CANDIDATES)) + 6]

    for repo in candidates:
        if enrich:
            repo["latest_release"] = fetch_latest_release(repo["full_name"], token=token)
            repo["readme_excerpt"] = fetch_readme_excerpt(
                repo["full_name"],
                token=token,
                max_chars=int(config.get("github_readme_max_chars", 220)),
            )
        repo["focus_labels"] = extract_focus_labels(repo, config)
        repo["relevance_score"] = compute_relevance_score(repo, config)
        repo["score"] = compute_repo_score(repo, now_local, config)

    relevant = [repo for repo in candidates if repo.get("watchlisted") or repo.get("relevance_score", 0) >= 4]
    watchlisted = [repo for repo in relevant if repo.get("watchlisted")]
    non_watchlisted = [repo for repo in relevant if not repo.get("watchlisted")]
    watchlisted.sort(key=lambda repo: (repo.get("score", 0.0), repo.get("stars", 0)), reverse=True)
    non_watchlisted.sort(
        key=lambda repo: (repo.get("relevance_score", 0), repo.get("score", 0.0), repo.get("stars", 0)),
        reverse=True,
    )

    picked: list[dict] = []
    picked.extend(watchlisted[: min(2, len(watchlisted))])
    covered_labels = {label for repo in picked for label in repo.get("focus_labels", [])}
    for label in resolve_focus_map(config):
        if len(picked) >= int(config.get("github_max_candidates", DEFAULT_GITHUB_MAX_CANDIDATES)):
            break
        if label in covered_labels:
            continue
        candidate = next((repo for repo in non_watchlisted if label in repo.get("focus_labels", [])), None)
        if candidate and candidate not in picked:
            picked.append(candidate)
            covered_labels.update(candidate.get("focus_labels", []))
    for repo in non_watchlisted:
        if len(picked) >= int(config.get("github_max_candidates", DEFAULT_GITHUB_MAX_CANDIDATES)):
            break
        if repo not in picked:
            picked.append(repo)
    return picked[: int(config.get("github_max_candidates", DEFAULT_GITHUB_MAX_CANDIDATES))]


def describe_focus(repo: dict) -> str:
    return " / ".join(repo.get("focus_labels", [])) or "AI development"


def format_absolute_date(dt: datetime | None, tzinfo) -> str:
    return "-" if dt is None else dt.astimezone(tzinfo).strftime("%Y-%m-%d")


def build_repo_summary(repo: dict, tzinfo) -> str:
    release = repo.get("latest_release") or {}
    if release.get("published_at"):
        return (
            f"{repo['full_name']} 更偏向 {describe_focus(repo)} 生态，最近 release "
            f"{release.get('tag_name') or release.get('name')} 发布于 {format_absolute_date(release['published_at'], tzinfo)}。"
        )
    if repo.get("bucket") == "fresh":
        return (
            f"{repo['full_name']} 是近期新项目，创建于 {format_absolute_date(repo.get('created_at'), tzinfo)}，"
            f"已累积 {repo['stars']} Stars。"
        )
    return (
        f"{repo['full_name']} 仍在持续更新，最近一次 push 为 {format_absolute_date(repo.get('pushed_at'), tzinfo)}，"
        f"当前 {repo['stars']} Stars。"
    )


def build_github_research_notes(now_local: datetime, config: dict, repos: list[dict]) -> str:
    window_start = now_local - timedelta(hours=int(config["lookback_hours"]))
    timezone_value = now_local.tzinfo or timezone.utc
    if not repos:
        return "\n".join(
            [
                "# Research Notes",
                "## Time Window",
                f"- {window_start.strftime('%Y-%m-%d %H:%M %Z')} 到 {now_local.strftime('%Y-%m-%d %H:%M %Z')}",
                "",
                "## Query Strategy",
                "- GitHub Search API：新建高星仓库 + 近 24 小时活跃仓库",
                "- 覆盖 Codex、Claude Code、Gemini、Qwen、DeepSeek、Kimi 等模型开发生态",
                "",
                "## Key Findings",
                f"- {now_local.strftime('%Y-%m-%d')}：无重大新增，未发现同时满足主题相关性、近期活跃度和 Star 门槛的高信号项目。",
                "",
                "## Evidence Table",
                "| Date | Topic | Repository | Claim | Why It Matters | Source |",
                "| --- | --- | --- | --- | --- | --- |",
                f"| {now_local.strftime('%Y-%m-%d')} | No major update | - | 无重大新增 | 保持信号纪律，避免噪音 | https://api.github.com/search/repositories |",
                "",
                "## Source Quality Notes",
                "- 数据直接来自 GitHub 官方 REST API。",
            ]
        )

    findings = []
    evidence_rows = []
    for repo in repos:
        date_label = format_absolute_date(repo.get("pushed_at"), timezone_value)
        findings.append(
            f"- {date_label}：{repo['full_name']}，{repo['stars']} Stars，"
            f"{build_repo_summary(repo, timezone_value)} {repo['html_url']}"
        )
        evidence_rows.append(
            f"| {date_label} | GitHub Repo | {repo['full_name']} | {build_repo_summary(repo, timezone_value)} "
            f"| 直接反映 {describe_focus(repo)} 生态的新玩法或活跃项目 | {repo['html_url']} |"
        )

    return "\n".join(
        [
            "# Research Notes",
            "## Time Window",
            f"- {window_start.strftime('%Y-%m-%d %H:%M %Z')} 到 {now_local.strftime('%Y-%m-%d %H:%M %Z')}",
            "",
            "## Query Strategy",
            "- GitHub Search API：过去 14 天高 Star 新项目 + 过去 24 小时活跃仓库",
            "- Watchlist：OpenAI / Anthropic / Gemini / 国内模型开发工具仓库",
            "",
            "## Key Findings",
            *findings,
            "",
            "## Evidence Table",
            "| Date | Topic | Repository | Claim | Why It Matters | Source |",
            "| --- | --- | --- | --- | --- | --- |",
            *evidence_rows,
            "",
            "## Source Quality Notes",
            "- 仓库元数据与 release 信息均来自 GitHub 官方 REST API。",
            "- README 摘要只作为玩法速读，不替代原始仓库说明。",
        ]
    )


def build_try_line(repo: dict) -> str:
    excerpt = repo.get("readme_excerpt") or repo.get("description") or "README 暂未提炼出足够清晰的一句话。"
    return f"- {repo['full_name']}：{excerpt}"


def build_github_report(now_local: datetime, config: dict, repos: list[dict]) -> str:
    timezone_value = now_local.tzinfo or timezone.utc
    lines = [
        f"# {config['topic_name']}",
        "",
        f"日期: {now_local.strftime('%Y-%m-%d')}",
        f"生成时间: {now_local.strftime('%Y-%m-%d %H:%M %Z')}",
        "",
        "## Executive Summary",
    ]
    if not repos:
        lines.extend(
            [
                "- 无重大新增。过去 24 小时没有筛出足够高信号的多模型开发 GitHub 项目。",
                "- 链路仍正常，说明今天更像低信号日，而不是抓取失败。",
                "- 继续观察官方仓库 release、CLI、Agent 工作流和社区模板。",
                "",
                "## Ecosystem Radar",
                "- 无重大新增。",
                "",
                "## Official Watch",
                "- openai/codex：本轮未发现足够高信号的新 release 或新仓库事件。",
                "- anthropics/claude-code-action：本轮未发现足够高信号的新 release 或新仓库事件。",
                "",
                "## What To Try Today",
                "- 保持观察，不强行追噪音项目。",
                "",
                "## Source Log",
                "1. GitHub Search Repositories",
                "   https://api.github.com/search/repositories",
            ]
        )
        return "\n".join(lines)

    top_repo = repos[0]
    top_focuses = ", ".join(sorted({label for repo in repos for label in repo.get("focus_labels", [])})) or "多模型开发"
    lines.extend(
        [
            f"- 本轮筛出 {len(repos)} 个高信号项目，最值得优先看的仍是 {top_repo['full_name']}。",
            f"- 本次覆盖到的生态包括 {top_focuses}，避免日报只盯单一工具链。",
            "- 目标不是穷举，而是帮你每天先抓到最值得试、最值得跟的 3-6 个动作。",
            "",
            "## Ecosystem Radar",
        ]
    )

    for repo in repos[:4]:
        lines.extend(
            [
                f"### {repo['full_name']}",
                f"- 标签：{describe_focus(repo)}；{build_repo_summary(repo, timezone_value)}",
                f"- 玩法速读：{repo.get('readme_excerpt') or repo.get('description') or 'README 摘要不足，建议直接点进仓库看示例。'}",
                f"- 最近更新时间：{format_absolute_date(repo.get('pushed_at'), timezone_value)}；语言：{repo.get('language') or '-'}。",
                "",
            ]
        )

    lines.append("## Official Watch")
    watch_items = [repo for repo in repos if repo.get("watchlisted")]
    if not watch_items:
        lines.append("- 本轮未命中 watchlist 的高信号更新，建议继续跟踪官方仓库 release 与 README 变化。")
    for repo in watch_items[:3]:
        release = repo.get("latest_release") or {}
        if release.get("published_at"):
            lines.append(
                f"- {repo['full_name']}：最近 release {release.get('tag_name') or release.get('name')} "
                f"发布于 {format_absolute_date(release['published_at'], timezone_value)}。"
            )
        else:
            lines.append(
                f"- {repo['full_name']}：最近一次 push 为 {format_absolute_date(repo.get('pushed_at'), timezone_value)}，"
                "建议继续跟踪 README、示例和 workflow 变化。"
            )

    lines.extend(["", "## What To Try Today"])
    for repo in repos[:3]:
        lines.append(build_try_line(repo))

    lines.extend(["", "## Source Log"])
    source_index = 1
    seen_sources: set[str] = set()
    for repo in repos:
        if repo["html_url"] not in seen_sources:
            lines.append(f"{source_index}. {repo['full_name']}")
            lines.append(f"   {repo['html_url']}")
            seen_sources.add(repo["html_url"])
            source_index += 1
        release = repo.get("latest_release") or {}
        if release.get("html_url") and release["html_url"] not in seen_sources:
            lines.append(f"{source_index}. {repo['full_name']} release")
            lines.append(f"   {release['html_url']}")
            seen_sources.add(release["html_url"])
            source_index += 1
    return "\n".join(lines)


def collect_github_report(now_local: datetime, config: dict) -> dict:
    token = os.environ.get("GITHUB_TOKEN", "").strip() or None
    repos = select_top_repositories(
        search_repositories(now_local, config, token=token) + build_watch_repositories(config, token=token),
        now_local,
        config,
        token=token,
    )
    return {
        "mode": "live-github",
        "research_notes": build_github_research_notes(now_local, config, repos),
        "report_markdown": build_github_report(now_local, config, repos),
        "research_response": {"mode": "github-live", "repos": repos, "used_token": bool(token)},
        "final_response": {"mode": "github-live", "repos_found": len(repos)},
        "items_found": len(repos),
        "degraded": not bool(repos),
    }

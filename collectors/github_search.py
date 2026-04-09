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
README_PLAY_HEADING_HINTS = (
    "feature",
    "features",
    "use case",
    "use cases",
    "workflow",
    "workflows",
    "example",
    "examples",
    "quickstart",
    "getting started",
    "capability",
    "capabilities",
    "why",
)
REPO_MODE_HINTS = (
    ("终端 CLI", ("cli", "terminal", "command line", "shell")),
    ("GitHub Action 自动化", ("github action", "github actions", "ci", "pull request")),
    ("工作流模板", ("workflow", "template", "starter", "boilerplate")),
    ("多代理协作", ("multi-agent", "multi agent", "planner", "reviewer", "delegate")),
    ("MCP / 工具接入", ("mcp", "model context protocol", "tool calling", "server")),
    ("SDK / 二次集成", ("sdk", "library", "api", "package")),
    ("IDE / 编辑器集成", ("vscode", "ide", "editor", "extension")),
    ("评测 / Benchmark", ("benchmark", "eval", "evaluation", "leaderboard", "test suite")),
    ("Prompt / Rules", ("prompt", "rules", "memory", "system prompt")),
)
MODE_ORDER = {label: index for index, (label, _) in enumerate(REPO_MODE_HINTS)}
MODE_MIN_SCORE = {"Prompt / Rules": 3}


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


def clean_markdown_line(line: str) -> str:
    text = re.sub(r"`([^`]+)`", r"\1", line)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"^>\s*", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -")


def dedupe_text_items(items: list[str], max_items: int | None = None) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        token = normalize_github_text(item)
        if not token or token in seen:
            continue
        seen.add(token)
        deduped.append(item)
        if max_items is not None and len(deduped) >= max_items:
            break
    return deduped


def extract_readme_brief(markdown_text: str, excerpt_max_chars: int = 220, max_points: int = 3) -> dict:
    excerpt_candidates: list[str] = []
    point_candidates: list[str] = []
    in_code_block = False
    current_heading = ""

    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block or not line:
            continue
        if "shields.io" in line or line.startswith("[![") or line.startswith("!["):
            continue
        if line.startswith("#"):
            current_heading = normalize_github_text(clean_markdown_line(line.lstrip("#").strip()))
            continue

        cleaned = clean_markdown_line(line)
        if len(cleaned) < 18:
            continue

        is_list_item = bool(re.match(r"^([-*]|\d+\.)\s+", line))
        preferred_heading = any(hint in current_heading for hint in README_PLAY_HEADING_HINTS)

        if len(cleaned) >= 36:
            excerpt_candidates.append(cleaned)
        if is_list_item or preferred_heading or len(cleaned) >= 54:
            point_candidates.append(cleaned)

    excerpt = compact_display_text(" ".join(dedupe_text_items(excerpt_candidates, max_items=2)), max_chars=excerpt_max_chars)
    point_candidates = [
        compact_display_text(candidate, max_chars=95)
        for candidate in dedupe_text_items(point_candidates)
        if normalize_github_text(candidate) != normalize_github_text(excerpt)
    ]
    return {"excerpt": excerpt, "key_points": point_candidates[:max_points]}


def extract_readme_excerpt(markdown_text: str, max_chars: int = 220) -> str:
    return extract_readme_brief(markdown_text, excerpt_max_chars=max_chars)["excerpt"]


def compact_display_text(value: str, max_chars: int = 120) -> str:
    text = re.sub(r"https?://\S+", "", value or "")
    text = re.sub(r"\s+", " ", text).strip(" -")
    if not text:
        return ""
    for separator in ("。", ". ", "!", "?"):
        if separator in text:
            first_sentence = text.split(separator, 1)[0].strip()
            if len(first_sentence) >= 18:
                text = first_sentence
                break
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "..."
    return text


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
        "readme_key_points": [],
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


def fetch_readme_details(full_name: str, token: str | None = None, max_chars: int = 220, max_points: int = 3) -> dict:
    payload = request_github_json(
        f"{GITHUB_API_ROOT}/repos/{parse.quote(full_name, safe='')}/readme",
        token=token,
        allow_404=True,
    )
    if not payload:
        return {"excerpt": "", "key_points": []}
    content = payload.get("content") or ""
    if payload.get("encoding") != "base64" or not content:
        return {"excerpt": "", "key_points": []}
    decoded = base64.b64decode(content).decode("utf-8", errors="ignore")
    return extract_readme_brief(decoded, excerpt_max_chars=max_chars, max_points=max_points)


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
            readme_details = fetch_readme_details(
                repo["full_name"],
                token=token,
                max_chars=int(config.get("github_readme_max_chars", 220)),
            )
            repo["readme_excerpt"] = readme_details.get("excerpt", "")
            repo["readme_key_points"] = readme_details.get("key_points", [])
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


def repo_text_haystack(repo: dict) -> str:
    return normalize_github_text(
        " ".join(
            [
                repo.get("full_name", ""),
                repo.get("description", ""),
                " ".join(repo.get("topics", [])),
                repo.get("matched_query", ""),
                repo.get("readme_excerpt", ""),
                " ".join(repo.get("readme_key_points", [])),
            ]
        )
    )


def infer_repo_modes(repo: dict) -> list[str]:
    primary_haystack = normalize_github_text(
        " ".join(
            [
                repo.get("full_name", ""),
                repo.get("description", ""),
                " ".join(repo.get("topics", [])),
                repo.get("matched_query", ""),
            ]
        )
    )
    secondary_haystack = normalize_github_text(
        " ".join([repo.get("readme_excerpt", ""), " ".join(repo.get("readme_key_points", []))])
    )
    scored_modes: list[tuple[int, str]] = []
    for label, keywords in REPO_MODE_HINTS:
        score = 0
        for keyword in keywords:
            token = normalize_github_text(keyword)
            if token and token in primary_haystack:
                score += 2
            elif token and token in secondary_haystack:
                score += 1
        if score > 0:
            scored_modes.append((score, label))
    if not scored_modes:
        return ["开发工具"]
    ranked_pairs = sorted(scored_modes, key=lambda item: (-item[0], MODE_ORDER.get(item[1], 999)))
    ranked = [label for score, label in ranked_pairs]
    strong = [label for score, label in ranked_pairs if score >= MODE_MIN_SCORE.get(label, 2)]
    return strong[:3] or ranked[:3]


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


def build_repo_reason(repo: dict, tzinfo) -> str:
    release = repo.get("latest_release") or {}
    if release.get("published_at"):
        return "这是官方发布信号，优先级高于社区二手总结。"
    if repo.get("watchlisted"):
        return "这是重点观察仓库，适合持续跟踪真实功能和工作流变化。"
    if repo.get("bucket") == "fresh":
        return "短时间涨星快，说明这套玩法正在被开发者快速试用。"
    return "仓库仍在持续更新，说明不是一次性热度，而是真实迭代中的项目。"


def build_repo_signal(repo: dict, tzinfo) -> str:
    return (
        f"{describe_focus(repo)} | {repo['stars']} Stars | "
        f"{format_absolute_date(repo.get('pushed_at'), tzinfo)} 更新 | {repo.get('language') or '-'}"
    )


def build_repo_theme(repo: dict) -> str:
    parts = []
    focus = describe_focus(repo)
    if focus != "AI development":
        parts.append(focus)
    parts.extend(infer_repo_modes(repo)[:2])
    return " / ".join(dedupe_text_items(parts, max_items=3)) or "多模型开发工具"


def build_repo_overview(repo: dict, tzinfo) -> str:
    base = compact_display_text(
        repo.get("description") or repo.get("readme_excerpt") or build_repo_summary(repo, tzinfo),
        max_chars=125,
    )
    if base:
        return base
    return compact_display_text(build_repo_summary(repo, tzinfo), max_chars=125)


def build_repo_play_points(repo: dict) -> list[str]:
    mode_actions = {
        "终端 CLI": "可以直接借它的终端入口做本地编码助手，把生成、修复、重构这些动作收进统一命令。",
        "GitHub Action 自动化": "可以参考它把 AI 能力接进 GitHub Actions，用在 PR 审查、修复、日报或提测链路。",
        "工作流模板": "可以直接照着它的模板拆你的流程，把提示词、步骤和产物约束成固定协作规范。",
        "多代理协作": "可以借它的多角色分工方式，把规划、执行、审查拆成独立角色再串起来。",
        "MCP / 工具接入": "可以把它当工具接入范式，给模型挂数据库、内部 API 或业务系统能力。",
        "SDK / 二次集成": "可以把它当集成层参考，思考怎么把模型能力包成你自己的产品接口或脚本。",
        "IDE / 编辑器集成": "可以参考它的编辑器接入方式，把模型能力塞进开发者已有的写码环境。",
        "评测 / Benchmark": "可以拿它做基线，判断你自己的玩法到底提升了哪些编码或交付指标。",
        "Prompt / Rules": "可以参考它的 prompt、rules 或 memory 结构，把经验固化成可复用资产。",
        "开发工具": "可以先看它把什么能力产品化，再决定你要复用入口、流程还是规则资产。",
    }
    points: list[str] = []
    for mode in infer_repo_modes(repo)[:2]:
        points.append(mode_actions.get(mode, mode_actions["开发工具"]))
    for hint in repo.get("readme_key_points", []) or []:
        points.append(f"README 线索：{hint}")
    if not points:
        points.append(
            f"先从 README 的核心说明入手：{compact_display_text(repo.get('readme_excerpt') or repo.get('description'), max_chars=95) or '建议直接打开仓库看示例。'}"
        )
    return dedupe_text_items(points, max_items=3)


def build_repo_fit(repo: dict) -> str:
    modes = set(infer_repo_modes(repo))
    fits: list[str] = []
    if {"终端 CLI", "IDE / 编辑器集成"} & modes:
        fits.append("个人开发助手或本地编码工具")
    if {"GitHub Action 自动化", "工作流模板", "多代理协作"} & modes:
        fits.append("团队协作、PR 流程或自动化交付")
    if {"MCP / 工具接入", "SDK / 二次集成"} & modes:
        fits.append("把模型接进你现有产品或内部系统")
    if "评测 / Benchmark" in modes:
        fits.append("做评测、选型或效果对比")
    return "；".join(fits[:3]) or "想把模型能力做成可复用开发入口的人"


def summarize_repo_modes(repos: list[dict]) -> list[str]:
    counts: dict[str, int] = {}
    for repo in repos:
        for mode in infer_repo_modes(repo):
            counts[mode] = counts.get(mode, 0) + 1
    return [
        label
        for label, _ in sorted(counts.items(), key=lambda item: (-item[1], MODE_ORDER.get(item[0], 999)))
        if label != "开发工具"
    ][:3]


def build_report_overview(repos: list[dict]) -> tuple[str, str]:
    top_modes = summarize_repo_modes(repos)
    if top_modes:
        theme = f"高 Star 玩法主要集中在 {'、'.join(top_modes)}。"
    else:
        theme = "高 Star 项目仍集中在多模型开发工具本身。"

    official_count = sum(1 for repo in repos if repo.get("watchlisted"))
    fresh_count = sum(1 for repo in repos if repo.get("bucket") == "fresh")
    if official_count and fresh_count:
        overview = "今天同时出现了官方链路更新和社区高 Star 新玩法，说明赛道重点已经从单点模型切到可复用工作流。"
    elif official_count:
        overview = "今天更偏向官方链路演进，重点看产品入口、示例和自动化方式怎么继续标准化。"
    elif fresh_count:
        overview = "今天更偏向社区新玩法冒头，重点看哪些交互形式和工作流最容易被开发者复用。"
    else:
        overview = "今天的重点不在新模型名词，而在已有工具如何继续沉淀成稳定的开发入口。"
    return theme, overview


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
    modes = infer_repo_modes(repo)
    if "终端 CLI" in modes:
        return f"- 以 {repo['full_name']} 为参考：先抄它的终端入口和命令结构，再替换成你的业务任务。"
    if "GitHub Action 自动化" in modes:
        return f"- 以 {repo['full_name']} 为参考：优先看它怎么接 GitHub Actions，再改成你的 PR 或交付流程。"
    if "工作流模板" in modes or "多代理协作" in modes:
        return f"- 以 {repo['full_name']} 为参考：直接复用它的分工和步骤模板，改成你的团队协作玩法。"
    return f"- 以 {repo['full_name']} 为参考：先看它把哪种能力产品化，再决定你要抄入口、流程还是规则资产。"


def build_github_report(now_local: datetime, config: dict, repos: list[dict]) -> str:
    timezone_value = now_local.tzinfo or timezone.utc
    lines = [
        f"# {config['topic_name']}",
        "",
        f"日期: {now_local.strftime('%Y-%m-%d')}",
        f"生成时间: {now_local.strftime('%Y-%m-%d %H:%M %Z')}",
        "",
        "只保留高信号仓库。先看结论，再决定点哪个链接。",
        "",
        "## 结论",
    ]
    if not repos:
        lines.extend(
            [
                "- 无重大新增。过去 24 小时没有筛出足够高信号的多模型开发 GitHub 项目。",
                "- 链路仍正常，说明今天更像低信号日，而不是抓取失败。",
                "- 继续观察官方仓库 release、CLI、Agent 工作流和社区模板。",
                "",
                "## 项目",
                "- 无重大新增。",
                "",
                "## 官方",
                "- openai/codex：本轮未发现足够高信号的新 release 或新仓库事件。",
                "- anthropics/claude-code-action：本轮未发现足够高信号的新 release 或新仓库事件。",
                "",
                "## 动作",
                "- 保持观察，不强行追噪音项目。",
                "",
                "## 来源",
                "1. GitHub Search Repositories",
                "   https://api.github.com/search/repositories",
            ]
        )
        return "\n".join(lines)

    top_repo = repos[0]
    top_focuses = ", ".join(sorted({label for repo in repos for label in repo.get("focus_labels", [])})) or "多模型开发"
    theme_line, overview_line = build_report_overview(repos)
    lines.extend(
        [
            f"- 今日主题：{theme_line}",
            f"- 可玩方向：先看 {top_repo['full_name']} 代表的主流做法，再横向对比 {top_focuses} 几个生态各自怎么落地。",
            f"- 整体概况：{overview_line}",
            "- 目标不是穷举，而是让你快速看出“这个仓库到底在玩什么、哪些点值得抄、适不适合做成你自己的玩法”。",
            "",
            "## 项目",
        ]
    )

    for repo in repos[:4]:
        play_points = build_repo_play_points(repo)
        lines.extend(
            [
                f"### {repo['full_name']}",
                f"- 主题：{build_repo_theme(repo)}",
                f"- 它在做什么：{build_repo_overview(repo, timezone_value)}",
                f"- 可玩点 1：{play_points[0] if len(play_points) >= 1 else '建议先看 README 和示例。'}",
                f"- 可玩点 2：{play_points[1] if len(play_points) >= 2 else build_repo_reason(repo, timezone_value)}",
                f"- 可玩点 3：{play_points[2] if len(play_points) >= 3 else compact_display_text(build_repo_summary(repo, timezone_value), max_chars=110)}",
                f"- 适合参考：{build_repo_fit(repo)}",
                f"- 关键信号：{build_repo_signal(repo, timezone_value)}",
                "",
            ]
        )

    lines.append("## 官方")
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

    lines.extend(["", "## 动作"])
    for repo in repos[:3]:
        lines.append(build_try_line(repo))

    lines.extend(["", "## 来源"])
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

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
JSON_PATH = OUTPUT_DIR / "hotspots.json"
REPORT_PATH = OUTPUT_DIR / "daily_report.md"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/json,text/plain,*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

ENTERTAINMENT_WORDS = {
    "新剧", "剧集", "电视剧", "短剧", "剧情", "电影", "综艺", "演员", "明星", "导演", "票房", "上映", "开播",
    "大结局", "预告", "官宣", "塌房", "红毯", "演唱会", "音乐", "舞台", "内娱", "爱奇艺", "腾讯视频",
    "优酷", "芒果", "CP", "吻戏", "名场面", "角色", "男主", "女主", "番外", "热播", "杀青",
}
RISK_WORDS = {
    "去世", "自杀", "违法", "犯罪", "诈骗", "造谣", "辟谣", "封杀", "涉毒", "出轨", "辱华", "战争",
    "暴力", "未成年", "网暴", "抵制", "维权", "事故", "死亡", "被捕", "逮捕",
}


@dataclass
class HotItem:
    platform: str
    rank: int
    keyword: str
    hot_value: int
    url: str
    collected_at: str
    source_status: str = "ok"
    description: str = ""


@dataclass
class Cluster:
    keyword: str
    aliases: list[str]
    platforms: list[str]
    best_rank: int
    total_hot_value: int
    score: float
    entertainment_score: float
    risk_level: str
    suggestion_level: str
    topic_angles: list[str]
    title_templates: list[str]
    tags: list[str]
    source_items: list[dict]
    ai_powered: bool = False
    ai_fit_score: int = 0
    ai_screen_reason: str = ""
    ai_reason: str = ""
    ai_brief: str = ""
    ai_web_summary: str = ""
    ai_enriched: bool = False
    ai_web_sources: list[dict] | None = None


def now_text() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_local_env() -> None:
    for name in (".env", ".env.local"):
        path = ROOT / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def fetch_text(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def tikhub_request(url: str, timeout: int = 30) -> dict:
    token = os.environ.get("TIKHUB_API_KEY", "").strip()
    if not token:
        return {}
    headers = {**HEADERS, "Accept": "application/json", "Authorization": f"Bearer {token}"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def clean_text(value: object) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_ai_summary(value: str) -> str:
    text = clean_text(value)
    text = re.sub(r"\[[^\]]{1,80}\]\(https?://[^)]+\)", "", text)
    text = re.sub(r"\(https?://[^)]+\)", "", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" 。，；;、")


def safe_int(value: object, default: int = 0) -> int:
    text = re.sub(r"[^\d]", "", str(value or ""))
    return int(text) if text else default


def iter_dicts(value: object) -> Iterable[dict]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_dicts(child)


def first_text(row: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return clean_text(value)
    return ""


def parse_tikhub_hot_items(data: dict, platform: str, source_status: str) -> list[HotItem]:
    title_keys = ("title", "keyword", "word", "name", "sentence", "note_title", "desc", "word_scheme")
    url_keys = ("url", "link", "share_url", "note_url", "web_url", "mobileUrl")
    hot_keys = ("hot", "hot_value", "heat", "score", "view_count", "likes", "like_count", "num", "raw_hot")
    desc_keys = ("description", "detail", "summary", "label", "sub_title", "display_title", "event_intro", "intro")
    items: list[HotItem] = []
    seen: set[str] = set()
    for row in iter_dicts(data.get("data", data)):
        keyword = first_text(row, title_keys)
        if (
            not keyword
            or keyword in seen
            or len(keyword) > 80
            or keyword in {"小红书", "发现", "登录", "注册", "搜索发现", "热门搜索", "大家都在搜"}
            or any(token in keyword for token in ("ICP备", "营业执照", "公网安备", "ListItem", '"url"'))
        ):
            continue
        seen.add(keyword)
        link = first_text(row, url_keys)
        if not link:
            if platform == "小红书":
                link = "https://www.xiaohongshu.com/search_result?keyword=" + urllib.parse.quote(keyword)
            elif platform == "抖音":
                link = "https://www.douyin.com/search/" + urllib.parse.quote(keyword)
            elif platform.startswith("微博"):
                link = "https://s.weibo.com/weibo?q=" + urllib.parse.quote(keyword)
            else:
                link = "https://www.baidu.com/s?wd=" + urllib.parse.quote(keyword)
        hot = 0
        for key in hot_keys:
            if key in row:
                hot = safe_int(row.get(key))
                if hot:
                    break
        desc = first_text(row, desc_keys)
        if desc == keyword:
            desc = ""
        items.append(HotItem(platform, len(items) + 1, keyword, hot, link, now_text(), source_status, desc[:180]))
        if len(items) >= 50:
            break
    return items


def collect_weibo_tikhub() -> list[HotItem]:
    data = tikhub_request("https://api.tikhub.io/api/v1/weibo/app/fetch_hot_search?category=fun&page=1&count=50")
    return parse_tikhub_hot_items(data, "微博文娱", "tikhub-weibo-fun") if data else []


def collect_weibo_public() -> list[HotItem]:
    data = json.loads(fetch_text("https://weibo.com/ajax/side/hotSearch"))
    rows = data.get("data", {}).get("realtime", [])
    items = []
    for idx, row in enumerate(rows, 1):
        keyword = clean_text(row.get("word") or row.get("note"))
        if keyword:
            items.append(HotItem("微博", idx, keyword, safe_int(row.get("num")), "https://s.weibo.com/weibo?q=" + urllib.parse.quote(keyword), now_text()))
    return items


def collect_baidu() -> list[HotItem]:
    text = fetch_text("https://top.baidu.com/board?tab=realtime")
    rows = re.findall(r'"word":"(.*?)".{0,800}?"hotScore":"?(\d+)"?', text)
    items, seen = [], set()
    for idx, (word, hot_score) in enumerate(rows, 1):
        keyword = clean_text(word.encode("utf-8").decode("unicode_escape", errors="ignore") if "\\u" in word else word)
        if keyword and keyword not in seen:
            seen.add(keyword)
            items.append(HotItem("百度", idx, keyword, safe_int(hot_score), "https://www.baidu.com/s?wd=" + urllib.parse.quote(keyword), now_text()))
    return items


def collect_bilibili() -> list[HotItem]:
    data = json.loads(fetch_text("https://api.bilibili.com/x/web-interface/popular?ps=30&pn=1"))
    items = []
    for idx, row in enumerate(data.get("data", {}).get("list", []), 1):
        keyword = clean_text(row.get("title"))
        if keyword:
            items.append(HotItem("B站", idx, keyword, safe_int(row.get("stat", {}).get("view")), "https://www.bilibili.com/video/" + str(row.get("bvid", "")), now_text(), description=clean_text(row.get("desc"))[:180]))
    return items


def collect_douyin_tikhub() -> list[HotItem]:
    url = os.environ.get("TIKHUB_DOUYIN_HOT_URL", "https://api.tikhub.io/api/v1/douyin/app/v3/fetch_hot_search_list?board_type=0&board_sub_type=")
    data = tikhub_request(url)
    return parse_tikhub_hot_items(data, "抖音", "tikhub-douyin") if data else []


def collect_douyin_public() -> list[HotItem]:
    url = "https://www.douyin.com/aweme/v1/web/hot/search/list/?device_platform=webapp&aid=6383&channel=channel_pc_web"
    data = json.loads(fetch_text(url))
    rows = data.get("data", {}).get("word_list", []) or data.get("word_list", [])
    items = []
    for idx, row in enumerate(rows, 1):
        keyword = clean_text(row.get("word") or row.get("sentence"))
        if keyword:
            items.append(HotItem("抖音", idx, keyword, safe_int(row.get("hot_value")), "https://www.douyin.com/search/" + urllib.parse.quote(keyword), now_text()))
    return items


def collect_xhs_tikhub() -> list[HotItem]:
    url = os.environ.get("TIKHUB_XHS_HOT_URL", "https://api.tikhub.io/api/v1/xiaohongshu/web_v2/fetch_hot_list")
    data = tikhub_request(url)
    return parse_tikhub_hot_items(data, "小红书", "tikhub-xhs") if data else []


def with_fallback(name: str, collectors: tuple[Callable[[], list[HotItem]], ...]) -> list[HotItem]:
    errors = []
    for collector in collectors:
        try:
            rows = collector()
            if rows:
                return rows
            errors.append(f"{collector.__name__}: no rows")
        except Exception as exc:
            errors.append(f"{collector.__name__}: {type(exc).__name__}: {exc}")
    raise RuntimeError("; ".join(errors) or f"{name}: no rows")


COLLECTORS: list[tuple[str, Callable[[], list[HotItem]]]] = [
    ("微博文娱", lambda: with_fallback("微博文娱", (collect_weibo_tikhub, collect_weibo_public))),
    ("抖音", lambda: with_fallback("抖音", (collect_douyin_tikhub, collect_douyin_public))),
    ("小红书", collect_xhs_tikhub),
    ("百度", collect_baidu),
    ("B站", collect_bilibili),
]


def read_manual_csv() -> list[HotItem]:
    path = DATA_DIR / "manual_hotspots.csv"
    if not path.exists():
        return []
    items = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        for idx, row in enumerate(csv.DictReader(fh), 1):
            keyword = clean_text(row.get("keyword"))
            if keyword:
                items.append(HotItem(row.get("platform") or "手动导入", safe_int(row.get("rank"), idx), keyword, safe_int(row.get("hot_value")), row.get("url", ""), now_text(), description=clean_text(row.get("description") or row.get("desc"))[:180]))
    return items


def fallback_items() -> list[HotItem]:
    samples = [("微博文娱", "某剧大结局反转", 1, 8800000), ("抖音", "某演员新剧名场面", 4, 5600000), ("百度", "某电影票房破纪录", 3, 7200000), ("B站", "年度高分悬疑剧盘点", 9, 950000)]
    return [HotItem(p, r, k, h, "", now_text(), "sample") for p, k, r, h in samples]


def collect_all(offline: bool = False) -> tuple[list[HotItem], list[str]]:
    DATA_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)
    if offline:
        return fallback_items() + read_manual_csv(), ["offline sample mode"]
    items, errors = [], []
    for name, collector in COLLECTORS:
        try:
            rows = collector()
            if not rows:
                errors.append(f"{name}: no public rows parsed")
            items.extend(rows)
            time.sleep(0.5)
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
    items.extend(read_manual_csv())
    if not items:
        return fallback_items(), errors + ["all collectors failed; using sample data"]
    return items, errors


def normalize_key(keyword: str) -> str:
    text = keyword.lower()
    text = re.sub(r"#|热搜|上热搜|官宣|冲上|回应|发文|最新|曝光", "", text)
    for old, new in {"赴泰": "泰国", "在泰": "泰国", "泰私拍": "泰国拍", "私拍": "拍", "逮捕": "被捕"}.items():
        text = text.replace(old, new)
    text = re.sub(r"\d+名?", "", text)
    text = re.sub(r"[一二三四五六七八九十]+名?", "", text)
    text = re.sub(r"(中国人|多人|人员|在|赴|私|被|了)", "", text)
    text = re.sub(r"[\s，。！？!?:：、\-_/|【】\[\]()（）]+", "", text)
    return text[:18]


def entertainment_score(keyword: str) -> float:
    score = sum(22 for word in ENTERTAINMENT_WORDS if word.lower() in keyword.lower())
    if re.search(r"(新剧|开播|上映|定档|路透|杀青|红毯|演唱会|新歌|预告|票房|剧照|第[一二三四五六七八九十0-9]+季)", keyword):
        score += 22
    if "《" in keyword and "》" in keyword:
        score += 18
    return min(score, 100)


def risk_level(keyword: str) -> str:
    hits = [word for word in RISK_WORDS if word in keyword]
    return "高" if len(hits) >= 2 else "中" if hits else "低"


def platform_score_weight(platform: str) -> float:
    return {"百度": 0.55, "B站": 0.7}.get(platform, 1.0)


def topic_angles(keyword: str, ent: float) -> list[str]:
    if ent < 25:
        return []
    return [
        f"拆解“{keyword}”为什么今天会被讨论，突出冲突、反转或名场面",
        f"把热点转成 15-30 秒短视频：开头 3 秒给结果，中段补剧情/人物关系",
        "做跨平台对照：微博看讨论点，抖音看情绪点，小红书看种草表达",
    ]


def title_templates(keyword: str) -> list[str]:
    return [f"难怪“{keyword}”今天全网都在刷", f"3 秒看懂“{keyword}”真正出圈的点", f"如果你只看一个片段，先看“{keyword}”这个反转"]


def tags_for(keyword: str) -> list[str]:
    tags = ["#影视娱乐", "#热点", "#短视频选题"]
    if any(word in keyword for word in ["剧", "电影", "开播", "大结局"]):
        tags += ["#剧集推荐", "#名场面"]
    if any(word in keyword for word in ["演员", "明星", "红毯"]):
        tags += ["#明星动态", "#娱乐资讯"]
    return tags[:6]


def cluster_items(items: Iterable[HotItem]) -> list[Cluster]:
    buckets: dict[str, list[HotItem]] = {}
    for item in items:
        key = normalize_key(item.keyword)
        if key:
            buckets.setdefault(key, []).append(item)
    clusters = []
    for rows in buckets.values():
        rows = sorted(rows, key=lambda row: row.rank or 999)
        keyword = rows[0].keyword
        aliases = sorted({row.keyword for row in rows})
        platforms = sorted({row.platform for row in rows})
        best_rank = min(row.rank for row in rows if row.rank)
        total_hot = sum(row.hot_value for row in rows)
        ent = max(entertainment_score(alias) for alias in aliases)
        rank_score = max(0, 35 - best_rank) * max(platform_score_weight(row.platform) for row in rows)
        hot_score = min(total_hot / 250000, 30) * max(platform_score_weight(row.platform) for row in rows)
        score = round(rank_score + hot_score + min(len(platforms) * 12, 36) + ent * 0.35 + 10, 1)
        risk = risk_level(" ".join(aliases))
        if risk == "高":
            score -= 20
        elif risk == "中":
            score -= 8
        if ent < 25:
            score = min(score, 55)
        score = max(0, min(score, 100))
        level = "强烈跟进" if score >= 72 and ent >= 25 and risk != "高" else "观察" if score >= 45 and ent >= 25 else "暂不跟进"
        clusters.append(Cluster(keyword, aliases, platforms, best_rank, total_hot, score, ent, risk, level, topic_angles(keyword, ent), title_templates(keyword), tags_for(keyword), [asdict(row) for row in rows]))
    return sorted(clusters, key=lambda c: (c.suggestion_level == "强烈跟进", c.entertainment_score, c.score), reverse=True)


def validate_openai_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    if not key.startswith("sk-"):
        raise RuntimeError("OPENAI_API_KEY should start with sk-")
    key.encode("ascii")
    return key


def extract_response_text(data: dict) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    chunks = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if isinstance(content.get("text"), str):
                chunks.append(content["text"])
    return "".join(chunks)


def call_openai_json(body: dict, timeout: int = 90) -> dict:
    key = validate_openai_key()
    req = urllib.request.Request("https://api.openai.com/v1/responses", data=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    text = extract_response_text(data)
    if not text.strip():
        raise RuntimeError(f"OpenAI returned no text output. status={data.get('status')}, details={data.get('incomplete_details')}")
    return json.loads(text), data


def ai_prompt_for_cluster(cluster: dict) -> str:
    sources = "；".join(f"{item.get('platform')}#{item.get('rank')} {item.get('keyword')}" for item in cluster.get("source_items", [])[:6])
    return f"热点主标题：{cluster.get('keyword')}\n来源：{sources}\n规则分：{cluster.get('score')}\n请判断它是否适合影视娱乐/剧集/明星/短视频账号，并给出选题角度、标题模板和标签。避免侵权搬运、站队争议或消费负面事件。"


def enhance_cluster_dict(cluster: dict, model: str) -> None:
    schema = {
        "type": "object",
        "properties": {
            "suggestion_level": {"type": "string", "enum": ["强烈跟进", "观察", "暂不跟进"]},
            "risk_level": {"type": "string", "enum": ["低", "中", "高"]},
            "ai_brief": {"type": "string"},
            "ai_reason": {"type": "string"},
            "topic_angles": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 3},
            "title_templates": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 3},
            "tags": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 6},
        },
        "required": ["suggestion_level", "risk_level", "ai_brief", "ai_reason", "topic_angles", "title_templates", "tags"],
        "additionalProperties": False,
    }
    body = {
        "model": model,
        "instructions": "你是谨慎的中文社媒内容运营策略助手。只输出符合 schema 的 JSON。",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": ai_prompt_for_cluster(cluster)}]}],
        "text": {"format": {"type": "json_schema", "name": "hotspot_enrichment", "schema": schema, "strict": True}, "verbosity": "low"},
        "reasoning": {"effort": "minimal"},
        "max_output_tokens": 1200,
    }
    result, _ = call_openai_json(body)
    cluster["ai_powered"] = True
    cluster["ai_enriched"] = True
    cluster["ai_brief"] = clean_text(result.get("ai_brief"))[:180]
    cluster["ai_reason"] = clean_text(result.get("ai_reason"))[:180]
    cluster["suggestion_level"] = result.get("suggestion_level", cluster.get("suggestion_level"))
    cluster["risk_level"] = result.get("risk_level", cluster.get("risk_level"))
    for field in ("topic_angles", "title_templates", "tags"):
        values = result.get(field)
        if isinstance(values, list) and values:
            cluster[field] = [clean_text(value) for value in values if clean_text(value)][:6]


def extract_web_sources(data: dict) -> list[dict]:
    sources = []
    for output in data.get("output", []) or []:
        for content in output.get("content", []) or []:
            for ann in content.get("annotations", []) or []:
                if ann.get("type") == "url_citation" and ann.get("url"):
                    sources.append({"title": ann.get("title", ""), "url": ann.get("url", "")})
    deduped, seen = [], set()
    for source in sources:
        url = source.get("url", "")
        if url and url not in seen:
            seen.add(url)
            deduped.append(source)
    return deduped[:4]


def summarize_cluster_dict(cluster: dict, model: str) -> None:
    schema = {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"], "additionalProperties": False}
    query = f"{cluster.get('keyword')} {' '.join(cluster.get('aliases', [])[:3])}"
    prompt = (
        "请先联网搜索这个中文社媒热点，再基于搜索结果总结。总结要说明：这个热点具体在说什么、核心人物/作品/事件是谁、网友主要讨论点是什么。"
        "如果搜索结果不足，请明确保守表达，不要编造。输出 60-120 字简体中文，适合放在运营看板里。正文不要包含 Markdown 链接、URL、括号引用。\n"
        f"搜索关键词：{query}\n来源平台：{', '.join(cluster.get('platforms', []))}"
    )
    body = {
        "model": model,
        "tools": [{"type": "web_search"}],
        "tool_choice": "auto",
        "instructions": "你是中文社媒热点摘要助手，会先联网搜索，再基于可靠搜索结果做简洁总结。只输出符合 schema 的 JSON。",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
        "text": {"format": {"type": "json_schema", "name": "hotspot_web_summary", "schema": schema, "strict": True}, "verbosity": "low"},
        "reasoning": {"effort": "low"},
        "max_output_tokens": 900,
    }
    result, raw = call_openai_json(body)
    cluster["ai_powered"] = True
    cluster["ai_web_summary"] = clean_ai_summary(result.get("summary", ""))[:240]
    cluster["ai_web_sources"] = extract_web_sources(raw)


def load_payload() -> dict:
    if not JSON_PATH.exists():
        items, errors = collect_all()
        clusters = cluster_items(items)
        write_outputs(items, clusters, errors)
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


def update_one_cluster(index: int, updater: Callable[[dict], None]) -> dict:
    payload = load_payload()
    clusters = payload.get("clusters", [])
    if index < 0 or index >= len(clusters):
        raise RuntimeError(f"cluster index out of range: {index}")
    updater(clusters[index])
    payload["generated_at"] = now_text()
    payload["ai_count"] = sum(1 for cluster in clusters if cluster.get("ai_powered"))
    JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return clusters[index]


def write_outputs(items: list[HotItem], clusters: list[Cluster], errors: list[str], ai_model: str | None = None) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    payload = {
        "generated_at": now_text(),
        "raw_count": len(items),
        "cluster_count": len(clusters),
        "errors": errors,
        "ai_model": ai_model or "",
        "ai_count": sum(1 for cluster in clusters if cluster.ai_powered),
        "clusters": [asdict(cluster) for cluster in clusters],
    }
    JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 中文社媒热点简报", "", f"生成时间：{payload['generated_at']}", f"采集原始热点：{len(items)} 条，合并后热点：{len(clusters)} 个", "", "## 今日优先跟进"]
    for idx, cluster in enumerate(clusters[:20], 1):
        lines += ["", f"### {idx}. {cluster.keyword}", f"- 推荐等级：{cluster.suggestion_level}；综合分：{cluster.score}；风险：{cluster.risk_level}", f"- 来源平台：{', '.join(cluster.platforms)}；最佳排名：#{cluster.best_rank}"]
    if errors:
        lines += ["", "## 采集提示"] + [f"- {err}" for err in errors]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    load_local_env()
    parser = argparse.ArgumentParser(description="Chinese social hotspot radar")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--ai", action="store_true")
    parser.add_argument("--ai-limit", type=int, default=10)
    parser.add_argument("--ai-model", default=os.environ.get("OPENAI_MODEL", "gpt-5-mini"))
    parser.add_argument("--ai-web-model", default=os.environ.get("OPENAI_WEB_MODEL", "gpt-5.5"))
    parser.add_argument("--enhance-index", type=int)
    parser.add_argument("--summarize-index", type=int)
    args = parser.parse_args()
    if args.enhance_index is not None:
        updated = update_one_cluster(args.enhance_index, lambda cluster: enhance_cluster_dict(cluster, args.ai_model))
        print(json.dumps({"ok": True, "cluster": updated}, ensure_ascii=False))
        return 0
    if args.summarize_index is not None:
        updated = update_one_cluster(args.summarize_index, lambda cluster: summarize_cluster_dict(cluster, args.ai_web_model))
        print(json.dumps({"ok": True, "cluster": updated}, ensure_ascii=False))
        return 0
    items, errors = collect_all(offline=args.offline)
    clusters = cluster_items(items)
    if args.ai:
        for idx, cluster in enumerate(clusters[: args.ai_limit]):
            cluster_dict = asdict(cluster)
            try:
                enhance_cluster_dict(cluster_dict, args.ai_model)
                for field, value in cluster_dict.items():
                    if hasattr(cluster, field):
                        setattr(cluster, field, value)
            except Exception as exc:
                errors.append(f"AI {cluster.keyword[:24]}: {type(exc).__name__}: {exc}")
    write_outputs(items, clusters, errors, ai_model=args.ai_model if args.ai else None)
    print(f"raw items: {len(items)}")
    print(f"clusters: {len(clusters)}")
    print(f"json: {JSON_PATH}")
    print(f"report: {REPORT_PATH}")
    if errors:
        print("collector notes:")
        for err in errors:
            print(f"- {err}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

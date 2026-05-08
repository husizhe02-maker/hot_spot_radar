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
import urllib.error
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
    "大结局", "预告", "官宣", "红毯", "演唱会", "音乐", "舞台", "韩剧", "美剧", "港剧", "爱奇艺",
    "腾讯视频", "优酷", "芒果", "Netflix", "CP", "吻戏", "名场面", "角色", "男主", "女主", "番外", "热播", "杀青",
}
RISK_WORDS = {"去世", "自杀", "违法", "犯罪", "诈骗", "造谣", "辟谣", "封杀", "涉毒", "出轨", "辱华", "战争", "暴力", "未成年", "网暴", "抵制", "维权", "事故", "死亡"}

@dataclass
class HotItem:
    platform: str
    rank: int
    keyword: str
    hot_value: int
    url: str
    collected_at: str
    source_status: str = "ok"

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
    ai_reason: str = ""
    ai_brief: str = ""

def now_text() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def fetch_text(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace")

def clean_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", value).strip()

def safe_int(value: object, default: int = 0) -> int:
    text = re.sub(r"[^\d]", "", str(value or ""))
    return int(text) if text else default

def decode_jsonish_text(value: str) -> str:
    if "\\u" in value or "\\x" in value:
        try:
            return value.encode("utf-8").decode("unicode_escape", errors="ignore")
        except UnicodeError:
            return value
    return value

def normalize_key(keyword: str) -> str:
    text = keyword.lower()
    text = re.sub(r"#|热搜|上热搜|官宣|冲上|回应|发文|最新|曝光", "", text)
    text = re.sub(r"[\s，。！？!?:：、\-_/|【】\[\]()（）]+", "", text)
    return text[:18]

def entertainment_score(keyword: str) -> float:
    score = sum(22 for word in ENTERTAINMENT_WORDS if word.lower() in keyword.lower())
    if re.search(r"(新剧|开播|上映|定档|路透|杀青|红毯|演唱会|新歌|预告|票房|剧照|第[一二三四五六七八九十0-9]+季|PV)", keyword):
        score += 22
    if "《" in keyword and "》" in keyword:
        score += 18
    return min(score, 100)

def risk_level(keyword: str) -> str:
    hits = [word for word in RISK_WORDS if word in keyword]
    return "高" if len(hits) >= 2 else "中" if hits else "低"

def collect_weibo() -> list[HotItem]:
    data = json.loads(fetch_text("https://weibo.com/ajax/side/hotSearch"))
    rows = data.get("data", {}).get("realtime", [])
    items = []
    for idx, row in enumerate(rows, 1):
        keyword = clean_text(row.get("word") or row.get("note") or "")
        if keyword:
            items.append(HotItem("微博", idx, keyword, safe_int(row.get("num")), "https://s.weibo.com/weibo?q=" + urllib.parse.quote(keyword), now_text()))
    return items

def collect_baidu() -> list[HotItem]:
    text = fetch_text("https://top.baidu.com/board?tab=realtime")
    blocks = re.findall(r'"word":"(.*?)".{0,800}?"hotScore":"?(\d+)"?', text)
    items, seen = [], set()
    for idx, (word, hot_score) in enumerate(blocks, 1):
        keyword = clean_text(decode_jsonish_text(word))
        if keyword and keyword not in seen:
            seen.add(keyword)
            items.append(HotItem("百度", idx, keyword, safe_int(hot_score), "https://www.baidu.com/s?wd=" + urllib.parse.quote(keyword), now_text()))
    return items

def collect_bilibili() -> list[HotItem]:
    data = json.loads(fetch_text("https://api.bilibili.com/x/web-interface/popular?ps=30&pn=1"))
    items = []
    for idx, row in enumerate(data.get("data", {}).get("list", []), 1):
        keyword = clean_text(row.get("title", ""))
        if keyword:
            items.append(HotItem("B站", idx, keyword, safe_int(row.get("stat", {}).get("view")), "https://www.bilibili.com/video/" + str(row.get("bvid", "")), now_text()))
    return items

def collect_douyin() -> list[HotItem]:
    url = "https://www.douyin.com/aweme/v1/web/hot/search/list/?device_platform=webapp&aid=6383&channel=channel_pc_web"
    data = json.loads(fetch_text(url))
    rows = data.get("data", {}).get("word_list", []) or data.get("word_list", [])
    items = []
    for idx, row in enumerate(rows, 1):
        keyword = clean_text(row.get("word") or row.get("sentence") or "")
        if keyword:
            items.append(HotItem("抖音", idx, keyword, safe_int(row.get("hot_value")), "https://www.douyin.com/search/" + urllib.parse.quote(keyword), now_text()))
    return items

def collect_xiaohongshu() -> list[HotItem]:
    text = fetch_text("https://www.xiaohongshu.com/explore")
    candidates = re.findall(r'"(?:keyword|name|title)"\s*:\s*"([^"]{2,40})"', text)
    items, seen = [], set()
    for word in candidates:
        keyword = clean_text(decode_jsonish_text(word))
        if not keyword or keyword in seen or len(keyword) > 30 or "ICP备" in keyword or keyword in {"小红书", "发现", "登录", "注册"}:
            continue
        seen.add(keyword)
        items.append(HotItem("小红书", len(items) + 1, keyword, 0, "https://www.xiaohongshu.com/search_result?keyword=" + urllib.parse.quote(keyword), now_text()))
        if len(items) >= 20:
            break
    return items

def read_manual_csv() -> list[HotItem]:
    path = DATA_DIR / "manual_hotspots.csv"
    if not path.exists():
        return []
    items = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        for idx, row in enumerate(csv.DictReader(fh), 1):
            keyword = clean_text(row.get("keyword", ""))
            if keyword:
                items.append(HotItem(row.get("platform") or "手动导入", safe_int(row.get("rank"), idx), keyword, safe_int(row.get("hot_value")), row.get("url", ""), now_text()))
    return items

def fallback_items() -> list[HotItem]:
    samples = [("微博", "某剧大结局反转", 1, 8800000), ("抖音", "某演员新剧名场面", 4, 5600000), ("小红书", "新加坡留学生都在看什么剧", 8, 180000), ("百度", "某电影票房破纪录", 3, 7200000), ("B站", "年度高分悬疑剧盘点", 9, 950000)]
    return [HotItem(p, r, k, h, "", now_text(), "sample") for p, k, r, h in samples]

COLLECTORS: list[tuple[str, Callable[[], list[HotItem]]]] = [("微博", collect_weibo), ("百度", collect_baidu), ("B站", collect_bilibili), ("抖音", collect_douyin), ("小红书", collect_xiaohongshu)]

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
            time.sleep(1)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, KeyError) as exc:
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
    items.extend(read_manual_csv())
    if not items:
        items, errors = fallback_items(), errors + ["all collectors failed; using sample data"]
    return items, errors

def extract_response_text(data: dict) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    chunks = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if isinstance(content.get("text"), str):
                chunks.append(content["text"])
    return "".join(chunks)

def openai_json_request(prompt: str, model: str, timeout: int = 45) -> dict:
    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    if not api_key.startswith("sk-"):
        raise RuntimeError("OPENAI_API_KEY should start with sk-")
    api_key.encode("ascii")
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
        "instructions": "你是影视娱乐账号矩阵的内容策略助手。只输出 JSON，帮助运营判断热点是否值得做短视频选题。",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
        "text": {"format": {"type": "json_schema", "name": "hotspot_enrichment", "schema": schema, "strict": True}, "verbosity": "low"},
        "reasoning": {"effort": "minimal"},
        "max_output_tokens": 1200,
    }
    req = urllib.request.Request("https://api.openai.com/v1/responses", data=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    text = extract_response_text(data)
    if not text.strip():
        raise RuntimeError(f"OpenAI returned no text output. status={data.get('status')}, details={data.get('incomplete_details')}")
    return json.loads(text)

def ai_prompt_for_cluster(cluster: Cluster) -> str:
    source_text = "；".join(f"{item['platform']}#{item['rank']} {item['keyword']}" for item in cluster.source_items[:6])
    return f"""请基于以下热点输出结构化 JSON。
热点主标题：{cluster.keyword}
来源：{source_text}
规则分：{cluster.score}
规则推荐等级：{cluster.suggestion_level}
规则风险：{cluster.risk_level}
要求：角度适合影视娱乐/剧集/明星/短视频账号；避免鼓励侵权搬运、站队争议或消费负面事件；tags 必须以 # 开头。"""

def enrich_with_ai(clusters: list[Cluster], limit: int, model: str) -> list[str]:
    errors = []
    candidates = [c for c in clusters if c.entertainment_score >= 25 or c.suggestion_level in {"强烈跟进", "观察"}][:max(0, limit)]
    for cluster in candidates:
        try:
            result = openai_json_request(ai_prompt_for_cluster(cluster), model=model)
            cluster.ai_powered = True
            cluster.ai_brief = clean_text(str(result.get("ai_brief", "")))[:160]
            cluster.ai_reason = clean_text(str(result.get("ai_reason", "")))[:180]
            if result.get("suggestion_level") in {"强烈跟进", "观察", "暂不跟进"}:
                cluster.suggestion_level = result["suggestion_level"]
            if result.get("risk_level") in {"低", "中", "高"}:
                cluster.risk_level = result["risk_level"]
            for field in ("topic_angles", "title_templates", "tags"):
                values = result.get(field)
                if isinstance(values, list) and values:
                    cleaned = [clean_text(str(v)) for v in values if clean_text(str(v))]
                    if cleaned:
                        setattr(cluster, field, cleaned[:3])
        except Exception as exc:
            errors.append(f"AI {cluster.keyword[:24]}: {type(exc).__name__}: {exc}")
    return errors

def topic_angles(keyword: str, ent: float) -> list[str]:
    if ent < 25:
        return [f"从大众情绪切入，判断“{keyword}”是否能关联影视娱乐内容", "观察评论区高频词，寻找可转化为剧情/明星/综艺角度的切口", "仅作为热点背景，不建议直接占用核心账号发布位"]
    return [f"拆解“{keyword}”为什么今天会被讨论，突出冲突、反转或名场面", "把热点转成 15-30 秒短视频：开头 3 秒给结果，中段补剧情/人物关系", "做跨平台对照：微博看讨论点，抖音看情绪点，小红书看种草表达"]

def title_templates(keyword: str) -> list[str]:
    return [f"难怪“{keyword}”今天全网都在刷", f"3 秒看懂“{keyword}”真正出圈的点", f"如果你只看一个片段，先看“{keyword}”这个反转"]

def tags_for(keyword: str) -> list[str]:
    tags = ["#影视娱乐", "#热点", "#短视频选题"]
    if any(word in keyword for word in ["剧", "电影", "开播", "大结局"]):
        tags.extend(["#剧集推荐", "#名场面"])
    if any(word in keyword for word in ["演员", "明星", "红毯"]):
        tags.extend(["#明星动态", "#娱乐资讯"])
    return tags[:6]

def cluster_items(items: Iterable[HotItem]) -> list[Cluster]:
    buckets: dict[str, list[HotItem]] = {}
    for item in items:
        key = normalize_key(item.keyword)
        if key:
            buckets.setdefault(key, []).append(item)
    clusters = []
    for rows in buckets.values():
        rows = sorted(rows, key=lambda x: x.rank or 999)
        keyword = rows[0].keyword
        aliases = sorted({row.keyword for row in rows})
        platforms = sorted({row.platform for row in rows})
        best_rank = min(row.rank for row in rows if row.rank)
        total_hot = sum(row.hot_value for row in rows)
        ent = max(entertainment_score(alias) for alias in aliases)
        score = round(max(0, 35 - best_rank) + min(total_hot / 250000, 30) + min(len(platforms) * 12, 36) + ent * 0.35 + 10, 1)
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
    return sorted(clusters, key=lambda x: (x.suggestion_level == "强烈跟进", x.entertainment_score, x.score), reverse=True)

def write_outputs(items: list[HotItem], clusters: list[Cluster], errors: list[str], ai_model: str | None = None) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    payload = {"generated_at": now_text(), "raw_count": len(items), "cluster_count": len(clusters), "errors": errors, "ai_model": ai_model or "", "ai_count": sum(1 for c in clusters if c.ai_powered), "clusters": [asdict(c) for c in clusters]}
    JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    top = [c for c in clusters if c.entertainment_score >= 25][:20]
    if len(top) < 10:
        top.extend([c for c in clusters if c not in top][:20 - len(top)])
    lines = ["# 中文社媒影视娱乐热点简报", "", f"生成时间：{payload['generated_at']}", f"采集原始热点：{len(items)} 条，合并后热点：{len(clusters)} 个", "", "## 今日优先跟进"]
    for idx, item in enumerate(top, 1):
        lines += ["", f"### {idx}. {item.keyword}", f"- 推荐等级：{item.suggestion_level}；综合分：{item.score}；风险：{item.risk_level}", f"- AI增强：{'是' if item.ai_powered else '否'}{('；' + item.ai_brief) if item.ai_brief else ''}", f"- 来源平台：{', '.join(item.platforms)}；最佳排名：#{item.best_rank}", f"- 选题角度：{item.topic_angles[0]}", f"- 标题模板：{item.title_templates[0]}", f"- 标签：{' '.join(item.tags)}"]
    if errors:
        lines += ["", "## 采集提示"] + [f"- {err}" for err in errors]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")

def main() -> int:
    parser = argparse.ArgumentParser(description="Chinese social hotspot radar")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--ai", action="store_true")
    parser.add_argument("--ai-limit", type=int, default=10)
    parser.add_argument("--ai-model", default=os.environ.get("OPENAI_MODEL", "gpt-5-nano"))
    args = parser.parse_args()
    items, errors = collect_all(offline=args.offline)
    clusters = cluster_items(items)
    ai_model = None
    if args.ai:
        ai_model = args.ai_model
        errors.extend(enrich_with_ai(clusters, args.ai_limit, args.ai_model))
    write_outputs(items, clusters, errors, ai_model)
    print(f"raw items: {len(items)}")
    print(f"clusters: {len(clusters)}")
    if args.ai:
        print(f"ai model: {args.ai_model}")
        print(f"ai enriched: {sum(1 for c in clusters if c.ai_powered)}")
    print(f"json: {JSON_PATH}")
    print(f"report: {REPORT_PATH}")
    if errors:
        print("collector notes:")
        for err in errors:
            print(f"- {err}")
    return 0

if __name__ == "__main__":
    sys.exit(main())

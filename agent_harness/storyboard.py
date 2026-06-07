from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


SCENE_TYPES = {
    "statement",
    "context",
    "stat",
    "bullets",
    "card",
    "compare",
    "compare_table",
    "terminal",
    "flow",
    "chart",
    "code_diff",
    "quote",
    "cta",
}
THEMES = {"radar", "minimal", "editorial"}
DENSITIES = {"minimal", "standard", "rich"}
MOTIONS = {"calm", "standard", "punchy"}
EMPHASIS = {"low", "normal", "high"}
HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
MAX_SCENES = 8

REQUIRED_SCENE_TEXT: dict[str, tuple[str, ...]] = {
    "statement": ("title", "heading"),
    "context": ("text", "summary", "detail"),
    "stat": ("value", "stat", "label", "heading"),
    "bullets": ("heading", "title", "items"),
    "card": ("value", "detail"),
    "compare": ("left", "right"),
    "compare_table": ("rows", "items"),
    "terminal": ("lines", "commands", "items"),
    "flow": ("nodes", "steps", "items"),
    "chart": ("value", "stat", "points", "items"),
    "code_diff": ("additions", "added", "removals", "removed", "items"),
    "quote": ("quote", "text"),
    "cta": ("text",),
}


def bounded_text(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _first_text(props: dict[str, Any], keys: tuple[str, ...], fallback: str = "", limit: int = 120) -> str:
    for key in keys:
        value = props.get(key)
        if isinstance(value, str) and value.strip():
            return bounded_text(value, limit)
    return bounded_text(fallback, limit)


def normalize_style(style: Any) -> dict[str, Any]:
    raw = style if isinstance(style, dict) else {}
    theme = raw.get("theme") if raw.get("theme") in THEMES else "radar"
    default_chrome = {
        "radar": {"topbar": True, "progress": True, "beam": True},
        "minimal": {"topbar": False, "progress": False, "beam": False},
        "editorial": {"topbar": True, "progress": True, "beam": False},
    }[theme]
    chrome = raw.get("chrome") if isinstance(raw.get("chrome"), dict) else {}
    accent = raw.get("accent")
    return {
        "theme": theme,
        "density": raw.get("density") if raw.get("density") in DENSITIES else "standard",
        "motion": raw.get("motion") if raw.get("motion") in MOTIONS else "standard",
        "accent": accent if isinstance(accent, str) and HEX_RE.match(accent) else ("#72e7ff" if theme == "editorial" else "#ffd60a"),
        "chrome": {
            "topbar": bool(chrome.get("topbar", default_chrome["topbar"])),
            "progress": bool(chrome.get("progress", default_chrome["progress"])),
            "beam": bool(chrome.get("beam", default_chrome["beam"])),
        },
    }


def _normalize_items(value: Any, limit: int = 58, max_items: int = 4) -> list[str]:
    if not isinstance(value, list):
        return []
    return [bounded_text(item, limit) for item in value if str(item or "").strip()][:max_items]


def _raw_has_required_text(scene_type: str, props: Any) -> bool:
    raw = props if isinstance(props, dict) else {}
    for key in REQUIRED_SCENE_TEXT.get(scene_type, ()):
        value = raw.get(key)
        if isinstance(value, list) and any(str(item or "").strip() for item in value):
            return True
        if isinstance(value, str) and value.strip():
            return True
    return False


def normalize_scene_props(scene_type: str, props: Any) -> dict[str, Any]:
    raw = props if isinstance(props, dict) else {}
    if scene_type == "statement":
        return {
            "kicker": _first_text(raw, ("kicker",), "今天为什么刷到它", 18),
            "title": _first_text(raw, ("title", "heading"), "", 68),
            "sub": _first_text(raw, ("sub", "subtitle", "detail"), "", 110),
        }
    if scene_type == "context":
        return {
            "kicker": _first_text(raw, ("kicker",), "一句话看懂", 18),
            "text": _first_text(raw, ("text", "summary", "detail"), "", 128),
            "metric": _first_text(raw, ("metric", "value"), "", 28),
            "metricNote": _first_text(raw, ("metricNote", "note"), "", 18),
            "sourceLabel": _first_text(raw, ("sourceLabel",), "来源边界", 18),
            "sourceValue": _first_text(raw, ("sourceValue", "source"), "", 76),
        }
    if scene_type == "stat":
        return {
            "kicker": _first_text(raw, ("kicker",), "一个信号", 18),
            "value": _first_text(raw, ("value", "stat"), "", 30),
            "label": _first_text(raw, ("label", "heading"), "", 54),
            "detail": _first_text(raw, ("detail", "sub"), "", 104),
        }
    if scene_type == "bullets":
        return {
            "kicker": _first_text(raw, ("kicker",), "拆成几步看", 18),
            "heading": _first_text(raw, ("heading", "title"), "", 56),
            "items": _normalize_items(raw.get("items")),
        }
    if scene_type == "compare":
        return {
            "kicker": _first_text(raw, ("kicker",), "别混在一起", 18),
            "heading": _first_text(raw, ("heading", "title"), "", 56),
            "leftLabel": _first_text(raw, ("leftLabel",), "已知", 14),
            "left": _first_text(raw, ("left",), "", 90),
            "rightLabel": _first_text(raw, ("rightLabel",), "边界", 14),
            "right": _first_text(raw, ("right",), "", 90),
        }
    if scene_type == "compare_table":
        return {
            "kicker": _first_text(raw, ("kicker",), "横向比较", 18),
            "heading": _first_text(raw, ("heading", "title"), "", 56),
            "leftLabel": _first_text(raw, ("leftLabel",), "当前方案", 14),
            "rightLabel": _first_text(raw, ("rightLabel",), "失败边界", 14),
            "rows": _normalize_items(raw.get("rows") or raw.get("items"), limit=76, max_items=4),
        }
    if scene_type == "terminal":
        return {
            "kicker": _first_text(raw, ("kicker",), "把它放进终端看", 18),
            "title": _first_text(raw, ("title", "heading"), "开发者路径", 42),
            "prompt": _first_text(raw, ("prompt",), "$", 8),
            "lines": _normalize_items(raw.get("lines") or raw.get("commands") or raw.get("items"), limit=64, max_items=5),
        }
    if scene_type == "flow":
        return {
            "kicker": _first_text(raw, ("kicker",), "机制怎么跑", 18),
            "heading": _first_text(raw, ("heading", "title"), "", 56),
            "nodes": _normalize_items(raw.get("nodes") or raw.get("steps") or raw.get("items"), limit=34, max_items=5),
            "caption": _first_text(raw, ("caption", "detail", "summary"), "", 80),
        }
    if scene_type == "chart":
        return {
            "kicker": _first_text(raw, ("kicker",), "一个数据点", 18),
            "heading": _first_text(raw, ("heading", "title"), "", 56),
            "label": _first_text(raw, ("label",), "信号", 18),
            "value": _first_text(raw, ("value", "stat"), "", 28),
            "points": _normalize_items(raw.get("points") or raw.get("items"), limit=18, max_items=5),
        }
    if scene_type == "code_diff":
        return {
            "kicker": _first_text(raw, ("kicker",), "代码视角", 18),
            "title": _first_text(raw, ("title", "heading"), "不是只看 README", 50),
            "filename": _first_text(raw, ("filename", "file"), "skill.md", 34),
            "additions": _normalize_items(raw.get("additions") or raw.get("added") or raw.get("items"), limit=70, max_items=4),
            "removals": _normalize_items(raw.get("removals") or raw.get("removed"), limit=70, max_items=2),
        }
    if scene_type == "quote":
        return {
            "kicker": _first_text(raw, ("kicker",), "原始信号", 18),
            "quote": _first_text(raw, ("quote", "text"), "", 112),
            "attribution": _first_text(raw, ("attribution", "source"), "", 42),
        }
    if scene_type == "cta":
        return {
            "kicker": _first_text(raw, ("kicker",), "判断框架", 18),
            "text": _first_text(raw, ("text",), "", 48),
            "footer": _first_text(raw, ("footer",), "", 80),
        }
    return {
        "label": _first_text(raw, ("label",), "证据", 18),
        "value": _first_text(raw, ("value",), "", 54),
        "detail": _first_text(raw, ("detail",), "", 118),
    }


def _scene_has_text(scene_type: str, props: dict[str, Any]) -> bool:
    if scene_type == "bullets":
        return bool(props.get("heading") or props.get("items"))
    if scene_type == "terminal":
        return bool(props.get("title") or props.get("lines"))
    if scene_type == "flow":
        return bool(props.get("heading") or props.get("nodes"))
    if scene_type == "chart":
        return bool(props.get("heading") or props.get("value") or props.get("points"))
    if scene_type == "code_diff":
        return bool(props.get("title") or props.get("additions") or props.get("removals"))
    if scene_type == "compare_table":
        return bool(props.get("heading") or props.get("rows"))
    return any(str(value or "").strip() for value in props.values() if not isinstance(value, list))


def validate_storyboard(storyboard: Any) -> dict[str, Any]:
    if not isinstance(storyboard, dict):
        raise ValueError("storyboard must be an object")
    scenes_in = storyboard.get("scenes")
    if not isinstance(scenes_in, list):
        raise ValueError("storyboard.scenes must be an array")
    if len(scenes_in) > MAX_SCENES:
        raise ValueError(f"storyboard.scenes must contain at most {MAX_SCENES} scenes")
    scenes: list[dict[str, Any]] = []
    for index, item in enumerate(scenes_in, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"storyboard scene {index} must be an object")
        scene_type = item.get("type")
        if scene_type not in SCENE_TYPES:
            raise ValueError(f"storyboard scene {index} has unknown type: {scene_type}")
        if not isinstance(item.get("props"), dict):
            raise ValueError(f"storyboard scene {index} props must be an object")
        if not _raw_has_required_text(str(scene_type), item.get("props")):
            raise ValueError(f"storyboard scene {index} ({scene_type}) missing provider-authored text")
        props = normalize_scene_props(str(scene_type), item.get("props"))
        if not _scene_has_text(str(scene_type), props):
            raise ValueError(f"storyboard scene {index} ({scene_type}) has no renderable text")
        clean: dict[str, Any] = {"type": scene_type, "props": props}
        weight = item.get("weight")
        if isinstance(weight, (int, float)) and 0 < float(weight) <= 1:
            clean["weight"] = round(float(weight), 4)
        emphasis = item.get("emphasis")
        if emphasis in EMPHASIS:
            clean["emphasis"] = emphasis
        scenes.append(clean)
    if not scenes:
        raise ValueError("storyboard requires at least one known text scene")
    return {
        "version": 1,
        "style": normalize_style(storyboard.get("style")),
        "scenes": scenes,
    }


def storyboard_text_items(storyboard: Any) -> list[str]:
    if not storyboard:
        return []
    clean = validate_storyboard(storyboard)
    items: list[str] = []
    for scene in clean["scenes"]:
        props = scene.get("props") or {}
        for value in props.values():
            if isinstance(value, list):
                items.extend(str(item) for item in value if str(item or "").strip())
            elif str(value or "").strip():
                items.append(str(value))
    return items


def card_scenes(storyboard: Any) -> list[dict[str, str]]:
    if not storyboard:
        return []
    clean = validate_storyboard(storyboard)
    cards: list[dict[str, str]] = []
    for scene in clean["scenes"]:
        if scene.get("type") != "card":
            continue
        props = scene.get("props") or {}
        cards.append(
            {
                "label": bounded_text(props.get("label"), 18),
                "value": bounded_text(props.get("value"), 54),
                "detail": bounded_text(props.get("detail"), 118),
            }
        )
    return [card for card in cards if card["label"] or card["value"] or card["detail"]]


def public_source_value(url: str) -> str:
    host = urlparse(str(url or "")).netloc.lower()
    if host.endswith("github.com"):
        return "公开仓库来源已留档"
    if host:
        return "外部来源已留档"
    return "来源已留档"


def _is_github_url(url: str) -> bool:
    return urlparse(str(url or "")).netloc.lower().endswith("github.com")


def _has_metric_signal(value: str) -> bool:
    return bool(re.search(r"\d", str(value or "")))


def derive_default_storyboard(
    *,
    display_title: str,
    summary: str,
    audience_metric: str,
    evidence_level: str,
    url: str,
    cards: list[dict[str, Any]],
    cta: str,
    verification_next_step: str,
    footer: str,
) -> dict[str, Any]:
    scenes: list[dict[str, Any]] = [
        {
            "type": "statement",
            "props": {"kicker": "今天为什么刷到它", "title": display_title, "sub": summary},
        },
        {
            "type": "context",
            "props": {
                "kicker": "一句话看懂",
                "text": summary,
                "metric": audience_metric,
                "metricNote": "证据边界" if "unverified" in str(evidence_level) else "实时信号",
                "sourceLabel": "来源边界",
                "sourceValue": public_source_value(url),
            },
        },
    ]
    if _has_metric_signal(audience_metric):
        scenes.append(
            {
                "type": "chart",
                "props": {
                    "kicker": "数据先当信号看",
                    "heading": "热度不是结论，但能说明关注方向",
                    "label": "公开指标",
                    "value": audience_metric,
                    "points": ["来源", "关注", "判断"],
                },
            }
        )
    if _is_github_url(url):
        scenes.extend(
            [
                {
                    "type": "terminal",
                    "props": {
                        "kicker": "开发者会先这样判断",
                        "title": "最小上手路径",
                        "prompt": "$",
                        "lines": ["clone / install", "run quick start", "inspect examples", "check tests"],
                    },
                },
                {
                    "type": "flow",
                    "props": {
                        "kicker": "机制不要只靠文字讲",
                        "heading": "把 repo 还原成一条工作流",
                        "nodes": ["输入", "核心模块", "输出", "失败边界"],
                        "caption": "这类场景让 agent 用结构图解释机制，而不是堆段落。",
                    },
                },
                {
                    "type": "code_diff",
                    "props": {
                        "kicker": "源码视角",
                        "title": "别只复述 README",
                        "filename": "repo / docs / tests",
                        "additions": ["看入口模块", "看示例输入输出", "看测试和 CI"],
                        "removals": ["只看 star 数"],
                    },
                },
            ]
        )
    card_limit = 1 if _is_github_url(url) and _has_metric_signal(audience_metric) else (2 if _is_github_url(url) else 4)
    for card in cards[:card_limit]:
        scenes.append(
            {
                "type": "card",
                "props": {
                    "label": card.get("label"),
                    "value": card.get("value"),
                    "detail": card.get("detail"),
                },
            }
        )
    scenes.append(
        {
            "type": "cta",
            "props": {
                "kicker": "判断框架",
                "text": cta,
                "footer": verification_next_step or footer,
            },
        }
    )
    return validate_storyboard({"version": 1, "style": {"theme": "radar"}, "scenes": scenes})

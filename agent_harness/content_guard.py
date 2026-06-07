from __future__ import annotations

import re
from typing import Any

from agent_harness.policy import policy_get


DEFAULT_BANNED_DISMISSIVE_PATTERNS = [
    r"自己验证",
    r"你自己动手验证",
    r"待验证案例继续观察",
    r"不能跳过最小验证",
    r"按证据验证[，,、 ]*不急着下结论",
    r"不急着下结论",
    r"别急着下结论",
    r"具体细节未知[，,、 ]*需要自己去试",
    r"待验证",
    r"(?:需要|需|要)验证(?:兼容性|适用性|可用性|效果|结果)?",
    r"需要自己去试",
    r"verify it yourself",
    r"you verify it yourself",
    r"try it yourself",
]

DISMISSIVE_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"按证据验证[，,、 ]*不急着下结论"), "用机制、适用场景和失败边界来判断"),
    (re.compile(r"待验证案例继续观察"), "按证据边界拆成判断框架"),
    (re.compile(r"不能跳过最小验证"), "先看最小可用条件和失败边界"),
    (re.compile(r"具体细节未知[，,、 ]*需要自己去试"), "证据不足时只提炼机制线索和判断口径"),
    (re.compile(r"你自己动手验证|自己验证"), "按判断框架评估"),
    (re.compile(r"不急着下结论"), "先给出可复用的判断框架"),
    (re.compile(r"别急着下结论"), "先给出可复用的判断框架"),
    (re.compile(r"待验证"), "证据边界内"),
    (re.compile(r"(?:需要|需|要)验证兼容性"), "需要看清兼容性边界"),
    (re.compile(r"(?:需要|需|要)验证适用性"), "需要看清适用边界"),
    (re.compile(r"(?:需要|需|要)验证可用性"), "需要看清可用条件"),
    (re.compile(r"(?:需要|需|要)验证效果"), "需要用可观察指标判断效果"),
    (re.compile(r"(?:需要|需|要)验证结果"), "需要用可观察指标判断结果"),
    (re.compile(r"(?:需要|需|要)验证"), "需要按证据边界判断"),
    (re.compile(r"需要自己去试"), "需要按适用场景评估"),
    (re.compile(r"verify it yourself", re.I), "use the evaluation framework"),
    (re.compile(r"you verify it yourself", re.I), "use the evaluation framework"),
    (re.compile(r"try it yourself", re.I), "evaluate it against the fit and failure boundaries"),
]

KNOWLEDGE_PHRASE_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"第一手(?=经验|资料|信息|案例|素材|观察|记录)"), "一手"),
    (re.compile(r"(?<!一)手(?=经验|资料|信息|案例|素材|观察|记录)"), "一手"),
    (re.compile(r"来源链接"), "来源标注"),
    (re.compile(r"附(?:上)?来源(?!标注)"), "附上来源标注"),
]

UNSUPPORTED_CLAIM_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"全球第一|行业第一|排名第一|第一名|第一"), "关键"),
    (re.compile(r"唯一"), "少见"),
    (re.compile(r"首个"), "早期"),
    (re.compile(r"首发"), "公开"),
    (re.compile(r"最强"), "高价值"),
    (re.compile(r"革命性"), "值得分析"),
    (re.compile(r"刚开源"), "已开源"),
    (re.compile(r"刚发布|正式发布"), "公开发布"),
    (re.compile(r"\bfirst\b", re.I), "early"),
    (re.compile(r"\bbest\b", re.I), "strong"),
    (re.compile(r"\bonly\b", re.I), "specific"),
    (re.compile(r"\bultimate\b", re.I), "complete"),
    (re.compile(r"\bgame.?changer\b", re.I), "important shift"),
    (re.compile(r"\brevolutionary\b", re.I), "worth analyzing"),
    (re.compile(r"\b10x\b", re.I), "clear"),
]


def banned_dismissive_patterns() -> list[str]:
    configured = policy_get("content.banned_dismissive_verification_patterns", [])
    patterns = [str(item) for item in configured if str(item).strip()] if isinstance(configured, list) else []
    return patterns or DEFAULT_BANNED_DISMISSIVE_PATTERNS


def _iter_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        rows: list[str] = []
        for item in value:
            rows.extend(_iter_strings(item))
        return rows
    if isinstance(value, dict):
        rows = []
        for key, item in value.items():
            if str(key) in {"banned_dismissive_phrases", "banned_dismissive_patterns"}:
                continue
            rows.extend(_iter_strings(item))
        return rows
    return []


def dismissive_verification_hits(value: Any) -> list[str]:
    text = "\n".join(_iter_strings(value))
    hits: list[str] = []
    for pattern in banned_dismissive_patterns():
        if re.search(pattern, text, re.I):
            hits.append(pattern)
    return sorted(set(hits))


def scrub_dismissive_verification_text(value: Any) -> Any:
    if isinstance(value, str):
        text = value
        for pattern, replacement in KNOWLEDGE_PHRASE_REPLACEMENTS:
            text = pattern.sub(replacement, text)
        for pattern, replacement in DISMISSIVE_REPLACEMENTS:
            text = pattern.sub(replacement, text)
        for pattern, replacement in UNSUPPORTED_CLAIM_REPLACEMENTS:
            text = pattern.sub(replacement, text)
        return re.sub(r"\s+", " ", text).strip()
    if isinstance(value, list):
        return [scrub_dismissive_verification_text(item) for item in value]
    if isinstance(value, dict):
        return {key: scrub_dismissive_verification_text(item) for key, item in value.items()}
    return value


def public_content_payload(polished: dict[str, Any]) -> dict[str, Any]:
    visual = polished.get("agent_visual") or polished.get("agentVisual") or {}
    if not isinstance(visual, dict):
        visual = {}
    return {
        "polished_title": polished.get("polished_title"),
        "voiceover_text": polished.get("voiceover_text"),
        "douyin_title": polished.get("douyin_title"),
        "douyin_desc": polished.get("douyin_desc"),
        "cards": polished.get("cards"),
        "storyboard": polished.get("storyboard"),
        "caveats": polished.get("caveats"),
        "agent_visual": {
            "description": visual.get("description"),
            "module_code": visual.get("module_code"),
            "component_code": visual.get("component_code"),
        },
    }

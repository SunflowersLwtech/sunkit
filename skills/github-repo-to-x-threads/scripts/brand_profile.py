"""Shared brand contract for Agent engineering X content."""

from __future__ import annotations

import re
from typing import Any


BRAND_PROFILE: dict[str, Any] = {
    "positioning": "Agent engineering practitioner",
    "tagline": "Agent 工程如何从 demo 变成可靠系统",
    "default_language": "Chinese with exact English technical names",
    "pillars": [
        "agent_reliability",
        "build_in_public",
        "paper_to_system",
        "embodied_ai_watch",
    ],
    "allowed_off_main_account": [
        "professional_bug_report",
        "customer_support_or_kyc_dispute",
        "life_or_media_note_without_agent_engineering_link",
    ],
    "required_public_shape": [
        "reader pain, technical conflict, or engineering risk in post 1",
        "one reusable asset per thread",
        "one concrete discussion question",
        "emotion converted into process, data, or failure-mode language",
        "one coherent creator pattern: engineering mentor, demo-first tool, test catalog, builder resource log, or product translator longform",
    ],
    "forbidden_public_shape": [
        "客服式控诉",
        "hashtag 堆叠",
        "全大写怒气",
        "纯论文摘要",
        "无 CTA 的自言自语",
    ],
}


PILLAR_KEYWORDS: dict[str, tuple[str, ...]] = {
    "agent_reliability": (
        "agent",
        "agents",
        "hallucination",
        "uncertainty",
        "tool",
        "routing",
        "memory",
        "debug",
        "failure",
        "eval",
        "可靠",
        "幻觉",
        "工具调用",
        "不确定",
        "失败",
        "记忆",
        "调试",
    ),
    "build_in_public": (
        "i built",
        "we built",
        "building",
        "shipped",
        "mcp",
        "creator growth",
        "debug_search",
        "debug_record",
        "debug memory",
        "build-in-public",
        "building in public",
        "我做",
        "我在做",
        "构建",
        "发布",
        "实战",
        "踩坑",
    ),
    "paper_to_system": (
        "paper",
        "arxiv",
        "alphaxiv",
        "icml",
        "neurips",
        "acl",
        "论文",
        "paper-to-system",
        "position paper",
        "系统",
        "工程启发",
    ),
    "embodied_ai_watch": (
        "embodied",
        "robot",
        "robotics",
        "具身",
        "机器人",
        "open world",
        "world model",
        "home robot",
    ),
}


BUG_REPORT_KEYWORDS = (
    "kyc",
    "sumsub",
    "ticket",
    "bug report",
    "plasma",
    "reject",
    "appeal",
    "support",
    "客服",
    "工单",
    "申诉",
    "维权",
    "拒绝",
    "表单",
)


LIFE_OR_MEDIA_KEYWORDS = (
    "电视剧",
    "电影",
    "剧",
    "life",
    "生活",
    "吐槽",
    "travel",
    "food",
    "日常",
)


EMOTION_KEYWORDS = (
    "angry",
    "furious",
    "slamming",
    "ridiculous",
    "fix this",
    "😤",
    "垃圾",
    "离谱",
    "气死",
    "崩溃",
    "傻逼",
    "sb",
)


ASSET_TYPES = (
    "checklist",
    "flowchart",
    "issue_template",
    "prompt_snippet",
    "before_after_table",
    "failure_mode_map",
)


CREATOR_PATTERNS = (
    "engineering_mentor",
    "demo_first_tool",
    "test_catalog",
    "builder_resource_log",
    "product_translator_longform",
)


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(keyword.lower() in lower for keyword in keywords)


def detect_content_pillar(text: str) -> str:
    scores = {
        pillar: sum(1 for keyword in keywords if keyword.lower() in text.lower())
        for pillar, keywords in PILLAR_KEYWORDS.items()
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "unassigned"


def classify_brand_input(prompt: str, source_kinds: set[str] | None = None) -> dict[str, Any]:
    """Classify the request against the account-positioning contract."""

    source_kinds = source_kinds or set()
    text = prompt or ""
    pillar = detect_content_pillar(text)
    lower = text.lower()
    if re.search(r"build-in-public|building in public|mcp creator|creator growth|我在做|我做", lower):
        pillar = "build_in_public"
    has_bug_word = bool(re.search(r"(?<!de)\bbug\b|#\w*bug\b|bug report", lower))
    is_bug_report = _contains_any(text, BUG_REPORT_KEYWORDS) or has_bug_word
    is_life_or_media = _contains_any(text, LIFE_OR_MEDIA_KEYWORDS)
    is_emotional = _contains_any(text, EMOTION_KEYWORDS) or text.count("!") >= 3

    if "paper" in source_kinds:
        pillar = "paper_to_system"
    elif "github_repo" in source_kinds or "local_repo" in source_kinds:
        if pillar == "unassigned":
            pillar = "agent_reliability"

    if is_bug_report:
        content_lane = "professional_bug_report"
        account_fit = "conditional"
        routing_note = "Rewrite as a cold PRD-style bug report; keep on main account only if tied to Agent/KYC workflow reliability."
    elif is_life_or_media and pillar == "unassigned":
        content_lane = "off_main_account_or_agent_link_required"
        account_fit = "weak"
        routing_note = "Do not publish as life/media chatter on the main account unless it becomes an Agent engineering failure-mode note."
    elif pillar == "unassigned":
        content_lane = "research_then_position"
        account_fit = "weak"
        routing_note = "Find or request a clear Agent engineering angle before publishing."
    else:
        content_lane = "main_account"
        account_fit = "strong"
        routing_note = "Publishable on the main account when evidence, reusable asset, and discussion question are present."

    return {
        "positioning": BRAND_PROFILE["positioning"],
        "tagline": BRAND_PROFILE["tagline"],
        "pillar": pillar,
        "content_lane": content_lane,
        "account_fit": account_fit,
        "emotion_risk": "high" if is_emotional else "normal",
        "bug_report_mode": is_bug_report,
        "routing_note": routing_note,
        "required_asset_types": list(ASSET_TYPES),
        "recommended_creator_patterns": list(CREATOR_PATTERNS),
        "required_discussion_question": True,
        "main_account_rule": (
            "Every public post must map to Agent reliability, build-in-public, "
            "paper-to-system, or embodied AI watch."
        ),
    }


def brand_contract_lines() -> list[str]:
    return [
        f"Positioning: {BRAND_PROFILE['positioning']} / {BRAND_PROFILE['tagline']}.",
        "Main content pillars: agent reliability, build-in-public, paper-to-system, embodied AI watch.",
        "Post 1 must start from reader pain, technical conflict, or engineering risk; never from a generic source note.",
        "Every thread needs one reusable asset: checklist, flowchart, issue template, prompt snippet, before/after table, or failure-mode map.",
        "End with one concrete discussion question. Avoid vague 'thoughts?' CTAs.",
        "Select one creator pattern before drafting: engineering mentor, demo-first tool, test catalog, builder resource log, or product translator longform.",
        "Use creator patterns as structure only; do not copy any specific creator's identity, catchphrases, emoji habits, or community nicknames.",
        "Convert emotion into process, data, repro steps, expected behavior, impact, or failure mode.",
        "KYC/support complaints become cold bug reports or off-main-account drafts unless tied to Agent workflow reliability.",
        "Life/media notes stay off the main account unless rewritten as an Agent engineering analogy with a concrete mechanism.",
    ]


def likely_discussion_question(text: str) -> bool:
    if "?" in text or "？" in text:
        return True
    return bool(re.search(r"(你会|你觉得|评论区|讨论|which|what would|how would)", text, flags=re.I))

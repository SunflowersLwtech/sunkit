from __future__ import annotations

import re
from typing import Any

from agent_harness.policy import policy_get
from agent_harness.agent_visual import agent_visual_text_items
from agent_harness.storyboard import storyboard_text_items
from agent_harness.subjects import is_operator_topic


REPO_SLUG_RE = re.compile(r"(?<![\w:/.@-])([A-Za-z0-9_.-]{2,})/([A-Za-z0-9_.-]{2,})(?![\w/.-])")
URL_RE = re.compile(r"https?://[^\s，。！？；;]+", re.I)
RAW_SLASH_RE = re.compile(r"\b[A-Za-z0-9_.-]{2,}/[A-Za-z0-9_.-]{2,}\b")
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
SPOKEN_TOKEN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaffA-Za-z0-9]")
SNAKE_CASE_INTERNAL_RE = re.compile(r"\b[a-z][a-z0-9]+(?:_[a-z0-9]+)+\b")
CLOSING_PUNCTUATION = set("/|,，;；。.!?！？:：)]}）】》”’、")
OPENING_PUNCTUATION = set("([{（【《“‘")


def bounded_text(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def normalize_repo_slashes_for_speech(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        owner, repo = match.group(1), match.group(2)
        return f"{owner} 的 {repo}"

    return REPO_SLUG_RE.sub(repl, text)


def normalize_voiceover_text(text: str) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()

    def normalize_io(match: re.Match[str]) -> str:
        context = f"{clean[max(0, match.start() - 24):match.start()]} {clean[match.end():match.end() + 24]}"
        if re.search(r"Google|Search|\b20\d{2}\b|大会|发布会", context, re.I):
            return "I O"
        return "输入输出"

    clean = re.sub(r"(?<![A-Za-z])I\s*[/，,／]\s*O(?![A-Za-z])", normalize_io, clean, flags=re.I)
    clean = URL_RE.sub(lambda m: m.group(0).replace("https://", "").replace("http://", "").replace("/", " 的 "), clean)
    clean = normalize_repo_slashes_for_speech(clean)
    clean = re.sub(r"(?<=\w)\.sh\b", " shell 脚本", clean)
    clean = clean.replace("@", " at ")
    clean = re.sub(r"\s*/\s*", "，", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def normalize_display_title(text: str) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    clean = REPO_SLUG_RE.sub(lambda m: f"{m.group(1)} / {m.group(2)}", clean)
    return clean


def chinese_ratio(text: str) -> float:
    tokens = SPOKEN_TOKEN_RE.findall(str(text or ""))
    if not tokens:
        return 0.0
    return len(CJK_RE.findall(str(text or ""))) / float(len(tokens))


def has_raw_speech_symbols(text: str) -> bool:
    lowered = str(text or "").lower()
    return bool(RAW_SLASH_RE.search(lowered) or URL_RE.search(lowered) or " slash " in f" {lowered} ")


def evidence_level_for_candidate(candidate: dict[str, Any]) -> str:
    if is_operator_topic(candidate):
        canonical_url = str(candidate.get("canonical_url") or "")
        manual_scheme = str(policy_get("subject_inputs.operator_topic.manual_url_scheme", "manual-topic://"))
        return "operator_topic_sourced" if canonical_url and not canonical_url.startswith(manual_scheme) else "operator_topic_unverified"
    signals = candidate.get("signals") or {}
    if signals.get("has_demo_keyword") or signals.get("has_code_signal"):
        return "source_observation_with_artifact_signal"
    return "source_observation_unverified"


def verification_next_step_for_candidate(candidate: dict[str, Any]) -> str:
    if is_operator_topic(candidate):
        return str(
            policy_get(
                "content.profiles.operator_topic.verification_next_step",
                "判断时先看机制是否成立、架构位置是否清楚、失败边界是否可控。",
            )
        )
    signals = candidate.get("signals") or {}
    if signals.get("has_demo_keyword"):
        return "判断时把 demo 路径、适用负载和失败边界分开看。"
    if signals.get("has_code_signal"):
        return "判断时看源码入口、安装路径、最小示例和维护边界是否匹配。"
    return "判断时先区分来源证据、机制线索、适用场景和失败边界。"


def unverified_quality_warning(candidate: dict[str, Any]) -> str | None:
    level = evidence_level_for_candidate(candidate)
    if level.endswith("unverified"):
        return "未发现 demo、源码细节或真实使用证据，只能做证据边界内的机制拆解。"
    if level == "operator_topic_unverified":
        return "指定主题未附外部来源，只能做证据边界内的判断框架。"
    return None


def _weighted_char(ch: str) -> float:
    if CJK_RE.match(ch):
        return 1.0
    if ch.isascii() and ch.isalnum():
        return 0.58
    if ch.isspace():
        return 0.28
    return 0.45


def _tokenize_display(text: str) -> list[str]:
    tokens: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        nonlocal buf
        if buf:
            tokens.append("".join(buf))
            buf = []

    for ch in text:
        if CJK_RE.match(ch):
            flush()
            tokens.append(ch)
        elif ch.isspace():
            flush()
            tokens.append(" ")
        elif ch in "/|:：,，;；。!?！？":
            flush()
            tokens.append(ch)
        else:
            buf.append(ch)
    flush()
    return tokens


def _rebalance_punctuation(lines: list[str]) -> list[str]:
    balanced: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        while line and line[0] in CLOSING_PUNCTUATION and balanced:
            balanced[-1] += line[0]
            line = line[1:].lstrip()
        if line:
            balanced.append(line)
    for index in range(len(balanced) - 1):
        if balanced[index] and balanced[index][-1] in OPENING_PUNCTUATION:
            punct = balanced[index][-1]
            balanced[index] = balanced[index][:-1].rstrip()
            balanced[index + 1] = f"{punct}{balanced[index + 1]}"
    return [line for line in balanced if line]


def _display_weight(text: str) -> float:
    return sum(_weighted_char(ch) for ch in text)


def plan_cover_title_lines(text: str, max_units: float = 8.6, max_lines: int = 6) -> dict[str, Any]:
    title = normalize_display_title(text)
    tokens = _tokenize_display(title)
    lines: list[str] = []
    line = ""

    def push_line() -> None:
        nonlocal line
        clean = line.strip()
        if clean:
            lines.append(clean)
        line = ""

    for token in tokens:
        if not token:
            continue
        candidate = f"{line}{token}"
        if line and token != " " and _display_weight(candidate) > max_units and token not in CLOSING_PUNCTUATION:
            push_line()
        line += token
    push_line()
    lines = _rebalance_punctuation(lines)
    if not lines:
        lines = [title]
    max_line_units = max(_display_weight(line) for line in lines)
    font_size = max(64, min(124, int(930 / max(max_line_units, 1.0))))
    return {
        "title": title,
        "lines": lines[:max_lines],
        "line_count": len(lines),
        "max_line_units": round(max_line_units, 3),
        "font_size": font_size,
        "safe": len(lines) <= max_lines and font_size >= 64 and max_line_units <= 14.5,
    }


def _policy_list(path: str) -> list[str]:
    value = policy_get(path, [])
    return [str(item) for item in value] if isinstance(value, list) else []


def _contains_any(text: str, terms: list[str]) -> list[str]:
    lowered = text.lower()
    hits: list[str] = []
    for term in terms:
        if term and term.lower() in lowered:
            hits.append(term)
    return sorted(set(hits))


def _internal_identifier_hits(text: str) -> list[str]:
    allowed = {term.lower() for term in _policy_list("quality_gate.allowed_snake_case_terms")}
    hits = [
        match.group(0)
        for match in SNAKE_CASE_INTERNAL_RE.finditer(text)
        if match.group(0).lower() not in allowed
    ]
    return sorted(set(hits))


def evaluate_quality_gate(
    *,
    candidate: dict[str, Any],
    render_payload: dict[str, Any],
    voiceover_manifest: dict[str, Any],
    captions: list[dict[str, Any]],
) -> dict[str, Any]:
    raw_voiceover = str(voiceover_manifest.get("source_voiceover_text") or render_payload.get("voiceoverText") or "")
    normalized_present = bool(voiceover_manifest.get("normalized_voiceover_text"))
    voiceover = normalize_voiceover_text(
        str(
            voiceover_manifest.get("normalized_voiceover_text")
            or voiceover_manifest.get("voiceover_text")
            or render_payload.get("voiceoverText")
            or ""
        )
    )
    evidence_level = str(render_payload.get("evidenceLevel") or evidence_level_for_candidate(candidate))
    public_fields = [
        render_payload.get("displayTitle") or render_payload.get("title"),
        render_payload.get("summary"),
        render_payload.get("metricLine"),
        render_payload.get("audienceMetricLine"),
        render_payload.get("cta"),
        render_payload.get("footer"),
        render_payload.get("verificationNextStep"),
        render_payload.get("source"),
    ]
    for card in render_payload.get("cards") or []:
        public_fields.extend([card.get("label"), card.get("value"), card.get("detail")])
    public_fields.extend(storyboard_text_items(render_payload.get("storyboard")))
    public_fields.extend(agent_visual_text_items(render_payload.get("agentVisual") or render_payload.get("agent_visual")))
    public_text = " ".join(str(item or "") for item in public_fields)
    combined_text = f"{public_text} {voiceover}"

    internal_hits = sorted(
        set(_contains_any(public_text, _policy_list("quality_gate.internal_terms")) + _internal_identifier_hits(public_text))
    )
    hype_hits = _contains_any(combined_text, _policy_list("quality_gate.hype_phrases"))
    unverified_markers = _contains_any(combined_text, _policy_list("quality_gate.unverified_markers"))
    disclaimer_hits = _contains_any(voiceover, _policy_list("quality_gate.disclaimer_phrases"))
    ratio = chinese_ratio(voiceover)
    min_ratio = float(policy_get("quality_gate.min_voiceover_chinese_ratio", 0.22))
    max_disclaimer_hits = int(policy_get("quality_gate.max_voiceover_disclaimer_hits", 2))
    title_layout = plan_cover_title_lines(str(render_payload.get("displayTitle") or render_payload.get("title") or ""))

    max_caption_chars = int(policy_get("quality_gate.max_caption_chars", 36))
    caption_lengths = [len(str(segment.get("text") or "")) for segment in captions]
    captions_safe = bool(captions) and max(caption_lengths or [0]) <= max_caption_chars
    speech_safe = bool(voiceover) and not has_raw_speech_symbols(voiceover) and (
        normalized_present or not has_raw_speech_symbols(raw_voiceover)
    )
    mandarin_safe = ratio >= min_ratio
    internal_safe = not internal_hits
    unverified = "unverified" in evidence_level or evidence_level.startswith("operator_topic")
    evidence_tone_safe = not (unverified and hype_hits)
    unverified_boundary_present = bool(unverified_markers) if unverified else True
    disclaimer_safe = len(disclaimer_hits) <= max_disclaimer_hits

    checks = {
        "cover_text_safe": bool(title_layout["safe"]),
        "douyin_safe_area": True,
        "no_internal_terms": internal_safe,
        "no_hype_without_evidence": evidence_tone_safe,
        "speech_pronunciation_safe": speech_safe,
        "voiceover_mandarin_safe": mandarin_safe,
        "audio_visual_alignment_safe": captions_safe,
        "unverified_boundary_present": unverified_boundary_present,
        "disclaimer_density_safe": disclaimer_safe,
    }
    blocking_issues: list[str] = []
    if not checks["cover_text_safe"]:
        blocking_issues.append(f"cover title is likely unsafe: {title_layout}")
    if internal_hits:
        blocking_issues.append(f"public copy leaks internal terms: {', '.join(internal_hits)}")
    if not speech_safe:
        blocking_issues.append("voiceover contains raw slash, URL, or symbol pronunciation risk")
    if not mandarin_safe:
        blocking_issues.append(f"voiceover Chinese ratio {ratio:.2f} is below {min_ratio:.2f}")
    if not evidence_tone_safe:
        blocking_issues.append(f"unverified subject uses hype terms: {', '.join(hype_hits)}")
    if not unverified_boundary_present:
        blocking_issues.append("unverified subject does not say it is untested or observation-only")
    if not disclaimer_safe:
        blocking_issues.append(f"voiceover overuses disclaimer phrases: {', '.join(disclaimer_hits)}")
    if not captions_safe:
        blocking_issues.append("caption segments are missing or too long for the two-line safe-area style")

    warnings: list[str] = []
    warning = unverified_quality_warning(candidate)
    if warning:
        warnings.append(warning)
    if hype_hits and not unverified:
        warnings.append(f"hype terms require evidence review: {', '.join(hype_hits)}")

    return {
        "status": "pass" if not blocking_issues else "fail",
        "blocking_issues": blocking_issues,
        "warnings": warnings,
        "checks": checks,
        "metrics": {
            "voiceover_chinese_ratio": round(ratio, 3),
            "voiceover_disclaimer_hits": len(disclaimer_hits),
            "caption_max_chars": max(caption_lengths or [0]),
            "evidence_level": evidence_level,
            "cover_title_layout": title_layout,
        },
    }

from __future__ import annotations

import re
from typing import Any

from agent_harness.policy import policy_get, unsupported_claim_regex
from agent_harness.agent_visual import agent_visual_text_items
from agent_harness.evidence import strong_research_review_errors
from agent_harness.storyboard import storyboard_text_items

URL_RE = re.compile(r"https?://[^\s，。！？；;]+", re.I)


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _policy_list(path: str) -> list[str]:
    value = policy_get(path, [])
    return [str(item) for item in value] if isinstance(value, list) else []


def _hits(text: str, terms: list[str]) -> list[str]:
    lowered = text.lower()
    found: list[str] = []
    for term in terms:
        term_text = term.strip()
        if term_text and term_text.lower() in lowered:
            found.append(term_text)
    return sorted(set(found))


def _regex_hits(text: str, patterns: list[str]) -> list[str]:
    found: list[str] = []
    for pattern in patterns:
        try:
            if re.search(pattern, text, flags=re.I):
                found.append(pattern)
        except re.error:
            continue
    return sorted(set(found))


def _regex_hits_in_units(units: list[str], patterns: list[str]) -> list[str]:
    found: list[str] = []
    for unit in units:
        unit_text = _clean_text(unit)
        if unit_text:
            found.extend(_regex_hits(unit_text, patterns))
    return sorted(set(found))


def candidate_terms(candidate: dict[str, Any]) -> list[str]:
    raw_values = [
        str(candidate.get("title") or ""),
        str(candidate.get("entity_key") or ""),
        str(candidate.get("canonical_url") or "").rstrip("/").rsplit("/", 1)[-1],
    ]
    terms: list[str] = []
    for raw in raw_values:
        for part in re.split(r"[\s/_:.-]+", raw):
            cleaned = part.strip()
            if len(cleaned) >= 4 and cleaned.lower() not in {"github", "repo", "http", "https", "topic"}:
                terms.append(cleaned)
    unique: list[str] = []
    seen: set[str] = set()
    for term in terms:
        key = term.lower()
        if key not in seen:
            seen.add(key)
            unique.append(term)
    return unique[:8]


def _render_payload_text_units(render_payload: dict[str, Any] | None) -> list[str]:
    if not render_payload:
        return []
    fields = [
        render_payload.get("displayTitle") or render_payload.get("title"),
        render_payload.get("summary"),
        render_payload.get("metricLine"),
        render_payload.get("audienceMetricLine"),
        render_payload.get("cta"),
        render_payload.get("footer"),
        render_payload.get("verificationNextStep"),
        render_payload.get("source"),
        render_payload.get("voiceoverText"),
    ]
    for card in render_payload.get("cards") or []:
        if isinstance(card, dict):
            fields.extend([card.get("label"), card.get("value"), card.get("detail")])
    fields.extend(storyboard_text_items(render_payload.get("storyboard")))
    orientation = render_payload.get("orientation") or "vertical"
    fields.extend(agent_visual_text_items(render_payload.get("agentVisual") or render_payload.get("agent_visual"), orientation))
    return [_clean_text(field) for field in fields if _clean_text(field)]


def _render_payload_text(render_payload: dict[str, Any] | None) -> str:
    return _clean_text(" ".join(_render_payload_text_units(render_payload)))


def _candidate_review_text(candidate: dict[str, Any]) -> str:
    fields = [
        candidate.get("title"),
        candidate.get("summary"),
        candidate.get("canonical_url"),
        candidate.get("entity_key"),
        " ".join(str(item or "") for item in candidate.get("source_ids") or []),
    ]
    for item in candidate.get("evidence") or []:
        if isinstance(item, dict):
            fields.extend([item.get("source"), item.get("url"), item.get("claim_role")])
    return _clean_text(" ".join(str(field or "") for field in fields))


def evaluate_douyin_distribution_gate(
    *,
    candidate: dict[str, Any],
    douyin_copy: dict[str, Any],
    render_payload: dict[str, Any] | None = None,
    cross_check_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deterministic Douyin recommendation-eligibility review.

    This intentionally does not estimate private ranking weights. It only checks
    public-risk boundaries and metadata hygiene that the report can support.
    """
    title = _clean_text(douyin_copy.get("title"))
    desc = _clean_text(douyin_copy.get("desc"))
    tags = [str(tag).strip() for tag in douyin_copy.get("tags") or [] if str(tag).strip()]
    public_units = [title, desc, *tags, *_render_payload_text_units(render_payload)]
    public_text = _clean_text(" ".join(public_units))
    subject_text = _candidate_review_text(candidate)
    cross_check_status = str((cross_check_review or {}).get("status") or "missing")

    max_tags = int(policy_get("douyin_distribution.max_tags", 5))
    max_tag_len = int(policy_get("douyin_distribution.max_tag_len", 20))
    max_title_len = int(policy_get("douyin_distribution.max_title_len", 55))
    max_desc_len = int(policy_get("douyin_distribution.max_desc_len", 600))

    terms = candidate_terms(candidate)
    subject_referenced = not terms or any(term.lower() in public_text.lower() for term in terms)
    unsupported_hits = sorted(set(match.group(0) for match in unsupported_claim_regex().finditer(public_text)))
    folk_rule_hits = _regex_hits(public_text, _policy_list("douyin_distribution.private_threshold_patterns"))
    anti_spam_hits = _hits(public_text, _policy_list("douyin_distribution.distribution_risk_terms"))
    platform_abuse_hits = _regex_hits(subject_text, _policy_list("douyin_distribution.platform_abuse_subject_patterns"))
    external_redirect_hits = _regex_hits_in_units(
        public_units,
        _policy_list("douyin_distribution.external_redirect_patterns"),
    )
    public_url_hits = sorted(set(URL_RE.findall(public_text)))
    bait_hits = _hits(public_text, _policy_list("douyin_distribution.engagement_bait_phrases"))
    interaction_hits = _hits(public_text, _policy_list("douyin_distribution.constructive_interaction_markers"))
    retention_hits = _hits(public_text, _policy_list("douyin_distribution.retention_structure_markers"))

    tag_lengths_ok = all(len(tag) <= max_tag_len for tag in tags)
    tag_count_ok = 0 < len(tags) <= max_tags
    title_length_ok = 0 < len(title) <= max_title_len
    desc_length_ok = 0 < len(desc) <= max_desc_len
    duplicate_tags_ok = len({tag.casefold() for tag in tags}) == len(tags)
    metadata_clean = tag_count_ok and tag_lengths_ok and title_length_ok and desc_length_ok and duplicate_tags_ok

    blocking_issues: list[str] = []
    if not subject_referenced:
        blocking_issues.append(f"public copy does not reference selected subject terms: {terms}")
    if unsupported_hits:
        blocking_issues.append(f"unsupported claim terms: {', '.join(unsupported_hits)}")
    if folk_rule_hits:
        blocking_issues.append(
            "private Douyin threshold or folk-rule claims appear in public copy: " + ", ".join(folk_rule_hits)
        )
    if anti_spam_hits:
        blocking_issues.append("distribution-risk terms appear in public copy: " + ", ".join(anti_spam_hits))
    if platform_abuse_hits:
        blocking_issues.append(
            "selected subject looks like platform automation, account, or transaction-cheating tooling: "
            + ", ".join(platform_abuse_hits)
        )
    if external_redirect_hits:
        blocking_issues.append("public copy contains off-platform download/use guidance: " + ", ".join(external_redirect_hits))
    if public_url_hits:
        blocking_issues.append("public copy contains raw URL(s): " + ", ".join(public_url_hits[:3]))
    if bait_hits:
        blocking_issues.append("engagement-bait language appears in public copy: " + ", ".join(bait_hits))
    if not metadata_clean:
        blocking_issues.append(
            "Douyin metadata is not clean: "
            f"tag_count={len(tags)}/{max_tags}, title_len={len(title)}/{max_title_len}, "
            f"desc_len={len(desc)}/{max_desc_len}, duplicate_tags_ok={duplicate_tags_ok}"
        )
    if cross_check_status != "pass":
        blocking_issues.append(f"cross-check status is {cross_check_status}")
    strong_research_errors = strong_research_review_errors(cross_check_review)
    if strong_research_errors:
        blocking_issues.append("strong research review failed: " + "; ".join(strong_research_errors))

    warnings: list[str] = []
    if not interaction_hits:
        warnings.append("public copy has no constructive interaction prompt; this may underuse comment/save signals")
    if not retention_hits:
        warnings.append("public copy has no clear problem/mechanism/tradeoff marker for retention")

    return {
        "schema_version": 1,
        "status": "pass" if not blocking_issues else "fail",
        "summary": (
            "Douyin distribution review passed without policy-risk blockers."
            if not blocking_issues
            else "Douyin distribution review failed."
        ),
        "checks": {
            "subject_referenced": subject_referenced,
            "metadata_clean": metadata_clean,
            "tag_count_ok": tag_count_ok,
            "tag_lengths_ok": tag_lengths_ok,
            "title_length_ok": title_length_ok,
            "desc_length_ok": desc_length_ok,
            "duplicate_tags_ok": duplicate_tags_ok,
            "no_unsupported_claim_terms": not unsupported_hits,
            "no_private_threshold_claims": not folk_rule_hits,
            "no_distribution_risk_terms": not anti_spam_hits,
            "subject_not_platform_abuse": not platform_abuse_hits,
            "no_external_redirect_guidance": not external_redirect_hits,
            "no_raw_public_urls": not public_url_hits,
            "no_engagement_bait": not bait_hits,
            "constructive_interaction_present": bool(interaction_hits),
            "retention_structure_present": bool(retention_hits),
            "cross_check_status": cross_check_status,
        },
        "blocking_issues": blocking_issues,
        "warnings": warnings,
        "hits": {
            "unsupported_claim_terms": unsupported_hits,
            "private_threshold_patterns": folk_rule_hits,
            "distribution_risk_terms": anti_spam_hits,
            "platform_abuse_subject_patterns": platform_abuse_hits,
            "external_redirect_patterns": external_redirect_hits,
            "public_urls": public_url_hits,
            "engagement_bait_phrases": bait_hits,
            "constructive_interaction_markers": interaction_hits,
            "retention_structure_markers": retention_hits,
        },
        "metrics": {
            "candidate_terms": terms,
            "tag_count": len(tags),
            "max_tags": max_tags,
            "max_tag_len": max_tag_len,
            "title_len": len(title),
            "desc_len": len(desc),
        },
    }

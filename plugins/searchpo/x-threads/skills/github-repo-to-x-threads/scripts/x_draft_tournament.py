#!/usr/bin/env python3
"""Generate Agent-engineering angle-first X draft variants and select a rewrite."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from x_eval_post import XAI_CHAT_URL, strip_code_fence  # noqa: E402
from x_publish_thread import extract_ready_to_post, load_env  # noqa: E402
from brand_profile import BRAND_PROFILE, brand_contract_lines, classify_brand_input  # noqa: E402
from model_quality_chain import quality_chain_markdown, quality_chain_prompt_lines, quality_chain_schema  # noqa: E402


ANGLE_CONTRACT = [
    "The account positioning is Agent 工程实战派: Agent 工程如何从 demo 变成可靠系统.",
    "Every winning variant must map to agent reliability, build-in-public, paper-to-system, or embodied AI watch.",
    "Every winning variant must include one reusable asset and one concrete discussion question.",
    "If the current pack is a support/KYC rant, convert it into a cold bug report or an Agent reliability failure-mode lesson.",
    "If the current pack is life/media chatter, move it off-main-account unless it has a concrete Agent engineering mechanism.",
    "Do the angle tournament before writing variants: produce at least 3 materially different angles, not 3 phrasings of the same summary.",
    "Each angle must include a repeatable thesis, reader pain, concrete example, caveat, and claim-risk note.",
    "Strong angle shape: not just <repo category>, but <mechanism> that changes <workflow constraint>.",
    "Select one creator content mode before drafting: engineering_mentor, demo_first_tool, test_catalog, builder_resource_log, or product_translator_longform.",
    "Creator patterns are structure only. Do not imitate a specific creator's personal identity, catchphrases, emoji habits, or community nicknames.",
    "For demo_first_tool, include real tested steps or a clear not-tested boundary plus screenshot/video placement when real media is available.",
    "For test_catalog, separate official release, preview, leak, rumor, tested result, and inference.",
    "For builder_resource_log, include artifact, current status, next validation, and a community loop.",
    "For product_translator_longform, separate original-source facts, interpretation, product/workflow implication, trend prediction, and user vision.",
    "For paper-to-system, product_translator_longform, and rich repo+vision sources, prefer 8-12 substantive posts with 180-260 characters each. Use 4-6 posts only for thin sources or fast test_catalog updates.",
    "Do not make a complex source look publish-ready by slicing it into short checklist fragments; preserve the explanation arc when evidence supports it.",
    "The winning first post must be repeatable as a thesis. It cannot simply introduce the repo or say it is interesting.",
    "Forbidden first-post patterns: 最近看到, 值得认真看, 很有意思, quick thread, this repo is, 这个项目是, 这个库是.",
    "Use one coherent voice. Chinese is default; English is for repo names, paths, APIs, commands, or one deliberate hook line.",
    "Every variant needs one concrete example or path/command/API and one visible caveat/boundary.",
    "Do not put multi-line code in one tweet. Use a one-line pseudo snippet, a path, or split the example across posts.",
    "Put repo name and URL by post 2 or the final post unless the current pack intentionally has no URL.",
    "Expose the model quality chain status; missing stages are not publish-ready.",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_text_limit(path: Path, limit: int = 12000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[truncated]"


def load_pack(repo_run_dir: Path) -> dict[str, Any]:
    posting_pack = repo_run_dir / "posting_pack.md"
    if not posting_pack.exists():
        raise SystemExit(f"posting_pack.md not found: {posting_pack}")
    posting_text = posting_pack.read_text(encoding="utf-8", errors="replace")
    return {
        "posting_pack": posting_text,
        "current_posts": extract_ready_to_post(posting_text),
        "claims_ledger": read_json(repo_run_dir / "claims_ledger.json"),
        "cross_check_review": read_text_limit(repo_run_dir / "cross_check_review.md", 6000),
        "source_context": read_json(repo_run_dir / "source_context.json") or read_json(repo_run_dir / "repo_context.json"),
        "strategy_decision": load_strategy_decision(repo_run_dir),
        "images_manifest": read_json(repo_run_dir / "images_manifest.json"),
        "previous_eval": read_json(repo_run_dir / "post_eval.json"),
    }


def load_strategy_decision(repo_run_dir: Path) -> dict[str, Any]:
    for parent in [repo_run_dir, *repo_run_dir.parents]:
        path = parent / "strategy_decision.json"
        if path.exists():
            return read_json(path)
    return {}


def parse_json_content(content: str) -> dict[str, Any]:
    clean = strip_code_fence(content)
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", clean, flags=re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def run_grok(api_key: str, model: str, pack: dict[str, Any], prompt: str, variants: int, timeout: int) -> dict[str, Any]:
    source_context = pack.get("source_context") if isinstance(pack.get("source_context"), dict) else {}
    source_kind = str(source_context.get("source_kind") or "")
    source_kinds = {source_kind} if source_kind else set()
    brand_fit = classify_brand_input(prompt + "\n" + pack.get("posting_pack", ""), source_kinds)
    system = (
        "You are a senior technical X editor. Your job is to make posts less rigid and more worth reading. "
        "Use only the provided evidence. Do not invent benchmarks, authorship, code availability, results, or affiliations. "
        "Prioritize one sharp repeatable thesis over a complete summary, while protecting the user's Agent engineering brand. "
        "Return only valid JSON."
    )
    user = {
        "task": "Run an angle-first draft tournament for this governed X posting pack.",
        "user_feedback": prompt,
        "brand_profile": BRAND_PROFILE,
        "brand_fit": brand_fit,
        "brand_contract": brand_contract_lines(),
        "model_quality_chain": quality_chain_prompt_lines(),
        "angle_contract": ANGLE_CONTRACT,
        "rules": [
            "Keep claim safety and attribution boundaries.",
            "The main account promise is Agent 工程如何从 demo 变成可靠系统.",
            "Diagnose brand fit before rewriting: pillar, account fit, noise risk, reusable asset, discussion question.",
            "If account fit is weak, recommend off-main-account handling or rewrite around a concrete Agent reliability mechanism.",
            "Do not turn caveats into hype.",
            "Avoid generic openers like 'recently saw', 'worth reading', or 'interesting paper'.",
            "The winning draft should sound like a real technical reader found a non-obvious takeaway.",
            "A shorter sharper thread can beat a complete summary, but not when it erases the source's mechanism, examples, caveats, or product/workflow implication.",
            "Pick a creator pattern and make the hook, media plan, reusable asset, and discussion question match it.",
            "Reward practical next action: the reader can try, inspect, compare, save, or adapt something after reading.",
            "Prefer 8-12 posts for paper-to-system, product-translator, and rich technical explainers; use 4-6 only for thin sources or fast status updates.",
            "Each post should usually carry 180-260 characters when there is real substance. If several posts are under 150 characters, merge or expand them with mechanism, example, caveat, or resource value.",
            "Do not remove a caveat just to make the hook cleaner.",
            "If the pack is metadata-only, do not add source-code-internal claims unless they are stated in the README or metadata.",
            "Every post must fit X length. If an example is long, compress it to the exact mechanism or split it.",
            "Chinese output is preferred when the current pack is Chinese.",
        ],
        "variant_count": variants,
        "pack": pack,
        "output_schema": {
            "quality_diagnosis": ["string"],
            "brand_diagnosis": {
                "pillar": "string",
                "account_fit": "string",
                "noise_risk": "string",
                "reusable_asset_needed": "string",
                "discussion_question_needed": "string",
            },
            "model_quality_chain": quality_chain_schema(),
            "angle_candidates": [
                {
                    "id": "A",
                    "angle": "string",
                    "thesis": "one-sentence repeatable claim",
                    "reader_pain": "string",
                "concrete_example": "string",
                "brand_connection": "string",
                "creator_pattern": "engineering_mentor|demo_first_tool|test_catalog|builder_resource_log|product_translator_longform|other",
                "reusable_asset": "string",
                "discussion_question": "string",
                    "why_it_might_work": "string",
                    "risk": "string",
                    "hook": "string",
                    "caveat": "string",
                }
            ],
            "thread_variants": [
                {
                    "id": "v1",
                    "angle_id": "A",
                    "style": "string",
                    "creator_pattern": "engineering_mentor|demo_first_tool|test_catalog|builder_resource_log|product_translator_longform|other",
                    "posts": ["paste-ready post text, already numbered if thread"],
                    "why_better_than_current": "string",
                    "risks_or_claim_checks": ["string"],
                    "brand_fit": "string",
                    "reusable_asset": "string",
                    "discussion_question": "string",
                    "scorecard": {
                        "thesis_strength": "string",
                        "concrete_example": "string",
                        "caveat_visible": "string",
                        "creator_pattern_fit": "string",
                        "practical_next_action": "string",
                        "voice_consistency": "string",
                    },
                }
            ],
            "recommended_variant_id": "v1",
            "rewrite_rules": ["string"],
        },
    }
    payload = {
        "model": model,
        "temperature": 0.65,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
    }
    request = urllib.request.Request(
        XAI_CHAT_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Grok API HTTP {exc.code}: {detail}") from exc
    data = json.loads(raw)
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not content:
        raise RuntimeError(f"Grok API returned no content: {data}")
    parsed = parse_json_content(content)
    parsed["_raw_usage"] = data.get("usage", {})
    return parsed


def selected_variant(result: dict[str, Any]) -> dict[str, Any]:
    wanted = str(result.get("recommended_variant_id") or "")
    variants = result.get("thread_variants") if isinstance(result.get("thread_variants"), list) else []
    for variant in variants:
        if str(variant.get("id")) == wanted:
            return variant
    return variants[0] if variants else {}


def write_markdown(path: Path, result: dict[str, Any]) -> None:
    variant = selected_variant(result)
    lines = [
        "# Draft Tournament",
        "",
        f"- Created at: {result['created_at']}",
        f"- Grok model: `{result['grok_model']}`",
        f"- Recommended variant: `{result.get('recommended_variant_id', '')}`",
        "",
        "## Diagnosis",
        "",
    ]
    for item in result.get("quality_diagnosis", []):
        lines.append(f"- {item}")
    lines.extend(["", *quality_chain_markdown(result)])
    diagnosis = result.get("brand_diagnosis") if isinstance(result.get("brand_diagnosis"), dict) else {}
    if diagnosis:
        lines.extend(["", "## Brand Diagnosis", ""])
        for key in ("pillar", "account_fit", "noise_risk", "reusable_asset_needed", "discussion_question_needed"):
            lines.append(f"- {key}: {diagnosis.get(key, '')}")
    lines.extend(["", "## Angle Candidates", ""])
    for angle in result.get("angle_candidates", []):
        lines.append(f"### {angle.get('id', '')}: {angle.get('angle', '')}")
        lines.append("")
        thesis = angle.get("thesis")
        if thesis:
            lines.append(f"- Thesis: {thesis}")
        reader_pain = angle.get("reader_pain")
        if reader_pain:
            lines.append(f"- Reader pain: {reader_pain}")
        example = angle.get("concrete_example")
        if example:
            lines.append(f"- Concrete example: {example}")
        brand = angle.get("brand_connection")
        if brand:
            lines.append(f"- Brand connection: {brand}")
        creator_pattern = angle.get("creator_pattern")
        if creator_pattern:
            lines.append(f"- Creator pattern: {creator_pattern}")
        asset = angle.get("reusable_asset")
        if asset:
            lines.append(f"- Reusable asset: {asset}")
        question = angle.get("discussion_question")
        if question:
            lines.append(f"- Discussion question: {question}")
        lines.append(f"- Why it might work: {angle.get('why_it_might_work', '')}")
        lines.append(f"- Risk: {angle.get('risk', '')}")
        caveat = angle.get("caveat")
        if caveat:
            lines.append(f"- Caveat: {caveat}")
        lines.append(f"- Hook: {angle.get('hook', '')}")
        lines.append("")
    lines.extend(["## Recommended Draft", "", "```text"])
    for post in variant.get("posts", []):
        lines.append(str(post).strip())
        lines.append("")
    lines.extend(["```", "", "## Rewrite Rules", ""])
    for rule in result.get("rewrite_rules", []):
        lines.append(f"- {rule}")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def extract_section(markdown: str, heading: str) -> str:
    start = markdown.find(heading)
    if start < 0:
        return ""
    next_start = markdown.find("\n## ", start + len(heading))
    if next_start < 0:
        return markdown[start:].strip()
    return markdown[start:next_start].strip()


def length_label(post: str) -> str:
    length = len(post)
    if length < 150:
        return "Short"
    if length <= 260:
        return "OK"
    if length <= 280:
        return "Tight"
    return "Split"


def number_posts(posts: list[str]) -> list[str]:
    clean = [str(post).strip() for post in posts if str(post).strip()]
    total = len(clean)
    numbered: list[str] = []
    for index, post in enumerate(clean, start=1):
        post = re.sub(r"^\(\d+/\d+\)\s*", "", post)
        numbered.append(f"({index}/{total}) {post}")
    return numbered


def write_proposed_pack(path: Path, source_pack: str, variant: dict[str, Any]) -> None:
    posts = number_posts([str(post).strip() for post in variant.get("posts", []) if str(post).strip()])
    if not posts:
        return
    block = "```text\n" + "\n\n".join(posts) + "\n```"
    head = source_pack.split("## Ready To Post", 1)[0].rstrip()
    sections = [
        extract_section(source_pack, "## Posting Map"),
        extract_section(source_pack, "## Images"),
        extract_section(source_pack, "## Pre-Flight"),
        extract_section(source_pack, "## Do Not Say"),
    ]
    audit_lines = ["## Length Audit", ""]
    total = len(posts)
    for index, post in enumerate(posts, start=1):
        audit_lines.append(f"- {index}/{total}: {length_label(post)} ({len(post)} chars)")
    proposed_parts = [
        head,
        "## Ready To Post",
        "",
        block,
        "",
        "## Tournament Note",
        "",
        f"- Recommended variant: `{variant.get('id', '')}`",
        f"- Angle: `{variant.get('angle_id', '')}`",
        f"- Creator pattern: {variant.get('creator_pattern', '')}",
        f"- Why better: {variant.get('why_better_than_current', '')}",
        f"- Brand fit: {variant.get('brand_fit', '')}",
        f"- Reusable asset: {variant.get('reusable_asset', '')}",
        f"- Discussion question: {variant.get('discussion_question', '')}",
        "",
        "\n".join(audit_lines),
    ]
    proposed_parts.extend(section for section in sections if section)
    proposed = "\n\n".join(part.rstrip() for part in proposed_parts if part).rstrip() + "\n"
    path.write_text(proposed, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo_run_dir", help="Run source directory containing posting_pack.md")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--model", default="")
    parser.add_argument("--variants", type=int, default=3)
    parser.add_argument("--prompt", default="User feels the current skill is too rigid and the published quality is not good.")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--write-proposed-pack", action="store_true")
    args = parser.parse_args()

    repo_run_dir = Path(args.repo_run_dir).expanduser().resolve()
    env, _ = load_env([repo_run_dir / ".env", Path.cwd() / ".env", Path(args.env_file)])
    api_key = env.get("GROK_API_KEY") or env.get("XAI_API_KEY") or ""
    model = args.model or env.get("GROK_MODEL") or env.get("XAI_MODEL") or "grok-4.3"
    if not api_key:
        raise SystemExit("Missing GROK_API_KEY or XAI_API_KEY for draft tournament.")

    pack = load_pack(repo_run_dir)
    result = run_grok(api_key, model, pack, args.prompt, max(2, args.variants), args.timeout)
    result["schema_version"] = 1
    result["created_at"] = utc_now()
    result["repo_run_dir"] = str(repo_run_dir)
    result["grok_model"] = model
    result["user_feedback"] = args.prompt

    write_json(repo_run_dir / "draft_tournament.json", result)
    write_markdown(repo_run_dir / "draft_tournament.md", result)
    if args.write_proposed_pack:
        write_proposed_pack(repo_run_dir / "posting_pack.proposed.md", pack["posting_pack"], selected_variant(result))
        print(f"Wrote: {repo_run_dir / 'posting_pack.proposed.md'}")
    print(f"Wrote: {repo_run_dir / 'draft_tournament.json'}")
    print(f"Wrote: {repo_run_dir / 'draft_tournament.md'}")
    print(f"Recommended variant: {result.get('recommended_variant_id', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

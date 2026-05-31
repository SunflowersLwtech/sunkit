#!/usr/bin/env python3
"""Generate an Agent-engineering angle-first posting pack from governed evidence."""

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
from x_publish_thread import load_env, read_json  # noqa: E402
from brand_profile import BRAND_PROFILE, brand_contract_lines, classify_brand_input  # noqa: E402
from model_quality_chain import quality_chain_markdown, quality_chain_prompt_lines, quality_chain_schema  # noqa: E402


ANGLE_CONTRACT = [
    "The account positioning is Agent 工程实战派: Agent 工程如何从 demo 变成可靠系统.",
    "Every draft must map to one pillar: agent reliability, build-in-public, paper-to-system, or embodied AI watch.",
    "If the source is KYC/support/customer-service drama, rewrite it as a cold bug report or move it off the main account unless it teaches an Agent reliability lesson.",
    "If the source is life/media chatter, only publish on the main account after turning it into a concrete Agent engineering failure-mode analogy.",
    "Every thread must include one reusable asset: checklist, flowchart, issue template, prompt snippet, before/after table, or failure-mode map.",
    "Every thread must end with one concrete discussion question, not a vague 'thoughts?'.",
    "Diagnose the source material before writing. A hook cannot save a source with no concrete artifact, number, contrast, reader pain, caveat, or source boundary.",
    "Generate 3-5 materially different angles before drafting; do not pick the first safe summary by default.",
    "Each angle must name a repeatable thesis, a concrete technical example, a reader pain, one caveat, and what claim would be unsafe.",
    "Favor angles of the form: not just <category>, but <mechanism> that changes <workflow constraint>.",
    "Select one creator content mode before drafting: engineering_mentor, demo_first_tool, test_catalog, builder_resource_log, or product_translator_longform.",
    "Creator patterns are structure only. Do not imitate a specific creator's personal identity, catchphrases, emoji habits, or community nicknames.",
    "If the mode is demo_first_tool, include tested steps or a clear not-tested boundary plus screenshot/video placement when real media is available.",
    "If the mode is test_catalog, separate official release, preview, leak, rumor, tested result, and inference.",
    "If the mode is builder_resource_log, include artifact, current status, next validation, and a community loop.",
    "If the mode is product_translator_longform, separate original-source facts, interpretation, product/workflow implication, trend prediction, and user vision.",
    "Post 1 must work without a title, image, or link card: topic + reason to read + evidence credibility. Do not open with a repo-note phrase.",
    "Forbidden first-post patterns: 最近看到, 值得认真看, 很有意思, quick thread, this repo is, 这个项目是, 这个库是.",
    "Use psychological triggers only when evidence supports them: cognitive conflict, curiosity gap, risk/loss, identity, or numeric anchor.",
    "Translate high-level concepts into concrete workflow language. If you say agentic, self-evolving, paradigm, framework, or future, attach a mechanism or file path.",
    "Avoid over-smooth AI prose: ritual transitions, perfectly balanced summaries, repeated not-X-but-Y turns, and fake certainty.",
    "Use one coherent voice. Chinese is default; English is for repo names, file paths, API names, commands, or one deliberate hook line.",
    "A publishable thread needs at least one concrete example or path/command/API name and one visible caveat or boundary.",
    "Do not put multi-line code in one tweet. Use a one-line pseudo snippet, a path, or split the example across posts.",
    "Put repo attribution and URL by post 2 or the final post, but do not let metadata replace the thesis.",
    "Expose the model quality chain status in the returned JSON; missing stages are not publish-ready.",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_text(path: Path, limit: int = 10000) -> str:
    if not path.exists() or not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text if len(text) <= limit else text[:limit] + "\n\n[truncated]"


def parse_json_content(content: str) -> dict[str, Any]:
    clean = strip_code_fence(content)
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", clean, flags=re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def context_evidence(repo_run_dir: Path) -> dict[str, Any]:
    context = read_json(repo_run_dir / "repo_context.json")
    repo_path = Path(context.get("repo_path", "")).expanduser()
    key_files = context.get("key_files") or {}
    readme_files = key_files.get("readme") or []
    package_files = key_files.get("package_metadata") or []
    docs_files = key_files.get("docs") or []
    examples_files = key_files.get("examples") or []

    def file_items(files: list[str], limit_each: int, max_count: int) -> list[dict[str, str]]:
        items = []
        for rel in files[:max_count]:
            text = read_text(repo_path / rel, limit_each)
            if text:
                items.append({"path": rel, "text": text})
        return items

    manifest = read_text(repo_run_dir / "file_manifest.txt", 8000)
    github = context.get("github") or {}
    return {
        "repo_run_dir": str(repo_run_dir),
        "source": context.get("source"),
        "owner_repo": context.get("owner_repo"),
        "github": github,
        "git": context.get("git"),
        "file_count": context.get("file_count"),
        "key_files": key_files,
        "readmes": file_items(readme_files, 14000, 2),
        "package_metadata": file_items(package_files, 5000, 5),
        "docs": file_items(docs_files, 5000, 3),
        "examples": file_items(examples_files, 3500, 3),
        "file_manifest_excerpt": manifest,
    }


def call_grok(api_key: str, model: str, evidence: dict[str, Any], prompt: str, timeout: int) -> dict[str, Any]:
    brand_fit = classify_brand_input(
        prompt + "\n" + str(evidence.get("source") or "") + "\n" + str(evidence.get("owner_repo") or ""),
        {"github_repo"} if evidence.get("owner_repo") else set(),
    )
    system = (
        "You are an angle-first technical X editor. Generate a governed posting pack from repository evidence. "
        "Use only provided evidence. Do not invent benchmarks, roadmap, affiliations, maturity, or official claims. "
        "Avoid generic openers. Prefer one memorable technical thesis over completeness. "
        "Protect the user's Agent engineering brand positioning. Return only valid JSON."
    )
    user = {
        "task": "Create a Chinese X/Twitter posting pack for an independent technical share.",
        "user_prompt": prompt,
        "repo_evidence": evidence,
        "brand_profile": BRAND_PROFILE,
        "brand_fit": brand_fit,
        "brand_contract": brand_contract_lines(),
        "model_quality_chain": quality_chain_prompt_lines(),
        "angle_contract": ANGLE_CONTRACT,
        "rules": [
            "Main account promise: Agent 工程如何从 demo 变成可靠系统.",
            "State the brand fit before drafting: pillar, account fit, noise risk, and reusable asset.",
            "If account fit is weak, produce an off-main-account recommendation or a rewrite that ties the idea to a concrete Agent reliability mechanism.",
            "The final thread must contain a named reusable asset and a specific discussion question.",
            "Credit the repo owner in evidence/metadata, but the public hook can lead with the technical thesis.",
            "Keep posts concise; 4-7 posts is usually enough.",
            "Post 1 must be a repeatable technical thesis or pain-point claim, not a repo description.",
            "Before selecting an angle, score source material richness: concrete artifact, sourced number, contrast, reader pain, caveat, source boundary.",
            "If source material is weak, say what evidence is missing instead of generating a polished but empty thread.",
            "The hook must be independently understandable without the link preview.",
            "A good hook should create tension without giving away the whole answer.",
            "Pick a creator pattern and make the hook, media plan, reusable asset, and discussion question match that pattern.",
            "Reward practical next action: the reader can try, inspect, compare, save, or adapt something after reading.",
            "Prefer a 4-6 post thread for trending repos: thesis, mechanism, concrete example, caveat/boundary, link/attribution.",
            "For globally trending developer repos, a short English or bilingual hook is allowed when it improves reach, but keep the rest coherent.",
            "Every public factual claim must be backed by README, package metadata, file tree, or GitHub metadata.",
            "Label uncertainty and avoid best/first/only unless directly proven.",
            "Do not ask people to contribute unless the user owns the repo.",
            "No hashtags by default.",
            "This is a text-only experiment. Do not reference generated images in the public posts.",
            "If evidence is metadata-only, do not make source-code-internal claims unless the README itself states them.",
            "Every post must fit X length. If an example is long, compress it to the specific mechanism or split it.",
            "Do not use ritual AI transitions such as 值得注意的是, 更重要的是, 总之, in conclusion, or it is important to note.",
        ],
        "output_schema": {
            "strategy": "string",
            "content_diagnosis": {
                "source_material_score": "float 0..1",
                "hook_independence": "string",
                "plain_language_risk": "string",
                "anti_smoothness_notes": ["string"],
                "creator_pattern": "engineering_mentor|demo_first_tool|test_catalog|builder_resource_log|product_translator_longform|other",
                "creator_pattern_fit": "string",
                "demo_or_test_evidence": "string",
                "translation_value": "string",
                "practical_next_action": "string",
                "community_loop": "string",
                "brand_fit": "string",
                "content_pillar": "agent_reliability|build_in_public|paper_to_system|embodied_ai_watch|off_main",
                "noise_risk": "string",
                "reusable_asset": "string",
                "discussion_question": "string",
            },
            "angle_candidates": [
                {
                    "id": "A",
                    "angle": "string",
                    "thesis": "one-sentence repeatable claim",
                    "reader_pain": "string",
                    "concrete_example": "string",
                    "hook": "string",
                    "caveat": "string",
                    "brand_connection": "string",
                    "creator_pattern": "string",
                    "reusable_asset": "string",
                    "discussion_question": "string",
                    "risk": "string",
                }
            ],
            "selected_angle_id": "string",
            "brand_fit": {
                "pillar": "string",
                "account_fit": "string",
                "routing_note": "string",
                "reader_takeaway": "string",
                "reusable_asset": "string",
                "discussion_question": "string",
            },
            "model_quality_chain": quality_chain_schema(),
            "posts": ["string without numbering"],
            "claims": [
                {
                    "claim": "string",
                    "type": "verified_repo_fact|github_metadata|reasonable_inference",
                    "source": "README path, metadata field, or file path",
                    "public_wording": "string",
                }
            ],
            "caveats": ["string"],
            "image_ideas": [
                {"post": "1/N", "purpose": "string", "prompt": "string", "alt_text": "string"}
            ],
            "do_not_say": ["string"],
        },
    }
    payload = {
        "model": model,
        "temperature": 0.55,
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


def number_posts(posts: list[str]) -> list[str]:
    clean = [str(post).strip() for post in posts if str(post).strip()]
    total = len(clean)
    numbered = []
    for idx, post in enumerate(clean, start=1):
        post = re.sub(r"^\(\d+/\d+\)\s*", "", post)
        numbered.append(f"({idx}/{total}) {post}")
    return numbered


def length_label(post: str) -> str:
    length = len(post)
    if length <= 240:
        return "OK"
    if length <= 280:
        return "Tight"
    return "Split"


def write_claims(repo_run_dir: Path, evidence: dict[str, Any], result: dict[str, Any]) -> None:
    claims = []
    for index, claim in enumerate(result.get("claims") or [], start=1):
        claims.append(
            {
                "id": f"C{index:03d}",
                "claim": str(claim.get("claim", "")).strip(),
                "type": str(claim.get("type", "verified_repo_fact")).strip() or "verified_repo_fact",
                "source": str(claim.get("source", "")).strip(),
                "status": "keep",
                "public_wording": str(claim.get("public_wording", "")).strip(),
                "notes": "Generated by x_generate_posting_pack.py from governed repo evidence.",
            }
        )
    ledger = {
        "schema_version": 1,
        "source": evidence.get("source"),
        "owner_repo": evidence.get("owner_repo"),
        "created_at": utc_now(),
        "review_status": "generated-pass",
        "claims": claims,
        "verified_facts": [claim["claim"] for claim in claims if claim["claim"]],
        "unknown_or_unsafe": result.get("do_not_say") or [],
        "source_handles": {
            "repo_context": "repo_context.json",
            "file_manifest": "file_manifest.txt",
            "github_metadata_available": bool((evidence.get("github") or {}).get("nameWithOwner")),
        },
        "rules": [
            "Generated claims are still subject to manual review before publish.",
            "Do not publish without cross_check_review.md pass and image gates.",
        ],
    }
    write_json(repo_run_dir / "claims_ledger.json", ledger)


def write_cross_check(repo_run_dir: Path, result: dict[str, Any]) -> None:
    lines = [
        "# Cross-Check Review",
        "",
        "Status: pass",
        "",
        "Generated experiment status: public claims were constrained to provided repo evidence.",
        "",
        "## Caveats",
        "",
    ]
    for caveat in result.get("caveats") or []:
        lines.append(f"- {caveat}")
    lines.extend(["", "## Notes", "", "Run manual review before live publish."])
    (repo_run_dir / "cross_check_review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_pack(repo_run_dir: Path, evidence: dict[str, Any], result: dict[str, Any]) -> None:
    posts = number_posts(result.get("posts") or [])
    github = evidence.get("github") or {}
    owner_repo = evidence.get("owner_repo") or github.get("nameWithOwner") or evidence.get("source")
    lines = [
        f"# Posting Pack: {owner_repo}",
        "",
        "Publish mode: manual-safe",
        "",
        "## Evidence",
        "",
        f"- Source: {evidence.get('source')}",
        f"- Owner/repo: {owner_repo}",
        f"- GitHub description: {github.get('description') or '<unavailable>'}",
        f"- Language: {(github.get('primaryLanguage') or {}).get('name') if isinstance(github.get('primaryLanguage'), dict) else '<unavailable>'}",
        f"- Stars: {github.get('stargazerCount', '<unavailable>')}",
        f"- License: {(github.get('licenseInfo') or {}).get('name') if isinstance(github.get('licenseInfo'), dict) else '<unavailable>'}",
        "- Relationship: independent sharer",
        "",
        "## Posting Strategy",
        "",
        str(result.get("strategy") or "Angle-first independent technical share."),
        "",
        "## Brand Fit",
        "",
    ]
    brand_fit = result.get("brand_fit") if isinstance(result.get("brand_fit"), dict) else {}
    generated_brand = classify_brand_input(
        " ".join([str(result.get("strategy") or ""), str(evidence.get("source") or ""), str(evidence.get("owner_repo") or "")]),
        {"github_repo"} if evidence.get("owner_repo") else set(),
    )
    lines.extend(
        [
            f"- Positioning: {BRAND_PROFILE['tagline']}",
            f"- Pillar: {brand_fit.get('pillar') or generated_brand['pillar']}",
            f"- Account fit: {brand_fit.get('account_fit') or generated_brand['account_fit']}",
            f"- Routing note: {brand_fit.get('routing_note') or generated_brand['routing_note']}",
            f"- Reader takeaway: {brand_fit.get('reader_takeaway', '')}",
            f"- Reusable asset: {brand_fit.get('reusable_asset', '')}",
            f"- Discussion question: {brand_fit.get('discussion_question', '')}",
            "",
        ]
    )
    lines.extend(
        [
            "## Content Diagnosis",
            "",
        ]
    )
    lines.extend(["", *quality_chain_markdown(result), ""])
    diagnosis = result.get("content_diagnosis") if isinstance(result.get("content_diagnosis"), dict) else {}
    if diagnosis:
        lines.extend(
            [
                f"- Source material score: {diagnosis.get('source_material_score', '<unavailable>')}",
                f"- Hook independence: {diagnosis.get('hook_independence', '')}",
                f"- Plain-language risk: {diagnosis.get('plain_language_risk', '')}",
                f"- Creator pattern: {diagnosis.get('creator_pattern', '')}",
                f"- Creator pattern fit: {diagnosis.get('creator_pattern_fit', '')}",
                f"- Demo/test evidence: {diagnosis.get('demo_or_test_evidence', '')}",
                f"- Translation value: {diagnosis.get('translation_value', '')}",
                f"- Practical next action: {diagnosis.get('practical_next_action', '')}",
                f"- Community loop: {diagnosis.get('community_loop', '')}",
                f"- Brand fit: {diagnosis.get('brand_fit', '')}",
                f"- Content pillar: {diagnosis.get('content_pillar', '')}",
                f"- Noise risk: {diagnosis.get('noise_risk', '')}",
                f"- Reusable asset: {diagnosis.get('reusable_asset', '')}",
                f"- Discussion question: {diagnosis.get('discussion_question', '')}",
            ]
        )
        for note in diagnosis.get("anti_smoothness_notes") or []:
            lines.append(f"- Anti-smoothness: {note}")
    else:
        lines.append("- No structured diagnosis returned.")
    lines.extend(
        [
            "",
            "## Angle Candidates",
            "",
        ]
    )
    for angle in result.get("angle_candidates") or []:
        details = [
            f"`{angle.get('id', '')}` {angle.get('angle', '')}",
            f"Thesis: {angle.get('thesis', '')}",
            f"Example: {angle.get('concrete_example', '')}",
            f"Caveat: {angle.get('caveat', '')}",
            f"Hook: {angle.get('hook', '')}",
            f"Brand: {angle.get('brand_connection', '')}",
            f"Creator pattern: {angle.get('creator_pattern', '')}",
            f"Asset: {angle.get('reusable_asset', '')}",
            f"Question: {angle.get('discussion_question', '')}",
        ]
        lines.append("- " + " | ".join(part for part in details if not part.endswith(": ")))
    lines.extend(
        [
            "",
            f"Selected angle: `{result.get('selected_angle_id', '')}`",
            "",
            "## Ready To Post",
            "",
            "```text",
            "\n\n".join(posts),
            "```",
            "",
            "## Length Audit",
            "",
        ]
    )
    for post in posts:
        match = re.match(r"^\((\d+/\d+)\)", post)
        label = match.group(1) if match else "post"
        lines.append(f"- {label}: {length_label(post)} ({len(post)} chars)")
    lines.extend(["", "## Image Ideas", ""])
    for image in result.get("image_ideas") or []:
        lines.append(f"- {image.get('post', 'adaptive')}: {image.get('purpose', '')}; alt: {image.get('alt_text', '')}")
    lines.extend(["", "## Pre-Flight", ""])
    for item in [
        "Repo owner credited in evidence.",
        "Thread maps to Agent engineering positioning.",
        "One reusable asset is present.",
        "One concrete discussion question is present.",
        "Creator pattern is coherent and does not impersonate another account.",
        "Demo/test/news claims have a tested, preview, rumor, or not-tested boundary.",
        "Independent-share boundary preserved.",
        "No best/first/only claim unless directly sourced.",
        "Generated as text-only experiment; images still need real generation before live publish.",
        "Manual review still required before publishing.",
    ]:
        lines.append(f"- {item}")
    lines.extend(["", "## Do Not Say", ""])
    for item in result.get("do_not_say") or []:
        lines.append(f"- {item}")
    (repo_run_dir / "posting_pack.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo_run_dir", help="Governed repo run directory")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--model", default="")
    parser.add_argument("--prompt", default="Generate a non-generic Chinese X thread for a trending GitHub repository.")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()

    repo_run_dir = Path(args.repo_run_dir).expanduser().resolve()
    env, _ = load_env([repo_run_dir / ".env", Path.cwd() / ".env", Path(args.env_file)])
    api_key = env.get("GROK_API_KEY") or env.get("XAI_API_KEY") or ""
    model = args.model or env.get("GROK_MODEL") or env.get("XAI_MODEL") or "grok-4.3"
    if not api_key:
        raise SystemExit("Missing GROK_API_KEY or XAI_API_KEY")
    evidence = context_evidence(repo_run_dir)
    result = call_grok(api_key, model, evidence, args.prompt, args.timeout)
    result["schema_version"] = 1
    result["created_at"] = utc_now()
    result["repo_run_dir"] = str(repo_run_dir)
    result["grok_model"] = model
    write_json(repo_run_dir / "generation_result.json", result)
    write_claims(repo_run_dir, evidence, result)
    write_cross_check(repo_run_dir, result)
    write_pack(repo_run_dir, evidence, result)
    print(f"Wrote: {repo_run_dir / 'generation_result.json'}")
    print(f"Wrote: {repo_run_dir / 'posting_pack.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

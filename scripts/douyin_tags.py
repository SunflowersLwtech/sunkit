#!/usr/bin/env python3
"""Normalize Douyin hashtags (#话题) to the platform's practical constraints.

Douyin treats a hashtag topic as ``#text`` terminated by whitespace or the next
``#``. That means a topic may not contain spaces or most punctuation, only a
limited number of topics are effective, and over-long topics get truncated by
the client. The previous pipeline passed raw DeepSeek/​fallback tags straight to
the uploader, so ``"AI 工具"`` silently became the topic ``#AI`` plus the literal
text ``工具``, and there was no cap on how many ``#`` topics were emitted.

This module is the single source of truth for that normalization. It is imported
by ``agent_harness/stages.py`` when the Douyin package is built, and also exposes
a small CLI so a run's ``douyin_upload_manifest.json`` can be re-normalized or a
tag list inspected in isolation.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

# Conservative, widely-cited Douyin limits. Each is overridable via env / args so
# we can tighten or relax without touching call sites.
DEFAULT_MAX_TAGS = 5
DEFAULT_MAX_TAG_LEN = 20
DEFAULT_MAX_CAPTION_LEN = 1000

# Characters that terminate or are invalid inside a Douyin hashtag topic. We keep
# CJK ideographs, latin letters and digits; everything else inside a tag is
# dropped so a single topic stays a single topic.
_TAG_INVALID_RE = re.compile(
    r"[^0-9A-Za-z一-鿿぀-ヿ가-힣]+"
)


def _env_int(name: str, default: int) -> int:
    import os

    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def normalize_tag(tag: Any, max_tag_len: int = DEFAULT_MAX_TAG_LEN) -> str:
    """Reduce one raw tag to a valid single Douyin topic body (no leading #)."""
    text = str(tag or "").strip()
    # Strip any leading hashes the model may have included, then remove every
    # character that would break or terminate the topic.
    text = text.lstrip("#＃").strip()
    text = _TAG_INVALID_RE.sub("", text)
    if max_tag_len > 0:
        text = text[:max_tag_len]
    return text


def normalize_tags(
    tags: Iterable[Any],
    max_tags: int = DEFAULT_MAX_TAGS,
    max_tag_len: int = DEFAULT_MAX_TAG_LEN,
) -> list[str]:
    """Clean, de-duplicate (case-insensitive) and cap a list of raw tags."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in tags or []:
        tag = normalize_tag(raw, max_tag_len=max_tag_len)
        if not tag:
            continue
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(tag)
        if len(out) >= max_tags:
            break
    return out


# A ``#topic`` token embedded in free text, terminated by whitespace or the next #.
_INLINE_HASHTAG_RE = re.compile(r"[#＃]([0-9A-Za-z一-鿿぀-ヿ가-힣]+)")


def extract_inline_hashtags(text: str) -> tuple[list[str], str]:
    """Pull ``#topic`` tokens out of a description so they can be re-capped.

    Returns ``(hashtags, cleaned_text)``. This matters because the limit is on
    the *total* number of hashtags, no matter whether they came from the tags
    list or were written inline by the model.
    """
    if not text:
        return [], ""
    found = [m.group(1) for m in _INLINE_HASHTAG_RE.finditer(text)]
    cleaned = _INLINE_HASHTAG_RE.sub("", text)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return found, cleaned


def hashtag_string(tags: Iterable[str]) -> str:
    """Render normalized tags as a space-separated ``#topic`` string."""
    return " ".join(f"#{tag}" for tag in tags if tag)


def compose_caption(
    desc: str,
    tags: Iterable[str],
    max_caption_len: int = DEFAULT_MAX_CAPTION_LEN,
) -> str:
    """Append the ``#topic`` block to a description, bounded to the caption cap.

    If appending every tag would overflow ``max_caption_len`` the tag block is
    dropped first (a complete description matters more than trailing topics).
    """
    base = (desc or "").strip()
    block = hashtag_string(tags)
    if not block:
        return base[:max_caption_len]
    candidate = f"{base}\n\n{block}" if base else block
    if len(candidate) <= max_caption_len:
        return candidate
    # Try to keep the description and as many leading tags as fit.
    tag_list = [t for t in tags if t]
    while tag_list:
        tag_list.pop()
        block = hashtag_string(tag_list)
        candidate = f"{base}\n\n{block}" if (base and block) else (base or block)
        if len(candidate) <= max_caption_len:
            return candidate
    return base[:max_caption_len]


def build_tag_bundle(
    raw_tags: Iterable[Any],
    desc: str = "",
    max_tags: int | None = None,
    max_tag_len: int | None = None,
    max_caption_len: int | None = None,
) -> dict[str, Any]:
    """Return a structured normalization result used by the harness + CLI."""
    max_tags = _env_int("SEARCHPO_DOUYIN_MAX_TAGS", DEFAULT_MAX_TAGS) if max_tags is None else max_tags
    max_tag_len = _env_int("SEARCHPO_DOUYIN_MAX_TAG_LEN", DEFAULT_MAX_TAG_LEN) if max_tag_len is None else max_tag_len
    max_caption_len = (
        _env_int("SEARCHPO_DOUYIN_MAX_CAPTION_LEN", DEFAULT_MAX_CAPTION_LEN)
        if max_caption_len is None
        else max_caption_len
    )
    raw_list = [str(t) for t in (raw_tags or [])]
    tags = normalize_tags(raw_list, max_tags=max_tags, max_tag_len=max_tag_len)
    dropped = max(0, len([t for t in raw_list if str(t).strip()]) - len(tags))
    return {
        "tags": tags,
        "tags_raw": raw_list,
        "hashtag_string": hashtag_string(tags),
        "caption": compose_caption(desc, tags, max_caption_len=max_caption_len),
        "max_tags": max_tags,
        "max_tag_len": max_tag_len,
        "max_caption_len": max_caption_len,
        "dropped_tag_count": dropped,
    }


def _rewrite_manifest(run_dir: Path) -> dict[str, Any]:
    manifest_path = run_dir / "post" / "douyin_upload_manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"douyin_upload_manifest.json missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    bundle = build_tag_bundle(manifest.get("tags") or [], desc=manifest.get("desc") or "")
    manifest["tags"] = bundle["tags"]
    manifest["tags_raw"] = bundle["tags_raw"]
    manifest["hashtag_string"] = bundle["hashtag_string"]
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tags_csv = ",".join(bundle["tags"])
    (run_dir / "post" / "douyin_tags.txt").write_text(tags_csv + "\n", encoding="utf-8")
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", nargs="?", help="Re-normalize this run's douyin manifest in place.")
    parser.add_argument("--tags", help="Comma-separated raw tags to normalize and print (no run_dir needed).")
    parser.add_argument("--desc", default="", help="Optional description for caption composition with --tags.")
    args = parser.parse_args()

    if args.tags is not None:
        bundle = build_tag_bundle(args.tags.split(","), desc=args.desc)
        print(json.dumps(bundle, ensure_ascii=False, indent=2))
        return 0
    if not args.run_dir:
        parser.error("provide a run_dir or --tags")
    bundle = _rewrite_manifest(Path(args.run_dir).resolve())
    print(json.dumps({"tags": bundle["tags"], "dropped_tag_count": bundle["dropped_tag_count"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

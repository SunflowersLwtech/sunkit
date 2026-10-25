"""Parse short Chinese/English switch commands, e.g. "关视频" "视频和声音关掉" "隐私模式" "AI 开".

Shared by the voice path (after a wake word) and the text API (/api/command, e.g. from a
chat bot), so both understand exactly the same sentences.
"""
from __future__ import annotations

import re

TARGET_WORDS = {
    "video": ["摄像头", "视频", "画面", "镜头", "相机", "video", "camera"],
    "audio": ["麦克风", "声音", "音频", "录音", "语音", "话筒", "audio", "mic"],
    "ai": ["人工智能", "助手", "模型", "ai"],
    "all": ["全部", "所有", "一切", "三个", "都给我", "all"],
}
OFF_WORDS = ["关闭", "关掉", "关上", "断开", "断掉", "停止", "停掉", "暂停", "关", "停", "off"]
ON_WORDS = ["打开", "开启", "启动", "恢复", "开", "on"]
STATUS_WORDS = ["状态", "status", "现在怎样", "开着吗"]
PRIVACY_ON = ["隐私模式", "私密模式", "别看了", "别听了"]
PRIVACY_OFF = ["退出隐私模式", "结束隐私模式", "关闭隐私模式"]

_PUNCT = re.compile(r"[\s,，。.!！?？、;；:：\"'“”‘’（）()\[\]【】~～-]+")


def normalize(text: str) -> str:
    """Drop punctuation; keep one space only between latin words ("ai off")."""
    s = _PUNCT.sub(" ", text or "").strip().lower()
    return re.sub(r" (?=[^\x00-\x7f])|(?<=[^\x00-\x7f]) ", "", re.sub(r"\s+", " ", s))


def strip_wake(text: str, wake_words, fuzzy_suffix: str | None = None) -> str | None:
    """Return the text after the first wake word, or None if there is none.

    fuzzy_suffix (e.g. "助手"): also accept 1-3 misheard characters plus the suffix at the very start,
    because speech recognition turns 房间助手 into something like 放检助手 now and then (measured)."""
    n = normalize(text)
    for w in wake_words:
        w = normalize(w)
        i = n.find(w)
        if i >= 0:
            return n[i + len(w):]
    if fuzzy_suffix:
        m = re.match(r"^.{1,3}?" + re.escape(fuzzy_suffix), n)
        if m:
            return n[m.end():]
    return None


def _tokens(n: str):
    vocab = []
    for key, words in TARGET_WORDS.items():
        vocab += [(w, ("target", key)) for w in words]
    vocab += [(w, ("action", False)) for w in OFF_WORDS]
    vocab += [(w, ("action", True)) for w in ON_WORDS]
    vocab.sort(key=lambda x: -len(x[0]))  # longest match first
    out = []
    i = 0
    while i < len(n):
        for w, tok in vocab:
            if n.startswith(w, i):
                # "ai"/"on"/"off" must not be part of a longer latin word
                if w.isascii() and ((i > 0 and n[i - 1].isascii() and n[i - 1].isalpha()) or
                                    (i + len(w) < len(n) and n[i + len(w)].isascii() and n[i + len(w)].isalpha())):
                    continue
                out.append(tok)
                i += len(w)
                break
        else:
            i += 1
    return out


def parse(text: str) -> dict:
    """Returns {"changes": {key: bool}} or {"status": True} or {"error": "..."}."""
    # "房间助手关视频" / "房间AI 关视频": the name is not a target
    n = re.sub(r"^(房间助手|房间ai|房间)", "", normalize(text))
    if not n:
        return {"error": "空命令"}
    if any(w in n for w in PRIVACY_OFF):
        return {"error": "退出隐私模式要说清楚开哪个，例如「开视频」「开声音」「开AI」"}
    if any(w in n for w in PRIVACY_ON):
        return {"changes": {"video": False, "audio": False, "ai": False}}
    if n in ("全关", "全部关", "都关"):
        return {"changes": {"video": False, "audio": False, "ai": False}}
    if n in ("全开", "全部开", "都开"):
        return {"changes": {"video": True, "audio": True, "ai": True}}
    toks = _tokens(n)
    if not any(t[0] == "action" for t in toks):
        if any(w in n for w in STATUS_WORDS):
            return {"status": True}
        return {"error": "没听懂要开还是关"}
    targets = [t for t in toks if t[0] == "target"]
    if not targets:
        return {"error": "没说是视频、声音还是AI"}
    changes: dict = {}
    postfix = toks[0][0] == "target"  # "视频关掉" vs "关掉视频"
    pending = []
    current = None
    for kind, val in toks:
        if kind == "target":
            if postfix:
                pending.append(val)
            elif current is not None:
                _assign(changes, val, current)
            else:
                pending.append(val)
        else:
            if postfix:
                for p in pending:
                    _assign(changes, p, val)
                pending = []
            current = val
    if pending:
        if current is None:
            return {"error": "没听懂要开还是关"}
        for p in pending:
            _assign(changes, p, current)
    return {"changes": changes}


def _assign(changes: dict, target: str, value: bool):
    keys = ("video", "audio", "ai") if target == "all" else (target,)
    for k in keys:
        changes[k] = value

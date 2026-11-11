#!/usr/bin/env python3
"""droid.py — element-level Android control over uiautomator2 (no root).

Run through uv so nothing is installed globally:
  uv run --quiet --with uiautomator2 python -I droid.py -s emulator-5580 <command> ...

Commands
  ui                         one line per element with text/desc: "cx,cy | text | desc | id | class"
  app                        foreground package/activity
  tap  --text T | --text-contains T | --desc D | --id RID  [--timeout S]
                             clicks the element; exit 1 if it is not found (no coordinate fallback)
  type TEXT [--into-text T | --into-id RID] [--check]
                             types any Unicode (Chinese included) through uiautomator2's own IME;
                             --into-* taps that field first; --check exits 3 unless the focused
                             field reads back containing TEXT
  pinch in|out [--percent N] [--steps N] [--id RID | --desc D | --class C]
                             two-finger pinch on an element; default target is the first WebView,
                             then Chrome's "Web View" container, then the first scrollable view
  shot OUT.png               screenshot of the current display

Safety: -s is mandatory and only emulator-N serials are accepted. A physical phone answers
exit 5 unless PHONE_USE_REAL_DEVICE_OK=1 is set — set it only after the owner said yes for
this run. Someone else's phone may be attached over adb at any time, so "the only device" is
never a safe assumption.
"""
import argparse
import os
import re
import sys
import time
import xml.etree.ElementTree as ET


def connect(serial):
    if not re.fullmatch(r"emulator-\d+", serial) and os.environ.get("PHONE_USE_REAL_DEVICE_OK") != "1":
        print(f"refusing {serial}: not an emulator. Ask the owner first, then set "
              f"PHONE_USE_REAL_DEVICE_OK=1 for that run.", file=sys.stderr)
        sys.exit(5)
    import uiautomator2 as u2
    return u2.connect(serial)


def selector(d, a):
    if getattr(a, "text", None):
        return d(text=a.text)
    if getattr(a, "text_contains", None):
        return d(textContains=a.text_contains)
    if getattr(a, "desc", None):
        return d(description=a.desc)
    if getattr(a, "id", None):
        return d(resourceId=a.id)
    if getattr(a, "cls", None):
        return d(className=a.cls)
    return None


def cmd_ui(d, a):
    root = ET.fromstring(d.dump_hierarchy())
    for n in root.iter("node"):
        t, c = n.get("text", ""), n.get("content-desc", "")
        if not (t or c or a.all):
            continue
        l, tp, r, b = map(int, re.findall(r"\d+", n.get("bounds", "[0,0][0,0]")))
        rid = n.get("resource-id", "")
        print(f"{(l + r) // 2},{(tp + b) // 2} | {t[:60]} | {c[:40]} | {rid} | {n.get('class', '').split('.')[-1]}")


def cmd_app(d, a):
    print(d.app_current())


def cmd_tap(d, a):
    sel = selector(d, a)
    if sel is None:
        sys.exit("tap needs --text, --text-contains, --desc or --id")
    sel.click(timeout=a.timeout)  # raises UiObjectNotFoundError -> exit 1
    print("tapped")


def cmd_type(d, a):
    target = d(text=a.into_text) if a.into_text else d(resourceId=a.into_id) if a.into_id else None
    if target is not None:
        target.click(timeout=5)
        time.sleep(0.8)
    d.send_keys(a.text, clear=True)
    time.sleep(0.8)
    # read back the field we aimed at; the focused node is often a container
    # (Chrome reports the WebView itself as focused, text None)
    f = target if target is not None and target.exists else d(focused=True)
    got = f.get_text() if f.exists else None
    print(f"field reads back: {got!r}")
    if a.check and (got is None or a.text not in got):
        sys.exit(3)


def cmd_pinch(d, a):
    sel = selector(d, a)
    candidates = [sel] if sel is not None else [
        d(className="android.webkit.WebView"), d(description="Web View"), d(scrollable=True)]
    for obj in candidates:
        if obj.exists:
            getattr(obj, "pinch_" + a.direction)(percent=a.percent, steps=a.steps)
            print(f"pinch {a.direction} on {obj.info.get('className')} {obj.info.get('contentDescription') or ''}".rstrip())
            return
    sys.exit("no pinch target on screen (pass --id/--desc/--class)")


def cmd_shot(d, a):
    d.screenshot(a.out)
    print(a.out)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-s", "--serial", required=True)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("ui"); s.add_argument("--all", action="store_true"); s.set_defaults(f=cmd_ui)
    s = sub.add_parser("app"); s.set_defaults(f=cmd_app)
    s = sub.add_parser("tap"); s.set_defaults(f=cmd_tap)
    for flag, dest in (("--text", "text"), ("--text-contains", "text_contains"), ("--desc", "desc"), ("--id", "id")):
        s.add_argument(flag, dest=dest)
    s.add_argument("--timeout", type=float, default=5)
    s = sub.add_parser("type"); s.set_defaults(f=cmd_type)
    s.add_argument("text"); s.add_argument("--into-text"); s.add_argument("--into-id"); s.add_argument("--check", action="store_true")
    s = sub.add_parser("pinch"); s.set_defaults(f=cmd_pinch)
    s.add_argument("direction", choices=["in", "out"]); s.add_argument("--percent", type=int, default=70)
    s.add_argument("--steps", type=int, default=30)
    s.add_argument("--id", dest="id"); s.add_argument("--desc", dest="desc"); s.add_argument("--class", dest="cls")
    s = sub.add_parser("shot"); s.add_argument("out"); s.set_defaults(f=cmd_shot)
    a = p.parse_args()
    a.f(connect(a.serial), a)


if __name__ == "__main__":
    main()

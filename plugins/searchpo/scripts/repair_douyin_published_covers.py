#!/usr/bin/env python3
"""Repair already-published Douyin vertical covers from Searchpo run artifacts.

This is intentionally live-gated. Without --live it only reports which runs
would be edited.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def collect_runs(report_path: Path, explicit: list[str]) -> list[dict[str, Any]]:
    run_dirs: list[Path] = []
    if explicit:
        run_dirs = [Path(value).expanduser().resolve() for value in explicit]
    else:
        report = read_json(report_path)
        run_dirs = [Path(str(entry["run_dir"])).resolve() for entry in report.get("entries") or [] if entry.get("applied")]
    runs = []
    for run_dir in run_dirs:
        upload = read_json(run_dir / "post" / "douyin_upload_manifest.json")
        cover_path = Path(str(upload.get("cover_path") or run_dir / "cover" / "final.jpg")).expanduser()
        if not cover_path.is_absolute():
            cover_path = ROOT / cover_path
        title = str(upload.get("title") or "").strip()
        if title and cover_path.is_file():
            runs.append({"run_dir": str(run_dir), "title": title, "cover_path": str(cover_path)})
    return runs


def import_social_modules(social_root: Path):
    venv_site = next((social_root / ".venv" / "lib").glob("python*/site-packages"), None)
    if venv_site and str(venv_site) not in sys.path:
        sys.path.insert(0, str(venv_site))
    from patchright.async_api import async_playwright  # type: ignore
    from sau_cli import resolve_account_file  # type: ignore

    return async_playwright, resolve_account_file


async def dismiss_known_popovers(page) -> None:
    for _ in range(3):
        buttons = page.locator("text=我知道了")
        count = await buttons.count()
        if count == 0:
            return
        for index in range(count):
            try:
                await buttons.nth(index).click(timeout=1000)
            except Exception:
                pass
        await page.wait_for_timeout(500)


async def click_edit_for_title(page, title: str) -> bool:
    fragment = title[: min(18, len(title))]
    title_locator = page.get_by_text(fragment).first
    try:
        await title_locator.wait_for(state="visible", timeout=15000)
        await title_locator.scroll_into_view_if_needed()
        title_box = await title_locator.bounding_box()
    except Exception:
        return False
    if not title_box:
        return False
    edits = await page.locator("text=编辑作品").element_handles()
    best = None
    best_distance = 10**9
    for edit in edits:
        box = await edit.bounding_box()
        if not box:
            continue
        distance = abs((box["y"] + box["height"] / 2) - (title_box["y"] + title_box["height"] / 2))
        if distance < best_distance:
            best = edit
            best_distance = distance
    if best is None or best_distance > 90:
        return False
    await best.click()
    return True


async def repair_one(page, run: dict[str, str], screenshot_dir: Path, live: bool) -> dict[str, Any]:
    title = run["title"]
    cover_path = run["cover_path"]
    result: dict[str, Any] = {
        "title": title,
        "run_dir": run["run_dir"],
        "cover_path": cover_path,
        "status": "dry-run" if not live else "pending",
        "errors": [],
    }
    if not live:
        return result

    await page.goto("https://creator.douyin.com/creator-micro/content/manage", wait_until="domcontentloaded", timeout=90000)
    await page.wait_for_timeout(5000)
    await dismiss_known_popovers(page)
    if not await click_edit_for_title(page, title):
        result["status"] = "fail"
        result["errors"].append("could not locate edit action for title")
        return result
    await page.wait_for_url("**/content/post/video?**", timeout=30000)
    await page.wait_for_timeout(5000)
    await dismiss_known_popovers(page)

    vertical_tiles = page.locator('div[class^="background-"]')
    if await vertical_tiles.count() == 0:
        result["status"] = "fail"
        result["errors"].append("vertical cover tile not found")
        return result
    tile_box = await vertical_tiles.first.bounding_box()
    if not tile_box:
        result["status"] = "fail"
        result["errors"].append("vertical cover tile has no bounding box")
        return result
    await page.mouse.click(tile_box["x"] + tile_box["width"] / 2, tile_box["y"] + tile_box["height"] / 2)
    await page.wait_for_timeout(2000)

    upload_inputs = page.locator('input[type="file"]')
    if await upload_inputs.count() == 0:
        screenshot = screenshot_dir / f"{Path(run['run_dir']).name}-upload-button-missing.png"
        await page.screenshot(path=str(screenshot), full_page=True)
        result["screenshot"] = str(screenshot)
        result["status"] = "fail"
        result["errors"].append("cover upload input not found")
        return result
    await upload_inputs.last.set_input_files(cover_path)
    await page.wait_for_function(
        """() => Array.from(document.querySelectorAll('button')).some((button) => {
            const text = (button.innerText || button.textContent || '').trim();
            const className = String(button.className || '');
            return text === '完成' && !button.disabled && !className.includes('disabled');
        })""",
        timeout=90000,
    )

    await page.evaluate(
        """() => {
            const button = Array.from(document.querySelectorAll('button')).find((candidate) => {
                const text = (candidate.innerText || candidate.textContent || '').trim();
                const className = String(candidate.className || '');
                return text === '完成' && !candidate.disabled && !className.includes('disabled');
            });
            if (!button) throw new Error('enabled Done button not found');
            button.click();
        }"""
    )
    await page.wait_for_timeout(3000)

    try:
        await page.wait_for_function(
            """() => Array.from(document.querySelectorAll('button')).some((button) => {
                const text = (button.innerText || button.textContent || '').trim();
                const className = String(button.className || '');
                return text === '提交修改' && !button.disabled && !className.includes('disabled');
            })""",
            timeout=60000,
        )
        await page.evaluate(
            """() => {
                const button = Array.from(document.querySelectorAll('button')).find((candidate) => {
                    const text = (candidate.innerText || candidate.textContent || '').trim();
                    const className = String(candidate.className || '');
                    return text === '提交修改' && !candidate.disabled && !className.includes('disabled');
                });
                if (!button) throw new Error('enabled submit button not found');
                button.click();
            }"""
        )
    except Exception as exc:
        screenshot = screenshot_dir / f"{Path(run['run_dir']).name}-submit-failed.png"
        await page.screenshot(path=str(screenshot), full_page=True)
        result["screenshot"] = str(screenshot)
        result["status"] = "fail"
        result["errors"].append(f"submit failed: {exc}")
        return result
    await page.wait_for_timeout(5000)
    screenshot = screenshot_dir / f"{Path(run['run_dir']).name}-repair.png"
    await page.screenshot(path=str(screenshot), full_page=True)
    result["status"] = "submitted"
    result["screenshot"] = str(screenshot)
    result["url"] = page.url
    return result


async def run_async(args: argparse.Namespace) -> int:
    social_root = Path(args.social_root).expanduser().resolve()
    async_playwright, resolve_account_file = import_social_modules(social_root)
    runs = collect_runs(Path(args.report), args.run_dir)
    if args.limit:
        runs = runs[: args.limit]
    screenshot_dir = ROOT / "runtime" / "inspect" / "douyin-cover-repair"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    if not args.live:
        results = [{**run, "status": "dry-run"} for run in runs]
    else:
        account_file = resolve_account_file("douyin", args.account)
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=not args.headed, channel="chrome")
            context = await browser.new_context(storage_state=str(account_file), viewport={"width": 1280, "height": 1800})
            page = await context.new_page()
            for run in runs:
                try:
                    results.append(await repair_one(page, run, screenshot_dir, live=True))
                except Exception as exc:
                    results.append(
                        {
                            "title": run.get("title"),
                            "run_dir": run.get("run_dir"),
                            "cover_path": run.get("cover_path"),
                            "status": "fail",
                            "errors": [str(exc)],
                        }
                    )
            await context.storage_state(path=str(account_file))
            await browser.close()
    payload = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "live": args.live,
        "account": args.account,
        "results": results,
        "summary": {
            "total": len(results),
            "submitted": sum(1 for item in results if item.get("status") == "submitted"),
            "failed": sum(1 for item in results if item.get("status") == "fail"),
            "dry_run": sum(1 for item in results if item.get("status") == "dry-run"),
        },
    }
    write_json(Path(args.output), payload)
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print(args.output)
    return 1 if payload["summary"]["failed"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", default=str(ROOT / "runtime" / "cover_backfill_apply.json"))
    parser.add_argument("--output", default=str(ROOT / "runtime" / "douyin_cover_repair_report.json"))
    parser.add_argument("--run-dir", action="append", default=[])
    parser.add_argument("--social-root", default=str(ROOT / "runtime" / "social-auto-upload"))
    parser.add_argument("--account", default="searchpo-main")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--live", action="store_true", help="Actually submit edits to Douyin")
    args = parser.parse_args()
    return asyncio.run(run_async(args))


if __name__ == "__main__":
    raise SystemExit(main())

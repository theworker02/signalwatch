"""Capture honest, labelled UI previews from the actual shipped HTML/CSS/JS.

The preview dataset is synthetic, selected by ?preview=1 in a running app.
The capture pipeline renders the same static frontend in-memory to support
locked-down build environments that disallow localhost browser navigation.
Requires: pip install playwright, and a local Chromium executable.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / 'static'
OUTPUT = ROOT / 'docs' / 'screenshots'


def preview_html() -> str:
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    css = (STATIC / 'style.css').read_text(encoding='utf-8')
    # The screenshot should remain reproducible without fetching remote fonts.
    css = css.replace("@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@400;500;600;700;800&display=swap');", '')
    js = (STATIC / 'app.js').read_text(encoding='utf-8').replace(
        "new URLSearchParams(location.search).get('preview') === '1'", 'true'
    )
    html = html.replace('<link rel="stylesheet" href="/static/style.css"/>', f'<style>{css}</style>')
    html = html.replace('<script src="/static/preview.js" defer></script>', f'<script>{(STATIC / "preview.js").read_text(encoding="utf-8")}</script>')
    html = html.replace('<script src="/static/app.js" defer></script>', f'<script>{js}</script>')
    return html


def capture(chrome: str | None = None) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    html = preview_html()
    with sync_playwright() as playwright:
        executable = chrome or shutil.which('chromium') or shutil.which('google-chrome')
        browser = playwright.chromium.launch(headless=True, executable_path=executable, args=['--no-sandbox'])
        errors = []
        page = browser.new_page(viewport={'width': 1500, 'height': 940}, device_scale_factor=1)
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.set_content(html, wait_until='load')
        page.wait_for_function("document.querySelector('#m-events').textContent.trim() === '247'", timeout=8000)
        page.screenshot(path=str(OUTPUT / 'dashboard-desktop.png'), full_page=False)
        page.evaluate("document.documentElement.style.scrollBehavior = 'auto'; window.scrollTo(0, document.querySelector('#signals').offsetTop - 75)")
        page.wait_for_timeout(200)
        page.screenshot(path=str(OUTPUT / 'solar-analysis.png'), full_page=False)
        page.locator('#triage').scroll_into_view_if_needed()
        page.screenshot(path=str(OUTPUT / 'research-overview.png'), full_page=False)
        page.locator('#alert-list .inspect-event').first.click()
        page.wait_for_timeout(100)
        assert page.locator('#research-modal').is_visible()
        page.screenshot(path=str(OUTPUT / 'investigation-detail.png'), full_page=False)
        page.locator('#close-research').click()
        page.locator('#event-search').fill('solar')
        assert page.locator('.event').count() >= 1
        page.locator('#event-search').fill('')
        assert page.locator('.event').count() == 5
        assert not errors, errors
        mobile = browser.new_page(viewport={'width': 390, 'height': 844}, device_scale_factor=1)
        mobile.on('pageerror', lambda error: errors.append(str(error)))
        mobile.set_content(html, wait_until='load')
        mobile.wait_for_function("document.querySelector('#m-events').textContent.trim() === '247'", timeout=8000)
        assert mobile.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile horizontal overflow'
        mobile.screenshot(path=str(OUTPUT / 'dashboard-mobile.png'), full_page=False)
        assert not errors, errors
        browser.close()
    for png in OUTPUT.glob('*.png'):
        print(f'{png.relative_to(ROOT)}: {png.stat().st_size:,} bytes')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chromium', help='Path to local Chromium executable')
    args = parser.parse_args()
    capture(args.chromium)

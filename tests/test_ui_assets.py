"""Front-end packaging and honest preview labeling checks."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent


def test_preview_is_visibly_and_scientifically_labeled():
    html=(ROOT/'static/index.html').read_text()
    js=(ROOT/'static/app.js').read_text()
    preview=(ROOT/'static/preview.js').read_text()
    assert 'PREVIEW MODE' in html
    assert 'SAMPLE DATA · NOT LIVE' in js
    assert "new URLSearchParams(location.search).get('preview') === '1'" in js
    assert 'does not request external feeds' in html
    assert 'synthetic' in preview.lower()
    assert 'if(PREVIEW_MODE)' in js


def test_documentation_references_regenerated_screenshots():
    readme=(ROOT/'README.md').read_text()
    for name in ('dashboard-desktop.png','dashboard-mobile.png','research-overview.png','solar-analysis.png','investigation-detail.png'):
        assert f'docs/screenshots/{name}' in readme
    assert 'synthetic' in readme.lower()
    assert 'not a live' in readme.lower() or 'not live' in readme.lower()


def test_screenshot_generator_uses_shipped_ui_assets():
    capture=(ROOT/'scripts/capture_screenshots.py').read_text()
    assert "STATIC / 'index.html'" in capture
    assert "STATIC / 'style.css'" in capture
    assert "STATIC / 'app.js'" in capture
    assert "preview.js" in capture

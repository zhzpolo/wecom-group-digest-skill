from PIL import Image
from playwright.sync_api import sync_playwright

from wecom_digest.demo import demo


def test_demo_report_is_offline_complete_and_mobile_safe(tmp_path):
    artifact = demo(tmp_path)
    html = (artifact / "index.html").read_text(encoding="utf-8")
    assert "虚构数据演示" in html
    assert "WECOM · LOCAL DIGEST" in html
    assert "<script>alert" not in html
    with Image.open(artifact / "report.png") as image:
        assert image.width == 1500
        assert image.height > 1350

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844})
            requests, errors = [], []
            page.on("request", lambda request: requests.append(request.url))
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto((artifact / "index.html").as_uri())
            assert page.evaluate("document.documentElement.scrollWidth") == 390
            assert page.locator("details[open]").count() == 0
            page.locator("details summary").first.click()
            assert page.locator("details[open]").count() == 1
            assert not errors
            assert not any(url.startswith(("http:", "https:")) for url in requests)
        finally:
            browser.close()

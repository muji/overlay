from playwright.sync_api import sync_playwright

def capture_transparent_png(url, output_file):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-gpu"])
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=2
        )
        page = context.new_page()
        page.goto(url, wait_until="networkidle")

        # Inject CSS to make everything transparent
        page.add_style_tag(content="""
            body, html {
                background: transparent !important;
            }
            * {
                background-color: transparent !important;
                background: transparent !important;
            }
        """)

        page.screenshot(path=output_file, type="png", omit_background=True)
        print(f"✅ Transparent PNG saved at: {output_file}")
        browser.close()

if __name__ == "__main__":
    capture_transparent_png(
        "http://103.217.176.16:8080/scorecards/baseball/scorecard/1",
        "output.png"
    )

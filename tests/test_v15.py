"""Playwright verification for v15: notifications + desktop layout."""
import os
from playwright.sync_api import sync_playwright

BASE = "http://localhost:8800"
SS = os.path.join(os.path.dirname(__file__), "screenshots")
os.makedirs(SS, exist_ok=True)

MOBILE = {"width": 390, "height": 844}
DESKTOP = {"width": 1280, "height": 800}


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch()

        # ===== MOBILE TESTS =====
        print("=" * 50)
        print("MOBILE VIEWPORT (390x844)")
        print("=" * 50)

        page = browser.new_page(viewport=MOBILE)
        page.goto(BASE, wait_until="networkidle")

        css = page.locator('link[rel="stylesheet"]').get_attribute("href")
        print(f"Version: {css}")
        assert "v=15" in css, f"Expected v=15, got {css}"

        page.screenshot(path=f"{SS}/v15_mobile_list.png")
        print("1. Mobile session list - OK")

        # Open session
        cards = page.locator(".session-card:not(.dead)")
        assert cards.count() > 0, "No active sessions"
        cards.first.click()
        page.locator("#screenChat").wait_for(state="visible", timeout=5000)
        page.wait_for_timeout(2000)

        page.screenshot(path=f"{SS}/v15_mobile_chat.png")
        print("2. Mobile chat view - OK")

        # Verify tool blocks still work (regression check)
        blocks = page.locator(".tool-activity-block")
        block_h = blocks.first.evaluate("el => el.getBoundingClientRect().height") if blocks.count() > 0 else 0
        print(f"3. Tool blocks: {blocks.count()} found, first height={block_h}px")
        assert block_h > 10, f"Tool block collapsed! height={block_h}"

        # Check notification sound setting exists
        page.evaluate("""() => {
            var gear = document.getElementById('gearBtn');
            if (gear) gear.click();
        }""")
        page.wait_for_timeout(500)
        page.screenshot(path=f"{SS}/v15_mobile_settings.png")

        # Look for notification sound toggle
        settings_text = page.locator(".settings-panel").text_content()
        has_notif_sound = "Notification" in settings_text or "Sound" in settings_text or "sound" in settings_text
        print(f"4. Settings panel - notification sound toggle: {has_notif_sound}")

        # Close settings
        page.locator("#settingsBackdrop").click(force=True)
        page.wait_for_timeout(300)

        # Check tab title functionality
        title = page.title()
        print(f"5. Tab title: '{title}'")

        page.close()

        # ===== DESKTOP TESTS =====
        print("\n" + "=" * 50)
        print("DESKTOP VIEWPORT (1280x800)")
        print("=" * 50)

        page = browser.new_page(viewport=DESKTOP)
        page.goto(BASE, wait_until="networkidle")
        page.wait_for_timeout(1500)

        page.screenshot(path=f"{SS}/v15_desktop_list.png")
        print("6. Desktop session list - OK")

        # Check sidebar layout
        list_screen = page.locator("#screenList")
        chat_screen = page.locator("#screenChat")

        list_rect = list_screen.evaluate("el => { var r = el.getBoundingClientRect(); return {w: r.width, h: r.height, left: r.left}; }")
        chat_rect = chat_screen.evaluate("el => { var r = el.getBoundingClientRect(); return {w: r.width, h: r.height, left: r.left}; }")

        print(f"7. Sidebar: width={list_rect['w']}, left={list_rect['left']}")
        print(f"   Main panel: width={chat_rect['w']}, left={chat_rect['left']}")

        # Sidebar should be ~320px, main panel should be to the right
        assert list_rect['w'] >= 300 and list_rect['w'] <= 340, f"Sidebar width unexpected: {list_rect['w']}"
        assert chat_rect['left'] >= 300, f"Main panel not to the right of sidebar: left={chat_rect['left']}"
        print("   PASS: Side-by-side layout confirmed")

        # Check both screens are visible (no hidden classes taking effect)
        list_opacity = list_screen.evaluate("el => getComputedStyle(el).opacity")
        chat_opacity = chat_screen.evaluate("el => getComputedStyle(el).opacity")
        print(f"8. List opacity={list_opacity}, Chat opacity={chat_opacity}")
        assert float(list_opacity) == 1, "List screen hidden on desktop!"
        assert float(chat_opacity) == 1, "Chat screen hidden on desktop!"
        print("   PASS: Both panels visible")

        # Check for desktop empty state (no session selected yet)
        empty_state = page.locator(".desktop-empty-state")
        if empty_state.count() > 0:
            empty_text = empty_state.text_content()
            print(f"9. Desktop empty state: '{empty_text.strip()}'")
        else:
            print("9. No desktop empty state (may have auto-opened a session)")

        # Click a session on desktop
        desktop_cards = page.locator(".session-card:not(.dead)")
        if desktop_cards.count() > 0:
            desktop_cards.first.click()
            page.wait_for_timeout(2000)
            page.screenshot(path=f"{SS}/v15_desktop_chat.png")
            print("10. Desktop chat view - OK")

            # Both panels should still be visible
            list_visible = list_screen.evaluate("el => getComputedStyle(el).opacity")
            assert float(list_visible) == 1, "Sidebar disappeared after opening session!"
            print("    PASS: Sidebar stays visible after opening session")

            # Check active card highlight
            active_cards = page.locator(".session-card.active")
            active_count = active_cards.count()
            print(f"11. Active card highlight: {active_count} cards highlighted")

            # Back button should be hidden on desktop
            back_btn = page.locator("#backBtn")
            back_display = back_btn.evaluate("el => getComputedStyle(el).display")
            print(f"12. Back button display on desktop: '{back_display}'")

            # Check hover effect exists (CSS rule)
            has_hover = page.evaluate("""() => {
                var sheets = document.styleSheets;
                for (var i = 0; i < sheets.length; i++) {
                    try {
                        var rules = sheets[i].cssRules;
                        for (var j = 0; j < rules.length; j++) {
                            if (rules[j].selectorText && rules[j].selectorText.indexOf('session-card:hover') >= 0) return true;
                        }
                    } catch(e) {}
                }
                return false;
            }""")
            print(f"13. Session card hover CSS: {has_hover}")

        # Keyboard navigation test
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        page.screenshot(path=f"{SS}/v15_desktop_after_escape.png")
        print("14. Escape key pressed - OK")

        # Test Cmd+K (focus input)
        page.keyboard.press("Control+k")
        page.wait_for_timeout(300)
        focused = page.evaluate("document.activeElement.id")
        print(f"15. Ctrl+K focused element: '{focused}'")

        page.screenshot(path=f"{SS}/v15_desktop_final.png")
        print("\n16. Final desktop state captured")

        browser.close()
        print(f"\nAll screenshots in {SS}")


if __name__ == "__main__":
    run()

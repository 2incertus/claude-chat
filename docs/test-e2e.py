#!/usr/bin/env python3
"""End-to-end Playwright test for claude-chat dev deployment."""

import os
import time
from playwright.sync_api import sync_playwright

BASE = "http://localhost:8801"
PIN = "0028"
OUT = "/home/ubuntu/docker/claude-chat/docs/images/e2e"
os.makedirs(OUT, exist_ok=True)

PASS = 0
FAIL = 0
RESULTS = []


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        RESULTS.append(f"  PASS  {name}")
    else:
        FAIL += 1
        RESULTS.append(f"  FAIL  {name} -- {detail}")


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # ── Mobile viewport ──
        ctx = browser.new_context(
            viewport={"width": 393, "height": 852},
            device_scale_factor=3,
        )
        page = ctx.new_page()

        # Set dark theme
        page.goto(BASE)
        page.wait_for_timeout(500)
        page.evaluate("localStorage.setItem('claude_chat_settings', JSON.stringify({theme: 'dark'}))")
        page.reload()
        page.wait_for_timeout(500)

        # ── Test 1: Auth ──
        login = page.locator(".login-input")
        if login.is_visible(timeout=2000):
            login.fill(PIN)
            login.press("Enter")
            page.wait_for_timeout(1500)

        session_cards = page.locator(".session-card")
        check("Auth + session list loads", session_cards.count() > 0, f"Found {session_cards.count()} cards")
        page.screenshot(path=f"{OUT}/01-session-list.png")

        # ── Test 2: CWD folder grouping ──
        folder_headers = page.locator(".folder-header")
        # CWD grouping shows group headers like "~/docker/claude-chat (2)"
        group_headers = page.locator(".session-group-header")
        has_grouping = folder_headers.count() > 0 or group_headers.count() > 0
        check("Session grouping visible", has_grouping, f"folders={folder_headers.count()}, groups={group_headers.count()}")

        # ── Test 3: Open a session ──
        card = page.locator('.session-card[data-name="test-ui"]')
        if not card.is_visible(timeout=3000):
            card = page.locator(".session-card").first
        card.click()
        page.wait_for_timeout(2000)

        chat_title = page.locator("#chatTitle").text_content()
        check("Session opens with title", bool(chat_title), f"title='{chat_title}'")

        messages = page.locator(".msg")
        check("Messages render", messages.count() > 0, f"Found {messages.count()} messages")
        page.screenshot(path=f"{OUT}/02-chat-view.png")

        # ── Test 4: Header buttons present ──
        export_btn = page.locator("#exportBtn")
        check("Export button visible", export_btn.is_visible())

        refresh_btn = page.locator("#refreshBtn")
        check("Refresh button visible", refresh_btn.is_visible())

        bell_btn = page.locator("#bellBtn")
        check("Bell button visible", bell_btn.is_visible())

        # ── Test 5: Mobile ? shortcuts button ──
        shortcuts_btn = page.locator("#mobileShortcutsBtn")
        check("Mobile ? button visible", shortcuts_btn.is_visible())

        shortcuts_btn.click()
        page.wait_for_timeout(500)
        shortcuts_panel = page.locator("#shortcutsPanel")
        check("Shortcuts panel opens", shortcuts_panel.is_visible())

        # Check action buttons in shortcuts
        action_copy = page.locator("#actionCopyAll")
        action_export_md = page.locator("#actionExportMd")
        action_export_json = page.locator("#actionExportJson")
        check("Action: Copy All visible", action_copy.is_visible())
        check("Action: Export MD visible", action_export_md.is_visible())
        check("Action: Export JSON visible", action_export_json.is_visible())
        page.screenshot(path=f"{OUT}/03-shortcuts-panel.png")

        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        # ── Test 6: Copy button hidden on mobile ──
        copy_btn = page.locator("#copyAllBtn")
        check("Copy button hidden on mobile", not copy_btn.is_visible())

        # ── Test 7: Star buttons hidden on mobile ──
        star_btns = page.locator(".msg-star-btn")
        any_star_visible = False
        for i in range(min(star_btns.count(), 5)):
            if star_btns.nth(i).is_visible():
                any_star_visible = True
                break
        check("Star buttons hidden on mobile", not any_star_visible)

        # ── Test 8: CTX badge in special keys row ──
        cost_badge = page.locator("#costBadge")
        # It may or may not be visible depending on session data
        check("Cost badge element exists", cost_badge.count() > 0)

        # ── Test 9: Special keys toolbar ──
        special_keys = page.locator(".special-key")
        check("Special keys visible", special_keys.count() >= 5, f"Found {special_keys.count()}")

        # ── Test 10: Export dropdown ──
        export_btn.click()
        page.wait_for_timeout(500)
        dropdown = page.locator(".export-dropdown")
        check("Export dropdown opens", dropdown.count() > 0)
        page.screenshot(path=f"{OUT}/04-export-dropdown.png")
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        # ── Test 11: Upload image and check rendering ──
        # Create a small test image
        import struct, zlib
        def make_png(w, h, color=(255, 100, 50)):
            def chunk(ctype, data):
                return struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)
            header = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
            raw = b""
            for _ in range(h):
                raw += b"\x00" + bytes(color) * w
            return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")

        test_img_path = "/tmp/test-upload.png"
        with open(test_img_path, "wb") as f:
            f.write(make_png(100, 100))

        # Navigate to test-ui session for upload test
        page.evaluate("document.getElementById('backBtn').click()")
        page.wait_for_timeout(500)
        test_card = page.locator('.session-card[data-name="test-ui"]')
        if test_card.is_visible(timeout=3000):
            test_card.click()
            page.wait_for_timeout(2000)

            # Upload via file input
            file_input = page.locator("#fileInput")
            file_input.set_input_files(test_img_path)
            page.wait_for_timeout(3000)

            # Check text input has the upload reference appended
            text_val = page.locator("#textInput").input_value()
            check("Upload ref in text input", "/srv/appdata/claude-chat/uploads/" in text_val, f"value='{text_val[:80]}'")
            page.screenshot(path=f"{OUT}/05-upload-ref.png")

            # Don't actually send the message — just verify the ref was appended
            # Clear the input
            page.locator("#textInput").fill("")

        # ── Test 12: Check image rendering on chat-2 (has uploaded images) ──
        page.evaluate("document.getElementById('backBtn').click()")
        page.wait_for_timeout(500)
        chat2 = page.locator('.session-card[data-name="chat-2"]')
        if chat2.is_visible(timeout=3000):
            chat2.click()
            page.wait_for_timeout(3000)

            # Scroll through looking for images
            feed = page.locator("#chatFeed")
            img_count = page.locator("img.msg-image").count()

            # Scroll to find them
            for _ in range(10):
                feed.evaluate("el => el.scrollBy(0, 300)")
                page.wait_for_timeout(300)
                new_count = page.locator("img.msg-image").count()
                if new_count > img_count:
                    img_count = new_count

            check("Image elements found in chat", img_count > 0, f"Found {img_count}")

            # Check if any loaded successfully
            if img_count > 0:
                loaded = page.evaluate("""() => {
                    var imgs = document.querySelectorAll('img.msg-image');
                    var loaded = 0;
                    for (var i = 0; i < imgs.length; i++) {
                        if (imgs[i].complete && imgs[i].naturalWidth > 0) loaded++;
                    }
                    return loaded;
                }""")
                check("Images loaded successfully", loaded > 0, f"{loaded}/{img_count} loaded")
                page.screenshot(path=f"{OUT}/06-image-render.png")
        else:
            check("chat-2 session found", False, "not visible")

        # ── Test 13: Folder swipe action ──
        page.evaluate("document.getElementById('backBtn').click()")
        page.wait_for_timeout(500)
        first_wrapper = page.locator(".session-card-wrapper").first
        if first_wrapper.is_visible():
            # Simulate swipe by using touch events
            box = first_wrapper.bounding_box()
            if box:
                page.mouse.move(box["x"] + box["width"] - 20, box["y"] + box["height"] / 2)
                page.mouse.down()
                page.mouse.move(box["x"] + box["width"] - 160, box["y"] + box["height"] / 2, steps=10)
                page.mouse.up()
                page.wait_for_timeout(500)
                folder_btn = page.locator(".card-action-folder").first
                check("Folder swipe button exists", folder_btn.count() > 0)
                page.screenshot(path=f"{OUT}/07-swipe-actions.png")

        # ── Desktop viewport tests ──
        ctx.close()
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 800},
            device_scale_factor=2,
        )
        page = ctx.new_page()
        page.goto(BASE)
        page.wait_for_timeout(500)
        page.evaluate("localStorage.setItem('claude_chat_settings', JSON.stringify({theme: 'dark'}))")
        page.reload()
        page.wait_for_timeout(500)
        login = page.locator(".login-input")
        if login.is_visible(timeout=2000):
            login.fill(PIN)
            login.press("Enter")
            page.wait_for_timeout(1500)

        # ── Test 14: Desktop dual-pane ──
        list_screen = page.locator("#screenList")
        chat_screen = page.locator("#screenChat")
        check("Desktop: both panels visible",
              list_screen.is_visible() and chat_screen.is_visible())

        # ── Test 15: Desktop ? keyboard shortcut ──
        page.keyboard.press("?")
        page.wait_for_timeout(500)
        check("Desktop: ? opens shortcuts", page.locator("#shortcutsPanel").is_visible())
        page.screenshot(path=f"{OUT}/08-desktop-shortcuts.png")
        page.keyboard.press("Escape")

        # ── Test 16: Desktop copy button visible ──
        card = page.locator('.session-card[data-name="test-ui"]')
        if card.is_visible(timeout=3000):
            card.click()
            page.wait_for_timeout(2000)
        copy_btn = page.locator("#copyAllBtn")
        check("Desktop: copy button visible", copy_btn.is_visible())

        # ── Test 17: Desktop star buttons visible ──
        star_btns = page.locator(".msg-star-btn")
        desktop_star_visible = False
        for i in range(min(star_btns.count(), 5)):
            if star_btns.nth(i).is_visible():
                desktop_star_visible = True
                break
        check("Desktop: star buttons visible", desktop_star_visible)

        # ── Test 18: Mobile ? button hidden on desktop ──
        mobile_btn = page.locator("#mobileShortcutsBtn")
        check("Desktop: mobile ? button hidden", not mobile_btn.is_visible())

        page.screenshot(path=f"{OUT}/09-desktop-chat.png")

        ctx.close()
        browser.close()

    # ── Report ──
    print(f"\n{'='*50}")
    print(f"  E2E Test Results: {PASS} passed, {FAIL} failed")
    print(f"{'='*50}")
    for r in RESULTS:
        print(r)
    print(f"{'='*50}")
    print(f"Screenshots saved to {OUT}/")

    return FAIL == 0


if __name__ == "__main__":
    success = run()
    exit(0 if success else 1)

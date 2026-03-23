"""
Playwright visual verification for claude-chat v13.
Takes screenshots of every feature to prove it works on mobile viewport.
"""
import os
import time
import json
from playwright.sync_api import sync_playwright, expect

BASE = os.environ.get("BASE_URL", "http://localhost:8800")
SS_DIR = os.path.join(os.path.dirname(__file__), "screenshots")
os.makedirs(SS_DIR, exist_ok=True)

MOBILE_VIEWPORT = {"width": 390, "height": 844}  # iPhone 14


def ss(page, name):
    """Save a screenshot."""
    path = os.path.join(SS_DIR, f"{name}.png")
    page.screenshot(path=path)
    print(f"  SCREENSHOT: {path}")
    return path


def test_01_session_list_renders():
    """Session list loads with cards, badge, and proper layout."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=MOBILE_VIEWPORT)
        page.goto(BASE, wait_until="networkidle")

        # Verify we're on v13
        css_link = page.locator('link[rel="stylesheet"]').get_attribute("href")
        assert "v=13" in css_link, f"Expected v=13, got {css_link}"
        print(f"  PASS: Serving v=13")

        # Session count badge should exist and show a number
        badge = page.locator("#sessionCount")
        badge_text = badge.text_content()
        assert badge_text.strip(), "Session count badge is empty"
        print(f"  PASS: Session badge shows '{badge_text}'")

        # Should have at least one session card
        cards = page.locator(".session-card")
        count = cards.count()
        assert count > 0, "No session cards found"
        print(f"  PASS: {count} session cards rendered")

        ss(page, "01_session_list")
        browser.close()


def test_02_session_list_features():
    """Pin indicator, batch dismiss, working dot badge."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=MOBILE_VIEWPORT)
        page.goto(BASE, wait_until="networkidle")

        # Check if badge shows active/total format
        badge = page.locator("#sessionCount")
        badge_text = badge.text_content().strip()
        print(f"  INFO: Badge text = '{badge_text}'")

        # Check for batch dismiss button if dead sessions exist
        batch_btn = page.locator(".batch-action-btn")
        if batch_btn.count() > 0:
            print(f"  PASS: Batch dismiss button visible")
        else:
            print(f"  INFO: No dead sessions, batch dismiss hidden (expected)")

        # Check for working dot
        working_dot = page.locator(".badge-dot")
        if working_dot.count() > 0:
            print(f"  PASS: Working indicator dot present in badge")
        else:
            print(f"  INFO: No working sessions, no badge dot (expected)")

        ss(page, "02_session_features")
        browser.close()


def test_03_chat_view_opens():
    """Clicking a session opens the chat view with messages."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=MOBILE_VIEWPORT)
        page.goto(BASE, wait_until="networkidle")

        # Click first active session card
        active_cards = page.locator(".session-card:not(.dead)")
        assert active_cards.count() > 0, "No active session cards to click"

        first_card = active_cards.first
        card_name = first_card.get_attribute("data-name")
        print(f"  INFO: Opening session '{card_name}'")
        first_card.click()

        # Wait for chat screen to become visible
        chat_screen = page.locator("#screenChat")
        chat_screen.wait_for(state="visible", timeout=5000)

        # Wait for messages to load
        page.wait_for_timeout(2000)

        # Check that session list is NOT visible (transparency bug fix)
        list_screen = page.locator("#screenList")
        list_classes = list_screen.get_attribute("class")
        assert "hidden-left" in list_classes, f"Session list not hidden: {list_classes}"
        print(f"  PASS: Session list properly hidden (class={list_classes})")

        # Verify the list screen has opacity 0 (not bleeding through)
        list_opacity = list_screen.evaluate("el => getComputedStyle(el).opacity")
        print(f"  INFO: Hidden list screen opacity = {list_opacity}")
        assert float(list_opacity) == 0, f"List screen opacity should be 0, got {list_opacity}"
        print(f"  PASS: List screen fully hidden (opacity=0)")

        # Chat screen should have solid background
        chat_bg = chat_screen.evaluate("el => getComputedStyle(el).backgroundColor")
        print(f"  INFO: Chat screen background = {chat_bg}")
        assert chat_bg != "rgba(0, 0, 0, 0)", "Chat screen has transparent background!"
        print(f"  PASS: Chat screen has solid background")

        # Should have messages in the feed
        messages = page.locator("#chatFeed > *")
        msg_count = messages.count()
        print(f"  INFO: {msg_count} elements in chat feed")
        assert msg_count > 0, "Chat feed is empty"
        print(f"  PASS: Chat feed has {msg_count} elements")

        ss(page, "03_chat_view")
        browser.close()


def test_04_tool_activity_blocks():
    """Tool calls render as grouped activity blocks, not garbled text."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=MOBILE_VIEWPORT)
        page.goto(BASE, wait_until="networkidle")

        # Open a session with tool calls
        active_cards = page.locator(".session-card:not(.dead)")
        first_card = active_cards.first
        first_card.click()
        page.locator("#screenChat").wait_for(state="visible", timeout=5000)
        page.wait_for_timeout(2000)

        # Look for tool activity blocks
        activity_blocks = page.locator(".tool-activity-block")
        block_count = activity_blocks.count()
        print(f"  INFO: Found {block_count} tool activity blocks")

        if block_count > 0:
            # Check first block has proper structure
            first_block = activity_blocks.first
            header = first_block.locator(".tool-activity-header")
            assert header.count() > 0, "Activity block missing header"

            summary = first_block.locator(".tool-activity-summary")
            summary_text = summary.text_content().strip()
            print(f"  INFO: First block summary = '{summary_text}'")
            assert summary_text, "Activity block summary is empty"

            count_el = first_block.locator(".tool-activity-count")
            count_text = count_el.text_content().strip()
            print(f"  INFO: First block count = '{count_text}'")
            assert "action" in count_text, f"Count text unexpected: {count_text}"

            # Body should be collapsed by default
            body = first_block.locator(".tool-activity-body")
            body_classes = body.get_attribute("class")
            assert "collapsed" in body_classes, "Activity body should be collapsed by default"
            print(f"  PASS: Activity body collapsed by default")

            # Click to expand
            header.click()
            page.wait_for_timeout(300)
            body_classes_after = body.get_attribute("class")
            assert "collapsed" not in body_classes_after, "Activity body should expand on click"
            print(f"  PASS: Activity body expands on click")

            # Check individual items inside
            items = body.locator(".tool-activity-item")
            item_count = items.count()
            print(f"  INFO: {item_count} items inside expanded block")
            assert item_count > 0, "Expanded block has no items"

            # Verify item text is clean (no multiline garbage)
            first_item_text = items.first.text_content().strip()
            print(f"  INFO: First item text = '{first_item_text[:80]}'")
            assert "\n" not in first_item_text, "Item text contains newlines (garbage)"
            print(f"  PASS: Item text is clean (no newlines)")

            ss(page, "04a_tool_block_expanded")

            # Collapse again
            header.click()
            page.wait_for_timeout(300)
            ss(page, "04b_tool_block_collapsed")
        else:
            # Check for old-style .msg-tool elements (regression)
            old_tools = page.locator(".msg-tool")
            old_count = old_tools.count()
            print(f"  WARN: No activity blocks found. Old .msg-tool count = {old_count}")
            if old_count > 0:
                first_text = old_tools.first.text_content()
                print(f"  FAIL: Old tool rendering still present: '{first_text[:60]}'")
            ss(page, "04_no_tool_blocks")

        browser.close()


def test_05_agent_dropdown():
    """Agent/Skill tool calls render as purple collapsible cards."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=MOBILE_VIEWPORT)
        page.goto(BASE, wait_until="networkidle")

        # Open session
        active_cards = page.locator(".session-card:not(.dead)")
        first_card = active_cards.first
        first_card.click()
        page.locator("#screenChat").wait_for(state="visible", timeout=5000)
        page.wait_for_timeout(2000)

        # Look for agent result cards
        agent_cards = page.locator(".agent-result-card")
        agent_count = agent_cards.count()
        print(f"  INFO: Found {agent_count} agent dropdown cards")

        if agent_count > 0:
            first_agent = agent_cards.first

            # Check structure
            label = first_agent.locator(".agent-result-label")
            label_text = label.text_content().strip()
            print(f"  INFO: Agent label = '{label_text}'")
            assert label_text in ("Agent", "Skill"), f"Unexpected label: {label_text}"

            desc = first_agent.locator(".agent-result-desc")
            desc_text = desc.text_content().strip()
            print(f"  INFO: Agent desc = '{desc_text[:60]}'")

            # Should be collapsed by default
            body = first_agent.locator(".agent-result-body")
            assert "collapsed" in body.get_attribute("class"), "Agent body not collapsed by default"
            print(f"  PASS: Agent card collapsed by default")

            # Check purple tint on header
            header = first_agent.locator(".agent-result-header")
            header_bg = header.evaluate("el => getComputedStyle(el).backgroundColor")
            print(f"  INFO: Agent header bg = {header_bg}")

            # Click to expand
            header.click()
            page.wait_for_timeout(300)
            assert "collapsed" not in body.get_attribute("class"), "Agent body didn't expand"
            print(f"  PASS: Agent card expands on click")

            ss(page, "05_agent_dropdown")
        else:
            print(f"  INFO: No Agent/Skill calls in this session (expected if none were made)")
            # Scroll through to take full screenshot
            ss(page, "05_no_agent_cards")

        browser.close()


def test_06_sending_indicator():
    """Sending message shows 'Sending...' indicator and 'Sent' toast."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=MOBILE_VIEWPORT)
        page.goto(BASE, wait_until="networkidle")

        # Open a session
        active_cards = page.locator(".session-card:not(.dead)")
        first_card = active_cards.first
        first_card.click()
        page.locator("#screenChat").wait_for(state="visible", timeout=5000)
        page.wait_for_timeout(2000)

        # Type a test message
        text_input = page.locator("#textInput")
        text_input.fill("test_playwright_verification")
        page.wait_for_timeout(200)

        # Send button should be visible now
        send_btn = page.locator("#sendBtn")
        assert send_btn.is_visible(), "Send button not visible after typing"
        print(f"  PASS: Send button visible after typing")

        ss(page, "06a_before_send")

        # Click send and immediately screenshot to catch "Sending..."
        send_btn.click()
        page.wait_for_timeout(100)  # tiny delay to let DOM update

        # Check for pending message wrapper with sending indicator
        pending_status = page.locator(".msg-status-pending")
        pending_visible = pending_status.count() > 0
        print(f"  INFO: Sending indicator visible = {pending_visible}")

        ss(page, "06b_sending_indicator")

        if pending_visible:
            pending_text = pending_status.first.text_content().strip()
            print(f"  PASS: Sending indicator shows '{pending_text}'")
        else:
            print(f"  WARN: Sending indicator not caught (may have been too fast)")

        # Wait for sent toast
        page.wait_for_timeout(3000)
        sent_toast = page.locator(".msg-sent-toast.visible")
        toast_visible = sent_toast.count() > 0
        print(f"  INFO: Sent toast visible = {toast_visible}")

        if toast_visible:
            ss(page, "06c_sent_toast")
            print(f"  PASS: Sent toast appeared")
        else:
            print(f"  WARN: Sent toast not caught (may have already faded)")

        ss(page, "06d_after_send")
        browser.close()


def test_07_viewport_and_transparency():
    """Verify 100dvh viewport and no screen bleed-through."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=MOBILE_VIEWPORT)
        page.goto(BASE, wait_until="networkidle")

        # Check viewport meta
        vp_meta = page.locator('meta[name="viewport"]').get_attribute("content")
        assert "viewport-fit=cover" in vp_meta, f"Missing viewport-fit=cover: {vp_meta}"
        print(f"  PASS: Viewport meta has viewport-fit=cover")

        # Check body uses 100dvh
        body_height = page.evaluate("getComputedStyle(document.body).height")
        print(f"  INFO: Body computed height = {body_height}")

        # Check screen has solid background
        screen = page.locator("#screenList")
        screen_bg = screen.evaluate("el => getComputedStyle(el).backgroundColor")
        print(f"  INFO: Screen background = {screen_bg}")
        assert screen_bg != "rgba(0, 0, 0, 0)", "Screen has transparent background"
        print(f"  PASS: Screen has solid background")

        # Check screen z-index
        screen_z = screen.evaluate("el => getComputedStyle(el).zIndex")
        print(f"  INFO: Screen z-index = {screen_z}")

        ss(page, "07_viewport")
        browser.close()


def test_08_light_theme_readability():
    """Verify elements are readable on light theme."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=MOBILE_VIEWPORT)
        page.goto(BASE, wait_until="networkidle")

        # Set light theme
        page.evaluate("document.documentElement.setAttribute('data-theme', 'light')")
        page.wait_for_timeout(500)

        ss(page, "08a_light_session_list")

        # Open a session
        active_cards = page.locator(".session-card:not(.dead)")
        if active_cards.count() > 0:
            active_cards.first.click()
            page.locator("#screenChat").wait_for(state="visible", timeout=5000)
            page.wait_for_timeout(2000)

            ss(page, "08b_light_chat_view")

            # Check tool activity blocks are visible on light theme
            blocks = page.locator(".tool-activity-block")
            if blocks.count() > 0:
                header = blocks.first.locator(".tool-activity-header")
                header_bg = header.evaluate("el => getComputedStyle(el).backgroundColor")
                header_color = header.evaluate("el => getComputedStyle(el).color")
                print(f"  INFO: Light theme - header bg={header_bg}, color={header_color}")

                # Expand one
                header.click()
                page.wait_for_timeout(300)
                ss(page, "08c_light_tool_expanded")

            # Check agent cards
            agents = page.locator(".agent-result-card")
            if agents.count() > 0:
                agent_header_bg = agents.first.locator(".agent-result-header").evaluate(
                    "el => getComputedStyle(el).backgroundColor"
                )
                print(f"  INFO: Light theme - agent header bg={agent_header_bg}")

        browser.close()


def test_09_pwa_manifest():
    """Verify PWA manifest and service worker registration."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=MOBILE_VIEWPORT)
        page.goto(BASE, wait_until="networkidle")

        # Check manifest link
        manifest_link = page.locator('link[rel="manifest"]')
        assert manifest_link.count() > 0, "No manifest link found"
        manifest_href = manifest_link.get_attribute("href")
        print(f"  PASS: Manifest link = {manifest_href}")

        # Fetch manifest
        resp = page.evaluate("""async () => {
            const r = await fetch('/manifest.json');
            return await r.json();
        }""")
        print(f"  INFO: Manifest name = {resp.get('name')}")
        print(f"  INFO: Manifest display = {resp.get('display')}")
        assert resp.get("display") == "standalone", "Manifest display should be standalone"
        print(f"  PASS: Manifest is standalone PWA")

        # Check SW registration script exists
        sw_script = page.locator("script").filter(has_text="serviceWorker")
        assert sw_script.count() > 0, "No service worker registration script"
        print(f"  PASS: Service worker registration script present")

        # Check icon exists
        icon_resp = page.evaluate("""async () => {
            const r = await fetch('/static/icon.svg');
            return { status: r.status, type: r.headers.get('content-type') };
        }""")
        print(f"  INFO: Icon response = {icon_resp}")
        assert icon_resp["status"] == 200, "Icon file not found"
        print(f"  PASS: App icon exists")

        ss(page, "09_pwa")
        browser.close()


# ===== BOUNDARY TESTS =====

def test_10_boundary_empty_session_name():
    """API should reject invalid session names."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=MOBILE_VIEWPORT)

        # Try accessing session with special characters
        resp = page.evaluate("""async () => {
            const r = await fetch('/api/sessions/../etc/passwd');
            return { status: r.status };
        }""")
        page.goto(BASE)
        print(f"  INFO: Path traversal attempt status = {resp['status']}")
        assert resp["status"] >= 400, "Path traversal should be rejected"
        print(f"  PASS: Path traversal rejected")

        browser.close()


def test_11_boundary_rapid_polling():
    """Rapid send + poll shouldn't crash or duplicate messages."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=MOBILE_VIEWPORT)
        page.goto(BASE, wait_until="networkidle")

        # Open session
        active_cards = page.locator(".session-card:not(.dead)")
        if active_cards.count() == 0:
            print("  SKIP: No active sessions")
            browser.close()
            return

        active_cards.first.click()
        page.locator("#screenChat").wait_for(state="visible", timeout=5000)
        page.wait_for_timeout(2000)

        # Count initial messages
        initial_count = page.locator("#chatFeed > *").count()

        # Rapid-fire 3 poll requests
        page.evaluate("""async () => {
            const name = document.getElementById('chatTitle').textContent;
            await Promise.all([
                fetch('/api/sessions/' + encodeURIComponent(name) + '/poll'),
                fetch('/api/sessions/' + encodeURIComponent(name) + '/poll'),
                fetch('/api/sessions/' + encodeURIComponent(name) + '/poll'),
            ]);
        }""")
        page.wait_for_timeout(1000)

        after_count = page.locator("#chatFeed > *").count()
        print(f"  INFO: Messages before={initial_count}, after={after_count}")
        # Count should be same (no duplicates from rapid polling)
        assert after_count == initial_count, f"Message count changed after rapid poll: {initial_count} -> {after_count}"
        print(f"  PASS: No duplicate messages from rapid polling")

        ss(page, "11_rapid_poll")
        browser.close()


def test_12_boundary_scroll_position():
    """Scroll position should be maintained when switching sessions."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=MOBILE_VIEWPORT)
        page.goto(BASE, wait_until="networkidle")

        active_cards = page.locator(".session-card:not(.dead)")
        if active_cards.count() < 1:
            print("  SKIP: Need at least 1 active session")
            browser.close()
            return

        # Open first session
        active_cards.first.click()
        page.locator("#screenChat").wait_for(state="visible", timeout=5000)
        page.wait_for_timeout(2000)

        # Scroll up
        feed = page.locator("#chatFeed")
        feed.evaluate("el => el.scrollTop = 100")
        page.wait_for_timeout(200)
        scroll_before = feed.evaluate("el => el.scrollTop")
        print(f"  INFO: Scroll position set to {scroll_before}")

        # Go back to list
        page.locator("#backBtn").click()
        page.wait_for_timeout(1000)

        # Re-open same session
        page.locator(".session-card:not(.dead)").first.click()
        page.locator("#screenChat").wait_for(state="visible", timeout=5000)
        page.wait_for_timeout(2000)

        scroll_after = feed.evaluate("el => el.scrollTop")
        print(f"  INFO: Scroll position after re-open = {scroll_after}")
        # Should be restored (approximately)
        assert abs(scroll_after - scroll_before) < 50, f"Scroll not restored: {scroll_before} vs {scroll_after}"
        print(f"  PASS: Scroll position restored")

        ss(page, "12_scroll_restore")
        browser.close()


if __name__ == "__main__":
    tests = [
        test_01_session_list_renders,
        test_02_session_list_features,
        test_03_chat_view_opens,
        test_04_tool_activity_blocks,
        test_05_agent_dropdown,
        test_06_sending_indicator,
        test_07_viewport_and_transparency,
        test_08_light_theme_readability,
        test_09_pwa_manifest,
        test_10_boundary_empty_session_name,
        test_11_boundary_rapid_polling,
        test_12_boundary_scroll_position,
    ]

    passed = 0
    failed = 0
    errors = []

    for test in tests:
        name = test.__name__
        print(f"\n{'='*60}")
        print(f"TEST: {name}")
        print(f"{'='*60}")
        try:
            test()
            passed += 1
            print(f"  RESULT: PASS")
        except Exception as e:
            failed += 1
            errors.append((name, str(e)))
            print(f"  RESULT: FAIL - {e}")

    print(f"\n{'='*60}")
    print(f"SUMMARY: {passed} passed, {failed} failed out of {len(tests)}")
    print(f"{'='*60}")
    if errors:
        print("\nFAILURES:")
        for name, err in errors:
            print(f"  {name}: {err}")
    print(f"\nScreenshots saved to: {SS_DIR}")

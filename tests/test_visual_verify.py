"""Scroll to and screenshot every feature element."""
import os
from playwright.sync_api import sync_playwright

BASE = "http://localhost:8800"
SS_DIR = os.path.join(os.path.dirname(__file__), "screenshots")
os.makedirs(SS_DIR, exist_ok=True)
VP = {"width": 390, "height": 844}


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=VP)
        page.goto(BASE, wait_until="networkidle")

        # 1. Session list
        page.screenshot(path=f"{SS_DIR}/v_01_session_list.png")
        print("1. Session list captured")

        # Open first active session
        cards = page.locator(".session-card:not(.dead)")
        if cards.count() == 0:
            print("No active sessions!")
            browser.close()
            return
        cards.first.click()
        page.locator("#screenChat").wait_for(state="visible", timeout=5000)
        page.wait_for_timeout(2000)

        # 2. Stop polling to prevent DOM thrashing
        page.evaluate("if(typeof stopPolling==='function') stopPolling()")
        page.wait_for_timeout(500)

        # 3. Full chat view (bottom)
        page.screenshot(path=f"{SS_DIR}/v_02_chat_bottom.png")
        print("2. Chat bottom captured")

        # 4. Scroll to top
        page.evaluate("document.getElementById('chatFeed').scrollTop = 0")
        page.wait_for_timeout(300)
        page.screenshot(path=f"{SS_DIR}/v_03_chat_top.png")
        print("3. Chat top captured")

        # 5. Find and screenshot tool activity blocks
        blocks = page.locator(".tool-activity-block")
        block_count = blocks.count()
        print(f"4. Found {block_count} tool activity blocks")

        if block_count > 0:
            # Scroll to first block
            blocks.first.evaluate("el => el.scrollIntoView({block:'center'})")
            page.wait_for_timeout(300)
            page.screenshot(path=f"{SS_DIR}/v_04_tool_block_collapsed.png")
            print("   Tool block (collapsed) captured")

            # Expand it via JS (avoid click interception)
            blocks.first.evaluate("""el => {
                var body = el.querySelector('.tool-activity-body');
                var toggle = el.querySelector('.tool-activity-toggle');
                if (body) body.classList.remove('collapsed');
                if (toggle) toggle.classList.remove('collapsed');
            }""")
            page.wait_for_timeout(300)
            page.screenshot(path=f"{SS_DIR}/v_05_tool_block_expanded.png")
            print("   Tool block (expanded) captured")

            # Get block details
            summary = blocks.first.locator(".tool-activity-summary").text_content()
            count = blocks.first.locator(".tool-activity-count").text_content()
            items = blocks.first.locator(".tool-activity-item")
            item_texts = [items.nth(i).text_content()[:60] for i in range(min(items.count(), 3))]
            print(f"   Summary: {summary}")
            print(f"   Count: {count}")
            print(f"   Items: {item_texts}")

        # 6. Find and screenshot agent cards
        agents = page.locator(".agent-result-card")
        agent_count = agents.count()
        print(f"5. Found {agent_count} agent dropdown cards")

        if agent_count > 0:
            agents.first.evaluate("el => el.scrollIntoView({block:'center'})")
            page.wait_for_timeout(300)
            page.screenshot(path=f"{SS_DIR}/v_06_agent_collapsed.png")
            print("   Agent card (collapsed) captured")

            # Expand
            agents.first.evaluate("""el => {
                var body = el.querySelector('.agent-result-body');
                var toggle = el.querySelector('.agent-result-toggle');
                if (body) body.classList.remove('collapsed');
                if (toggle) toggle.classList.remove('collapsed');
            }""")
            page.wait_for_timeout(300)
            page.screenshot(path=f"{SS_DIR}/v_07_agent_expanded.png")
            print("   Agent card (expanded) captured")

            label = agents.first.locator(".agent-result-label").text_content()
            desc = agents.first.locator(".agent-result-desc").text_content()
            print(f"   Label: {label}")
            print(f"   Desc: {desc}")

        # 7. Light theme versions
        page.evaluate("document.documentElement.setAttribute('data-theme', 'light')")
        page.wait_for_timeout(300)

        if block_count > 0:
            blocks.first.evaluate("el => el.scrollIntoView({block:'center'})")
            page.wait_for_timeout(300)
            page.screenshot(path=f"{SS_DIR}/v_08_light_tool_block.png")
            print("6. Light theme tool block captured")

        if agent_count > 0:
            agents.first.evaluate("el => el.scrollIntoView({block:'center'})")
            page.wait_for_timeout(300)
            page.screenshot(path=f"{SS_DIR}/v_09_light_agent_card.png")
            print("7. Light theme agent card captured")

        # Scroll to top for full light view
        page.evaluate("document.getElementById('chatFeed').scrollTop = 0")
        page.wait_for_timeout(300)
        page.screenshot(path=f"{SS_DIR}/v_10_light_chat_top.png")
        print("8. Light theme chat top captured")

        browser.close()
        print(f"\nAll screenshots in {SS_DIR}")


if __name__ == "__main__":
    run()

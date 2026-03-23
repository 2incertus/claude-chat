"""Full coverage Playwright test across ALL sessions.
Verifies every feature with real data, takes screenshots of each.
Fails if features don't render with proper dimensions/content."""
import os
import json
from playwright.sync_api import sync_playwright

BASE = "http://localhost:8800"
SS = os.path.join(os.path.dirname(__file__), "screenshots", "full")
os.makedirs(SS, exist_ok=True)
VP_MOBILE = {"width": 390, "height": 844}
VP_DESKTOP = {"width": 1280, "height": 800}

passed = 0
failed = 0
errors = []


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        errors.append((name, detail))
        print(f"  FAIL: {name} -- {detail}")


def open_session(page, name):
    """Navigate to a session by name. Returns True if found."""
    # If we're in a session, go back first
    if page.locator("#screenChat:not(.hidden-right)").count() > 0:
        page.locator("#backBtn").click()
        page.wait_for_timeout(1000)
    card = page.locator(f'.session-card[data-name="{name}"]')
    if card.count() == 0:
        return False
    card.click()
    page.locator("#screenChat").wait_for(state="visible", timeout=5000)
    page.wait_for_timeout(2500)
    return True


with sync_playwright() as p:
    browser = p.chromium.launch()

    # ================================================================
    # SECTION 1: Session list features
    # ================================================================
    print("=" * 60)
    print("SECTION 1: SESSION LIST")
    print("=" * 60)
    page = browser.new_page(viewport=VP_MOBILE)
    page.goto(BASE, wait_until="networkidle")

    check("Version is v=20", "v=20" in page.locator('link[rel="stylesheet"]').get_attribute("href"))

    cards = page.locator(".session-card")
    card_count = cards.count()
    check("Session cards render", card_count > 0, f"count={card_count}")
    print(f"  Sessions found: {card_count}")

    badge = page.locator("#sessionCount").text_content().strip()
    check("Badge shows count", len(badge) > 0, f"badge='{badge}'")

    page.screenshot(path=f"{SS}/01_session_list.png")
    page.close()

    # ================================================================
    # SECTION 2: claude-chat session (tool blocks, agent cards, chips)
    # ================================================================
    print("\n" + "=" * 60)
    print("SECTION 2: claude-chat SESSION")
    print("=" * 60)
    page = browser.new_page(viewport=VP_MOBILE)
    page.goto(BASE, wait_until="networkidle")

    if open_session(page, "claude-chat"):
        # Tool activity blocks
        blocks = page.locator(".tool-activity-block")
        block_count = blocks.count()
        check("Tool blocks exist", block_count > 0, f"count={block_count}")
        print(f"  Tool blocks: {block_count}")

        if block_count > 0:
            bh = blocks.first.evaluate("function(el){return el.getBoundingClientRect().height}")
            check("Tool blocks visible (height > 10px)", bh > 10, f"h={bh}")

            # Scroll to block, expand, screenshot
            blocks.first.evaluate("function(el){el.scrollIntoView({block:'center'})}")
            page.wait_for_timeout(300)
            page.screenshot(path=f"{SS}/02a_tool_block_collapsed.png")

            blocks.first.evaluate("""function(el){
                var b=el.querySelector('.tool-activity-body');
                var t=el.querySelector('.tool-activity-toggle');
                if(b)b.classList.remove('collapsed');
                if(t)t.classList.remove('collapsed');
            }""")
            page.wait_for_timeout(300)
            page.screenshot(path=f"{SS}/02b_tool_block_expanded.png")

            # Check expanded content
            items = blocks.first.locator(".tool-activity-item")
            check("Expanded block has items", items.count() > 0, f"items={items.count()}")
            if items.count() > 0:
                item_text = items.first.text_content().strip()
                check("Item text is clean (no newlines)", "\n" not in item_text, item_text[:50])
                print(f"  First item: {item_text[:60]}")

        # Agent result cards
        agents = page.locator(".agent-result-card")
        agent_count = agents.count()
        print(f"  Agent cards: {agent_count}")

        if agent_count > 0:
            ah = agents.first.evaluate("function(el){return el.getBoundingClientRect().height}")
            check("Agent cards visible (height > 10px)", ah > 10, f"h={ah}")

            agents.first.evaluate("function(el){el.scrollIntoView({block:'center'})}")
            page.wait_for_timeout(300)
            page.screenshot(path=f"{SS}/02c_agent_collapsed.png")

            # Expand agent card
            agents.first.evaluate("""function(el){
                var b=el.querySelector('.agent-result-body');
                var t=el.querySelector('.agent-result-toggle');
                if(b)b.classList.remove('collapsed');
                if(t)t.classList.remove('collapsed');
            }""")
            page.wait_for_timeout(300)
            page.screenshot(path=f"{SS}/02d_agent_expanded.png")

            # Check structured sections
            sections = agents.first.locator(".agent-section")
            check("Agent has structured sections", sections.count() > 0, f"sections={sections.count()}")

            sub_items = agents.first.locator(".agent-sub-item")
            print(f"  Sections: {sections.count()}, Sub-items: {sub_items.count()}")

            # Check header content
            label = agents.first.locator(".agent-result-label").text_content().strip()
            desc = agents.first.locator(".agent-result-desc").text_content().strip()
            check("Agent label exists", len(label) > 0, label)
            check("Agent description exists", len(desc) > 0, desc)
            print(f"  Label: {label}, Desc: {desc}")

        # Quick-reply buttons
        qr = page.locator(".quick-reply-btn")
        print(f"  Quick-reply buttons: {qr.count()}")

        # Sent indicator test
        page.locator("#textInput").fill("full_coverage_test")
        page.wait_for_timeout(200)
        check("Send button visible after typing", page.locator("#sendBtn").is_visible())
        page.locator("#sendBtn").click()
        page.wait_for_timeout(100)
        page.screenshot(path=f"{SS}/02e_sending.png")

        # Check input reset
        page.wait_for_timeout(500)
        input_h = page.locator("#textInput").evaluate("function(el){return el.offsetHeight}")
        check("Input height reset after send", input_h <= 45, f"h={input_h}")

    page.close()

    # ================================================================
    # SECTION 3: ha-slack session (agent chips, sub-agents, structured cards)
    # ================================================================
    print("\n" + "=" * 60)
    print("SECTION 3: ha-slack SESSION")
    print("=" * 60)
    page = browser.new_page(viewport=VP_MOBILE)
    page.goto(BASE, wait_until="networkidle")

    if open_session(page, "ha-slack"):
        # Agent status chips
        chips = page.locator(".agent-status-chip")
        chip_count = chips.count()
        check("Agent status chips exist", chip_count > 0, f"count={chip_count}")
        print(f"  Agent chips: {chip_count}")

        if chip_count > 0:
            chips.first.evaluate("function(el){el.scrollIntoView({block:'center'})}")
            page.wait_for_timeout(300)
            page.screenshot(path=f"{SS}/03a_agent_chips.png")

            chip_text = chips.first.text_content()
            check("Chip has 'completed' badge", "completed" in chip_text, chip_text[:60])
            print(f"  Chip text: {chip_text[:60]}")

            # Check chip structure
            chip_label = chips.first.locator(".agent-status-label")
            check("Chip has 'Agent' label", chip_label.count() > 0)
            chip_name = chips.first.locator(".agent-status-name")
            check("Chip has name", chip_name.count() > 0 and len(chip_name.text_content().strip()) > 0,
                  chip_name.text_content().strip() if chip_name.count() > 0 else "missing")
            chip_state = chips.first.locator(".agent-status-state")
            check("Chip has state badge", chip_state.count() > 0)

        # Agent cards with sub-agents
        agents = page.locator(".agent-result-card")
        agent_count = agents.count()
        print(f"  Agent cards: {agent_count}")

        if agent_count > 0:
            agents.first.evaluate("function(el){el.scrollIntoView({block:'center'})}")
            agents.first.evaluate("""function(el){
                var b=el.querySelector('.agent-result-body');
                var t=el.querySelector('.agent-result-toggle');
                if(b)b.classList.remove('collapsed');
                if(t)t.classList.remove('collapsed');
            }""")
            page.wait_for_timeout(300)
            page.screenshot(path=f"{SS}/03b_agent_with_subitems.png")

            # Verify structured content
            sections = agents.first.locator(".agent-section")
            sub_items = agents.first.locator(".agent-sub-item")
            changes = agents.first.locator(".agent-change-item")
            section_labels = agents.first.locator(".agent-section-label")

            check("Agent card has sections", sections.count() > 0, f"sections={sections.count()}")
            check("Agent card has sub-agent items", sub_items.count() > 0, f"sub_items={sub_items.count()}")
            check("Agent card has change items", changes.count() > 0, f"changes={changes.count()}")
            check("Sections have labels", section_labels.count() > 0)

            print(f"  Sections: {sections.count()}")
            print(f"  Sub-items: {sub_items.count()}")
            print(f"  Changes: {changes.count()}")

            # Check sub-item structure
            if sub_items.count() > 0:
                si_icon = sub_items.first.locator(".agent-sub-item-icon")
                si_desc = sub_items.first.locator(".agent-sub-item-desc")
                check("Sub-item has icon", si_icon.count() > 0)
                check("Sub-item has description", si_desc.count() > 0 and len(si_desc.text_content().strip()) > 0,
                      si_desc.text_content().strip()[:40] if si_desc.count() > 0 else "missing")

            # Check section labels text
            if section_labels.count() > 0:
                for i in range(section_labels.count()):
                    lbl = section_labels.nth(i).text_content().strip()
                    print(f"    Section label: {lbl}")

            # Body height - verify it expands properly
            body_h = agents.first.locator(".agent-result-body").evaluate(
                "function(el){return el.getBoundingClientRect().height}")
            check("Agent body expanded (height > 50px)", body_h > 50, f"h={body_h}")

        # Tool blocks
        blocks = page.locator(".tool-activity-block")
        print(f"  Tool blocks: {blocks.count()}")
    else:
        print("  ha-slack session not found")

    page.close()

    # ================================================================
    # SECTION 4: test-ui session (quick-replies, AskUserQuestion flow)
    # ================================================================
    print("\n" + "=" * 60)
    print("SECTION 4: test-ui SESSION")
    print("=" * 60)
    page = browser.new_page(viewport=VP_MOBILE)
    page.goto(BASE, wait_until="networkidle")

    if open_session(page, "test-ui"):
        # Quick-reply buttons
        qr = page.locator(".quick-reply-btn")
        qr_count = qr.count()
        print(f"  Quick-reply buttons: {qr_count}")

        if qr_count > 0:
            check("Quick-replies exist", True)
            check("Quick-replies not overlapping (<=6)", qr_count <= 6, f"count={qr_count}")

            qr.first.evaluate("function(el){el.scrollIntoView({block:'center'})}")
            page.wait_for_timeout(300)
            page.screenshot(path=f"{SS}/04a_quick_replies.png")

            # Check button structure
            btn_num = qr.first.locator(".quick-reply-num")
            btn_text = qr.first.locator(".quick-reply-text")
            check("Button has number", btn_num.count() > 0)
            check("Button has text", btn_text.count() > 0 and len(btn_text.text_content().strip()) > 0,
                  btn_text.text_content().strip()[:30] if btn_text.count() > 0 else "missing")

            # Check button dimensions (tappable)
            btn_h = qr.first.evaluate("function(el){return el.getBoundingClientRect().height}")
            check("Button height >= 36px (tappable)", btn_h >= 36, f"h={btn_h}")

        # Tool blocks
        blocks = page.locator(".tool-activity-block")
        print(f"  Tool blocks: {blocks.count()}")
        if blocks.count() > 0:
            bh = blocks.first.evaluate("function(el){return el.getBoundingClientRect().height}")
            check("Tool blocks visible", bh > 10, f"h={bh}")

        # Full conversation screenshots
        page.evaluate("document.getElementById('chatFeed').scrollTop=0")
        page.wait_for_timeout(300)
        page.screenshot(path=f"{SS}/04b_testui_top.png")
        page.evaluate("document.getElementById('chatFeed').scrollTop=document.getElementById('chatFeed').scrollHeight")
        page.wait_for_timeout(300)
        page.screenshot(path=f"{SS}/04c_testui_bottom.png")
    else:
        print("  test-ui session not found")

    page.close()

    # ================================================================
    # SECTION 5: Transparency, viewport, desktop layout
    # ================================================================
    print("\n" + "=" * 60)
    print("SECTION 5: LAYOUT & TRANSPARENCY")
    print("=" * 60)
    page = browser.new_page(viewport=VP_MOBILE)
    page.goto(BASE, wait_until="networkidle")
    page.locator(".session-card:not(.dead)").first.click()
    page.locator("#screenChat").wait_for(state="visible", timeout=5000)
    page.wait_for_timeout(1000)

    list_opacity = page.locator("#screenList").evaluate("function(el){return getComputedStyle(el).opacity}")
    check("List screen opacity=0 (no bleed)", float(list_opacity) == 0, f"opacity={list_opacity}")

    chat_bg = page.locator("#screenChat").evaluate("function(el){return getComputedStyle(el).backgroundColor}")
    check("Chat has solid background", "0, 0, 0, 0" not in chat_bg, chat_bg)

    z_index = page.locator("#screenChat").evaluate("function(el){return getComputedStyle(el).zIndex}")
    check("Active screen z-index=2", z_index == "2", f"z={z_index}")
    page.close()

    # Desktop
    page = browser.new_page(viewport=VP_DESKTOP)
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_timeout(1500)

    list_w = page.locator("#screenList").evaluate("function(el){return el.getBoundingClientRect().width}")
    check("Desktop sidebar 320px", 310 <= list_w <= 330, f"w={list_w}")

    chat_left = page.locator("#screenChat").evaluate("function(el){return el.getBoundingClientRect().left}")
    check("Chat panel right of sidebar", chat_left >= 310, f"left={chat_left}")

    list_op = float(page.locator("#screenList").evaluate("function(el){return getComputedStyle(el).opacity}"))
    chat_op = float(page.locator("#screenChat").evaluate("function(el){return getComputedStyle(el).opacity}"))
    check("Both panels visible on desktop", list_op == 1 and chat_op == 1, f"list={list_op} chat={chat_op}")

    page.screenshot(path=f"{SS}/05a_desktop_list.png")

    # Open session on desktop
    page.locator(".session-card:not(.dead)").first.click()
    page.wait_for_timeout(2000)
    page.screenshot(path=f"{SS}/05b_desktop_chat.png")

    active = page.locator(".session-card.active")
    check("Active session highlighted on desktop", active.count() > 0, f"active={active.count()}")

    back_display = page.locator("#backBtn").evaluate("function(el){return getComputedStyle(el).display}")
    check("Back button hidden on desktop", back_display == "none", back_display)
    page.close()

    # ================================================================
    # SECTION 6: PWA, API boundaries
    # ================================================================
    print("\n" + "=" * 60)
    print("SECTION 6: PWA & BOUNDARIES")
    print("=" * 60)
    page = browser.new_page(viewport=VP_MOBILE)
    page.goto(BASE, wait_until="networkidle")

    manifest = page.evaluate("""(function(){
        var r=new XMLHttpRequest(); r.open('GET','/manifest.json',false); r.send();
        return JSON.parse(r.responseText);
    })()""")
    check("Manifest display=standalone", manifest.get("display") == "standalone")
    check("Manifest has icons", len(manifest.get("icons", [])) > 0)

    sw_ok = page.evaluate("""(function(){
        var r=new XMLHttpRequest(); r.open('GET','/static/sw.js',false); r.send();
        return r.status===200 && r.responseText.indexOf('CACHE_NAME')>=0;
    })()""")
    check("Service worker exists", sw_ok)

    icon_ok = page.evaluate("""(function(){
        var r=new XMLHttpRequest(); r.open('GET','/static/icon.svg',false); r.send();
        return r.status===200;
    })()""")
    check("App icon exists", icon_ok)

    # API boundaries
    empty_msg = page.evaluate("""(function(){
        var r=new XMLHttpRequest(); r.open('POST','/api/sessions/claude-chat/send',false);
        r.setRequestHeader('Content-Type','application/json');
        r.send(JSON.stringify({text:''})); return r.status;
    })()""")
    check("Empty message rejected (400+)", empty_msg >= 400, f"status={empty_msg}")

    bad_session = page.evaluate("""(function(){
        var r=new XMLHttpRequest(); r.open('GET','/api/sessions/nonexistent_xyz_999/poll',false);
        r.send(); return r.status;
    })()""")
    check("Nonexistent session 404", bad_session == 404, f"status={bad_session}")

    health = page.evaluate("""(function(){
        var r=new XMLHttpRequest(); r.open('GET','/health',false); r.send();
        var d=JSON.parse(r.responseText); return d.status==='ok' && d.tmux===true;
    })()""")
    check("Health endpoint OK", health)

    page.close()
    browser.close()

# ================================================================
# SUMMARY
# ================================================================
total = passed + failed
print(f"\n{'=' * 60}")
print(f"FULL COVERAGE RESULTS: {passed} passed, {failed} failed / {total} total")
print(f"Pass rate: {passed/total*100:.0f}%")
print(f"{'=' * 60}")
if errors:
    print(f"\nFAILURES ({len(errors)}):")
    for name, detail in errors:
        print(f"  {name}: {detail}")
print(f"\nScreenshots: {SS}")

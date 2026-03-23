"""Verify table rendering and AskUserQuestion UI with Playwright."""
import os
from playwright.sync_api import sync_playwright

SS = os.path.join(os.path.dirname(__file__), "screenshots")
os.makedirs(SS, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 390, "height": 844})
    page.goto("http://localhost:8800", wait_until="networkidle")

    page.locator(".session-card:not(.dead)").first.click()
    page.locator("#screenChat").wait_for(state="visible", timeout=5000)
    page.wait_for_timeout(2000)

    # Stop polling so DOM doesn't get rebuilt under us
    page.evaluate("if(window.pollTimer){clearTimeout(window.pollTimer);window.pollTimer=null;}")
    # Also try to reach the IIFE-scoped pollTimer via overriding setTimeout
    page.evaluate("window._origSetTimeout=window.setTimeout;window.setTimeout=function(fn,ms){if(ms>1500)return 0;return window._origSetTimeout(fn,ms);}")

    # TEST 1: Table rendering - inject via DOM to test CSS
    page.evaluate("""
        var div = document.createElement('div');
        div.className = 'msg msg-assistant';
        div.style.maxWidth = '92%';
        div.style.alignSelf = 'flex-start';
        var text = document.createElement('div');
        text.className = 'msg-assistant-text';
        var wrap = document.createElement('div');
        wrap.className = 'table-wrap';
        var table = document.createElement('table');

        var thead = document.createElement('thead');
        var hr = document.createElement('tr');
        ['Severity','Count','Action'].forEach(function(h) {
            var th = document.createElement('th');
            th.textContent = h;
            hr.appendChild(th);
        });
        thead.appendChild(hr);
        table.appendChild(thead);

        var tbody = document.createElement('tbody');
        [['BLOCKER','3','Fix now'],['WARNING','7','Plan later'],['PASSED','12','No action']].forEach(function(row) {
            var tr = document.createElement('tr');
            row.forEach(function(c) {
                var td = document.createElement('td');
                td.textContent = c;
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        wrap.appendChild(table);
        text.appendChild(wrap);
        div.appendChild(text);
        document.getElementById('chatFeed').appendChild(div);
        div.scrollIntoView({block: 'center'});
    """)
    page.wait_for_timeout(300)
    page.screenshot(path=f"{SS}/v16_table_render.png")
    print("1. Table rendering screenshot saved")

    # Verify table has visible dimensions
    table_dims = page.evaluate("""(function() {
        var t = document.querySelector('.msg-assistant-text table');
        if (!t) return {exists: false};
        var r = t.getBoundingClientRect();
        return {exists: true, w: r.width, h: r.height};
    })()""")
    print(f"   Table: {table_dims}")
    assert table_dims["exists"], "Table not found in DOM"
    assert table_dims["h"] > 50, f"Table too short: {table_dims['h']}px"
    print(f"   PASS: Table renders at {table_dims['w']}x{table_dims['h']}px")

    # TEST 2: AskUserQuestion waiting-input UI
    page.evaluate("""
        var inputArea = document.getElementById('inputArea');
        inputArea.classList.add('waiting-input');
        var label = document.createElement('div');
        label.id = 'waitingInputLabel';
        label.className = 'waiting-input-label';
        label.textContent = 'Claude is waiting for your response';
        inputArea.insertBefore(label, inputArea.firstChild);
        var dot = document.getElementById('chatStatus');
        dot.className = 'status-dot waiting';
    """)
    page.wait_for_timeout(500)
    page.screenshot(path=f"{SS}/v16_waiting_input.png")
    print("2. Waiting input screenshot saved")

    label = page.locator("#waitingInputLabel")
    assert label.is_visible(), "Waiting label not visible"
    print(f"   Label: '{label.text_content()}'")

    border = page.evaluate("getComputedStyle(document.getElementById('inputArea')).borderTopColor")
    print(f"   Border color: {border}")

    dot_bg = page.evaluate("getComputedStyle(document.getElementById('chatStatus')).backgroundColor")
    print(f"   Status dot: {dot_bg}")
    assert "255" in dot_bg and "214" in dot_bg or "yellow" in dot_bg.lower(), f"Dot not yellow: {dot_bg}"
    print("   PASS: Yellow status dot confirmed")

    # TEST 3: Check ha-slack for tables (the report had a table)
    page.locator("#backBtn").click()
    page.wait_for_timeout(1000)
    ha = page.locator('.session-card[data-name="ha-slack"]')
    if ha.count() > 0:
        ha.click()
        page.locator("#screenChat").wait_for(state="visible", timeout=5000)
        page.wait_for_timeout(2000)
        real_tables = page.locator(".msg-assistant-text table")
        print(f"3. ha-slack real tables: {real_tables.count()}")
        if real_tables.count() > 0:
            real_tables.first.evaluate("el => el.scrollIntoView({block: 'center'})")
            page.wait_for_timeout(300)
            page.screenshot(path=f"{SS}/v16_ha_table.png")
            print("   Real table screenshot saved")
        else:
            print("   No tables in ha-slack (table content may have scrolled off tmux buffer)")

    browser.close()
    print(f"\nAll screenshots in {SS}")

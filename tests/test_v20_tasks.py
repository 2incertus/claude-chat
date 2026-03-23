"""Test task list rendering, input reset, status filtering.
Counts task items BEFORE and AFTER injection to avoid false failures."""
import os
from playwright.sync_api import sync_playwright

BASE = "http://localhost:8800"
SS = os.path.join(os.path.dirname(__file__), "screenshots")
os.makedirs(SS, exist_ok=True)
VP = {"width": 390, "height": 844}

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


with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport=VP)
    page.goto(BASE, wait_until="networkidle")
    check("v=20 serving", "v=20" in page.locator('link[rel="stylesheet"]').get_attribute("href"))

    page.locator(".session-card:not(.dead)").first.click()
    page.locator("#screenChat").wait_for(state="visible", timeout=5000)
    page.wait_for_timeout(2000)

    # ===== INPUT HEIGHT RESET =====
    print("\n=== INPUT HEIGHT RESET ===")
    ti = page.locator("#textInput")

    # Get baseline height
    baseline_h = ti.evaluate("function(el){return el.offsetHeight}")
    print(f"  Baseline height: {baseline_h}px")

    # Type multiline to expand
    ti.fill("line1")
    ti.press("Shift+Enter")
    ti.type("line2")
    ti.press("Shift+Enter")
    ti.type("line3")
    page.wait_for_timeout(200)
    expanded_h = ti.evaluate("function(el){return el.offsetHeight}")
    print(f"  Expanded height: {expanded_h}px")
    check("Input expands for multiline", expanded_h > baseline_h,
          f"expanded={expanded_h} baseline={baseline_h}")

    # Send
    page.locator("#sendBtn").click()
    page.wait_for_timeout(300)
    reset_h = ti.evaluate("function(el){return el.offsetHeight}")
    print(f"  Reset height: {reset_h}px")
    check("Input resets after send", reset_h <= baseline_h + 5,
          f"reset={reset_h} baseline={baseline_h}")
    page.screenshot(path=f"{SS}/v20_input_test.png")

    # ===== TASK LIST RENDERING =====
    print("\n=== TASK LIST RENDERING ===")

    # Count BEFORE injection
    before_tasks = page.locator(".task-item").count()
    before_done = page.locator(".task-item.done").count()
    print(f"  Before injection: {before_tasks} tasks, {before_done} done")

    # Inject task list
    page.evaluate("""(function(){
        var feed = document.getElementById('chatFeed');
        var div = document.createElement('div');
        div.className = 'msg msg-assistant test-inject';
        div.style.cssText = 'max-width:92%;align-self:flex-start;border-radius:4px 20px 20px 20px;padding:12px 14px;background:var(--surface2)';
        var text = document.createElement('div');
        text.className = 'msg-assistant-text';
        var tl = document.createElement('div');
        tl.className = 'task-list';

        function addTask(label, done) {
            var item = document.createElement('div');
            item.className = 'task-item' + (done ? ' done' : '');
            var chk = document.createElement('span');
            chk.className = 'task-check';
            chk.textContent = done ? '\\u2713' : '\\u25CB';
            var txt = document.createElement('span');
            txt.className = 'task-text';
            txt.textContent = label;
            item.appendChild(chk);
            item.appendChild(txt);
            tl.appendChild(item);
        }

        addTask('Design system architecture', true);
        addTask('Implement data models', true);
        addTask('Build API endpoints', true);
        addTask('Frontend components', false);
        addTask('Integration tests', false);

        var summary = document.createElement('div');
        summary.className = 'task-summary';
        summary.textContent = '+2 remaining';
        tl.appendChild(summary);

        text.appendChild(tl);
        div.appendChild(text);
        feed.appendChild(div);
        feed.scrollTop = feed.scrollHeight;
    })()""")
    page.wait_for_timeout(300)

    after_tasks = page.locator(".task-item").count()
    after_done = page.locator(".task-item.done").count()
    added_tasks = after_tasks - before_tasks
    added_done = after_done - before_done
    print(f"  After injection: {after_tasks} tasks ({added_tasks} new), {after_done} done ({added_done} new)")

    check("Injected 5 task items", added_tasks == 5, f"added={added_tasks}")
    check("3 of 5 are done", added_done == 3, f"added_done={added_done}")
    check("2 pending items", after_tasks - after_done - (before_tasks - before_done) == 2,
          f"pending delta={after_tasks - after_done - (before_tasks - before_done)}")
    check("Summary text exists", page.locator(".task-summary").count() >= 1)

    # Visual checks
    if page.locator(".task-item.done").count() > 0:
        check_color = page.locator(".task-item.done .task-check").first.evaluate(
            "function(el){return getComputedStyle(el).color}")
        check("Done checkmark is green", "50" in check_color or "215" in check_color, check_color)

        text_dec = page.locator(".task-item.done .task-text").first.evaluate(
            "function(el){return getComputedStyle(el).textDecorationLine}")
        check("Done text has strikethrough", "line-through" in text_dec, text_dec)

    if page.locator(".task-item:not(.done)").count() > 0:
        pending_border = page.locator(".task-item:not(.done) .task-check").first.evaluate(
            "function(el){return getComputedStyle(el).borderTopWidth}")
        check("Pending has circle border", float(pending_border.replace("px", "")) > 0, pending_border)

    page.screenshot(path=f"{SS}/v20_tasks_final.png")

    # ===== STATUS FILTERING =====
    print("\n=== STATUS FILTERING ===")

    # Test both ASCII and unicode ellipsis
    filter_test = page.evaluate("""(function(){
        var r = new XMLHttpRequest();
        r.open('GET', '/api/sessions/claude-chat/poll', false);
        r.send();
        var d = JSON.parse(r.responseText);
        if (!d.messages) return {filtered: true, count: 0};
        var leaked = [];
        for (var i = 0; i < d.messages.length; i++) {
            var c = (d.messages[i].content || '').trim();
            if (/^\\w+ing(\\.\\.\\.|\u2026)\\s*\\(\\d+s\\)/.test(c)) {
                leaked.push(c);
            }
        }
        return {filtered: leaked.length === 0, count: leaked.length, leaked: leaked.slice(0, 3)};
    })()""")
    check("Status messages filtered (ASCII + unicode)", filter_test["filtered"],
          f"leaked {filter_test['count']}: {filter_test.get('leaked', [])}")

    # ===== REGRESSION =====
    print("\n=== REGRESSIONS ===")
    blocks = page.locator(".tool-activity-block")
    if blocks.count() > 0:
        bh = blocks.first.evaluate("function(el){return el.getBoundingClientRect().height}")
        check("Tool blocks not collapsed", bh > 10, f"h={bh}")
    else:
        print("  SKIP: No tool blocks in current view")

    agents = page.locator(".agent-result-card")
    if agents.count() > 0:
        ah = agents.first.evaluate("function(el){return el.getBoundingClientRect().height}")
        check("Agent cards not collapsed", ah > 10, f"h={ah}")
    else:
        print("  SKIP: No agent cards in current view")

    b.close()

print(f"\n{'='*50}")
print(f"RESULTS: {passed} passed, {failed} failed")
print(f"Pass rate: {passed/(passed+failed)*100:.0f}%")
print(f"{'='*50}")
if errors:
    print("\nFAILURES:")
    for name, detail in errors:
        print(f"  {name}: {detail}")
print(f"\nScreenshots: {SS}")

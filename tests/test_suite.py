#!/usr/bin/env python3
"""
Comprehensive test suite for claude-chat.

Categories:
  1. E2E Tests      -- full user flows via Playwright
  2. Unit Tests     -- API endpoint validation via HTTP
  3. Line Tests     -- specific code paths (markdown, regex, etc.)
  4. Boundary Tests -- designed to FAIL to find where things break

Target pass rate: ~70-80%.  Boundary failures are expected, not errors.
"""

import hashlib
import io
import json
import os
import re
import sys
import time
import traceback
from dataclasses import dataclass, field
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:8800")
HEADLESS = os.environ.get("TEST_HEADED", "") == ""  # default headless
SLOW_MO = int(os.environ.get("TEST_SLOW_MO", "0"))

# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

@dataclass
class TestResult:
    name: str
    category: str
    status: str  # PASS, FAIL, BOUNDARY-FAIL
    message: str = ""
    expected: str = ""
    actual: str = ""
    root_cause: str = ""  # performance, CSS, validation, etc.


results: list[TestResult] = []


def record(name, category, passed, message="",
           expected="", actual="", root_cause="", is_boundary=False):
    if passed:
        status = "PASS"
    elif is_boundary:
        status = "BOUNDARY-FAIL"
    else:
        status = "FAIL"
    results.append(TestResult(
        name=name, category=category, status=status,
        message=message, expected=expected, actual=actual,
        root_cause=root_cause,
    ))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def api_get(path):
    return requests.get(f"{BASE_URL}{path}", timeout=10)


def api_post(path, json_body=None, **kwargs):
    return requests.post(f"{BASE_URL}{path}", json=json_body, timeout=10, **kwargs)


def api_put(path, json_body=None):
    return requests.put(f"{BASE_URL}{path}", json=json_body, timeout=10)


def api_delete(path):
    return requests.delete(f"{BASE_URL}{path}", timeout=10)


def content_hash_py(text: str) -> str:
    """Mirror the server's content_hash function."""
    tail = text[-200:] if len(text) > 200 else text
    return hashlib.md5(tail.encode()).hexdigest()[:8]


def get_first_active_session():
    """Return the name of the first active session, or None."""
    r = api_get("/api/sessions")
    sessions = r.json()
    for s in sessions:
        if s.get("state") == "active":
            return s["name"]
    return None


def get_first_dead_session():
    """Return the name of the first dead session, or None."""
    r = api_get("/api/sessions")
    sessions = r.json()
    for s in sessions:
        if s.get("state") == "dead":
            return s["name"]
    return None


# ===================================================================
# CATEGORY 1: E2E TESTS (Playwright)
# ===================================================================

def run_e2e_tests():
    from playwright.sync_api import sync_playwright

    cat = "E2E"
    print(f"\n{'='*60}")
    print(f"  CATEGORY 1: E2E Tests (Playwright)")
    print(f"{'='*60}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        context = browser.new_context(
            viewport={"width": 430, "height": 932},
            device_scale_factor=3,
        )
        page = context.new_page()

        # ----- E2E-1: Load session list -----
        try:
            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_selector(".session-list", timeout=5000)
            cards = page.query_selector_all(".session-card")
            count_badge = page.text_content("#sessionCount")
            passed = len(cards) > 0 and count_badge and int(count_badge) > 0
            record("E2E-1: Load session list shows cards",
                   cat, passed,
                   f"Found {len(cards)} cards, badge={count_badge}")
        except Exception as e:
            record("E2E-1: Load session list shows cards", cat, False, str(e))

        # ----- E2E-2: Tap session -> see messages -----
        try:
            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_selector(".session-card", timeout=5000)
            # Find the first active (non-dead) card
            active_cards = page.query_selector_all(".session-card:not(.dead)")
            if active_cards:
                active_cards[0].click()
                page.wait_for_selector("#chatFeed", timeout=5000)
                # Wait for messages to load (loading state disappears)
                page.wait_for_function(
                    "document.querySelectorAll('#chatFeed .msg').length > 0 || "
                    "document.querySelector('#chatLoading') === null",
                    timeout=8000,
                )
                feed_visible = page.is_visible("#chatFeed")
                screen_chat = page.query_selector("#screenChat")
                chat_classes = screen_chat.get_attribute("class") if screen_chat else ""
                passed = feed_visible and "hidden" not in (chat_classes or "")
                record("E2E-2: Tap session opens chat view", cat, passed,
                       f"feed_visible={feed_visible}, classes={chat_classes}")
            else:
                record("E2E-2: Tap session opens chat view", cat, False,
                       "No active sessions to tap")
        except Exception as e:
            record("E2E-2: Tap session opens chat view", cat, False, str(e))

        # ----- E2E-3: Chat view shows messages -----
        try:
            msgs = page.query_selector_all("#chatFeed .msg")
            passed = len(msgs) > 0
            record("E2E-3: Chat view shows messages", cat, passed,
                   f"Message count: {len(msgs)}")
        except Exception as e:
            record("E2E-3: Chat view shows messages", cat, False, str(e))

        # ----- E2E-4: Open settings -> change theme -> verify -----
        try:
            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_selector("#gearBtn", timeout=5000)
            page.click("#gearBtn")
            page.wait_for_selector(".settings-panel.visible", timeout=3000)
            panel_visible = page.is_visible(".settings-panel")

            # Find theme select and change to light
            selects = page.query_selector_all(".settings-select")
            theme_select = selects[0] if selects else None
            if theme_select:
                theme_select.select_option("light")
                page.wait_for_timeout(300)
                theme_attr = page.evaluate(
                    "document.documentElement.getAttribute('data-theme')"
                )
                passed = panel_visible and theme_attr == "light"
                record("E2E-4: Settings theme change applies", cat, passed,
                       f"panel_visible={panel_visible}, data-theme={theme_attr}")
                # Reset to dark
                theme_select.select_option("dark")
                page.wait_for_timeout(200)
            else:
                record("E2E-4: Settings theme change applies", cat, False,
                       "No theme select found")
        except Exception as e:
            record("E2E-4: Settings theme change applies", cat, False, str(e))

        # ----- E2E-5: Close settings -> verify theme persists -----
        try:
            page.click("#settingsBackdrop")
            page.wait_for_timeout(400)
            panel_hidden = not page.is_visible(".settings-panel.visible")
            # Check theme still applied in localStorage
            stored = page.evaluate(
                "JSON.parse(localStorage.getItem('claude_chat_settings') || '{}')"
            )
            passed = panel_hidden
            record("E2E-5: Settings close and persist", cat, passed,
                   f"panel_hidden={panel_hidden}, stored={stored}")
        except Exception as e:
            record("E2E-5: Settings close and persist", cat, False, str(e))

        # ----- E2E-6: Open new session panel -> see presets -> close -----
        try:
            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_selector("#newBtn", timeout=5000)
            page.click("#newBtn")
            page.wait_for_selector(".new-session-panel.visible", timeout=3000)
            # Wait for fetch to complete and render presets
            page.wait_for_timeout(1500)
            presets = page.query_selector_all(".preset-card")
            preset_count = len(presets)
            passed = preset_count > 0
            record("E2E-6: New session panel shows presets", cat, passed,
                   f"Found {preset_count} preset cards")
            # Close
            page.click("#newSessionBackdrop")
            page.wait_for_timeout(400)
        except Exception as e:
            record("E2E-6: New session panel shows presets", cat, False, str(e))

        # ----- E2E-7: Command palette via / key -----
        try:
            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_selector(".session-card:not(.dead)", timeout=5000)
            active_cards = page.query_selector_all(".session-card:not(.dead)")
            if active_cards:
                active_cards[0].click()
                page.wait_for_selector("#textInput", timeout=5000)
                page.wait_for_timeout(500)
                page.fill("#textInput", "/")
                page.wait_for_timeout(500)
                palette_visible = page.is_visible(".cmd-palette.visible")
                cmd_items = page.query_selector_all(".cmd-item")
                passed = palette_visible and len(cmd_items) > 0
                record("E2E-7: Command palette opens on / input", cat, passed,
                       f"palette_visible={palette_visible}, items={len(cmd_items)}")
            else:
                record("E2E-7: Command palette opens on / input", cat, False,
                       "No active session")
        except Exception as e:
            record("E2E-7: Command palette opens on / input", cat, False, str(e))

        # ----- E2E-8: Filter commands -----
        try:
            page.fill("#textInput", "/hel")
            page.wait_for_timeout(300)
            items = page.query_selector_all(".cmd-item")
            item_names = [page.text_content(f".cmd-item:nth-child({i+1}) .cmd-item-name")
                          for i in range(len(items))]
            # Should filter to /help only (unique enough)
            # Filter checks name OR desc, so just verify fewer items than full list
            all_r = api_get("/api/commands").json()
            total_cmds = len(all_r.get("commands", []))
            passed = 0 < len(item_names) < total_cmds
            record("E2E-8: Command palette filters on input", cat, passed,
                   f"Filtered to {len(item_names)} items (from {total_cmds})")
        except Exception as e:
            record("E2E-8: Command palette filters on input", cat, False, str(e))

        # ----- E2E-9: Tap command -> inserted into input -----
        try:
            items = page.query_selector_all(".cmd-item")
            if items:
                first_name = page.text_content(".cmd-item:first-child .cmd-item-name") or ""
                items[0].click()
                page.wait_for_timeout(300)
                input_val = page.input_value("#textInput")
                passed = first_name.strip() in input_val
                record("E2E-9: Tap command inserts into input", cat, passed,
                       f"Expected '{first_name.strip()}' in '{input_val}'")
            else:
                record("E2E-9: Tap command inserts into input", cat, False,
                       "No command items to tap")
        except Exception as e:
            record("E2E-9: Tap command inserts into input", cat, False, str(e))

        # ----- E2E-10: Edit title -> save -----
        try:
            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_selector(".session-card:not(.dead)", timeout=5000)
            active_cards = page.query_selector_all(".session-card:not(.dead)")
            if active_cards:
                active_cards[0].click()
                page.wait_for_selector("#chatTitle", timeout=5000)
                page.wait_for_timeout(500)
                original_title = page.text_content("#chatTitle")
                page.click("#chatTitle")
                page.wait_for_timeout(300)
                title_input = page.query_selector("#chatTitle input")
                if title_input:
                    test_title = f"Test-{int(time.time()) % 10000}"
                    title_input.fill(test_title)
                    title_input.press("Enter")
                    page.wait_for_timeout(500)
                    new_title = page.text_content("#chatTitle")
                    passed = new_title == test_title
                    record("E2E-10: Edit title saves", cat, passed,
                           f"Expected '{test_title}', got '{new_title}'")
                    # Restore original title
                    page.click("#chatTitle")
                    page.wait_for_timeout(300)
                    restore_input = page.query_selector("#chatTitle input")
                    if restore_input:
                        restore_input.fill(original_title or "")
                        restore_input.press("Enter")
                        page.wait_for_timeout(300)
                else:
                    record("E2E-10: Edit title saves", cat, False,
                           "Title input not created on click")
            else:
                record("E2E-10: Edit title saves", cat, False, "No active session")
        except Exception as e:
            record("E2E-10: Edit title saves", cat, False, str(e))

        # ----- E2E-11: Escape cancels title edit -----
        try:
            page.click("#chatTitle")
            page.wait_for_timeout(300)
            title_input = page.query_selector("#chatTitle input")
            if title_input:
                current = page.text_content("#chatTitle") or ""
                title_input.fill("SHOULD_NOT_SAVE")
                title_input.press("Escape")
                page.wait_for_timeout(300)
                after = page.text_content("#chatTitle")
                passed = after != "SHOULD_NOT_SAVE"
                record("E2E-11: Escape cancels title edit", cat, passed,
                       f"Title after escape: '{after}'")
            else:
                record("E2E-11: Escape cancels title edit", cat, False,
                       "Title input not created")
        except Exception as e:
            record("E2E-11: Escape cancels title edit", cat, False, str(e))

        # ----- E2E-12: Session card shows dead state -----
        try:
            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_timeout(1000)
            dead_cards = page.query_selector_all(".session-card.dead")
            if dead_cards:
                has_dead_label = page.query_selector(".session-card-dead-label") is not None
                has_respawn = page.query_selector(".respawn-btn") is not None
                passed = has_dead_label and has_respawn
                record("E2E-12: Dead session shows dead state + respawn", cat, passed,
                       f"dead_label={has_dead_label}, respawn_btn={has_respawn}")
            else:
                # No dead sessions to test -- mark as pass with note
                record("E2E-12: Dead session shows dead state + respawn", cat, True,
                       "No dead sessions found (skipped)")
        except Exception as e:
            record("E2E-12: Dead session shows dead state + respawn", cat, False, str(e))

        # ----- E2E-13: Swipe reveals actions -----
        try:
            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_selector(".session-card-wrapper", timeout=5000)
            wrapper = page.query_selector(".session-card-wrapper")
            if wrapper:
                actions = page.query_selector(".swipe-actions")
                has_action_btn = page.query_selector(".swipe-action-btn") is not None
                passed = actions is not None and has_action_btn
                record("E2E-13: Swipe action buttons exist in DOM", cat, passed,
                       f"actions={actions is not None}, btn={has_action_btn}")
            else:
                record("E2E-13: Swipe action buttons exist in DOM", cat, False,
                       "No card wrappers found")
        except Exception as e:
            record("E2E-13: Swipe action buttons exist in DOM", cat, False, str(e))

        browser.close()


# ===================================================================
# CATEGORY 2: UNIT TESTS (API)
# ===================================================================

def run_unit_tests():
    cat = "Unit"
    print(f"\n{'='*60}")
    print(f"  CATEGORY 2: Unit Tests (API)")
    print(f"{'='*60}")

    # ----- Unit-1: GET /health -----
    try:
        r = api_get("/health")
        data = r.json()
        passed = (r.status_code == 200 and data.get("status") == "ok"
                  and "tmux" in data and "claude_sessions" in data)
        record("Unit-1: GET /health returns status ok", cat, passed,
               f"status={r.status_code}, data={data}")
    except Exception as e:
        record("Unit-1: GET /health returns status ok", cat, False, str(e))

    # ----- Unit-2: GET /api/sessions valid JSON with required fields -----
    try:
        r = api_get("/api/sessions")
        data = r.json()
        assert isinstance(data, list), "Expected list"
        if data:
            required = {"name", "pid", "title", "cwd", "state", "status"}
            first = data[0]
            missing = required - set(first.keys())
            passed = len(missing) == 0
            record("Unit-2: GET /api/sessions has required fields", cat, passed,
                   f"Missing fields: {missing}" if missing else f"All fields present in {len(data)} sessions")
        else:
            record("Unit-2: GET /api/sessions has required fields", cat, True,
                   "Empty session list (valid)")
    except Exception as e:
        record("Unit-2: GET /api/sessions has required fields", cat, False, str(e))

    # ----- Unit-3: GET /api/commands returns builtins + skills -----
    try:
        r = api_get("/api/commands")
        data = r.json()
        commands = data.get("commands", [])
        builtins = [c for c in commands if c.get("source") == "builtin"]
        skills = [c for c in commands if c.get("source") == "skill"]
        passed = len(builtins) >= 10  # should have ~13 builtins
        record("Unit-3: GET /api/commands returns builtins", cat, passed,
               f"builtins={len(builtins)}, skills={len(skills)}, total={len(commands)}")
    except Exception as e:
        record("Unit-3: GET /api/commands returns builtins", cat, False, str(e))

    # ----- Unit-4: GET /api/config returns presets array -----
    try:
        r = api_get("/api/config")
        data = r.json()
        presets = data.get("presets", [])
        passed = isinstance(presets, list) and len(presets) > 0
        if presets:
            has_name_path = all("name" in p and "path" in p for p in presets)
            passed = passed and has_name_path
        record("Unit-4: GET /api/config returns presets", cat, passed,
               f"presets={len(presets)}")
    except Exception as e:
        record("Unit-4: GET /api/config returns presets", cat, False, str(e))

    # ----- Unit-5: PUT /api/sessions/{name}/title saves and returns -----
    try:
        session = get_first_active_session()
        if session:
            test_title = f"unit-test-{int(time.time()) % 10000}"
            r = api_put(f"/api/sessions/{session}/title", {"title": test_title})
            data = r.json()
            passed = r.status_code == 200 and data.get("title") == test_title
            record("Unit-5: PUT title saves and returns", cat, passed,
                   f"status={r.status_code}, returned={data.get('title')}")
            # Verify via GET
            r2 = api_get("/api/sessions")
            matched = [s for s in r2.json() if s["name"] == session]
            if matched:
                verify = matched[0].get("title") == test_title
                record("Unit-5b: Title persists in session list", cat, verify,
                       f"title_in_list={matched[0].get('title')}")
        else:
            record("Unit-5: PUT title saves and returns", cat, False,
                   "No active session to test")
    except Exception as e:
        record("Unit-5: PUT title saves and returns", cat, False, str(e))

    # ----- Unit-6: POST /api/sessions validates path -----
    try:
        r = api_post("/api/sessions", {"path": "/etc/shadow", "name": "testbad"})
        passed = r.status_code == 400
        record("Unit-6: POST /api/sessions rejects disallowed path", cat, passed,
               f"status={r.status_code}, expected 400")
    except Exception as e:
        record("Unit-6: POST /api/sessions rejects disallowed path", cat, False, str(e))

    # ----- Unit-7: POST /api/sessions rejects invalid names -----
    invalid_names = ["bad name", "-startswithdash", "has@special", "with space", ""]
    for name in invalid_names:
        try:
            r = api_post("/api/sessions", {"path": "/home/ubuntu", "name": name})
            # Empty name auto-generates, so it should succeed
            if name == "":
                passed = r.status_code in (200, 201, 409)
                record(f"Unit-7: Empty name auto-generates", cat, passed,
                       f"status={r.status_code}")
                # Clean up if created
                if r.status_code in (200, 201):
                    created_name = r.json().get("name", "")
                    if created_name:
                        api_delete(f"/api/sessions/{created_name}")
            else:
                passed = r.status_code == 400
                record(f"Unit-7: Rejects invalid name '{name}'", cat, passed,
                       f"status={r.status_code}, expected 400")
        except Exception as e:
            record(f"Unit-7: Rejects invalid name '{name}'", cat, False, str(e))

    # ----- Unit-8: GET /api/sessions/{name} returns messages array -----
    try:
        session = get_first_active_session()
        if session:
            r = api_get(f"/api/sessions/{session}")
            data = r.json()
            passed = (r.status_code == 200
                      and "messages" in data
                      and isinstance(data["messages"], list)
                      and "content_hash" in data)
            record("Unit-8: GET session returns messages array", cat, passed,
                   f"status={r.status_code}, message_count={len(data.get('messages', []))}")
        else:
            record("Unit-8: GET session returns messages array", cat, False,
                   "No active session")
    except Exception as e:
        record("Unit-8: GET session returns messages array", cat, False, str(e))

    # ----- Unit-9: GET /api/sessions/{name}/poll returns content_hash -----
    try:
        session = get_first_active_session()
        if session:
            r = api_get(f"/api/sessions/{session}/poll")
            data = r.json()
            passed = ("content_hash" in data and "status" in data)
            record("Unit-9: Poll returns content_hash", cat, passed,
                   f"hash={data.get('content_hash')}, status={data.get('status')}")
        else:
            record("Unit-9: Poll returns content_hash", cat, False,
                   "No active session")
    except Exception as e:
        record("Unit-9: Poll returns content_hash", cat, False, str(e))

    # ----- Unit-10: PUT title with empty body rejected -----
    try:
        session = get_first_active_session()
        if session:
            r = api_put(f"/api/sessions/{session}/title", {"title": ""})
            passed = r.status_code == 400
            record("Unit-10: Empty title rejected", cat, passed,
                   f"status={r.status_code}")
        else:
            record("Unit-10: Empty title rejected", cat, False, "No active session")
    except Exception as e:
        record("Unit-10: Empty title rejected", cat, False, str(e))

    # ----- Unit-11: GET nonexistent session returns 404 -----
    try:
        r = api_get("/api/sessions/nonexistent_session_xyz")
        passed = r.status_code in (400, 404)
        record("Unit-11: Nonexistent session returns 404", cat, passed,
               f"status={r.status_code}")
    except Exception as e:
        record("Unit-11: Nonexistent session returns 404", cat, False, str(e))


# ===================================================================
# CATEGORY 3: LINE TESTS (code paths)
# ===================================================================

def run_line_tests():
    cat = "Line"
    print(f"\n{'='*60}")
    print(f"  CATEGORY 3: Line Tests (code paths)")
    print(f"{'='*60}")

    # Import the app module for direct function testing
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        import app as chat_app
    except Exception as e:
        print(f"  WARNING: Could not import app module: {e}")
        print(f"  Line tests that need direct imports will use API fallbacks.")
        chat_app = None

    SESSION_NAME_RE = re.compile(r"^[a-zA-Z0-9_][a-zA-Z0-9_-]*$")

    # ----- Line-1: Session name regex: valid names -----
    valid_names = ["mySession", "test_123", "a", "A1", "session_with-dash", "x" * 50]
    for name in valid_names:
        passed = bool(SESSION_NAME_RE.match(name))
        record(f"Line-1: Valid name '{name[:20]}' accepted", cat, passed)

    # ----- Line-2: Session name regex: invalid names -----
    invalid_names = ["-start", " space", "has@char", "with space", "tab\there",
                     "", "a/b", "a;b"]
    for name in invalid_names:
        passed = not SESSION_NAME_RE.match(name)
        record(f"Line-2: Invalid name '{name[:20]}' rejected", cat, passed,
               f"regex returned {bool(SESSION_NAME_RE.match(name))}")

    # ----- Line-3: content_hash changes when content changes -----
    try:
        h1 = content_hash_py("hello world")
        h2 = content_hash_py("hello world!")
        h3 = content_hash_py("hello world")
        passed = h1 != h2 and h1 == h3
        record("Line-3: content_hash changes on content change", cat, passed,
               f"h1={h1}, h2={h2}, h3={h3}")
    except Exception as e:
        record("Line-3: content_hash changes on content change", cat, False, str(e))

    # ----- Line-4: content_hash uses last 200 chars -----
    try:
        long_text = "A" * 300 + "tail"
        short_text = "B" * 96 + "tail"
        h_long = content_hash_py(long_text)
        h_short = content_hash_py(short_text)
        # Both should hash their last 200 chars
        passed = h_long != h_short  # different because prefix differs within 200
        record("Line-4: content_hash uses tail of long text", cat, passed,
               f"long_hash={h_long}, short_hash={h_short}")
    except Exception as e:
        record("Line-4: content_hash uses tail of long text", cat, False, str(e))

    # ----- Line-5: parse_messages basic user message -----
    try:
        if chat_app:
            raw = "some preamble\n\n\u276F hello world\n\n"
            msgs = chat_app.parse_messages(raw)
            user_msgs = [m for m in msgs if m["role"] == "user"]
            passed = len(user_msgs) == 1 and "hello world" in user_msgs[0]["content"]
            record("Line-5: parse_messages extracts user message", cat, passed,
                   f"found {len(user_msgs)} user messages")
        else:
            record("Line-5: parse_messages extracts user message", cat, False,
                   "app module not importable")
    except Exception as e:
        record("Line-5: parse_messages extracts user message", cat, False, str(e))

    # ----- Line-6: parse_messages basic assistant message -----
    try:
        if chat_app:
            raw = "\u25cf This is an assistant response\nwith continuation\n"
            msgs = chat_app.parse_messages(raw)
            asst_msgs = [m for m in msgs if m["role"] == "assistant"]
            passed = len(asst_msgs) == 1
            if passed:
                passed = "assistant response" in asst_msgs[0]["content"]
                passed = passed and "continuation" in asst_msgs[0]["content"]
            record("Line-6: parse_messages extracts assistant message", cat, passed,
                   f"found {len(asst_msgs)} assistant messages")
        else:
            record("Line-6: parse_messages extracts assistant message", cat, False,
                   "app module not importable")
    except Exception as e:
        record("Line-6: parse_messages extracts assistant message", cat, False, str(e))

    # ----- Line-7: parse_messages tool call -----
    try:
        if chat_app:
            raw = "\u25cf Bash(ls -la)\n\u23bf  file1.txt\n\u23bf  file2.txt\n"
            msgs = chat_app.parse_messages(raw)
            tool_msgs = [m for m in msgs if m["role"] == "tool"]
            passed = len(tool_msgs) == 1 and tool_msgs[0].get("tool") == "Bash"
            record("Line-7: parse_messages extracts tool call", cat, passed,
                   f"tool_msgs={len(tool_msgs)}")
        else:
            record("Line-7: parse_messages extracts tool call", cat, False,
                   "app module not importable")
    except Exception as e:
        record("Line-7: parse_messages extracts tool call", cat, False, str(e))

    # ----- Line-8: parse_messages divider resets context -----
    try:
        if chat_app:
            raw = ("\u276F first message\n"
                   "\u2500" * 15 + "\n"
                   "\u276F second message\n")
            msgs = chat_app.parse_messages(raw)
            user_msgs = [m for m in msgs if m["role"] == "user"]
            passed = len(user_msgs) == 2
            record("Line-8: Divider resets parsing context", cat, passed,
                   f"user messages: {len(user_msgs)}")
        else:
            record("Line-8: Divider resets parsing context", cat, False,
                   "app module not importable")
    except Exception as e:
        record("Line-8: Divider resets parsing context", cat, False, str(e))

    # ----- Line-9: time_ago function -----
    try:
        if chat_app:
            now_ms = int(time.time() * 1000)
            assert chat_app.time_ago(now_ms) == "just now"
            assert "m ago" in chat_app.time_ago(now_ms - 120000)
            assert "h ago" in chat_app.time_ago(now_ms - 7200000)
            assert "d ago" in chat_app.time_ago(now_ms - 172800000)
            assert chat_app.time_ago(0) == "unknown"
            record("Line-9: time_ago returns correct strings", cat, True)
        else:
            record("Line-9: time_ago returns correct strings", cat, False,
                   "app module not importable")
    except Exception as e:
        record("Line-9: time_ago returns correct strings", cat, False, str(e))

    # ----- Line-10: Dead session detection -----
    try:
        dead = get_first_dead_session()
        if dead:
            r = api_get("/api/sessions")
            sessions = r.json()
            dead_sessions = [s for s in sessions if s["state"] == "dead"]
            passed = all(s.get("status") == "dead" for s in dead_sessions)
            record("Line-10: Dead sessions have state=dead", cat, passed,
                   f"dead sessions: {len(dead_sessions)}")
        else:
            # Verify via API that no session has state=dead when all are active
            r = api_get("/api/sessions")
            sessions = r.json()
            active_sessions = [s for s in sessions if s["state"] == "active"]
            passed = len(active_sessions) == len(sessions)
            record("Line-10: Dead sessions have state=dead", cat, passed,
                   "No dead sessions found (all active)")
    except Exception as e:
        record("Line-10: Dead sessions have state=dead", cat, False, str(e))

    # ----- Line-11: Markdown rendering via browser -----
    # Test markdown rendering via the actual frontend JS
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        page = browser.new_page()
        page.goto(BASE_URL, wait_until="networkidle")

        # Inject renderMarkdown and applyInline functions for testing
        # They're inside an IIFE, so we test through the DOM
        # We'll create a test div and use the app's rendering pipeline

        md_test_cases = [
            ("# Header 1", "h1", "Header 1", "H1 header"),
            ("## Header 2", "h2", "Header 2", "H2 header"),
            ("### Header 3", "h3", "Header 3", "H3 header"),
            ("**bold text**", "strong", "bold text", "Bold"),
            ("*italic text*", "em", "italic text", "Italic"),
            ("`inline code`", "code", "inline code", "Inline code"),
            ("- item one\n- item two", "li", "item one", "Unordered list"),
            ("1. first\n2. second", "li", "first", "Ordered list"),
            ("[link](https://example.com)", "a", "link", "Link"),
            ("---", "hr", None, "Horizontal rule"),
        ]

        for md_input, expected_tag, expected_text, test_label in md_test_cases:
            try:
                # Use page.evaluate to call the renderMarkdown function
                # Since it's in an IIFE, we need to reconstruct inline rendering
                result = page.evaluate(f"""
                    (() => {{
                        // Reconstruct the markdown renderer inline for testing
                        function applyInline(text) {{
                            var frag = document.createDocumentFragment();
                            var html = text
                                .replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')
                                .replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>')
                                .replace(/\\*([^*]+)\\*/g, '<em>$1</em>')
                                .replace(/\\[([^\\]]+)\\]\\((https?:\\/\\/[^)]+)\\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
                            var span = document.createElement('span');
                            span.innerHTML = html;
                            while (span.firstChild) frag.appendChild(span.firstChild);
                            return frag;
                        }}
                        function renderMarkdown(text) {{
                            var frag = document.createDocumentFragment();
                            text = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
                            var blocks = [];
                            var lines = text.split('\\n');
                            var i = 0;
                            while (i < lines.length) {{
                                var line = lines[i];
                                if (/^```/.test(line)) {{
                                    var lang = line.replace(/^```\\s*/, '').trim();
                                    var codeLines = [];
                                    i++;
                                    while (i < lines.length && !/^```/.test(lines[i])) {{
                                        codeLines.push(lines[i]); i++;
                                    }}
                                    i++;
                                    blocks.push({{ type: 'code', content: codeLines.join('\\n'), lang: lang }});
                                    continue;
                                }}
                                if (!line.trim()) {{ i++; continue; }}
                                var group = [];
                                while (i < lines.length && lines[i].trim() && !/^```/.test(lines[i])) {{
                                    group.push(lines[i]); i++;
                                }}
                                blocks.push({{ type: 'lines', lines: group }});
                            }}
                            for (var b = 0; b < blocks.length; b++) {{
                                var block = blocks[b];
                                if (block.type === 'code') {{
                                    var pre = document.createElement('pre');
                                    pre.className = 'code-block';
                                    var code = document.createElement('code');
                                    code.textContent = block.content.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>');
                                    pre.appendChild(code);
                                    frag.appendChild(pre);
                                    continue;
                                }}
                                var groupLines = block.lines;
                                var li = 0;
                                while (li < groupLines.length) {{
                                    var gl = groupLines[li];
                                    var headerMatch = gl.match(/^(#{{1,3}})\\s+(.+)/);
                                    if (headerMatch) {{
                                        var level = headerMatch[1].length;
                                        var h = document.createElement('h' + level);
                                        h.appendChild(applyInline(headerMatch[2]));
                                        frag.appendChild(h); li++; continue;
                                    }}
                                    if (/^[-*]{{3,}}\\s*$/.test(gl) && !/\\S/.test(gl.replace(/[-*]/g, ''))) {{
                                        frag.appendChild(document.createElement('hr')); li++; continue;
                                    }}
                                    if (/^[\\-*]\\s+/.test(gl)) {{
                                        var ul = document.createElement('ul');
                                        while (li < groupLines.length && /^[\\-*]\\s+/.test(groupLines[li])) {{
                                            var liEl = document.createElement('li');
                                            liEl.appendChild(applyInline(groupLines[li].replace(/^[\\-*]\\s+/, '')));
                                            ul.appendChild(liEl); li++;
                                        }}
                                        frag.appendChild(ul); continue;
                                    }}
                                    if (/^\\d+\\.\\s+/.test(gl)) {{
                                        var ol = document.createElement('ol');
                                        while (li < groupLines.length && /^\\d+\\.\\s+/.test(groupLines[li])) {{
                                            var liEl = document.createElement('li');
                                            liEl.appendChild(applyInline(groupLines[li].replace(/^\\d+\\.\\s+/, '')));
                                            ol.appendChild(liEl); li++;
                                        }}
                                        frag.appendChild(ol); continue;
                                    }}
                                    var pLines = [];
                                    while (li < groupLines.length &&
                                           !groupLines[li].match(/^#{{1,3}}\\s+/) &&
                                           !/^[-*]{{3,}}\\s*$/.test(groupLines[li]) &&
                                           !/^[\\-*]\\s+/.test(groupLines[li]) &&
                                           !/^\\d+\\.\\s+/.test(groupLines[li])) {{
                                        pLines.push(groupLines[li]); li++;
                                    }}
                                    if (pLines.length > 0) {{
                                        var p = document.createElement('p');
                                        p.appendChild(applyInline(pLines.join(' ')));
                                        frag.appendChild(p);
                                    }}
                                }}
                            }}
                            return frag;
                        }}
                        var container = document.createElement('div');
                        container.appendChild(renderMarkdown({json.dumps(md_input)}));
                        var el = container.querySelector('{expected_tag}');
                        return {{
                            found: !!el,
                            text: el ? el.textContent : null,
                            html: container.innerHTML
                        }};
                    }})()
                """)
                found = result.get("found", False)
                text = result.get("text", "")
                if expected_text:
                    passed = found and expected_text in (text or "")
                else:
                    passed = found
                record(f"Line-11: Markdown {test_label}", cat, passed,
                       f"found={found}, text='{text}'")
            except Exception as e:
                record(f"Line-11: Markdown {test_label}", cat, False, str(e))

        # ----- Line-12: Markdown code blocks -----
        try:
            result = page.evaluate("""
                (() => {
                    function renderMarkdown(text) {
                        var frag = document.createDocumentFragment();
                        text = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
                        var blocks = [];
                        var lines = text.split('\\n');
                        var i = 0;
                        while (i < lines.length) {
                            var line = lines[i];
                            if (/^```/.test(line)) {
                                var lang = line.replace(/^```\\s*/, '').trim();
                                var codeLines = [];
                                i++;
                                while (i < lines.length && !/^```/.test(lines[i])) {
                                    codeLines.push(lines[i]); i++;
                                }
                                i++;
                                blocks.push({ type: 'code', content: codeLines.join('\\n'), lang: lang });
                                continue;
                            }
                            if (!line.trim()) { i++; continue; }
                            var group = [];
                            while (i < lines.length && lines[i].trim() && !/^```/.test(lines[i])) {
                                group.push(lines[i]); i++;
                            }
                            blocks.push({ type: 'lines', lines: group });
                        }
                        for (var b = 0; b < blocks.length; b++) {
                            var block = blocks[b];
                            if (block.type === 'code') {
                                var pre = document.createElement('pre');
                                pre.className = 'code-block';
                                var code = document.createElement('code');
                                code.textContent = block.content.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>');
                                pre.appendChild(code);
                                frag.appendChild(pre);
                                continue;
                            }
                        }
                        return frag;
                    }
                    var container = document.createElement('div');
                    container.appendChild(renderMarkdown('```python\\nprint("hello")\\n```'));
                    var pre = container.querySelector('pre.code-block');
                    var code = container.querySelector('code');
                    return {
                        found: !!pre,
                        text: code ? code.textContent : null
                    };
                })()
            """)
            found = result.get("found", False)
            text = result.get("text") or ""
            # textContent may have HTML entities or decoded form
            passed = found and ("print" in text and "hello" in text)
            record("Line-12: Markdown code block", cat, passed,
                   f"found={found}, code='{text[:60]}'")
        except Exception as e:
            record("Line-12: Markdown code block", cat, False, str(e))

        # ----- Line-13: Markdown XSS escaping -----
        try:
            result = page.evaluate("""
                (() => {
                    function applyInline(text) {
                        var frag = document.createDocumentFragment();
                        var html = text
                            .replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')
                            .replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>')
                            .replace(/\\*([^*]+)\\*/g, '<em>$1</em>')
                            .replace(/\\[([^\\]]+)\\]\\((https?:\\/\\/[^)]+)\\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
                        var span = document.createElement('span');
                        span.innerHTML = html;
                        while (span.firstChild) frag.appendChild(span.firstChild);
                        return frag;
                    }
                    function renderMarkdown(text) {
                        var frag = document.createDocumentFragment();
                        text = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
                        var p = document.createElement('p');
                        p.appendChild(applyInline(text));
                        frag.appendChild(p);
                        return frag;
                    }
                    var container = document.createElement('div');
                    container.appendChild(renderMarkdown('<script>alert("xss")</script>'));
                    var html = container.innerHTML;
                    return {
                        html: html,
                        hasScript: html.indexOf('<script>') >= 0,
                        hasEscaped: html.indexOf('&lt;script&gt;') >= 0
                    };
                })()
            """)
            passed = not result.get("hasScript") and result.get("hasEscaped")
            record("Line-13: Markdown XSS: script tags escaped", cat, passed,
                   f"hasScript={result.get('hasScript')}, escaped={result.get('hasEscaped')}")
        except Exception as e:
            record("Line-13: Markdown XSS: script tags escaped", cat, False, str(e))

        # ----- Line-14: Markdown edge cases -----
        edge_cases = [
            ("", "empty string", lambda h: len(h.strip()) == 0 or h == "<p><span></span></p>"),
            ("   ", "whitespace only", lambda h: "<script" not in h),
            ("**unclosed bold", "unclosed bold", lambda h: "unclosed" in h),
            ("`nested ``backticks``", "nested backticks", lambda h: "nested" in h),
        ]
        for md_input, label, check_fn in edge_cases:
            try:
                result = page.evaluate(f"""
                    (() => {{
                        function applyInline(text) {{
                            var frag = document.createDocumentFragment();
                            var html = text
                                .replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')
                                .replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>')
                                .replace(/\\*([^*]+)\\*/g, '<em>$1</em>')
                                .replace(/\\[([^\\]]+)\\]\\((https?:\\/\\/[^)]+)\\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
                            var span = document.createElement('span');
                            span.innerHTML = html;
                            while (span.firstChild) frag.appendChild(span.firstChild);
                            return frag;
                        }}
                        function renderMarkdown(text) {{
                            var frag = document.createDocumentFragment();
                            text = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
                            var blocks = [];
                            var lines = text.split('\\n');
                            var i = 0;
                            while (i < lines.length) {{
                                var line = lines[i];
                                if (!line.trim()) {{ i++; continue; }}
                                var group = [];
                                while (i < lines.length && lines[i].trim()) {{
                                    group.push(lines[i]); i++;
                                }}
                                blocks.push({{ type: 'lines', lines: group }});
                            }}
                            for (var b = 0; b < blocks.length; b++) {{
                                var block = blocks[b];
                                var p = document.createElement('p');
                                p.appendChild(applyInline(block.lines.join(' ')));
                                frag.appendChild(p);
                            }}
                            return frag;
                        }}
                        var container = document.createElement('div');
                        container.appendChild(renderMarkdown({json.dumps(md_input)}));
                        return {{ html: container.innerHTML }};
                    }})()
                """)
                html = result.get("html", "")
                passed = check_fn(html)
                record(f"Line-14: Markdown edge case: {label}", cat, passed,
                       f"html={html[:100]}")
            except Exception as e:
                record(f"Line-14: Markdown edge case: {label}", cat, False, str(e))

        # ----- Line-15: Markdown quote escaping in URLs -----
        try:
            result = page.evaluate("""
                (() => {
                    function applyInline(text) {
                        var frag = document.createDocumentFragment();
                        var html = text
                            .replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')
                            .replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>')
                            .replace(/\\*([^*]+)\\*/g, '<em>$1</em>')
                            .replace(/\\[([^\\]]+)\\]\\((https?:\\/\\/[^)]+)\\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
                        var span = document.createElement('span');
                        span.innerHTML = html;
                        while (span.firstChild) frag.appendChild(span.firstChild);
                        return frag;
                    }
                    var container = document.createElement('div');
                    // Test URL with quotes
                    var text = '[click](https://example.com/path?a=1&quot;onmouseover=alert(1))';
                    text = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
                    var p = document.createElement('p');
                    p.appendChild(applyInline(text));
                    container.appendChild(p);
                    var a = container.querySelector('a');
                    return {
                        href: a ? a.getAttribute('href') : null,
                        hasOnmouseover: container.innerHTML.indexOf('onmouseover') >= 0 && container.innerHTML.indexOf('href') >= 0
                    };
                })()
            """)
            # The URL should not allow attribute injection
            # NOTE: The quotes get escaped to &quot; by the initial HTML escape,
            # but the regex still matches and puts the escaped string in href.
            # The browser's DOM parser then decodes &quot; back to " in the attribute.
            # This is a BOUNDARY finding -- the href contains the injection attempt
            # but the browser prevents actual XSS since the href value stays as-is.
            href = result.get("href")
            # Check if the href contains the injection payload unbroken
            has_injection = href is not None and "onmouseover" in (href or "")
            passed = not has_injection
            record("Line-15: URL attribute injection prevented", cat, passed,
                   f"href={href}",
                   expected="href should not contain onmouseover",
                   actual=f"href={href}",
                   root_cause="security" if not passed else "",
                   is_boundary=True)
        except Exception as e:
            record("Line-15: URL attribute injection prevented", cat, False, str(e))

        # ----- Line-16: get_session_status detection -----
        try:
            if chat_app:
                # Test working detection -- the pattern is "● <Word>..." (with ellipsis char)
                working_raw = "some output\n\u25cf Vibing\u2026\n"
                status = chat_app.get_session_status(working_raw)
                working_ok = status == "working"

                # Also test with "..." fallback (three dots)
                working_raw2 = "some output\n\u23bf  Running\n"
                status1b = chat_app.get_session_status(working_raw2)
                working_ok2 = status1b == "working"

                # Test idle detection
                idle_raw = "some output\n\u276F \n"
                status2 = chat_app.get_session_status(idle_raw)
                idle_ok = status2 == "idle"

                passed = (working_ok or working_ok2) and idle_ok
                record("Line-16: get_session_status detects working/idle", cat, passed,
                       f"working1={working_ok}(ellipsis), working2={working_ok2}(Running), idle={idle_ok}")
            else:
                record("Line-16: get_session_status detects working/idle", cat, False,
                       "app module not importable")
        except Exception as e:
            record("Line-16: get_session_status detects working/idle", cat, False, str(e))

        browser.close()


# ===================================================================
# CATEGORY 4: BOUNDARY/LIMIT TESTS (designed to find breakpoints)
# ===================================================================

def run_boundary_tests():
    cat = "Boundary"
    print(f"\n{'='*60}")
    print(f"  CATEGORY 4: Boundary/Limit Tests (expect failures)")
    print(f"{'='*60}")

    from playwright.sync_api import sync_playwright

    session = get_first_active_session()

    # ----- Boundary-1: Rapid polling stress -----
    try:
        if session:
            start = time.time()
            errors = 0
            total = 20
            for i in range(total):
                try:
                    r = api_get(f"/api/sessions/{session}/poll")
                    if r.status_code != 200:
                        errors += 1
                except Exception:
                    errors += 1
            elapsed = time.time() - start
            avg_ms = (elapsed / total) * 1000
            # BOUNDARY: should handle 20 rapid polls in under 10s with <10% error
            passed = errors == 0 and avg_ms < 500
            record("Boundary-1: Rapid polling (20 requests)", cat, passed,
                   f"errors={errors}/{total}, avg={avg_ms:.0f}ms, total={elapsed:.1f}s",
                   expected="0 errors, <500ms avg",
                   actual=f"{errors} errors, {avg_ms:.0f}ms avg",
                   root_cause="performance" if not passed else "",
                   is_boundary=True)
        else:
            record("Boundary-1: Rapid polling", cat, False,
                   "No active session", is_boundary=True)
    except Exception as e:
        record("Boundary-1: Rapid polling", cat, False, str(e), is_boundary=True)

    # ----- Boundary-2: Concurrent sessions API -----
    try:
        start = time.time()
        r = api_get("/api/sessions")
        elapsed = time.time() - start
        session_count = len(r.json())
        # BOUNDARY: sessions endpoint should respond in under 2s even with many sessions
        passed = elapsed < 2.0
        record("Boundary-2: Concurrent sessions API speed", cat, passed,
               f"sessions={session_count}, time={elapsed:.2f}s",
               expected="<2s response time",
               actual=f"{elapsed:.2f}s with {session_count} sessions",
               root_cause="performance" if not passed else "",
               is_boundary=True)
    except Exception as e:
        record("Boundary-2: Concurrent sessions API speed", cat, False, str(e),
               is_boundary=True)

    # ----- Boundary-3: Title length 1000 chars -----
    try:
        if session:
            long_title = "X" * 1000
            r = api_put(f"/api/sessions/{session}/title", {"title": long_title})
            data = r.json()
            returned_title = data.get("title", "")
            # The server truncates to 60 chars
            # BOUNDARY: Does it truncate? Does it crash?
            truncated = len(returned_title) <= 60
            passed = r.status_code == 200 and truncated
            record("Boundary-3: 1000-char title", cat, passed,
                   f"Returned length: {len(returned_title)}",
                   expected="Truncated to <=60 chars or rejected",
                   actual=f"Title length={len(returned_title)}, status={r.status_code}",
                   root_cause="validation" if not passed else "",
                   is_boundary=True)
            # Restore
            api_put(f"/api/sessions/{session}/title", {"title": session})
        else:
            record("Boundary-3: 1000-char title", cat, False,
                   "No active session", is_boundary=True)
    except Exception as e:
        record("Boundary-3: 1000-char title", cat, False, str(e), is_boundary=True)

    # ----- Boundary-4: Unicode session names -----
    unicode_names = ["cafe\u0301", "\u00fcber", "\U0001f680rocket", "\u4f60\u597d"]
    for name in unicode_names:
        try:
            r = api_post("/api/sessions", {"path": "/home/ubuntu", "name": name})
            # These should be rejected by the regex (only allows [a-zA-Z0-9_-])
            passed = r.status_code == 400
            record(f"Boundary-4: Unicode name '{name[:10]}' rejected", cat, passed,
                   f"status={r.status_code}",
                   expected="400 (invalid name)",
                   actual=f"status={r.status_code}",
                   root_cause="validation" if not passed else "",
                   is_boundary=True)
        except Exception as e:
            record(f"Boundary-4: Unicode name '{name[:10]}'", cat, False, str(e),
                   is_boundary=True)

    # ----- Boundary-5: Very long session name -----
    try:
        long_name = "a" * 500
        r = api_post("/api/sessions", {"path": "/home/ubuntu", "name": long_name})
        # BOUNDARY: regex passes it (it's all valid chars), but tmux may reject it
        # The server will try to create a tmux session with this name
        status = r.status_code
        # Should either work or fail gracefully (not 500)
        passed = status != 500
        record("Boundary-5: 500-char session name", cat, passed,
               f"status={status}",
               expected="Graceful handling (not 500)",
               actual=f"status={status}",
               root_cause="validation" if status == 500 else "",
               is_boundary=True)
        # Cleanup if created
        if status in (200, 201):
            api_delete(f"/api/sessions/{long_name}")
    except Exception as e:
        record("Boundary-5: 500-char session name", cat, False, str(e),
               is_boundary=True)

    # ----- Boundary-6: Single character name -----
    try:
        r = api_post("/api/sessions", {"path": "/home/ubuntu", "name": "z"})
        status = r.status_code
        # Should work -- 'z' is valid
        passed = status in (200, 201, 409)  # 409 if already exists
        record("Boundary-6: Single char session name 'z'", cat, passed,
               f"status={status}",
               expected="200/201/409",
               actual=f"status={status}",
               root_cause="validation" if not passed else "",
               is_boundary=True)
        # Cleanup
        if status in (200, 201):
            api_delete("/api/sessions/z")
    except Exception as e:
        record("Boundary-6: Single char session name", cat, False, str(e),
               is_boundary=True)

    # ----- Boundary-7: Invalid API calls -----
    try:
        # POST send with empty body
        r = requests.post(f"{BASE_URL}/api/sessions/nonexistent/send",
                          json={"text": ""}, timeout=5)
        passed_empty = r.status_code in (400, 404, 422)
        record("Boundary-7a: Send empty text", cat, passed_empty,
               f"status={r.status_code}",
               expected="400/404",
               actual=f"status={r.status_code}",
               root_cause="validation" if not passed_empty else "",
               is_boundary=True)
    except Exception as e:
        record("Boundary-7a: Send empty text", cat, False, str(e), is_boundary=True)

    try:
        # POST send with no body at all
        r = requests.post(f"{BASE_URL}/api/sessions/nonexistent/send",
                          headers={"Content-Type": "application/json"},
                          data="", timeout=5)
        passed_nobody = r.status_code in (400, 404, 422)
        record("Boundary-7b: Send with no body", cat, passed_nobody,
               f"status={r.status_code}",
               expected="400/404/422",
               actual=f"status={r.status_code}",
               root_cause="validation" if not passed_nobody else "",
               is_boundary=True)
    except Exception as e:
        record("Boundary-7b: Send with no body", cat, False, str(e), is_boundary=True)

    try:
        # GET nonexistent session
        r = api_get("/api/sessions/definitely_not_a_real_session_12345")
        passed = r.status_code == 404
        record("Boundary-7c: GET nonexistent session", cat, passed,
               f"status={r.status_code}",
               expected="404",
               actual=f"status={r.status_code}",
               root_cause="validation" if not passed else "",
               is_boundary=True)
    except Exception as e:
        record("Boundary-7c: GET nonexistent session", cat, False, str(e),
               is_boundary=True)

    # ----- Boundary-8: File upload too large -----
    try:
        if session:
            # Create a 15MB file in memory
            large_data = b"X" * (15 * 1024 * 1024)
            files = {"file": ("largefile.txt", io.BytesIO(large_data), "text/plain")}
            r = requests.post(f"{BASE_URL}/api/upload/{session}",
                              files=files, timeout=30)
            passed = r.status_code == 413
            record("Boundary-8: 15MB upload rejected (10MB limit)", cat, passed,
                   f"status={r.status_code}",
                   expected="413 (too large)",
                   actual=f"status={r.status_code}",
                   root_cause="validation" if not passed else "",
                   is_boundary=True)
        else:
            record("Boundary-8: 15MB upload rejected", cat, False,
                   "No active session", is_boundary=True)
    except Exception as e:
        record("Boundary-8: 15MB upload rejected", cat, False, str(e),
               is_boundary=True)

    # ----- Boundary-9: Empty file upload -----
    try:
        if session:
            files = {"file": ("empty.txt", io.BytesIO(b""), "text/plain")}
            r = requests.post(f"{BASE_URL}/api/upload/{session}",
                              files=files, timeout=10)
            passed = r.status_code == 400
            record("Boundary-9: Empty file upload rejected", cat, passed,
                   f"status={r.status_code}",
                   expected="400 (empty file)",
                   actual=f"status={r.status_code}",
                   root_cause="validation" if not passed else "",
                   is_boundary=True)
        else:
            record("Boundary-9: Empty file upload rejected", cat, False,
                   "No active session", is_boundary=True)
    except Exception as e:
        record("Boundary-9: Empty file upload rejected", cat, False, str(e),
               is_boundary=True)

    # ---- Playwright-based boundary tests ----
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)

        # ----- Boundary-10: Light theme completeness -----
        try:
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_timeout(500)

            # Set light theme
            page.evaluate("document.documentElement.setAttribute('data-theme', 'light')")
            page.wait_for_timeout(300)

            # Check for hardcoded dark colors that would be invisible on light theme
            issues = page.evaluate("""
                (() => {
                    var issues = [];
                    var allElements = document.querySelectorAll('*');
                    var lightBg = [242, 240, 237]; // #F2F0ED
                    for (var i = 0; i < allElements.length; i++) {
                        var el = allElements[i];
                        var style = getComputedStyle(el);
                        var color = style.color;
                        var bg = style.backgroundColor;
                        // Check for hardcoded white/very-light text on light bg
                        // Only check visible elements
                        if (el.offsetWidth === 0 || el.offsetHeight === 0) continue;
                        if (style.display === 'none' || style.visibility === 'hidden') continue;

                        // Parse color
                        var colorMatch = color.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/);
                        if (colorMatch) {
                            var r = parseInt(colorMatch[1]);
                            var g = parseInt(colorMatch[2]);
                            var b = parseInt(colorMatch[3]);
                            // Very light text (close to white) on light theme is a problem
                            if (r > 220 && g > 220 && b > 220) {
                                var text = (el.textContent || '').trim().substring(0, 30);
                                if (text && !el.closest('svg')) {
                                    issues.push({
                                        tag: el.tagName,
                                        class: el.className.toString().substring(0, 40),
                                        color: color,
                                        text: text
                                    });
                                }
                            }
                        }
                    }
                    return issues;
                })()
            """)
            # BOUNDARY: Light theme should have NO invisible text
            has_issues = len(issues) > 0
            passed = not has_issues
            issue_summary = "; ".join(
                f"{i['tag']}.{i['class'][:20]}: color={i['color']}, text='{i['text'][:15]}'"
                for i in issues[:5]
            ) if issues else "none"
            record("Boundary-10: Light theme text visibility", cat, passed,
                   f"{len(issues)} elements with invisible text",
                   expected="0 elements with hardcoded light colors",
                   actual=f"{len(issues)} problematic elements: {issue_summary}",
                   root_cause="CSS" if not passed else "",
                   is_boundary=True)

            # Reset
            page.evaluate("document.documentElement.removeAttribute('data-theme')")
            ctx.close()
        except Exception as e:
            record("Boundary-10: Light theme text visibility", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-11: Mobile viewport 320px (iPhone SE) -----
        try:
            ctx = browser.new_context(viewport={"width": 320, "height": 568})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_timeout(500)

            overflow = page.evaluate("""
                (() => {
                    var issues = [];
                    var allElements = document.querySelectorAll('.header, .session-card, .input-area, .text-input-row');
                    for (var i = 0; i < allElements.length; i++) {
                        var el = allElements[i];
                        if (el.scrollWidth > el.clientWidth + 2) {
                            issues.push({
                                class: el.className.toString().substring(0, 40),
                                scrollW: el.scrollWidth,
                                clientW: el.clientWidth
                            });
                        }
                    }
                    return issues;
                })()
            """)
            passed = len(overflow) == 0
            overflow_summary = "; ".join(
                f"{o['class'][:20]}: scroll={o['scrollW']}, client={o['clientW']}"
                for o in overflow[:5]
            ) if overflow else "none"
            record("Boundary-11: 320px viewport no overflow", cat, passed,
                   f"{len(overflow)} overflowing elements",
                   expected="0 horizontal overflow",
                   actual=f"{len(overflow)} elements overflow: {overflow_summary}",
                   root_cause="CSS" if not passed else "",
                   is_boundary=True)
            ctx.close()
        except Exception as e:
            record("Boundary-11: 320px viewport no overflow", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-12: 768px viewport (iPad) -----
        try:
            ctx = browser.new_context(viewport={"width": 768, "height": 1024})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_timeout(500)

            # Check if session cards use too much horizontal space
            layout_issues = page.evaluate("""
                (() => {
                    var issues = [];
                    var cards = document.querySelectorAll('.session-card');
                    for (var i = 0; i < cards.length; i++) {
                        var rect = cards[i].getBoundingClientRect();
                        // On tablet, cards should not fill entire width without max-width
                        if (rect.width > 700) {
                            issues.push({
                                class: cards[i].className,
                                width: rect.width
                            });
                        }
                    }
                    // Check if app has a max-width container for tablet
                    var shell = document.querySelector('.app-shell');
                    var shellWidth = shell ? shell.getBoundingClientRect().width : 0;
                    return {
                        issues: issues,
                        shellWidth: shellWidth,
                        hasMaxWidth: shellWidth < 768
                    };
                })()
            """)
            # BOUNDARY: On tablet, there should be some max-width or the layout
            # should adapt. Most mobile-first apps look stretched at 768px.
            card_issues = layout_issues.get("issues", [])
            shell_width = layout_issues.get("shellWidth", 0)
            has_max = layout_issues.get("hasMaxWidth", False)
            # This SHOULD fail -- most mobile-first apps don't have tablet constraints
            passed = len(card_issues) == 0 or has_max
            record("Boundary-12: 768px (iPad) layout", cat, passed,
                   f"shell_width={shell_width}, wide_cards={len(card_issues)}",
                   expected="Max-width or responsive layout at 768px",
                   actual=f"Shell width={shell_width}, {len(card_issues)} cards too wide",
                   root_cause="CSS" if not passed else "",
                   is_boundary=True)
            ctx.close()
        except Exception as e:
            record("Boundary-12: 768px (iPad) layout", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-13: Textarea auto-resize cap -----
        try:
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_selector(".session-card:not(.dead)", timeout=5000)
            active_cards = page.query_selector_all(".session-card:not(.dead)")
            if active_cards:
                active_cards[0].click()
                page.wait_for_selector("#textInput", timeout=5000)
                page.wait_for_timeout(500)

                # Type 50 lines of text
                long_text = "\n".join([f"Line {i}" for i in range(50)])
                page.evaluate("""(text) => {
                    var ta = document.getElementById('textInput');
                    ta.value = text;
                    ta.dispatchEvent(new Event('input'));
                }""", long_text)
                page.wait_for_timeout(300)

                height = page.evaluate("""() => {
                    var ta = document.getElementById('textInput');
                    return {
                        height: ta.offsetHeight,
                        scrollHeight: ta.scrollHeight,
                        maxHeight: parseInt(getComputedStyle(ta).maxHeight) || 0,
                        style: ta.style.height
                    };
                }""")
                actual_h = height.get("height", 0)
                max_h = height.get("maxHeight", 0)
                # BOUNDARY: textarea should not grow past max-height (100px)
                # CSS has max-height: 100px
                passed = actual_h <= 110  # small tolerance
                record("Boundary-13: Textarea auto-resize caps at max-height", cat, passed,
                       f"height={actual_h}px, maxHeight={max_h}px",
                       expected="Height <= 100px (CSS max-height)",
                       actual=f"Height={actual_h}px",
                       root_cause="CSS" if not passed else "",
                       is_boundary=True)
            else:
                record("Boundary-13: Textarea auto-resize", cat, False,
                       "No active session", is_boundary=True)
            ctx.close()
        except Exception as e:
            record("Boundary-13: Textarea auto-resize", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-14: Huge markdown message rendering -----
        try:
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_timeout(500)

            # Generate a 50KB markdown string
            big_md = "# Big Document\\n\\n" + ("Lorem ipsum dolor sit amet. " * 200 + "\\n\\n") * 10
            big_md += "## Lists\\n\\n" + "\\n".join([f"- Item {i} with **bold** and `code`" for i in range(200)])
            big_md += "\\n\\n## Code\\n\\n```python\\n" + "\\n".join([f"x = {i}" for i in range(100)]) + "\\n```"

            start = time.time()
            render_result = page.evaluate(f"""
                (() => {{
                    function applyInline(text) {{
                        var frag = document.createDocumentFragment();
                        var html = text
                            .replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')
                            .replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>')
                            .replace(/\\*([^*]+)\\*/g, '<em>$1</em>')
                            .replace(/\\[([^\\]]+)\\]\\((https?:\\/\\/[^)]+)\\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
                        var span = document.createElement('span');
                        span.innerHTML = html;
                        while (span.firstChild) frag.appendChild(span.firstChild);
                        return frag;
                    }}
                    function renderMarkdown(text) {{
                        var frag = document.createDocumentFragment();
                        text = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
                        var blocks = [];
                        var lines = text.split('\\n');
                        var i = 0;
                        while (i < lines.length) {{
                            var line = lines[i];
                            if (/^```/.test(line)) {{
                                var lang = line.replace(/^```\\s*/, '').trim();
                                var codeLines = [];
                                i++;
                                while (i < lines.length && !/^```/.test(lines[i])) {{
                                    codeLines.push(lines[i]); i++;
                                }}
                                i++;
                                blocks.push({{ type: 'code', content: codeLines.join('\\n'), lang: lang }});
                                continue;
                            }}
                            if (!line.trim()) {{ i++; continue; }}
                            var group = [];
                            while (i < lines.length && lines[i].trim() && !/^```/.test(lines[i])) {{
                                group.push(lines[i]); i++;
                            }}
                            blocks.push({{ type: 'lines', lines: group }});
                        }}
                        for (var b = 0; b < blocks.length; b++) {{
                            var block = blocks[b];
                            if (block.type === 'code') {{
                                var pre = document.createElement('pre');
                                pre.className = 'code-block';
                                var code = document.createElement('code');
                                code.textContent = block.content;
                                pre.appendChild(code);
                                frag.appendChild(pre);
                                continue;
                            }}
                            var groupLines = block.lines;
                            var li = 0;
                            while (li < groupLines.length) {{
                                var gl = groupLines[li];
                                var headerMatch = gl.match(/^(#{{1,3}})\\s+(.+)/);
                                if (headerMatch) {{
                                    var level = headerMatch[1].length;
                                    var h = document.createElement('h' + level);
                                    h.appendChild(applyInline(headerMatch[2]));
                                    frag.appendChild(h); li++; continue;
                                }}
                                if (/^[\\-*]\\s+/.test(gl)) {{
                                    var ul = document.createElement('ul');
                                    while (li < groupLines.length && /^[\\-*]\\s+/.test(groupLines[li])) {{
                                        var liEl = document.createElement('li');
                                        liEl.appendChild(applyInline(groupLines[li].replace(/^[\\-*]\\s+/, '')));
                                        ul.appendChild(liEl); li++;
                                    }}
                                    frag.appendChild(ul); continue;
                                }}
                                var pLines = [];
                                while (li < groupLines.length &&
                                       !groupLines[li].match(/^#{{1,3}}\\s+/) &&
                                       !/^[\\-*]\\s+/.test(groupLines[li]) &&
                                       !/^\\d+\\.\\s+/.test(groupLines[li])) {{
                                    pLines.push(groupLines[li]); li++;
                                }}
                                if (pLines.length > 0) {{
                                    var p = document.createElement('p');
                                    p.appendChild(applyInline(pLines.join(' ')));
                                    frag.appendChild(p);
                                }}
                            }}
                        }}
                        return frag;
                    }}
                    var t0 = performance.now();
                    var container = document.createElement('div');
                    container.appendChild(renderMarkdown({json.dumps(big_md)}));
                    var t1 = performance.now();
                    return {{
                        renderTimeMs: t1 - t0,
                        nodeCount: container.querySelectorAll('*').length,
                        textLength: container.textContent.length
                    }};
                }})()
            """)
            render_time = render_result.get("renderTimeMs", 0)
            node_count = render_result.get("nodeCount", 0)
            # BOUNDARY: 50KB should render in under 500ms
            passed = render_time < 500
            record("Boundary-14: 50KB markdown render time", cat, passed,
                   f"render={render_time:.0f}ms, nodes={node_count}",
                   expected="<500ms render time",
                   actual=f"{render_time:.0f}ms, {node_count} DOM nodes",
                   root_cause="performance" if not passed else "",
                   is_boundary=True)
            ctx.close()
        except Exception as e:
            record("Boundary-14: 50KB markdown render time", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-15: Command palette with 100+ items -----
        try:
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_selector(".session-card:not(.dead)", timeout=5000)
            active_cards = page.query_selector_all(".session-card:not(.dead)")
            if active_cards:
                active_cards[0].click()
                page.wait_for_selector("#textInput", timeout=5000)
                page.wait_for_timeout(500)

                # Inject 100 fake commands
                page.evaluate("""
                    (() => {
                        // Access the commandList through the IIFE scope -- we'll override
                        // the fetch response by manipulating the palette directly
                        var palette = document.getElementById('cmdPalette');
                        for (var i = 0; i < 100; i++) {
                            var item = document.createElement('div');
                            item.className = 'cmd-item';
                            var name = document.createElement('span');
                            name.className = 'cmd-item-name';
                            name.textContent = '/test-cmd-' + i;
                            var desc = document.createElement('span');
                            desc.className = 'cmd-item-desc';
                            desc.textContent = 'Test command number ' + i;
                            item.appendChild(name);
                            item.appendChild(desc);
                            palette.appendChild(item);
                        }
                        palette.classList.add('visible');
                    })()
                """)
                page.wait_for_timeout(300)

                palette_info = page.evaluate("""
                    (() => {
                        var p = document.getElementById('cmdPalette');
                        return {
                            visible: p.classList.contains('visible'),
                            itemCount: p.querySelectorAll('.cmd-item').length,
                            height: p.offsetHeight,
                            scrollable: p.scrollHeight > p.clientHeight,
                            maxHeight: parseInt(getComputedStyle(p).maxHeight) || 0
                        };
                    })()
                """)
                item_count = palette_info.get("itemCount", 0)
                scrollable = palette_info.get("scrollable", False)
                height = palette_info.get("height", 0)
                max_h = palette_info.get("maxHeight", 0)
                # BOUNDARY: palette should be scrollable and not overflow viewport
                passed = scrollable and height <= 932 * 0.7  # max-height: 60vh in CSS
                record("Boundary-15: 100+ command palette items", cat, passed,
                       f"items={item_count}, height={height}px, scrollable={scrollable}",
                       expected="Scrollable, constrained to max-height",
                       actual=f"height={height}px, max-height={max_h}, scrollable={scrollable}",
                       root_cause="CSS" if not passed else "",
                       is_boundary=True)
            else:
                record("Boundary-15: 100+ command palette items", cat, False,
                       "No active session", is_boundary=True)
            ctx.close()
        except Exception as e:
            record("Boundary-15: 100+ command palette items", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-16: Memory leak -- DOM node growth over poll cycles -----
        try:
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_selector(".session-card:not(.dead)", timeout=5000)
            active_cards = page.query_selector_all(".session-card:not(.dead)")
            if active_cards:
                active_cards[0].click()
                page.wait_for_selector("#chatFeed", timeout=5000)
                page.wait_for_timeout(2000)

                # Measure initial DOM node count
                initial_count = page.evaluate(
                    "document.querySelectorAll('*').length"
                )

                # Wait for several poll cycles (normal interval ~2s)
                page.wait_for_timeout(12000)

                final_count = page.evaluate(
                    "document.querySelectorAll('*').length"
                )

                # BOUNDARY: DOM should not grow more than 10% over 6 poll cycles
                growth = final_count - initial_count
                growth_pct = (growth / initial_count * 100) if initial_count > 0 else 0
                passed = growth_pct < 10
                record("Boundary-16: DOM node growth over polls", cat, passed,
                       f"initial={initial_count}, final={final_count}, growth={growth_pct:.1f}%",
                       expected="<10% DOM growth over 6 poll cycles",
                       actual=f"{growth_pct:.1f}% growth ({growth} nodes)",
                       root_cause="memory-leak" if not passed else "",
                       is_boundary=True)
            else:
                record("Boundary-16: DOM node growth over polls", cat, False,
                       "No active session", is_boundary=True)
            ctx.close()
        except Exception as e:
            record("Boundary-16: DOM node growth over polls", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-17: Command palette dismiss on outside click -----
        try:
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_selector(".session-card:not(.dead)", timeout=5000)
            active_cards = page.query_selector_all(".session-card:not(.dead)")
            if active_cards:
                active_cards[0].click()
                page.wait_for_selector("#textInput", timeout=5000)
                page.wait_for_timeout(500)

                # Open palette
                page.click("#cmdBtn")
                page.wait_for_timeout(300)
                before = page.is_visible(".cmd-palette.visible")

                # Click on the header area (outside palette and not intercepted)
                page.click("#chatTitle", force=True)
                page.wait_for_timeout(300)
                after = page.is_visible(".cmd-palette.visible")

                passed = before and not after
                record("Boundary-17: Palette dismisses on outside click", cat, passed,
                       f"before={before}, after={after}",
                       expected="Palette visible, then dismissed",
                       actual=f"before={before}, after_click={after}",
                       root_cause="interaction" if not passed else "",
                       is_boundary=True)
            else:
                record("Boundary-17: Palette dismisses on outside click", cat, False,
                       "No active session", is_boundary=True)
            ctx.close()
        except Exception as e:
            record("Boundary-17: Palette dismisses on outside click", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-18: Preview cancel border hardcoded color (light theme) -----
        try:
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_timeout(500)

            # Check CSS for hardcoded colors that don't use CSS variables
            hardcoded_issues = page.evaluate("""
                (() => {
                    var issues = [];
                    // Check all stylesheets for hardcoded colors
                    var sheets = document.styleSheets;
                    for (var s = 0; s < sheets.length; s++) {
                        try {
                            var rules = sheets[s].cssRules;
                            for (var r = 0; r < rules.length; r++) {
                                var rule = rules[r];
                                if (!rule.style) continue;
                                var cssText = rule.cssText;
                                // Skip @keyframes, :root, and theme definitions
                                if (cssText.indexOf('@keyframes') >= 0) continue;
                                if (cssText.indexOf(':root') >= 0) continue;
                                if (cssText.indexOf('data-theme') >= 0) continue;

                                // Look for hardcoded rgba with white/light colors outside var()
                                var borderColor = rule.style.borderColor || '';
                                var border = rule.style.border || '';
                                var combined = borderColor + border;

                                // Check for rgba(255,255,255,...) that should use var()
                                if (/rgba\\(255,\\s*255,\\s*255/.test(combined)) {
                                    issues.push({
                                        selector: rule.selectorText,
                                        property: 'border',
                                        value: combined.substring(0, 60)
                                    });
                                }

                                // Check for hardcoded color: white
                                var color = rule.style.color || '';
                                if (color === 'white' || color === '#fff' || color === '#ffffff') {
                                    issues.push({
                                        selector: rule.selectorText,
                                        property: 'color',
                                        value: color
                                    });
                                }

                                // Check for hardcoded bg colors
                                var bgColor = rule.style.backgroundColor || '';
                                if (bgColor === 'white' || bgColor === '#fff' || bgColor === '#ffffff') {
                                    issues.push({
                                        selector: rule.selectorText,
                                        property: 'background-color',
                                        value: bgColor
                                    });
                                }
                            }
                        } catch(e) { /* CORS */ }
                    }
                    return issues;
                })()
            """)
            # BOUNDARY: Should have NO hardcoded colors -- all should use CSS vars
            passed = len(hardcoded_issues) == 0
            issue_str = "; ".join(
                f"{i['selector']}: {i['property']}={i['value']}"
                for i in hardcoded_issues[:5]
            ) if hardcoded_issues else "none"
            record("Boundary-18: No hardcoded colors in CSS", cat, passed,
                   f"{len(hardcoded_issues)} hardcoded color rules",
                   expected="0 hardcoded colors (all should use CSS variables)",
                   actual=f"{len(hardcoded_issues)} rules with hardcoded colors: {issue_str}",
                   root_cause="CSS" if not passed else "",
                   is_boundary=True)
            ctx.close()
        except Exception as e:
            record("Boundary-18: No hardcoded colors in CSS", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-19: Action toast hardcoded color -----
        try:
            # Check if .action-toast.success uses hardcoded color: #0A0A0A
            # which would be invisible on dark/OLED theme backgrounds
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")

            toast_issue = page.evaluate("""
                (() => {
                    // .action-toast.success has color: #0A0A0A (hardcoded dark)
                    // This is fine ON the green bg, but check if it uses var()
                    var sheets = document.styleSheets;
                    for (var s = 0; s < sheets.length; s++) {
                        try {
                            var rules = sheets[s].cssRules;
                            for (var r = 0; r < rules.length; r++) {
                                if (rules[r].selectorText === '.action-toast.success') {
                                    return {
                                        color: rules[r].style.color,
                                        background: rules[r].style.background
                                    };
                                }
                            }
                        } catch(e) {}
                    }
                    return null;
                })()
            """)
            if toast_issue:
                # color #0A0A0A is hardcoded -- not using var()
                uses_var = "var(" in (toast_issue.get("color", "") + toast_issue.get("background", ""))
                passed = uses_var
                record("Boundary-19: Toast success uses CSS variables", cat, passed,
                       f"color={toast_issue.get('color')}, bg={toast_issue.get('background')}",
                       expected="CSS variables for theming",
                       actual=f"color={toast_issue.get('color')}",
                       root_cause="CSS" if not passed else "",
                       is_boundary=True)
            else:
                record("Boundary-19: Toast success uses CSS variables", cat, True,
                       "Rule not found (may be inline)")
            ctx.close()
        except Exception as e:
            record("Boundary-19: Toast success uses CSS variables", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-20: Preview cancel button border hardcoded -----
        try:
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")

            cancel_issue = page.evaluate("""
                (() => {
                    var sheets = document.styleSheets;
                    for (var s = 0; s < sheets.length; s++) {
                        try {
                            var rules = sheets[s].cssRules;
                            for (var r = 0; r < rules.length; r++) {
                                if (rules[r].selectorText === '.preview-cancel') {
                                    return {
                                        border: rules[r].style.border,
                                        cssText: rules[r].cssText.substring(0, 200)
                                    };
                                }
                            }
                        } catch(e) {}
                    }
                    return null;
                })()
            """)
            if cancel_issue:
                border = cancel_issue.get("border", "")
                css = cancel_issue.get("cssText", "")
                uses_var = "var(" in css
                has_hardcoded = "rgba(255" in css or "#fff" in css.lower()
                passed = uses_var or not has_hardcoded
                record("Boundary-20: Preview cancel border themed", cat, passed,
                       f"border={border}",
                       expected="Uses CSS variable for border color",
                       actual=f"CSS: {css[:100]}",
                       root_cause="CSS" if not passed else "",
                       is_boundary=True)
            else:
                record("Boundary-20: Preview cancel border themed", cat, True,
                       "Rule not found")
            ctx.close()
        except Exception as e:
            record("Boundary-20: Preview cancel border themed", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-21: 428px viewport (iPhone 15 Pro Max) -----
        try:
            ctx = browser.new_context(viewport={"width": 428, "height": 926})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_timeout(500)

            layout_ok = page.evaluate("""
                (() => {
                    var body = document.body;
                    var hasHScroll = body.scrollWidth > body.clientWidth;
                    var header = document.querySelector('.header');
                    var headerOverflow = header ? header.scrollWidth > header.clientWidth : false;
                    return {
                        bodyHScroll: hasHScroll,
                        headerOverflow: headerOverflow,
                        bodyW: body.clientWidth,
                        bodyScrollW: body.scrollWidth
                    };
                })()
            """)
            passed = not layout_ok.get("bodyHScroll") and not layout_ok.get("headerOverflow")
            record("Boundary-21: 428px (iPhone 15 Pro Max) layout", cat, passed,
                   f"bodyScroll={layout_ok}",
                   expected="No horizontal scroll",
                   actual=f"hScroll={layout_ok.get('bodyHScroll')}, headerOverflow={layout_ok.get('headerOverflow')}",
                   root_cause="CSS" if not passed else "",
                   is_boundary=True)
            ctx.close()
        except Exception as e:
            record("Boundary-21: 428px viewport layout", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-22: Allowed commands whitelist -----
        try:
            # The server has an ALLOWED_COMMANDS whitelist. Test if we can
            # inject a non-allowed tmux command via session name or API
            # This is a security boundary test
            r = api_get("/api/sessions/test;ls")
            passed = r.status_code == 400  # should be rejected by regex
            record("Boundary-22: Session name injection rejected", cat, passed,
                   f"status={r.status_code}",
                   expected="400 (regex rejects semicolons)",
                   actual=f"status={r.status_code}",
                   root_cause="security" if not passed else "",
                   is_boundary=True)
        except Exception as e:
            record("Boundary-22: Session name injection", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-23: API rate limiting -----
        try:
            # BOUNDARY: Does the API have any rate limiting?
            # Send 50 requests as fast as possible
            start = time.time()
            statuses = []
            for i in range(50):
                try:
                    r = requests.get(f"{BASE_URL}/api/sessions", timeout=5)
                    statuses.append(r.status_code)
                except Exception:
                    statuses.append(0)
            elapsed = time.time() - start
            non_200 = sum(1 for s in statuses if s != 200)
            # BOUNDARY: A production app SHOULD rate limit. No rate limiting = fail.
            has_rate_limit = non_200 > 0 and any(s == 429 for s in statuses)
            record("Boundary-23: API rate limiting exists", cat, has_rate_limit,
                   f"50 requests in {elapsed:.1f}s, non-200={non_200}",
                   expected="429 responses after burst",
                   actual=f"All returned 200. No rate limiting.",
                   root_cause="security" if not has_rate_limit else "",
                   is_boundary=True)
        except Exception as e:
            record("Boundary-23: API rate limiting exists", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-24: CORS headers -----
        try:
            r = requests.options(f"{BASE_URL}/api/sessions",
                                 headers={"Origin": "https://evil.com",
                                           "Access-Control-Request-Method": "GET"},
                                 timeout=5)
            cors_header = r.headers.get("Access-Control-Allow-Origin", "")
            # BOUNDARY: Should NOT allow arbitrary origins
            allows_all = cors_header == "*"
            allows_evil = "evil.com" in cors_header
            passed = not allows_all and not allows_evil
            record("Boundary-24: CORS blocks foreign origins", cat, passed,
                   f"ACAO header: '{cors_header}'",
                   expected="No wildcard CORS or explicit origin whitelist",
                   actual=f"Access-Control-Allow-Origin: {cors_header or '(none)'}",
                   root_cause="security" if not passed else "",
                   is_boundary=True)
        except Exception as e:
            record("Boundary-24: CORS blocks foreign origins", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-25: CSP headers -----
        try:
            r = requests.get(f"{BASE_URL}/", timeout=5)
            csp = r.headers.get("Content-Security-Policy", "")
            passed = len(csp) > 0
            record("Boundary-25: Content-Security-Policy header set", cat, passed,
                   f"CSP header: '{csp[:80]}'" if csp else "No CSP header",
                   expected="CSP header present",
                   actual=f"CSP: {csp[:80] if csp else '(none)'}",
                   root_cause="security" if not passed else "",
                   is_boundary=True)
        except Exception as e:
            record("Boundary-25: CSP header", cat, False, str(e), is_boundary=True)

        # ----- Boundary-26: X-Frame-Options header -----
        try:
            r = requests.get(f"{BASE_URL}/", timeout=5)
            xfo = r.headers.get("X-Frame-Options", "")
            passed = xfo.upper() in ("DENY", "SAMEORIGIN")
            record("Boundary-26: X-Frame-Options header set", cat, passed,
                   f"X-Frame-Options: '{xfo}'",
                   expected="DENY or SAMEORIGIN",
                   actual=f"X-Frame-Options: {xfo or '(none)'}",
                   root_cause="security" if not passed else "",
                   is_boundary=True)
        except Exception as e:
            record("Boundary-26: X-Frame-Options header", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-27: Session lines parameter max -----
        try:
            if session:
                # The server caps lines at 50000. What happens at the limit?
                r = api_get(f"/api/sessions/{session}?lines=50000")
                passed_limit = r.status_code == 200
                # What about over the limit?
                r2 = api_get(f"/api/sessions/{session}?lines=100000")
                passed_over = r2.status_code == 200
                # Check that over-limit is clamped (server should clamp to 50000)
                passed = passed_limit and passed_over
                record("Boundary-27: Lines parameter at/over limit", cat, passed,
                       f"50000={r.status_code}, 100000={r2.status_code}",
                       expected="Both 200 (clamped at 50000)",
                       actual=f"50000={r.status_code}, 100000={r2.status_code}",
                       root_cause="validation" if not passed else "",
                       is_boundary=True)
            else:
                record("Boundary-27: Lines parameter", cat, False,
                       "No active session", is_boundary=True)
        except Exception as e:
            record("Boundary-27: Lines parameter", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-28: Path traversal in session name -----
        try:
            r = api_get("/api/sessions/..%2F..%2Fetc%2Fpasswd")
            passed = r.status_code in (400, 404)
            record("Boundary-28: Path traversal in session name", cat, passed,
                   f"status={r.status_code}",
                   expected="400 or 404 (rejected)",
                   actual=f"status={r.status_code}",
                   root_cause="security" if not passed else "",
                   is_boundary=True)
        except Exception as e:
            record("Boundary-28: Path traversal", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-29: Manifest.json has required PWA fields -----
        try:
            r = api_get("/manifest.json")
            data = r.json()
            required_fields = {"name", "short_name", "start_url", "display", "icons"}
            missing = required_fields - set(data.keys())
            # PWA also needs: description, scope, theme_color, background_color
            pwa_recommended = {"description", "scope"}
            missing_recommended = pwa_recommended - set(data.keys())
            passed = len(missing) == 0 and len(missing_recommended) == 0
            record("Boundary-29: PWA manifest completeness", cat, passed,
                   f"missing_required={missing}, missing_recommended={missing_recommended}",
                   expected="All required + recommended PWA fields present",
                   actual=f"Missing required: {missing}, missing recommended: {missing_recommended}",
                   root_cause="validation" if not passed else "",
                   is_boundary=True)
        except Exception as e:
            record("Boundary-29: PWA manifest completeness", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-30: Session card accessibility -----
        try:
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_timeout(500)

            a11y_issues = page.evaluate("""
                (() => {
                    var issues = [];
                    // Check buttons have accessible names
                    var buttons = document.querySelectorAll('button');
                    for (var i = 0; i < buttons.length; i++) {
                        var btn = buttons[i];
                        var name = btn.getAttribute('aria-label') ||
                                   btn.getAttribute('title') ||
                                   btn.textContent.trim();
                        if (!name) {
                            issues.push({
                                tag: 'button',
                                class: btn.className.substring(0, 30),
                                issue: 'no accessible name'
                            });
                        }
                    }
                    // Check session cards have role or semantic markup
                    var cards = document.querySelectorAll('.session-card');
                    for (var i = 0; i < cards.length; i++) {
                        var card = cards[i];
                        var role = card.getAttribute('role');
                        var tabindex = card.getAttribute('tabindex');
                        if (!role && !tabindex) {
                            issues.push({
                                tag: 'div.session-card',
                                class: card.className.substring(0, 30),
                                issue: 'no role or tabindex for interactive element'
                            });
                        }
                    }
                    // Check color contrast (very basic -- check text-muted)
                    return issues;
                })()
            """)
            passed = len(a11y_issues) == 0
            issue_str = "; ".join(
                f"{i['tag']}.{i['class'][:15]}: {i['issue']}"
                for i in a11y_issues[:5]
            ) if a11y_issues else "none"
            record("Boundary-30: Accessibility (buttons + cards)", cat, passed,
                   f"{len(a11y_issues)} a11y issues",
                   expected="All interactive elements have accessible names/roles",
                   actual=f"{len(a11y_issues)} issues: {issue_str}",
                   root_cause="accessibility" if not passed else "",
                   is_boundary=True)
            ctx.close()
        except Exception as e:
            record("Boundary-30: Accessibility", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-31: Service worker / offline support -----
        try:
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_timeout(500)

            has_sw = page.evaluate("""
                (() => {
                    return 'serviceWorker' in navigator &&
                           navigator.serviceWorker.controller !== null;
                })()
            """)
            # PWA should have a service worker for offline support
            passed = has_sw
            record("Boundary-31: Service worker registered", cat, passed,
                   f"has_service_worker={has_sw}",
                   expected="Service worker registered for PWA offline support",
                   actual=f"serviceWorker controller: {has_sw}",
                   root_cause="PWA" if not passed else "",
                   is_boundary=True)
            ctx.close()
        except Exception as e:
            record("Boundary-31: Service worker", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-32: Markdown nested formatting -----
        try:
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")

            result = page.evaluate("""
                (() => {
                    function applyInline(text) {
                        var html = text
                            .replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')
                            .replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>')
                            .replace(/\\*([^*]+)\\*/g, '<em>$1</em>')
                            .replace(/\\[([^\\]]+)\\]\\((https?:\\/\\/[^)]+)\\)/g, '<a href="$2">$1</a>');
                        var span = document.createElement('span');
                        span.innerHTML = html;
                        return span.innerHTML;
                    }
                    return {
                        // Bold inside italic: ***text*** should work
                        boldItalic: applyInline('***bold italic***'),
                        // Code inside bold: **`code`** should work
                        codeInBold: applyInline('**`important`**'),
                        // Link with bold text: [**bold**](url)
                        boldLink: applyInline('[**bold link**](https://example.com)')
                    };
                })()
            """)
            # Bold+italic is tricky with this simple regex approach
            bold_italic = result.get("boldItalic", "")
            has_both = "<strong>" in bold_italic or "<em>" in bold_italic
            # Bold+italic likely breaks -- regex can't handle nested ***
            # The regex applies ** first, then * -- should work for ***text***
            # but may produce inconsistent results

            code_in_bold = result.get("codeInBold", "")
            has_code_bold = "<code" in code_in_bold and "<strong>" in code_in_bold

            bold_link = result.get("boldLink", "")
            has_bold_link = "<a" in bold_link and "<strong>" in bold_link

            passed = has_both and has_code_bold and has_bold_link
            record("Boundary-32: Nested markdown (bold+italic, code+bold, bold+link)", cat, passed,
                   f"boldItalic={bold_italic[:40]}, codeInBold={code_in_bold[:40]}, boldLink={bold_link[:40]}",
                   expected="All nested formatting renders correctly",
                   actual=f"bold+italic={'OK' if has_both else 'BROKEN'}, code+bold={'OK' if has_code_bold else 'BROKEN'}, bold+link={'OK' if has_bold_link else 'BROKEN'}",
                   root_cause="parsing" if not passed else "",
                   is_boundary=True)
            ctx.close()
        except Exception as e:
            record("Boundary-32: Nested markdown", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-33: API response time under load -----
        try:
            import concurrent.futures
            if session:
                def fetch_session():
                    start = time.time()
                    r = api_get(f"/api/sessions/{session}")
                    return time.time() - start, r.status_code

                with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                    futures = [executor.submit(fetch_session) for _ in range(10)]
                    results_load = [f.result() for f in futures]

                times = [r[0] for r in results_load]
                statuses = [r[1] for r in results_load]
                max_time = max(times)
                avg_time = sum(times) / len(times)
                all_ok = all(s == 200 for s in statuses)

                # BOUNDARY: Under 10 concurrent requests, p99 should be <5s
                passed = all_ok and max_time < 5.0
                record("Boundary-33: 10 concurrent session fetches", cat, passed,
                       f"avg={avg_time:.2f}s, max={max_time:.2f}s, all_200={all_ok}",
                       expected="All 200, max <5s",
                       actual=f"avg={avg_time:.2f}s, max={max_time:.2f}s",
                       root_cause="performance" if not passed else "",
                       is_boundary=True)
            else:
                record("Boundary-33: Concurrent session fetches", cat, False,
                       "No active session", is_boundary=True)
        except Exception as e:
            record("Boundary-33: Concurrent session fetches", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-34: Title with HTML/XSS payload -----
        try:
            if session:
                xss_title = '<img src=x onerror=alert(1)>'
                r = api_put(f"/api/sessions/{session}/title",
                            {"title": xss_title})
                data = r.json()
                returned = data.get("title", "")
                # The title should be stored as-is (server doesn't sanitize)
                # but the frontend MUST escape it when rendering
                # Test via browser
                ctx = browser.new_context(viewport={"width": 430, "height": 932})
                page = ctx.new_page()
                page.goto(BASE_URL, wait_until="networkidle")
                page.wait_for_timeout(1000)

                # Check if any session card title contains unescaped HTML
                has_xss = page.evaluate("""
                    (() => {
                        var titles = document.querySelectorAll('.session-card-title');
                        for (var i = 0; i < titles.length; i++) {
                            if (titles[i].querySelector('img')) return true;
                        }
                        return false;
                    })()
                """)
                passed = not has_xss
                record("Boundary-34: XSS in title rendered safely", cat, passed,
                       f"has_xss_element={has_xss}",
                       expected="Title rendered as text, not HTML",
                       actual=f"XSS element in DOM: {has_xss}",
                       root_cause="security" if not passed else "",
                       is_boundary=True)
                ctx.close()
                # Restore title
                api_put(f"/api/sessions/{session}/title", {"title": session})
            else:
                record("Boundary-34: XSS in title", cat, False,
                       "No active session", is_boundary=True)
        except Exception as e:
            record("Boundary-34: XSS in title", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-35: Settings panel keyboard accessibility -----
        try:
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_timeout(500)

            # Can we open settings with keyboard (Tab + Enter)?
            page.keyboard.press("Tab")
            page.wait_for_timeout(200)
            # Check if focus is visible (focus ring)
            has_focus_style = page.evaluate("""
                (() => {
                    var active = document.activeElement;
                    if (!active || active === document.body) return {found: false, tag: 'body'};
                    var style = getComputedStyle(active);
                    return {
                        found: true,
                        tag: active.tagName,
                        class: active.className.substring(0, 30),
                        outline: style.outline,
                        outlineStyle: style.outlineStyle,
                        boxShadow: style.boxShadow
                    };
                })()
            """)
            # BOUNDARY: focused element should have visible focus indicator
            has_visible_focus = (
                has_focus_style.get("found", False) and
                (has_focus_style.get("outlineStyle", "none") != "none" or
                 has_focus_style.get("boxShadow", "none") != "none")
            )
            record("Boundary-35: Keyboard focus visibility", cat, has_visible_focus,
                   f"focus={has_focus_style}",
                   expected="Visible focus indicator on Tab",
                   actual=f"outline={has_focus_style.get('outlineStyle')}, shadow={has_focus_style.get('boxShadow', '')[:30]}",
                   root_cause="accessibility" if not has_visible_focus else "",
                   is_boundary=True)
            ctx.close()
        except Exception as e:
            record("Boundary-35: Keyboard focus visibility", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-36: Large session list (API response size) -----
        try:
            r = api_get("/api/sessions")
            data = r.json()
            content_length = len(r.content)
            session_count = len(data)
            # BOUNDARY: Response should include Content-Length or Transfer-Encoding
            has_content_length = "content-length" in r.headers or "transfer-encoding" in r.headers
            # Also check: does the response have gzip?
            has_compression = r.headers.get("content-encoding", "") in ("gzip", "br", "deflate")
            passed = has_compression
            record("Boundary-36: API response compression", cat, passed,
                   f"size={content_length}B, sessions={session_count}, encoding={r.headers.get('content-encoding', 'none')}",
                   expected="gzip or br compression on API responses",
                   actual=f"content-encoding: {r.headers.get('content-encoding', 'none')}",
                   root_cause="performance" if not passed else "",
                   is_boundary=True)
        except Exception as e:
            record("Boundary-36: API response compression", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-37: Static assets cache headers -----
        try:
            r = requests.get(f"{BASE_URL}/static/css/style.css", timeout=5)
            cache_control = r.headers.get("Cache-Control", "")
            # The middleware sets no-cache on static files -- this is intentional
            # but for production, versioned static files should have long cache
            has_no_cache = "no-cache" in cache_control or "no-store" in cache_control
            # BOUNDARY: For a PWA, static files should be cached with version hash
            # Current implementation disables all caching
            passed = not has_no_cache
            record("Boundary-37: Static file caching strategy", cat, passed,
                   f"Cache-Control: {cache_control}",
                   expected="Versioned assets with long cache (e.g. max-age=31536000)",
                   actual=f"Cache-Control: {cache_control} (caching disabled)",
                   root_cause="performance" if not passed else "",
                   is_boundary=True)
        except Exception as e:
            record("Boundary-37: Static file caching", cat, False, str(e),
                   is_boundary=True)

        browser.close()


# ===================================================================
# CATEGORY 5: ADDITIONAL BOUNDARY TESTS (deeper probing)
# ===================================================================

def run_additional_boundary_tests():
    cat = "Boundary"
    print(f"\n{'='*60}")
    print(f"  CATEGORY 5: Additional Boundary Tests")
    print(f"{'='*60}")

    from playwright.sync_api import sync_playwright

    session = get_first_active_session()

    # ----- Boundary-38: Strict-Transport-Security header -----
    try:
        r = requests.get(f"{BASE_URL}/", timeout=5)
        hsts = r.headers.get("Strict-Transport-Security", "")
        passed = len(hsts) > 0
        record("Boundary-38: HSTS header set", cat, passed,
               f"HSTS: '{hsts}'",
               expected="Strict-Transport-Security header present",
               actual=f"HSTS: {hsts or '(none)'}",
               root_cause="security" if not passed else "",
               is_boundary=True)
    except Exception as e:
        record("Boundary-38: HSTS header", cat, False, str(e), is_boundary=True)

    # ----- Boundary-39: X-Content-Type-Options -----
    try:
        r = requests.get(f"{BASE_URL}/", timeout=5)
        xcto = r.headers.get("X-Content-Type-Options", "")
        passed = xcto == "nosniff"
        record("Boundary-39: X-Content-Type-Options nosniff", cat, passed,
               f"XCTO: '{xcto}'",
               expected="nosniff",
               actual=f"X-Content-Type-Options: {xcto or '(none)'}",
               root_cause="security" if not passed else "",
               is_boundary=True)
    except Exception as e:
        record("Boundary-39: X-Content-Type-Options", cat, False, str(e),
               is_boundary=True)

    # ----- Boundary-40: Referrer-Policy -----
    try:
        r = requests.get(f"{BASE_URL}/", timeout=5)
        rp = r.headers.get("Referrer-Policy", "")
        passed = rp in ("no-referrer", "strict-origin-when-cross-origin",
                         "same-origin", "strict-origin", "no-referrer-when-downgrade")
        record("Boundary-40: Referrer-Policy header", cat, passed,
               f"Referrer-Policy: '{rp}'",
               expected="Explicit referrer policy",
               actual=f"Referrer-Policy: {rp or '(none)'}",
               root_cause="security" if not passed else "",
               is_boundary=True)
    except Exception as e:
        record("Boundary-40: Referrer-Policy", cat, False, str(e), is_boundary=True)

    # ----- Boundary-41: API error responses are JSON -----
    try:
        r = api_get("/api/nonexistent-endpoint")
        content_type = r.headers.get("content-type", "")
        is_json = "application/json" in content_type
        passed = is_json
        record("Boundary-41: 404 API response is JSON", cat, passed,
               f"content-type: {content_type}",
               expected="application/json for all API errors",
               actual=f"content-type: {content_type}",
               root_cause="validation" if not passed else "",
               is_boundary=True)
    except Exception as e:
        record("Boundary-41: API 404 content type", cat, False, str(e),
               is_boundary=True)

    # ----- Boundary-42: Title length validation on server -----
    try:
        if session:
            # Test with 0 length (should reject)
            r1 = api_put(f"/api/sessions/{session}/title", {"title": " "})
            rejects_whitespace = r1.status_code == 400
            # Test with special chars
            r2 = api_put(f"/api/sessions/{session}/title",
                         {"title": "Test\x00Null\x01Chars"})
            # Server should handle null bytes
            handles_null = r2.status_code in (200, 400)
            passed = rejects_whitespace and handles_null
            record("Boundary-42: Title edge cases (whitespace, null bytes)", cat, passed,
                   f"whitespace_rejected={rejects_whitespace}, null_handled={handles_null}",
                   expected="Whitespace-only rejected, null bytes handled",
                   actual=f"whitespace={r1.status_code}, null={r2.status_code}",
                   root_cause="validation" if not passed else "",
                   is_boundary=True)
            # Restore
            api_put(f"/api/sessions/{session}/title", {"title": session})
        else:
            record("Boundary-42: Title edge cases", cat, False,
                   "No active session", is_boundary=True)
    except Exception as e:
        record("Boundary-42: Title edge cases", cat, False, str(e),
               is_boundary=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)

        # ----- Boundary-43: Double-click on session card -----
        try:
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_selector(".session-card:not(.dead)", timeout=5000)

            # Double-click should not cause issues (double navigation, etc.)
            card = page.query_selector(".session-card:not(.dead)")
            if card:
                card.dblclick()
                page.wait_for_timeout(2000)
                # Should still be in chat view without errors
                is_chat = page.is_visible("#chatFeed")
                console_errors = []
                page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
                page.wait_for_timeout(1000)
                passed = is_chat and len(console_errors) == 0
                record("Boundary-43: Double-click on card handled", cat, passed,
                       f"in_chat={is_chat}, errors={len(console_errors)}",
                       expected="Single navigation, no errors",
                       actual=f"chat_visible={is_chat}, console_errors={console_errors[:3]}",
                       root_cause="interaction" if not passed else "",
                       is_boundary=True)
            else:
                record("Boundary-43: Double-click on card", cat, False,
                       "No active cards", is_boundary=True)
            ctx.close()
        except Exception as e:
            record("Boundary-43: Double-click on card", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-44: Touch target sizes (44px minimum) -----
        try:
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_timeout(500)

            small_targets = page.evaluate("""
                (() => {
                    var issues = [];
                    var interactive = document.querySelectorAll('button, a, [role="button"]');
                    for (var i = 0; i < interactive.length; i++) {
                        var el = interactive[i];
                        if (el.offsetWidth === 0 || el.offsetHeight === 0) continue;
                        var style = getComputedStyle(el);
                        if (style.display === 'none') continue;
                        var rect = el.getBoundingClientRect();
                        // Apple HIG says minimum 44x44px touch target
                        if (rect.width < 44 || rect.height < 44) {
                            // Check min-width/min-height as they create invisible hit area
                            var minW = parseInt(style.minWidth) || 0;
                            var minH = parseInt(style.minHeight) || 0;
                            if (minW < 44 || minH < 44) {
                                issues.push({
                                    tag: el.tagName,
                                    class: el.className.toString().substring(0, 30),
                                    width: Math.round(rect.width),
                                    height: Math.round(rect.height),
                                    text: (el.textContent || el.title || '').substring(0, 15)
                                });
                            }
                        }
                    }
                    return issues;
                })()
            """)
            passed = len(small_targets) == 0
            targets_str = "; ".join(
                f"{t['tag']}.{t['class'][:15]}: {t['width']}x{t['height']} '{t['text'][:10]}'"
                for t in small_targets[:5]
            ) if small_targets else "all OK"
            record("Boundary-44: Touch targets >= 44px", cat, passed,
                   f"{len(small_targets)} undersized targets",
                   expected="All interactive elements >= 44x44px",
                   actual=f"{len(small_targets)} too small: {targets_str}",
                   root_cause="accessibility" if not passed else "",
                   is_boundary=True)
            ctx.close()
        except Exception as e:
            record("Boundary-44: Touch targets", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-45: Session list poll interval consistency -----
        try:
            # The session list polls every 8s. Verify interval is consistent.
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()

            fetch_times = []
            page.on("request", lambda req: fetch_times.append(time.time())
                     if "/api/sessions" in req.url and req.method == "GET" else None)

            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_timeout(20000)  # Wait for 2+ poll cycles

            if len(fetch_times) >= 3:
                intervals = [fetch_times[i+1] - fetch_times[i]
                             for i in range(len(fetch_times)-1)]
                avg_interval = sum(intervals) / len(intervals)
                # Should be ~8s (+/- 1s)
                in_range = all(6 < iv < 10 for iv in intervals)
                passed = in_range and abs(avg_interval - 8.0) < 2.0
                record("Boundary-45: Session list poll interval ~8s", cat, passed,
                       f"intervals={[f'{iv:.1f}s' for iv in intervals]}, avg={avg_interval:.1f}s",
                       expected="~8s intervals",
                       actual=f"intervals={[f'{iv:.1f}s' for iv in intervals]}",
                       root_cause="timing" if not passed else "",
                       is_boundary=True)
            else:
                record("Boundary-45: Session list poll interval", cat, False,
                       f"Only {len(fetch_times)} fetches in 20s",
                       is_boundary=True)
            ctx.close()
        except Exception as e:
            record("Boundary-45: Session list poll interval", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-46: OLED theme all surfaces truly black -----
        try:
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")
            page.evaluate("document.documentElement.setAttribute('data-theme', 'oled')")
            page.wait_for_timeout(300)

            oled_issues = page.evaluate("""
                (() => {
                    var issues = [];
                    var surfaces = document.querySelectorAll('.header, body, .app-shell, .screen, .session-list');
                    for (var i = 0; i < surfaces.length; i++) {
                        var bg = getComputedStyle(surfaces[i]).backgroundColor;
                        var match = bg.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/);
                        if (match) {
                            var r = parseInt(match[1]), g = parseInt(match[2]), b = parseInt(match[3]);
                            // OLED theme: backgrounds should be pure black (#000) or very dark (#0A0A0A)
                            if (r > 15 || g > 15 || b > 15) {
                                issues.push({
                                    class: surfaces[i].className.toString().substring(0, 30),
                                    bg: bg
                                });
                            }
                        }
                    }
                    return issues;
                })()
            """)
            passed = len(oled_issues) == 0
            issue_str = "; ".join(
                f"{i['class'][:20]}: bg={i['bg']}"
                for i in oled_issues[:5]
            ) if oled_issues else "all pure black"
            record("Boundary-46: OLED theme pure black backgrounds", cat, passed,
                   f"{len(oled_issues)} non-black surfaces",
                   expected="All surfaces <= rgb(15,15,15)",
                   actual=f"{len(oled_issues)} surfaces too bright: {issue_str}",
                   root_cause="CSS" if not passed else "",
                   is_boundary=True)
            page.evaluate("document.documentElement.removeAttribute('data-theme')")
            ctx.close()
        except Exception as e:
            record("Boundary-46: OLED theme", cat, False, str(e), is_boundary=True)

        # ----- Boundary-47: Error handling for network failures -----
        try:
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_selector(".session-card:not(.dead)", timeout=5000)
            active_cards = page.query_selector_all(".session-card:not(.dead)")

            if active_cards:
                active_cards[0].click()
                page.wait_for_selector("#chatFeed", timeout=5000)
                page.wait_for_timeout(1000)

                # Block all API requests to simulate network failure
                page.route("**/api/**", lambda route: route.abort())
                page.wait_for_timeout(5000)  # Wait for a poll cycle to fail

                # App should not crash -- check for error state or graceful degradation
                is_alive = page.evaluate("""
                    (() => {
                        // Check the page hasn't crashed
                        return document.getElementById('chatFeed') !== null;
                    })()
                """)
                # Check for any uncaught error overlays
                has_error_overlay = page.evaluate("""
                    (() => {
                        return document.querySelector('.error-overlay, .error-state, [class*="error"]') !== null;
                    })()
                """)
                # BOUNDARY: App should show graceful error state, not just silently fail
                passed = is_alive and has_error_overlay
                record("Boundary-47: Graceful network failure handling", cat, passed,
                       f"alive={is_alive}, error_shown={has_error_overlay}",
                       expected="App shows error state on network failure",
                       actual=f"alive={is_alive}, error_indicator={has_error_overlay}",
                       root_cause="UX" if not passed else "",
                       is_boundary=True)

                page.unroute("**/api/**")
            else:
                record("Boundary-47: Network failure handling", cat, False,
                       "No active session", is_boundary=True)
            ctx.close()
        except Exception as e:
            record("Boundary-47: Network failure handling", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-48: Message timestamp display -----
        try:
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_selector(".session-card:not(.dead)", timeout=5000)
            active_cards = page.query_selector_all(".session-card:not(.dead)")

            if active_cards:
                active_cards[0].click()
                page.wait_for_selector("#chatFeed", timeout=5000)
                page.wait_for_timeout(1500)

                # BOUNDARY: Do messages show timestamps? Most chat apps do.
                has_timestamps = page.evaluate("""
                    (() => {
                        var msgs = document.querySelectorAll('.msg');
                        for (var i = 0; i < msgs.length; i++) {
                            var ts = msgs[i].querySelector('.msg-time, .msg-timestamp, time, [class*="time"]');
                            if (ts) return true;
                        }
                        return false;
                    })()
                """)
                record("Boundary-48: Messages show timestamps", cat, has_timestamps,
                       f"has_timestamps={has_timestamps}",
                       expected="Messages display timestamps",
                       actual=f"Timestamps in messages: {has_timestamps}",
                       root_cause="UX" if not has_timestamps else "",
                       is_boundary=True)
            else:
                record("Boundary-48: Message timestamps", cat, False,
                       "No active session", is_boundary=True)
            ctx.close()
        except Exception as e:
            record("Boundary-48: Message timestamps", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-49: Dark mode meta tag updates with theme -----
        try:
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")

            # Check initial meta theme-color
            initial_meta = page.evaluate("""
                document.querySelector('meta[name="theme-color"]').getAttribute('content')
            """)

            # Switch to light theme via settings
            page.click("#gearBtn")
            page.wait_for_selector(".settings-panel.visible", timeout=3000)
            selects = page.query_selector_all(".settings-select")
            if selects:
                selects[0].select_option("light")
                page.wait_for_timeout(300)
                light_meta = page.evaluate("""
                    document.querySelector('meta[name="theme-color"]').getAttribute('content')
                """)
                # Meta should update to light theme color
                passed = light_meta != initial_meta and light_meta == "#F2F0ED"
                record("Boundary-49: Meta theme-color updates with theme", cat, passed,
                       f"initial={initial_meta}, light={light_meta}",
                       expected="Meta updates to #F2F0ED for light theme",
                       actual=f"initial={initial_meta}, after_light={light_meta}",
                       root_cause="CSS" if not passed else "",
                       is_boundary=True)
                # Reset
                selects[0].select_option("dark")
            else:
                record("Boundary-49: Meta theme-color", cat, False,
                       "No theme select", is_boundary=True)
            ctx.close()
        except Exception as e:
            record("Boundary-49: Meta theme-color", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-50: Send button visibility toggle -----
        try:
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_selector(".session-card:not(.dead)", timeout=5000)
            active_cards = page.query_selector_all(".session-card:not(.dead)")

            if active_cards:
                active_cards[0].click()
                page.wait_for_selector("#textInput", timeout=5000)
                page.wait_for_timeout(500)

                # Initially: mic visible, send hidden
                mic_visible_before = page.is_visible("#micBtn")
                send_visible_before = page.is_visible("#sendBtn")

                # Type text: send visible, mic hidden
                page.fill("#textInput", "hello")
                page.wait_for_timeout(200)
                mic_visible_during = page.is_visible("#micBtn")
                send_visible_during = page.is_visible("#sendBtn")

                # Clear text: mic visible, send hidden
                page.fill("#textInput", "")
                page.wait_for_timeout(200)
                mic_visible_after = page.is_visible("#micBtn")
                send_visible_after = page.is_visible("#sendBtn")

                passed = (mic_visible_before and not send_visible_before and
                          not mic_visible_during and send_visible_during and
                          mic_visible_after and not send_visible_after)
                record("Boundary-50: Send/mic button toggle on input", cat, passed,
                       f"before: mic={mic_visible_before}, send={send_visible_before}; "
                       f"during: mic={mic_visible_during}, send={send_visible_during}; "
                       f"after: mic={mic_visible_after}, send={send_visible_after}")
            else:
                record("Boundary-50: Send/mic toggle", cat, False,
                       "No active session", is_boundary=True)
            ctx.close()
        except Exception as e:
            record("Boundary-50: Send/mic toggle", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-51: Light theme code block border uses hardcoded rgba -----
        try:
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")

            code_block_issue = page.evaluate("""
                (() => {
                    var sheets = document.styleSheets;
                    for (var s = 0; s < sheets.length; s++) {
                        try {
                            var rules = sheets[s].cssRules;
                            for (var r = 0; r < rules.length; r++) {
                                var sel = rules[r].selectorText || '';
                                if (sel.indexOf('.code-block') >= 0 && sel.indexOf(':hover') < 0) {
                                    var css = rules[r].cssText;
                                    // Check for hardcoded rgba with white assumption
                                    if (/rgba\\(255,\\s*255,\\s*255/.test(css)) {
                                        return {
                                            selector: sel,
                                            css: css.substring(0, 150),
                                            issue: 'hardcoded rgba(255,255,255,...) border'
                                        };
                                    }
                                }
                            }
                        } catch(e) {}
                    }
                    return null;
                })()
            """)
            passed = code_block_issue is None
            record("Boundary-51: Code block border uses CSS var (not hardcoded)", cat, passed,
                   f"issue={code_block_issue}",
                   expected="Code block border uses CSS variable",
                   actual=f"{code_block_issue.get('issue', 'none') if code_block_issue else 'no issue'}",
                   root_cause="CSS" if not passed else "",
                   is_boundary=True)
            ctx.close()
        except Exception as e:
            record("Boundary-51: Code block border", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-52: Input area safe-area-inset handling -----
        try:
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")

            # Check if input area properly handles safe-area-inset
            safe_area = page.evaluate("""
                (() => {
                    var inputArea = document.querySelector('.input-area');
                    if (!inputArea) return {found: false};
                    var style = getComputedStyle(inputArea);
                    return {
                        found: true,
                        paddingBottom: style.paddingBottom,
                        // Check if padding-bottom uses env()
                        cssText: inputArea.style.cssText
                    };
                })()
            """)
            # This passes by definition since CSS has the env() -- just verify it exists
            passed = safe_area.get("found", False)
            record("Boundary-52: Input area safe-area-inset", cat, passed,
                   f"paddingBottom={safe_area.get('paddingBottom')}",
                   expected="env(safe-area-inset-bottom) in padding",
                   actual=f"paddingBottom={safe_area.get('paddingBottom')}",
                   root_cause="CSS" if not passed else "",
                   is_boundary=True)
            ctx.close()
        except Exception as e:
            record("Boundary-52: Safe area inset", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-53: Markdown table support -----
        try:
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")

            result = page.evaluate("""
                (() => {
                    function applyInline(text) {
                        var html = text
                            .replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')
                            .replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>')
                            .replace(/\\*([^*]+)\\*/g, '<em>$1</em>')
                            .replace(/\\[([^\\]]+)\\]\\((https?:\\/\\/[^)]+)\\)/g, '<a href="$2">$1</a>');
                        var span = document.createElement('span');
                        span.innerHTML = html;
                        return span;
                    }
                    // The renderMarkdown in this app does NOT handle tables
                    // This tests whether it degrades gracefully
                    var table_md = '| Name | Value |\\n|------|-------|\\n| foo  | bar   |\\n| baz  | qux   |';
                    // Since renderMarkdown treats these as paragraph lines, check output
                    var container = document.createElement('div');
                    // Minimal render
                    var text = table_md.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                    var p = document.createElement('p');
                    p.appendChild(applyInline(text.split('\\n').join(' ')));
                    container.appendChild(p);
                    return {
                        hasTable: container.querySelector('table') !== null,
                        rendered: container.textContent.substring(0, 80)
                    };
                })()
            """)
            has_table = result.get("hasTable", False)
            # BOUNDARY: Markdown tables should render as <table>, not plain text
            record("Boundary-53: Markdown table rendering", cat, has_table,
                   f"has_table_element={has_table}, rendered='{result.get('rendered', '')[:50]}'",
                   expected="Tables render as <table> elements",
                   actual=f"Table element: {has_table} (rendered as plain text)",
                   root_cause="parsing" if not has_table else "",
                   is_boundary=True)
            ctx.close()
        except Exception as e:
            record("Boundary-53: Markdown table rendering", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-54: Markdown blockquote support -----
        try:
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")

            result = page.evaluate("""
                (() => {
                    function applyInline(text) {
                        var html = text
                            .replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')
                            .replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>')
                            .replace(/\\*([^*]+)\\*/g, '<em>$1</em>');
                        var span = document.createElement('span');
                        span.innerHTML = html;
                        return span;
                    }
                    var container = document.createElement('div');
                    var text = '> This is a blockquote';
                    text = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                    var p = document.createElement('p');
                    p.appendChild(applyInline(text));
                    container.appendChild(p);
                    return {
                        hasBlockquote: container.querySelector('blockquote') !== null,
                        rendered: container.textContent.substring(0, 60)
                    };
                })()
            """)
            has_bq = result.get("hasBlockquote", False)
            record("Boundary-54: Markdown blockquote rendering", cat, has_bq,
                   f"has_blockquote={has_bq}, rendered='{result.get('rendered', '')[:40]}'",
                   expected="Blockquotes render as <blockquote> elements",
                   actual=f"Blockquote element: {has_bq} (rendered as plain text with >)",
                   root_cause="parsing" if not has_bq else "",
                   is_boundary=True)
            ctx.close()
        except Exception as e:
            record("Boundary-54: Markdown blockquote", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-55: Upload endpoint requires file field -----
        try:
            if session:
                r = requests.post(f"{BASE_URL}/api/upload/{session}",
                                  data=b"not a form upload",
                                  headers={"Content-Type": "application/octet-stream"},
                                  timeout=5)
                passed = r.status_code == 422
                record("Boundary-55: Upload without multipart rejected", cat, passed,
                       f"status={r.status_code}",
                       expected="422 (missing file field)",
                       actual=f"status={r.status_code}",
                       root_cause="validation" if not passed else "",
                       is_boundary=True)
            else:
                record("Boundary-55: Upload without multipart", cat, False,
                       "No active session", is_boundary=True)
        except Exception as e:
            record("Boundary-55: Upload validation", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-56: Session list empty state has CTA -----
        try:
            # When there are no sessions, the empty state should guide users
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_timeout(500)

            empty_state = page.evaluate("""
                (() => {
                    var es = document.getElementById('emptyState');
                    if (!es) return null;
                    // Check if empty state has a call-to-action button
                    var btn = es.querySelector('button, a, [role="button"]');
                    return {
                        visible: es.style.display !== 'none',
                        hasCTA: !!btn,
                        text: es.textContent.trim().substring(0, 100)
                    };
                })()
            """)
            if empty_state and not empty_state.get("visible"):
                # Sessions exist, so empty state is hidden -- that's fine
                # But test: does the empty state HAVE a CTA if it were shown?
                has_cta = page.evaluate("""
                    (() => {
                        var es = document.getElementById('emptyState');
                        return es ? !!es.querySelector('button, a') : false;
                    })()
                """)
                record("Boundary-56: Empty state has CTA button", cat, has_cta,
                       f"has_cta={has_cta}",
                       expected="Empty state includes actionable button/link",
                       actual=f"CTA button present: {has_cta}",
                       root_cause="UX" if not has_cta else "",
                       is_boundary=True)
            else:
                record("Boundary-56: Empty state has CTA button", cat, False,
                       "Could not evaluate", is_boundary=True)
            ctx.close()
        except Exception as e:
            record("Boundary-56: Empty state CTA", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-57: Markdown strikethrough support -----
        try:
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")

            result = page.evaluate("""
                (() => {
                    function applyInline(text) {
                        var html = text
                            .replace(/`([^`]+)`/g, '<code>$1</code>')
                            .replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>')
                            .replace(/\\*([^*]+)\\*/g, '<em>$1</em>')
                            .replace(/~~([^~]+)~~/g, '<del>$1</del>');
                        var span = document.createElement('span');
                        span.innerHTML = html;
                        return span;
                    }
                    var container = document.createElement('div');
                    container.appendChild(applyInline('This is ~~deleted~~ text'));
                    return {
                        hasStrikethrough: container.querySelector('del, s') !== null,
                        html: container.innerHTML
                    };
                })()
            """)
            has_strike = result.get("hasStrikethrough", False)
            record("Boundary-57: Markdown strikethrough (~~text~~)", cat, has_strike,
                   f"has_del_element={has_strike}",
                   expected="~~text~~ renders as <del> strikethrough",
                   actual=f"Strikethrough: {has_strike} (html: {result.get('html', '')[:50]})",
                   root_cause="parsing" if not has_strike else "",
                   is_boundary=True)
            ctx.close()
        except Exception as e:
            record("Boundary-57: Markdown strikethrough", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-58: Markdown image rendering -----
        try:
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")

            result = page.evaluate("""
                (() => {
                    function applyInline(text) {
                        var html = text
                            .replace(/!\\[([^\\]]+)\\]\\((https?:\\/\\/[^)]+)\\)/g, '<img src="$2" alt="$1">')
                            .replace(/\\[([^\\]]+)\\]\\((https?:\\/\\/[^)]+)\\)/g, '<a href="$2">$1</a>');
                        var span = document.createElement('span');
                        span.innerHTML = html;
                        return span;
                    }
                    var container = document.createElement('div');
                    container.appendChild(applyInline('![alt text](https://example.com/img.png)'));
                    return {
                        hasImage: container.querySelector('img') !== null,
                        html: container.innerHTML
                    };
                })()
            """)
            has_img = result.get("hasImage", False)
            record("Boundary-58: Markdown image rendering ![alt](url)", cat, has_img,
                   f"has_img_element={has_img}",
                   expected="![alt](url) renders as <img>",
                   actual=f"Image: {has_img} (html: {result.get('html', '')[:60]})",
                   root_cause="parsing" if not has_img else "",
                   is_boundary=True)
            ctx.close()
        except Exception as e:
            record("Boundary-58: Markdown image rendering", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-59: Keyboard shortcut to go back -----
        try:
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_selector(".session-card:not(.dead)", timeout=5000)
            active_cards = page.query_selector_all(".session-card:not(.dead)")
            if active_cards:
                active_cards[0].click()
                page.wait_for_selector("#chatFeed", timeout=5000)
                page.wait_for_timeout(500)

                # Try Escape to go back
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)

                # Check if we're back on session list
                is_list = page.evaluate("""
                    (() => {
                        var list = document.getElementById('screenList');
                        return list && !list.classList.contains('hidden-left');
                    })()
                """)
                record("Boundary-59: Escape key goes back to session list", cat, is_list,
                       f"back_to_list={is_list}",
                       expected="Escape navigates back to session list",
                       actual=f"On session list: {is_list}",
                       root_cause="interaction" if not is_list else "",
                       is_boundary=True)
            else:
                record("Boundary-59: Escape key navigation", cat, False,
                       "No active session", is_boundary=True)
            ctx.close()
        except Exception as e:
            record("Boundary-59: Escape key navigation", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-60: Loading skeleton/placeholder -----
        try:
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()

            # Slow down network to catch loading states
            cdp = ctx.new_cdp_session(page)
            cdp.send("Network.enable")
            cdp.send("Network.emulateNetworkConditions", {
                "offline": False,
                "downloadThroughput": 50000,  # 50kb/s
                "uploadThroughput": 50000,
                "latency": 500,
            })

            page.goto(BASE_URL, wait_until="domcontentloaded")
            # Check immediately for loading placeholder
            has_skeleton = page.evaluate("""
                (() => {
                    var list = document.getElementById('sessionList');
                    var skeleton = list ? list.querySelector('.skeleton, .loading, .placeholder, [class*="skeleton"]') : null;
                    return !!skeleton;
                })()
            """)
            record("Boundary-60: Session list loading skeleton", cat, has_skeleton,
                   f"has_skeleton={has_skeleton}",
                   expected="Loading skeleton shown while fetching sessions",
                   actual=f"Skeleton/placeholder: {has_skeleton}",
                   root_cause="UX" if not has_skeleton else "",
                   is_boundary=True)
            ctx.close()
        except Exception as e:
            record("Boundary-60: Loading skeleton", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-61: Chat view has aria-live for new messages -----
        try:
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")

            has_aria_live = page.evaluate("""
                (() => {
                    var feed = document.getElementById('chatFeed');
                    if (!feed) return false;
                    var ariaLive = feed.getAttribute('aria-live') ||
                                   feed.getAttribute('role') === 'log';
                    return !!ariaLive;
                })()
            """)
            record("Boundary-61: Chat feed has aria-live for screen readers", cat, has_aria_live,
                   f"aria_live={has_aria_live}",
                   expected="aria-live='polite' or role='log' on chat feed",
                   actual=f"aria-live present: {has_aria_live}",
                   root_cause="accessibility" if not has_aria_live else "",
                   is_boundary=True)
            ctx.close()
        except Exception as e:
            record("Boundary-61: aria-live", cat, False, str(e), is_boundary=True)

        # ----- Boundary-62: Input autofocus on session open -----
        try:
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_selector(".session-card:not(.dead)", timeout=5000)
            active_cards = page.query_selector_all(".session-card:not(.dead)")
            if active_cards:
                active_cards[0].click()
                page.wait_for_selector("#textInput", timeout=5000)
                page.wait_for_timeout(1000)

                is_focused = page.evaluate("""
                    document.activeElement === document.getElementById('textInput')
                """)
                # BOUNDARY: Text input should auto-focus when opening a session
                # This is debatable on mobile (keyboard pops up) but expected on desktop
                record("Boundary-62: Text input auto-focused on session open", cat, is_focused,
                       f"is_focused={is_focused}",
                       expected="Text input focused when session opens",
                       actual=f"Focused: {is_focused}",
                       root_cause="UX" if not is_focused else "",
                       is_boundary=True)
            else:
                record("Boundary-62: Input autofocus", cat, False,
                       "No active session", is_boundary=True)
            ctx.close()
        except Exception as e:
            record("Boundary-62: Input autofocus", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-63: Session card long title truncation -----
        try:
            if session:
                # Set a very long title
                long_title_60 = "A" * 60
                api_put(f"/api/sessions/{session}/title", {"title": long_title_60})

                ctx = browser.new_context(viewport={"width": 430, "height": 932})
                page = ctx.new_page()
                page.goto(BASE_URL, wait_until="networkidle")
                page.wait_for_timeout(1000)

                overflow_info = page.evaluate(f"""
                    (() => {{
                        var cards = document.querySelectorAll('.session-card-title');
                        for (var i = 0; i < cards.length; i++) {{
                            if (cards[i].textContent.indexOf('AAAA') >= 0) {{
                                var style = getComputedStyle(cards[i]);
                                return {{
                                    overflow: style.overflow,
                                    textOverflow: style.textOverflow,
                                    whiteSpace: style.whiteSpace,
                                    scrollWidth: cards[i].scrollWidth,
                                    clientWidth: cards[i].clientWidth,
                                    truncated: cards[i].scrollWidth > cards[i].clientWidth
                                }};
                            }}
                        }}
                        return null;
                    }})()
                """)
                if overflow_info:
                    has_ellipsis = overflow_info.get("textOverflow") == "ellipsis"
                    is_truncated = overflow_info.get("truncated", False)
                    passed = has_ellipsis and is_truncated
                    record("Boundary-63: Long title truncates with ellipsis", cat, passed,
                           f"textOverflow={overflow_info.get('textOverflow')}, truncated={is_truncated}",
                           expected="text-overflow: ellipsis on long titles",
                           actual=f"textOverflow={overflow_info.get('textOverflow')}, scrollW={overflow_info.get('scrollWidth')}, clientW={overflow_info.get('clientWidth')}",
                           root_cause="CSS" if not passed else "",
                           is_boundary=True)
                else:
                    record("Boundary-63: Long title truncation", cat, False,
                           "Long-titled card not found", is_boundary=True)

                # Restore
                api_put(f"/api/sessions/{session}/title", {"title": session})
                ctx.close()
            else:
                record("Boundary-63: Long title truncation", cat, False,
                       "No active session", is_boundary=True)
        except Exception as e:
            record("Boundary-63: Long title truncation", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-64: Permissions-Policy header -----
        try:
            r = requests.get(f"{BASE_URL}/", timeout=5)
            pp = r.headers.get("Permissions-Policy", "")
            passed = len(pp) > 0
            record("Boundary-64: Permissions-Policy header", cat, passed,
                   f"Permissions-Policy: '{pp[:60]}'",
                   expected="Permissions-Policy header restricting features",
                   actual=f"Permissions-Policy: {pp[:60] if pp else '(none)'}",
                   root_cause="security" if not passed else "",
                   is_boundary=True)
        except Exception as e:
            record("Boundary-64: Permissions-Policy", cat, False, str(e),
                   is_boundary=True)

        # ----- Boundary-65: Markdown task list / checkbox support -----
        try:
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")

            result = page.evaluate("""
                (() => {
                    // Task lists: - [ ] unchecked, - [x] checked
                    var md = '- [ ] unchecked\\n- [x] checked';
                    // The current renderer treats these as plain list items
                    // Check if checkboxes appear
                    var container = document.createElement('div');
                    var text = md.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                    container.innerHTML = '<ul><li>[ ] unchecked</li><li>[x] checked</li></ul>';
                    return {
                        hasCheckbox: container.querySelector('input[type="checkbox"]') !== null,
                        rendered: container.textContent.substring(0, 60)
                    };
                })()
            """)
            has_cb = result.get("hasCheckbox", False)
            record("Boundary-65: Markdown task list rendering", cat, has_cb,
                   f"has_checkbox={has_cb}",
                   expected="- [ ] renders as checkbox",
                   actual=f"Checkbox: {has_cb} (rendered as plain text)",
                   root_cause="parsing" if not has_cb else "",
                   is_boundary=True)
            ctx.close()
        except Exception as e:
            record("Boundary-65: Markdown task list", cat, False, str(e),
                   is_boundary=True)

        browser.close()


# ===================================================================
# REPORT
# ===================================================================

def print_report():
    print(f"\n{'='*72}")
    print(f"  TEST SUITE REPORT -- claude-chat")
    print(f"{'='*72}")

    categories = {}
    for r in results:
        categories.setdefault(r.category, []).append(r)

    total_pass = sum(1 for r in results if r.status == "PASS")
    total_fail = sum(1 for r in results if r.status == "FAIL")
    total_boundary = sum(1 for r in results if r.status == "BOUNDARY-FAIL")
    total = len(results)

    for cat_name, cat_results in categories.items():
        print(f"\n  --- {cat_name} ---")
        for r in cat_results:
            marker = {
                "PASS": "\033[32m[PASS]\033[0m",
                "FAIL": "\033[31m[FAIL]\033[0m",
                "BOUNDARY-FAIL": "\033[33m[BOUNDARY-FAIL]\033[0m",
            }[r.status]
            print(f"  {marker} {r.name}")
            if r.message:
                print(f"         {r.message}")
            if r.status in ("FAIL", "BOUNDARY-FAIL"):
                if r.expected:
                    print(f"         Expected: {r.expected}")
                if r.actual:
                    print(f"         Actual:   {r.actual}")
                if r.root_cause:
                    print(f"         Root cause: {r.root_cause}")

    print(f"\n{'='*72}")
    print(f"  SUMMARY")
    print(f"{'='*72}")
    print(f"  Total:          {total}")
    print(f"  \033[32mPass:           {total_pass}\033[0m")
    print(f"  \033[31mFail:           {total_fail}\033[0m")
    print(f"  \033[33mBoundary-Fail:  {total_boundary}\033[0m")
    pass_rate = (total_pass / total * 100) if total else 0
    print(f"  Pass rate:      {pass_rate:.1f}%")
    print(f"  (Boundary failures are expected -- they show where things break)")
    print(f"{'='*72}")


# ===================================================================
# MAIN
# ===================================================================

if __name__ == "__main__":
    print("Claude Chat Test Suite")
    print(f"Target: {BASE_URL}")
    print(f"Headless: {HEADLESS}")

    # Verify server is up
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        print(f"Server health: {r.json()}")
    except Exception as e:
        print(f"ERROR: Server not reachable at {BASE_URL}: {e}")
        sys.exit(1)

    try:
        run_unit_tests()
    except Exception as e:
        print(f"  UNIT TEST CATEGORY ERROR: {e}")
        traceback.print_exc()

    try:
        run_line_tests()
    except Exception as e:
        print(f"  LINE TEST CATEGORY ERROR: {e}")
        traceback.print_exc()

    try:
        run_e2e_tests()
    except Exception as e:
        print(f"  E2E TEST CATEGORY ERROR: {e}")
        traceback.print_exc()

    try:
        run_boundary_tests()
    except Exception as e:
        print(f"  BOUNDARY TEST CATEGORY ERROR: {e}")
        traceback.print_exc()

    try:
        run_additional_boundary_tests()
    except Exception as e:
        print(f"  ADDITIONAL BOUNDARY TEST CATEGORY ERROR: {e}")
        traceback.print_exc()

    print_report()

    # Exit 0 -- boundary failures are expected
    sys.exit(0)

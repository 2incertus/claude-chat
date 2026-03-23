#!/usr/bin/env python3
"""Capture screenshots and GIFs of claude-chat for the README.

Strategy:
1. Feed the test-ui tmux session with rich demo content using tmux markers
2. Use Playwright to authenticate, navigate, and capture screenshots + GIF frames
3. Assemble GIF with ffmpeg
"""

import time
import subprocess
import os
import shutil
from playwright.sync_api import sync_playwright

BASE = "http://localhost:8800"
PIN = "0028"
OUT = "/home/ubuntu/docker/claude-chat/docs/images"
SOCKET = "/tmp/tmux-1000/default"
SESSION = "test-ui"
os.makedirs(OUT, exist_ok=True)

# ── tmux helpers ──

def tmux(*args):
    """Run tmux command."""
    cmd = ["tmux", "-S", SOCKET] + list(args)
    subprocess.run(cmd, capture_output=True, text=True)


def clear_pane():
    """Clear the test-ui pane completely."""
    tmux("send-keys", "-t", SESSION, "clear", "Enter")
    time.sleep(0.3)


def send_line(text):
    """Send a line of text to the tmux pane (raw, as if output)."""
    # Use send-keys with literal flag to write text, then Enter
    tmux("send-keys", "-t", SESSION, "-l", text)
    tmux("send-keys", "-t", SESSION, "Enter")
    time.sleep(0.05)


def populate_demo_conversation():
    """Fill the test-ui session with a realistic Claude Code conversation."""
    clear_pane()
    time.sleep(0.5)

    lines = [
        "────────────────────────────────────────────",
        "❯ Build me a REST API for a bookshelf app with CRUD endpoints",
        "",
        "● I'll create a FastAPI bookshelf app with full CRUD. Let me start by setting up the project structure.",
        "",
        "● TaskCreate({subject: 'Create bookshelf API', description: 'FastAPI CRUD endpoints for books'})",
        "  ⎿ Task #1 created: Create bookshelf API",
        "",
        "● Write(app.py)",
        "  ⎿ Created app.py (45 lines)",
        "",
        "● Write(models.py)",
        "  ⎿ Created models.py (28 lines)",
        "",
        "● Bash(pip install fastapi uvicorn sqlalchemy)",
        "  ⎿ Successfully installed fastapi-0.115.0 uvicorn-0.30.0 sqlalchemy-2.0.35",
        "",
        "● Here's what I built:",
        "",
        "  **Endpoints:**",
        "  - `GET /books` — List all books (with pagination)",
        "  - `GET /books/{id}` — Get a specific book",
        "  - `POST /books` — Add a new book",
        "  - `PUT /books/{id}` — Update a book",
        "  - `DELETE /books/{id}` — Remove a book",
        "",
        "  **Tech stack:** FastAPI + SQLAlchemy + SQLite",
        "  **Run it:** `uvicorn app:app --reload`",
        "",
        "● TaskUpdate({taskId: '1', status: 'completed'})",
        "  ⎿ Task #1 completed",
        "",
        "● Bash(python -m pytest tests/ -v)",
        "  ⎿ tests/test_books.py::test_create_book PASSED",
        "  ⎿ tests/test_books.py::test_list_books PASSED",
        "  ⎿ tests/test_books.py::test_get_book PASSED",
        "  ⎿ tests/test_books.py::test_update_book PASSED",
        "  ⎿ tests/test_books.py::test_delete_book PASSED",
        "  ⎿ 5 passed in 0.42s",
        "",
        "● All 5 tests pass. The API is ready to use.",
        "",
        "────────────────────────────────────────────",
        "❯ Now add authentication with JWT tokens",
        "",
        "● Agent(description: 'Research JWT best practices', subagent_type: 'Explore')",
        "  ⎿ Found existing auth patterns in the codebase. Recommending python-jose + passlib.",
        "",
        "● Edit(app.py)",
        "  ⎿ Updated app.py: added JWT middleware, /auth/login and /auth/register endpoints",
        "",
        "● Write(auth.py)",
        "  ⎿ Created auth.py (62 lines) — JWT token creation, password hashing, dependency injection",
        "",
        "● Bash(python -m pytest tests/ -v --tb=short)",
        "  ⎿ 12 passed in 0.87s",
        "",
        "● Authentication is live. Every endpoint except `/auth/login` and `/auth/register` now requires a Bearer token.",
        "",
        "────────────────────────────────────────────",
        "❯ /review",
        "",
        "● Skill(review)",
        "  ⎿ Reviewing all changes since last commit...",
        "",
        "● **Code Review Summary:**",
        "  - ✅ Clean separation of concerns (auth.py isolated from business logic)",
        "  - ✅ Passwords hashed with bcrypt (cost factor 12)",
        "  - ✅ JWT tokens expire after 30 minutes",
        "  - ⚠️  Consider adding refresh token rotation",
        "  - ⚠️  Add rate limiting to /auth/login",
        "",
    ]

    for line in lines:
        send_line(line)

    time.sleep(0.5)


def auth_and_navigate(page):
    """Authenticate via the PIN screen."""
    page.goto(BASE)
    page.wait_for_timeout(800)

    # Handle auth
    login_screen = page.locator(".login-screen")
    if login_screen.is_visible(timeout=2000):
        pin_input = page.locator(".login-input")
        pin_input.fill(PIN)
        pin_input.press("Enter")
        page.wait_for_timeout(1500)


def go_to_session(page, name="test-ui"):
    """Click on a session card by name."""
    page.wait_for_timeout(1000)
    card = page.locator(f'.session-card[data-name="{name}"]')
    if card.is_visible(timeout=5000):
        card.click()
        page.wait_for_timeout(2000)
        return True
    # Fallback: try partial match on title
    cards = page.locator(".session-card")
    count = cards.count()
    for i in range(count):
        c = cards.nth(i)
        title = c.locator(".session-card-title").text_content(timeout=2000) or ""
        if name.lower() in title.lower():
            c.click()
            page.wait_for_timeout(2000)
            return True
    return False


# ── Screenshot captures ──

def capture_hero(browser):
    """Hero shot: desktop chat view with rich conversation."""
    ctx = browser.new_context(
        viewport={"width": 1280, "height": 800},
        device_scale_factor=2,
        color_scheme="dark",
    )
    page = ctx.new_page()
    auth_and_navigate(page)
    go_to_session(page, "test-ui")

    # Scroll to show the interesting middle part
    feed = page.locator("#chatFeed")
    feed.evaluate("el => el.scrollTop = el.scrollHeight * 0.15")
    page.wait_for_timeout(500)

    page.screenshot(path=f"{OUT}/hero-dark.png")
    print("  -> hero-dark.png")
    ctx.close()


def capture_sessions(browser):
    """Session list showing multiple active sessions."""
    ctx = browser.new_context(
        viewport={"width": 1280, "height": 800},
        device_scale_factor=2,
        color_scheme="dark",
    )
    page = ctx.new_page()
    auth_and_navigate(page)
    page.wait_for_timeout(2000)
    page.screenshot(path=f"{OUT}/sessions.png")
    print("  -> sessions.png")
    ctx.close()


def capture_mobile(browser):
    """Mobile view of session list and chat."""
    # Session list
    ctx = browser.new_context(
        viewport={"width": 390, "height": 844},
        device_scale_factor=2,
        color_scheme="dark",
    )
    page = ctx.new_page()
    auth_and_navigate(page)
    page.wait_for_timeout(2000)
    page.screenshot(path=f"{OUT}/mobile-sessions.png")
    print("  -> mobile-sessions.png")

    # Chat view
    go_to_session(page, "test-ui")
    feed = page.locator("#chatFeed")
    feed.evaluate("el => el.scrollTop = el.scrollHeight * 0.3")
    page.wait_for_timeout(500)
    page.screenshot(path=f"{OUT}/mobile-chat.png")
    print("  -> mobile-chat.png")
    ctx.close()


def capture_themes(browser):
    """Light and OLED themes via localStorage manipulation."""
    for theme in ["light", "oled"]:
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 800},
            device_scale_factor=2,
            color_scheme="light" if theme == "light" else "dark",
        )
        page = ctx.new_page()
        # Set theme before navigating
        page.goto(BASE)
        page.wait_for_timeout(300)
        page.evaluate(f"localStorage.setItem('theme', '{theme}')")
        auth_and_navigate(page)
        go_to_session(page, "test-ui")

        feed = page.locator("#chatFeed")
        feed.evaluate("el => el.scrollTop = el.scrollHeight * 0.15")
        page.wait_for_timeout(500)

        page.screenshot(path=f"{OUT}/theme-{theme}.png")
        print(f"  -> theme-{theme}.png")
        ctx.close()


def capture_demo_gif(browser):
    """Animated GIF: session list -> click session -> scroll conversation -> type message."""
    ctx = browser.new_context(
        viewport={"width": 1000, "height": 700},
        device_scale_factor=2,
        color_scheme="dark",
    )
    page = ctx.new_page()
    auth_and_navigate(page)

    frames_dir = f"{OUT}/frames"
    os.makedirs(frames_dir, exist_ok=True)
    frame_num = [0]

    def snap(delay=300):
        page.wait_for_timeout(delay)
        page.screenshot(path=f"{frames_dir}/frame_{frame_num[0]:04d}.png")
        frame_num[0] += 1

    # ── Act 1: Session list (hold ~1.5s)
    page.wait_for_timeout(1500)
    snap(200)
    snap(400)
    snap(400)
    snap(400)

    # ── Act 2: Click test-ui session (like a human - hover then click)
    card = page.locator('.session-card[data-name="test-ui"]')
    if card.is_visible(timeout=5000):
        card.hover()
        snap(400)
        card.click()

    snap(500)
    snap(400)
    snap(300)

    # ── Act 3: Slowly scroll through conversation
    feed = page.locator("#chatFeed")
    for _ in range(8):
        feed.evaluate("el => el.scrollBy({top: 180, behavior: 'smooth'})")
        snap(450)

    # Hold at bottom
    snap(500)
    snap(500)

    # ── Act 4: Type a message naturally
    text_input = page.locator("#textInput")
    if text_input.is_visible():
        text_input.click()
        snap(400)

        msg = "Add rate limiting to the login endpoint"
        for i, char in enumerate(msg):
            text_input.type(char, delay=0)
            # Snap at natural pauses (spaces, punctuation, every ~6 chars)
            if char == " " or i == len(msg) - 1 or i % 6 == 5:
                snap(150)

        # Hold showing the complete message
        snap(600)
        snap(600)

    # ── Act 5: Show command palette briefly
    text_input.fill("")
    snap(200)
    text_input.fill("/")
    snap(500)
    snap(500)
    snap(500)

    # ── Act 6: Back to session list
    text_input.fill("")
    page.wait_for_timeout(100)
    # Press Escape to close cmd palette if open
    page.keyboard.press("Escape")
    snap(300)
    back = page.locator("#backBtn")
    if back.is_visible():
        back.click()
    snap(500)
    snap(500)
    snap(500)

    total_frames = frame_num[0]
    print(f"  -> {total_frames} frames captured")

    # ── Assemble GIF
    gif_path = f"{OUT}/demo.gif"
    result = subprocess.run([
        "ffmpeg", "-y",
        "-framerate", "5",
        "-i", f"{frames_dir}/frame_%04d.png",
        "-vf", "scale=800:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3",
        "-loop", "0",
        gif_path
    ], capture_output=True, text=True)

    if os.path.exists(gif_path):
        size_mb = os.path.getsize(gif_path) / (1024 * 1024)
        print(f"  -> demo.gif ({size_mb:.1f} MB)")
    else:
        print(f"  !! GIF creation failed: {result.stderr[:200]}")

    shutil.rmtree(frames_dir, ignore_errors=True)
    ctx.close()


def main():
    print("Step 1: Populating test-ui with demo conversation...")
    populate_demo_conversation()

    print("Step 2: Capturing screenshots...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        capture_hero(browser)
        capture_sessions(browser)
        capture_mobile(browser)
        capture_themes(browser)

        print("Step 3: Capturing demo GIF...")
        capture_demo_gif(browser)

        browser.close()

    print("\nAll captures complete!")
    for f in sorted(os.listdir(OUT)):
        path = os.path.join(OUT, f)
        if os.path.isfile(path):
            size = os.path.getsize(path) / 1024
            unit = "KB"
            if size > 1024:
                size /= 1024
                unit = "MB"
            print(f"  {f}: {size:.1f} {unit}")


if __name__ == "__main__":
    main()

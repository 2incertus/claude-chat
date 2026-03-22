# Phase A: Code Split + Session Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the monolithic single-file app into backend + static frontend files, then add session kill/respawn/hide/dismiss functionality.

**Architecture:** Extract the INDEX_HTML Python string into `static/index.html`, `static/css/style.css`, and `static/js/app.js`. FastAPI serves static files and provides API endpoints. New endpoints for session lifecycle (kill, respawn, dismiss). Frontend gets swipe gestures and dead session rendering.

**Tech Stack:** Python/FastAPI, vanilla JS/CSS (now in separate files), Docker, tmux, Playwright (testing)

**Spec:** `docs/superpowers/specs/2026-03-21-phase-a-split-and-sessions-design.md`

---

### Task 1: Extract static files from INDEX_HTML

This is the foundation. Extract HTML/CSS/JS from the Python string into separate files, update app.py to serve them, and update Dockerfile. No behavior changes -- pure extraction.

**Files:**
- Create: `static/index.html`
- Create: `static/css/style.css`
- Create: `static/js/app.js`
- Modify: `app.py` (remove INDEX_HTML, add static serving)
- Modify: `Dockerfile`

- [ ] **Step 1: Extract CSS to `static/css/style.css`**

Read `app.py` lines 77-661 (everything inside `<style>...</style>`). Write it to `static/css/style.css` as-is. This is pure CSS, no Python escaping involved.

- [ ] **Step 2: Extract JS to `static/js/app.js`**

Read `app.py` lines 718-1635 (everything inside `<script>...</script>`, the IIFE). Write to `static/js/app.js`. **CRITICAL:** The JS was inside a Python triple-quoted string, so all `\\n` in string literals are actually meant to be `\n` in real JS. You must find-and-replace:
- `'\\n'` -> `'\n'` (in JS string literals like `content.split('\\n')`)
- `'\\t'` -> `'\t'` (if any)
- `'\\\\n'` -> `'\\n'` (double-escaped in regex patterns)
- `'\\\\s'` -> `'\\s'` (in regex patterns)
- `'\\\\S'` -> `'\\S'` (in regex patterns)
- `'\\\\d'` -> `'\\d'` (in regex patterns)

The regex on the current line 1048 is particularly tricky:
```javascript
// Current (inside Python string):
var codeRe = new RegExp('^(\\\\s{4,}\\\\S|\\\\s*\\\\d+[\\u2192|:]\\\\s)');
// Correct in real JS file:
var codeRe = new RegExp('^(\\s{4,}\\S|\\s*\\d+[\\u2192|:]\\s)');
```

After extraction, validate with: `node --check static/js/app.js`

- [ ] **Step 3: Create `static/index.html`**

Create the HTML shell that links to the CSS and JS:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no, viewport-fit=cover">
  <title>Claude Voice Chat</title>
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="theme-color" content="#0A0A0A">
  <link rel="manifest" href="/manifest.json">
  <link rel="stylesheet" href="/static/css/style.css">
</head>
<body>
<!-- paste body content from app.py lines 664-665 (the app-shell div and everything inside) -->
<script src="/static/js/app.js"></script>
</body>
</html>
```

Copy the `<body>` content from app.py lines 664-665 (`<div class="app-shell">` through `</div>` at line 665 and all the screen divs, inputs, toast etc.) into the HTML body. Remove any Python escape artifacts.

- [ ] **Step 4: Update `app.py` to serve static files**

Remove the entire `INDEX_HTML = """..."""` block (lines 67-1637).

Add these imports at the top:
```python
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
```

After `app = FastAPI(...)`, add:
```python
app.mount("/static", StaticFiles(directory="static"), name="static")
```

Replace the index route:
```python
@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(
        "static/index.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )
```

Remove `HTMLResponse` from the `fastapi.responses` import if it's no longer used elsewhere (check first -- it might be used in type hints).

- [ ] **Step 5: Update Dockerfile**

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y tmux && rm -rf /var/lib/apt/lists/*
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn httpx python-multipart
COPY app.py .
COPY static/ ./static/
EXPOSE 8800
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8800"]
```

- [ ] **Step 6: Validate JS and rebuild**

```bash
node --check static/js/app.js
docker compose -f /home/ubuntu/compose/claude-chat-compose.yml up -d --build
```

Wait 3 seconds, then verify:
```bash
curl -s --max-time 10 http://localhost:8800/health
curl -s --max-time 10 http://localhost:8800/ | head -5
curl -s --max-time 10 http://localhost:8800/static/js/app.js | head -3
```

- [ ] **Step 7: Playwright regression test**

Run the existing test suite (`/tmp/test-claude-chat.js`) or write a quick verification:
```bash
cd /home/ubuntu/docker/mathias-life && NODE_PATH=./node_modules node -e "
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch({ headless: true });
  const p = await b.newPage({ viewport: { width: 390, height: 844 } });
  const errs = [];
  p.on('pageerror', e => { errs.push(e.message); console.log('PAGE ERROR:', e.message); });
  await p.goto('http://localhost:8800', { waitUntil: 'networkidle', timeout: 15000 });
  await p.waitForTimeout(2000);
  const cards = await p.\$\$('.session-card');
  console.log('Sessions:', cards.length);
  if (cards.length > 0) {
    await cards[0].click();
    await p.waitForTimeout(3000);
    const msgs = await p.\$\$('.msg');
    const copy = await p.\$\$('.msg-copy-btn');
    const tts = await p.\$\$('.msg-tts-btn');
    const bell = await p.\$('#bellBtn');
    console.log('Messages:', msgs.length, 'Copy:', copy.length, 'TTS:', tts.length, 'Bell:', !!bell);
  }
  console.log('JS errors:', errs.length === 0 ? 'none' : errs.join('; '));
  await b.close();
})();
"
```

All existing features (copy buttons, TTS, bell toggle, upload, send/mic toggle, ntfy) must still work.

- [ ] **Step 8: Commit**

```bash
cd /home/ubuntu/docker/claude-chat
git add static/ app.py Dockerfile
git commit -m "refactor: split frontend into static files

Extract INDEX_HTML into static/index.html, static/css/style.css, and
static/js/app.js. Eliminates Python escape sequence issues. app.py is
now pure API backend (~400 lines). No behavior changes."
```

---

### Task 2: Backend session lifecycle endpoints

Add kill, respawn, dismiss endpoints and update session discovery to return dead sessions.

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Add `kill-session` to ALLOWED_COMMANDS**

Find the `ALLOWED_COMMANDS` set (top of file) and add `"kill-session"`.

- [ ] **Step 2: Add `_session_exists` helper**

After the existing `_is_claude_session` function, add:

```python
def _session_exists(name: str) -> bool:
    """Return True if a tmux session with this name exists (regardless of what's running)."""
    try:
        raw = run_tmux("list-sessions", "-F", "#{session_name}")
        return name in raw.splitlines()
    except RuntimeError:
        return False
```

Add `"list-sessions"` to `ALLOWED_COMMANDS` if not already present (it is -- verify).

- [ ] **Step 3: Update `discover_sessions` to return dead sessions**

Update `discover_sessions()` to return all tmux sessions with a `state` field:

```python
def discover_sessions() -> list[dict]:
    """Return list of tmux sessions with state: active (claude running) or dead."""
    try:
        raw = run_tmux(
            "list-panes", "-a",
            "-F", "#{session_name}\t#{pane_pid}\t#{pane_current_command}\t#{pane_current_path}"
        )
    except RuntimeError:
        return []

    sessions = []
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        sname, pid_str, cmd, cwd = parts[0], parts[1], parts[2], parts[3]
        # Skip names starting with '-' -- they break tmux -t flag parsing
        if sname.startswith("-"):
            continue

        state = "active" if cmd == "claude" else "dead"

        meta: dict = {}
        if state == "active":
            try:
                pid = int(pid_str)
                meta_path = os.path.join(CLAUDE_DATA_DIR, "sessions", f"{pid}.json")
                with open(meta_path) as f:
                    meta = json.load(f)
            except Exception:
                pass

        sessions.append({
            "name": sname,
            "pid": pid_str,
            "cwd": meta.get("cwd", cwd),
            "session_id": meta.get("sessionId", ""),
            "started_at": meta.get("startedAt", 0),
            "state": state,
        })

    return sessions
```

- [ ] **Step 4: Update `list_sessions` endpoint to include state**

In the `list_sessions` endpoint, add `"state": s["state"]` to each result dict. For dead sessions, skip the title generation and preview (just use the session name as title and empty preview):

```python
if s["state"] == "dead":
    result.append({
        "name": name,
        "pid": s["pid"],
        "title": name,
        "cwd": s["cwd"],
        "last_activity": "",
        "status": "dead",
        "state": "dead",
        "preview": "",
    })
    continue
```

Place this check at the beginning of the `for s in sessions:` loop, before the `run_tmux("capture-pane", ...)` call (dead sessions may not have meaningful capture output).

- [ ] **Step 5: Add kill endpoint**

```python
@app.post("/api/sessions/{name}/kill")
async def kill_session(name: str):
    """Send Ctrl+C to Claude, wait, verify it exited."""
    validate_session_name(name)
    if not _session_exists(name):
        raise HTTPException(status_code=404, detail="Session not found")

    # Send Ctrl+C
    run_tmux("send-keys", "-t", name, "C-c")
    await asyncio.sleep(2)

    # Check if Claude is still running
    still_active = _is_claude_session(name)
    if still_active:
        run_tmux("send-keys", "-t", name, "C-c")
        await asyncio.sleep(1)
        still_active = _is_claude_session(name)

    state = "active" if still_active else "dead"
    return {"killed": not still_active, "state": state}
```

- [ ] **Step 6: Add respawn endpoint**

```python
@app.post("/api/sessions/{name}/respawn")
async def respawn_session(name: str):
    """Respawn Claude in an existing tmux session."""
    validate_session_name(name)
    if not _session_exists(name):
        raise HTTPException(status_code=404, detail="Session not found")
    if _is_claude_session(name):
        return {"respawned": False, "message": "Session already has Claude running"}

    run_tmux("send-keys", "-t", name, "-l", "claude --continue")
    run_tmux("send-keys", "-t", name, "Enter")
    return {"respawned": True}
```

- [ ] **Step 7: Add dismiss (delete) endpoint**

```python
@app.delete("/api/sessions/{name}")
async def dismiss_session(name: str):
    """Kill the tmux session entirely."""
    validate_session_name(name)
    if not _session_exists(name):
        raise HTTPException(status_code=404, detail="Session not found")

    # If Claude is still running, Ctrl+C first
    if _is_claude_session(name):
        run_tmux("send-keys", "-t", name, "C-c")
        await asyncio.sleep(1)

    run_tmux("kill-session", "-t", name)
    return {"dismissed": True}
```

- [ ] **Step 8: Rebuild and test endpoints with curl**

```bash
docker compose -f /home/ubuntu/compose/claude-chat-compose.yml up -d --build
sleep 3

# List sessions -- should include state field
curl -s http://localhost:8800/api/sessions | python3 -c "import sys,json; [print(s['name'], s['state']) for s in json.load(sys.stdin)]"

# Health check
curl -s http://localhost:8800/health
```

Do NOT test kill/respawn/dismiss on real sessions yet -- that's for manual testing.

- [ ] **Step 9: Commit**

```bash
git add app.py
git commit -m "feat: add session lifecycle endpoints (kill, respawn, dismiss)

- discover_sessions() now returns dead sessions with state field
- POST /api/sessions/{name}/kill sends Ctrl+C
- POST /api/sessions/{name}/respawn runs claude --continue
- DELETE /api/sessions/{name} kills tmux session
- Added _session_exists() helper, kill-session to ALLOWED_COMMANDS"
```

---

### Task 3: Frontend dead session rendering + swipe gestures

Add dead session card styling, swipe-to-reveal actions, kill/respawn/dismiss UI handlers, and hide functionality.

**Files:**
- Modify: `static/css/style.css`
- Modify: `static/js/app.js`
- Modify: `static/index.html` (if needed for new HTML elements)

- [ ] **Step 1: Add dead session + swipe CSS to `style.css`**

Add at the end of the session card styles:

```css
/* Dead session card */
.session-card.dead {
  opacity: 0.5;
  border-left: 3px solid var(--red);
}
.session-card.dead .session-card-status {
  background: var(--red);
  animation: none;
}

/* Swipe container */
.session-card-wrapper {
  position: relative;
  overflow: hidden;
  border-radius: var(--radius);
  margin-bottom: 10px;
}
.session-card-wrapper .session-card {
  margin-bottom: 0;
  transition: transform 200ms ease-out;
}
.swipe-actions {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  display: flex;
  align-items: center;
}
.swipe-action-btn {
  height: 100%;
  padding: 0 20px;
  border: none;
  color: white;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  touch-action: manipulation;
  display: flex;
  align-items: center;
}
.swipe-action-btn.kill { background: var(--red); }
.swipe-action-btn.dismiss { background: var(--red); }
.swipe-action-btn.hide { background: var(--text-dim); }

/* Respawn button on dead cards */
.respawn-btn {
  margin-top: 8px;
  background: rgba(232, 115, 74, 0.15);
  border: 1px solid var(--accent);
  color: var(--accent);
  padding: 6px 14px;
  border-radius: 8px;
  font-size: 0.78rem;
  font-weight: 600;
  cursor: pointer;
  touch-action: manipulation;
  width: 100%;
}
.respawn-btn:active { opacity: 0.7; }

/* Show hidden toggle */
.show-hidden-toggle {
  text-align: center;
  padding: 12px;
  color: var(--text-dim);
  font-size: 0.78rem;
  cursor: pointer;
  touch-action: manipulation;
}
.show-hidden-toggle:active { color: var(--text); }
```

- [ ] **Step 2: Update `renderSessionList` in `app.js` to handle dead sessions and swipe**

Replace the `renderSessionList` function to:
1. Wrap each card in a `.session-card-wrapper` with swipe actions behind it
2. Add `.dead` class and respawn button for dead sessions
3. Filter hidden sessions (from localStorage)
4. Add swipe gesture handling

This is a significant rewrite of `renderSessionList`. The new version should:
- Check `localStorage.getItem('hidden_sessions')` and filter
- For each session, create a wrapper div with the card and swipe action(s) behind it
- Active sessions: swipe left reveals "Kill" button
- Dead sessions: show respawn button on card, swipe left reveals "Dismiss"
- Add touch event listeners for swipe gesture (touchstart/touchmove/touchend on the card)
- Add click handlers for Kill, Respawn, Dismiss buttons that call the API

- [ ] **Step 3: Add API call functions for kill/respawn/dismiss**

Add to `app.js`:

```javascript
function killSession(name) {
  fetch('/api/sessions/' + encodeURIComponent(name) + '/kill', { method: 'POST' })
    .then(function(r) { return r.json(); })
    .then(function() { loadSessions(); })
    .catch(function() { loadSessions(); });
}

function respawnSession(name) {
  fetch('/api/sessions/' + encodeURIComponent(name) + '/respawn', { method: 'POST' })
    .then(function(r) { return r.json(); })
    .then(function() { loadSessions(); })
    .catch(function() { loadSessions(); });
}

function dismissSession(name) {
  fetch('/api/sessions/' + encodeURIComponent(name), { method: 'DELETE' })
    .then(function() {
      var dismissed = JSON.parse(localStorage.getItem('dismissed_sessions') || '[]');
      if (dismissed.indexOf(name) === -1) dismissed.push(name);
      localStorage.setItem('dismissed_sessions', JSON.stringify(dismissed));
      loadSessions();
    })
    .catch(function() { loadSessions(); });
}

function hideSession(name) {
  var hidden = JSON.parse(localStorage.getItem('hidden_sessions') || '[]');
  if (hidden.indexOf(name) === -1) hidden.push(name);
  localStorage.setItem('hidden_sessions', JSON.stringify(hidden));
  loadSessions();
}
```

- [ ] **Step 4: Add "Show hidden" toggle to session list**

In `index.html`, after the `#sessionList` div but still inside `#screenList`, add:
```html
<div class="show-hidden-toggle" id="showHiddenToggle" style="display:none;">Show hidden sessions</div>
```

In `app.js`, add toggle logic in `renderSessionList`:
- If there are hidden sessions, show the toggle
- Clicking toggles a `showHidden` flag and re-renders

- [ ] **Step 5: Rebuild and Playwright test**

```bash
docker compose -f /home/ubuntu/compose/claude-chat-compose.yml up -d --build
```

Playwright test to verify:
1. Session cards render (including any dead sessions)
2. Dead sessions have `.dead` class and respawn button
3. No JS errors
4. Existing features still work (messages, copy, TTS, bell, upload)

- [ ] **Step 6: Commit**

```bash
git add static/
git commit -m "feat: add session kill/respawn/dismiss UI with swipe gestures

- Dead sessions shown with red border and muted opacity
- Swipe left reveals Kill (active) or Dismiss (dead)
- Respawn button on dead session cards
- Hide sessions via swipe right
- Show hidden toggle at bottom of list"
```

---

### Task 4: Integration testing

Full end-to-end test of all features.

**Files:**
- Create: `/tmp/test-phase-a.js` (temporary)

- [ ] **Step 1: Write and run comprehensive Playwright test**

Test all features:
1. Page loads from static files, no JS errors
2. Sessions load with `state` field
3. Click into session, messages render with copy/TTS buttons
4. Bell toggle works
5. Send/mic toggle works
6. Dead sessions (if any) show dead styling
7. Text selection works on assistant messages
8. Navigate back, sessions still visible

- [ ] **Step 2: Test session lifecycle endpoints with curl**

```bash
# Test on a non-critical session or create a test session:
tmux new-session -d -s test-kill -c /tmp
tmux send-keys -t test-kill 'echo hello' Enter

# Verify it shows as dead in API
curl -s http://localhost:8800/api/sessions | python3 -c "import sys,json; [print(s['name'], s['state']) for s in json.load(sys.stdin) if s['name']=='test-kill']"

# Kill it
curl -s -X DELETE http://localhost:8800/api/sessions/test-kill
```

- [ ] **Step 3: Manual test on phone**

Open chat.library.icu (or Tailscale IP:8800) on phone and verify:
- Sessions load
- Swipe left on a session card reveals Kill button
- All existing features work

- [ ] **Step 4: Clean up**

Remove temporary test files.

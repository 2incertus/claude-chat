# Copy from Replies + ntfy Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add copy buttons to assistant messages and code blocks, and per-session ntfy notifications when Claude finishes working.

**Architecture:** All frontend changes live in the `INDEX_HTML` Python string inside `app.py`. One small backend endpoint (`POST /api/ntfy`) proxies notifications to the internal ntfy server. Playwright tests verify each feature after implementation.

**Tech Stack:** Python/FastAPI (backend), vanilla JS/CSS (frontend, inline in Python string), Playwright (testing)

**Spec:** `docs/superpowers/specs/2026-03-21-copy-and-ntfy-design.md`

---

### Task 1: Copy button CSS + code block copy button

**Files:**
- Modify: `/home/ubuntu/docker/claude-chat/app.py` (CSS section ~line 354-392, JS `appendMessage` ~line 951-1015)

**CRITICAL: All JS inside the Python triple-quoted `INDEX_HTML` string must use `\\n` not `\n`, `\\t` not `\t`, etc. Python interprets escape sequences before the browser sees the code. After ANY change, extract the rendered JS and run `node --check` on it.**

- [ ] **Step 1: Add CSS for copy buttons**

After the `.msg-tts-btn.playing` rule (line 392), add:

```css
    .msg-copy-btn {
      position: absolute;
      bottom: 8px;
      right: 48px;
      background: none;
      border: none;
      color: var(--text-dim);
      cursor: pointer;
      padding: 4px 6px;
      touch-action: manipulation;
      min-width: 44px;
      min-height: 44px;
      display: flex;
      align-items: center;
      justify-content: center;
      border-radius: 8px;
      transition: color 150ms, background 150ms;
    }
    .msg-copy-btn:active {
      background: rgba(255,255,255,0.08);
    }
    .code-block {
      position: relative;
    }
    .code-copy-btn {
      position: absolute;
      top: 4px;
      right: 4px;
      background: rgba(255,255,255,0.08);
      border: none;
      color: var(--text-dim);
      cursor: pointer;
      padding: 4px;
      border-radius: 4px;
      display: flex;
      align-items: center;
      justify-content: center;
      opacity: 0;
      transition: opacity 150ms;
      z-index: 2;
    }
    .code-block:hover .code-copy-btn,
    .code-copy-btn:focus { opacity: 1; }
    @media (hover: none) { .code-copy-btn { opacity: 0.6; } }
```

- [ ] **Step 2: Add clipboard helper function in JS**

At the top of the IIFE (after the element declarations, ~line 717), add a `copyToClipboard` helper:

```javascript
  // ========== Clipboard ==========
  function copyToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function() {
        showCopyToast();
      }).catch(function() {
        fallbackCopy(text);
      });
    } else {
      fallbackCopy(text);
    }
  }
  function fallbackCopy(text) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    showCopyToast();
  }
  function showCopyToast() {
    uploadToast.textContent = 'Copied!';
    uploadToast.style.display = 'block';
    setTimeout(function() { uploadToast.style.display = 'none'; }, 1500);
  }
```

Remember: inside the Python string, use `\\n` for literal `\n` in JS strings.

- [ ] **Step 3: Add copy button to code blocks in `appendMessage`**

In the `appendMessage` function, where code blocks are created (the two places where `pre.className = 'code-block'` is set, ~lines 980 and 997), add a copy button to each `<pre>` element right after `pre.appendChild(code)`:

```javascript
            var copyBtn = document.createElement('button');
            copyBtn.className = 'code-copy-btn';
            copyBtn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>';
            copyBtn.title = 'Copy code';
            (function(codeText) {
              copyBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                copyToClipboard(codeText);
              });
            })(codeBuf.join('\\n'));
            pre.appendChild(copyBtn);
```

This must be added in BOTH places where code blocks are created (the `if (inCode && codeBuf.length >= 2)` blocks inside the loop and after the loop).

- [ ] **Step 4: Add copy button to assistant messages**

In the `appendMessage` function, after the TTS button is appended (~line 1017 `el.appendChild(ttsBtn)`), add:

```javascript
      // Copy button
      var copyBtn = document.createElement('button');
      copyBtn.className = 'msg-copy-btn';
      copyBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>';
      copyBtn.title = 'Copy message';
      (function(text) {
        copyBtn.addEventListener('click', function(e) {
          e.stopPropagation();
          copyToClipboard(text);
        });
      })(content);
      el.appendChild(copyBtn);
```

- [ ] **Step 5: Validate JS and rebuild**

```bash
docker exec claude-chat python3 -c "
import sys; sys.path.insert(0, '/app'); from app import INDEX_HTML
start = INDEX_HTML.index('<script>') + 8; end = INDEX_HTML.index('</script>')
with open('/tmp/rendered.js', 'w') as f: f.write(INDEX_HTML[start:end])
" && docker cp claude-chat:/tmp/rendered.js /tmp/rendered.js && node --check /tmp/rendered.js
```

Then rebuild:
```bash
docker compose -f /home/ubuntu/compose/claude-chat-compose.yml up -d --build
```

- [ ] **Step 6: Playwright test for copy buttons**

Write and run a Playwright test that verifies:
1. Assistant messages have `.msg-copy-btn` elements
2. Code blocks have `.code-copy-btn` elements
3. No JS errors on page load
4. Copy buttons are clickable (click doesn't throw)

---

### Task 2: ntfy backend proxy endpoint

**Files:**
- Modify: `/home/ubuntu/docker/claude-chat/app.py` (Python section, after the upload endpoint ~line 1895)

- [ ] **Step 1: Add ntfy proxy endpoint**

After the upload endpoint, add:

```python
@app.post("/api/ntfy")
async def send_ntfy(request_body: dict):
    """Proxy notification to internal ntfy server."""
    title = request_body.get("title", "Claude Chat")
    body = request_body.get("body", "")
    tags = request_body.get("tags", "robot")
    try:
        resp = await http_client.post(
            "http://host.docker.internal:8180/ai-hub",
            content=body.encode(),
            headers={
                "Title": title,
                "Tags": tags,
            },
            timeout=5.0,
        )
        return {"sent": True, "status": resp.status_code}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"ntfy error: {str(e)}")
```

- [ ] **Step 2: Rebuild and test with curl**

```bash
docker compose -f /home/ubuntu/compose/claude-chat-compose.yml up -d --build
```

Then test:
```bash
curl -s -X POST http://localhost:8800/api/ntfy \
  -H 'Content-Type: application/json' \
  -d '{"title":"Test","body":"Hello from claude-chat","tags":"robot"}'
```

Expected: `{"sent":true,"status":200}` and a notification appears on your phone.

---

### Task 3: Bell toggle + ntfy notification logic (frontend)

**Files:**
- Modify: `/home/ubuntu/docker/claude-chat/app.py` (HTML ~line 639, CSS section, JS section)

- [ ] **Step 1: Add bell icon CSS**

Add after the `.status-dot.working` CSS (~line 206):

```css
    .bell-btn {
      background: none;
      border: none;
      color: var(--text-dim);
      cursor: pointer;
      padding: 4px;
      touch-action: manipulation;
      min-width: 44px;
      min-height: 44px;
      display: flex;
      align-items: center;
      justify-content: center;
      margin-left: 4px;
      flex-shrink: 0;
      transition: color 150ms;
    }
    .bell-btn.active { color: var(--accent); }
    .bell-btn:active { opacity: 0.7; }
```

- [ ] **Step 2: Add bell button to chat header HTML**

In the `#screenChat` header (line 639-641), add a bell button between the title and status dot:

Change:
```html
      <span class="session-header-title" id="chatTitle">Session</span>
      <div class="status-dot" id="chatStatus"></div>
```

To:
```html
      <span class="session-header-title" id="chatTitle">Session</span>
      <button class="bell-btn" id="bellBtn" title="Notify when done"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></svg></button>
      <div class="status-dot" id="chatStatus"></div>
```

- [ ] **Step 3: Add bell toggle JS + ntfy notification logic**

In the JS element declarations section (~line 717), add:

```javascript
  var bellBtn = document.getElementById('bellBtn');
```

Then add a new section after the File Upload section (~after line 1282):

```javascript
  // ========== ntfy Notifications ==========
  var previousStatus = {};
  var lastNtfyTime = {};

  function isNtfyEnabled(session) {
    try {
      var s = JSON.parse(localStorage.getItem('ntfy_sessions') || '{}');
      return !!s[session];
    } catch(e) { return false; }
  }

  function setNtfyEnabled(session, enabled) {
    try {
      var s = JSON.parse(localStorage.getItem('ntfy_sessions') || '{}');
      s[session] = enabled;
      localStorage.setItem('ntfy_sessions', JSON.stringify(s));
    } catch(e) {}
  }

  function updateBellIcon() {
    if (!currentSession) return;
    var on = isNtfyEnabled(currentSession);
    bellBtn.classList.toggle('active', on);
    bellBtn.innerHTML = on
      ? '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="1"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></svg>'
      : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></svg>';
  }

  bellBtn.addEventListener('click', function() {
    if (!currentSession) return;
    var now = !isNtfyEnabled(currentSession);
    setNtfyEnabled(currentSession, now);
    updateBellIcon();
  });

  function sendNtfy(title, body) {
    fetch('/api/ntfy', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: title, body: body, tags: 'robot' })
    }).catch(function() { /* silent fail */ });
  }

  function checkNtfyTrigger(sessionName, status, messages) {
    var prev = previousStatus[sessionName];
    previousStatus[sessionName] = status;
    if (prev === 'working' && status === 'idle' && isNtfyEnabled(sessionName)) {
      var now = Date.now();
      if (lastNtfyTime[sessionName] && (now - lastNtfyTime[sessionName]) < 30000) return;
      lastNtfyTime[sessionName] = now;
      var body = '';
      if (messages && messages.length > 0) {
        var asst = messages.filter(function(m) { return m.role === 'assistant'; });
        if (asst.length > 0) {
          body = (asst[asst.length - 1].content || '').substring(0, 200);
          if (body.length >= 200) {
            var sp = body.lastIndexOf(' ');
            if (sp > 150) body = body.substring(0, sp);
            body += '...';
          }
        }
      } else {
        var domMsgs = chatFeed.querySelectorAll('.msg-assistant-text');
        if (domMsgs.length > 0) {
          body = (domMsgs[domMsgs.length - 1].textContent || '').substring(0, 200);
          if (body.length >= 200) {
            var sp = body.lastIndexOf(' ');
            if (sp > 150) body = body.substring(0, sp);
            body += '...';
          }
        }
      }
      var title = 'Claude finished in ' + (chatTitle.textContent || sessionName);
      sendNtfy(title, body);
    }
  }
```

Remember: ALL `\\n` in string literals inside this Python string must be double-escaped.

- [ ] **Step 4: Wire ntfy check into the poll handler**

In the `doPoll` function's `.then(function(data) {...})` handler (~line 1048), add a call to `checkNtfyTrigger` right after `updateStatusDot(data.status)`:

```javascript
        checkNtfyTrigger(currentSession, data.status, data.has_changes ? data.messages : null);
```

- [ ] **Step 5: Update `showSessionView` to render bell state**

In the `showSessionView` function (~line 759), after `hidePreview();` and before the screen class changes, add:

```javascript
    updateBellIcon();
```

- [ ] **Step 6: Validate JS, rebuild, and test**

Extract JS and run `node --check`:
```bash
docker exec claude-chat python3 -c "
import sys; sys.path.insert(0, '/app'); from app import INDEX_HTML
start = INDEX_HTML.index('<script>') + 8; end = INDEX_HTML.index('</script>')
with open('/tmp/rendered.js', 'w') as f: f.write(INDEX_HTML[start:end])
" && docker cp claude-chat:/tmp/rendered.js /tmp/rendered.js && node --check /tmp/rendered.js
```

Rebuild:
```bash
docker compose -f /home/ubuntu/compose/claude-chat-compose.yml up -d --build
```

Run Playwright test verifying:
1. Bell button exists in chat header
2. Clicking bell toggles `.active` class
3. `localStorage.getItem('ntfy_sessions')` updates on click
4. No JS errors

---

### Task 4: Full integration test

**Files:**
- Create: `/tmp/test-copy-ntfy.js` (temporary Playwright test)

- [ ] **Step 1: Write and run comprehensive Playwright test**

Test all features:
1. Page loads without JS errors
2. Sessions load
3. Click into session, messages render
4. Assistant messages have `.msg-copy-btn` buttons
5. Code blocks (if any) have `.code-copy-btn` buttons
6. Bell button exists in header
7. Bell toggles on click, localStorage updates
8. Text selection not blocked on assistant messages (check computed `user-select` style)
9. Upload and send/mic toggle still work (regression check)
10. No JS errors after all interactions

- [ ] **Step 2: Test ntfy endpoint**

```bash
curl -s -X POST http://localhost:8800/api/ntfy \
  -H 'Content-Type: application/json' \
  -d '{"title":"Integration Test","body":"Copy + ntfy features verified","tags":"white_check_mark"}'
```

Verify notification arrives on phone.

- [ ] **Step 3: Clean up test files**

Remove temporary test scripts and uploaded test files.

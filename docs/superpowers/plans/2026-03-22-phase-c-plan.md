# Phase C: Slash Commands + Session Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add command palette, command result cards, session renaming, and session creation with presets to claude-chat.

**Architecture:** Four independent features developed in isolated git worktrees. Merge order: Task 3 (rename) first (smallest), then Task 2 (result cards, frontend-only), then Task 1 (command palette, backend+frontend), then Task 4 (session creation, backend+frontend+infra). Tasks 1 and 4 both modify the Dockerfile and index.html, so they must merge sequentially.

**Tech Stack:** Python/FastAPI, vanilla JS/CSS, Docker, PyYAML, Playwright (testing)

**Spec:** `docs/superpowers/specs/2026-03-22-phase-c-slash-commands-and-sessions-design.md`

---

### Task 1: Command Palette

**Files:**
- Modify: `app.py` (add `GET /api/commands` endpoint, add `import glob`, add `import yaml`)
- Modify: `static/js/app.js` (add command palette state, autocomplete popup handler, command button handler, fetch commands)
- Modify: `static/css/style.css` (add `.cmd-palette`, `.cmd-item`, `.cmd-btn` styles)
- Modify: `static/index.html` (add command button in input row, add palette container)
- Modify: `Dockerfile` (add `pyyaml` to pip install)

**Context:** The text input area is in `static/index.html` lines 55-62. The input row has: attach button, textarea, mic button, send button. The command `/` button goes between attach and textarea. The palette popup renders above the input area.

The backend scans `~/.claude/skills/*/SKILL.md` for custom skill definitions with YAML frontmatter. `CLAUDE_DATA_DIR` (line 19 in `app.py`) maps to `~/.claude` via the `/claude-data:ro` volume mount.

- [ ] **Step 1: Add pyyaml to Dockerfile**

In `Dockerfile`, change:
```
RUN pip install --no-cache-dir fastapi uvicorn httpx python-multipart
```
to:
```
RUN pip install --no-cache-dir fastapi uvicorn httpx python-multipart pyyaml
```

- [ ] **Step 2: Add `/api/commands` endpoint to app.py**

At the top of `app.py`, add `import glob` after `import json` (line 4) and add `import yaml` after `import httpx` (line 8).

After the `/api/ntfy` endpoint (end of file, around line 722), add:

```python
# ---------------------------------------------------------------------------
# Command discovery
# ---------------------------------------------------------------------------
_commands_cache: dict = {"commands": [], "ts": 0}

BUILTIN_COMMANDS = [
    {"name": "/compact", "desc": "Compress conversation context", "source": "builtin"},
    {"name": "/clear", "desc": "Clear conversation history", "source": "builtin"},
    {"name": "/help", "desc": "Show available commands", "source": "builtin"},
    {"name": "/doctor", "desc": "Check Claude Code health", "source": "builtin"},
    {"name": "/config", "desc": "View or change settings", "source": "builtin"},
    {"name": "/cost", "desc": "Show token usage and cost", "source": "builtin"},
    {"name": "/memory", "desc": "Edit CLAUDE.md memory files", "source": "builtin"},
    {"name": "/login", "desc": "Log in to your account", "source": "builtin"},
    {"name": "/logout", "desc": "Log out of your account", "source": "builtin"},
    {"name": "/status", "desc": "Show session status", "source": "builtin"},
    {"name": "/review", "desc": "Review recent changes", "source": "builtin"},
    {"name": "/bug", "desc": "Report a bug", "source": "builtin"},
    {"name": "/init", "desc": "Initialize project CLAUDE.md", "source": "builtin"},
]


@app.get("/api/commands")
async def list_commands():
    now = time.time()
    if _commands_cache["ts"] and (now - _commands_cache["ts"]) < 60:
        return {"commands": _commands_cache["commands"]}

    skills = []
    skills_dir = os.path.join(CLAUDE_DATA_DIR, "skills")
    for skill_md in glob.glob(os.path.join(skills_dir, "*", "SKILL.md")):
        try:
            with open(skill_md) as f:
                content = f.read(2000)
            if content.startswith("---"):
                end = content.index("---", 3)
                front = yaml.safe_load(content[3:end])
                if front and front.get("name"):
                    skills.append({
                        "name": "/" + front["name"],
                        "desc": (front.get("description") or "")[:100],
                        "source": "skill",
                    })
        except Exception:
            continue

    _commands_cache["commands"] = BUILTIN_COMMANDS + skills
    _commands_cache["ts"] = now
    return {"commands": _commands_cache["commands"]}
```

- [ ] **Step 3: Add command button to index.html**

In `static/index.html`, find the text input row (line 56-61). Add the command button AFTER the attach button (line 57) and BEFORE the textarea (line 58):

```html
        <button class="cmd-btn" id="cmdBtn" title="Commands">/</button>
```

Then add the palette container. Find the `<div class="input-area" id="inputArea">` (line 55). Add BEFORE it:

```html
    <div class="cmd-palette" id="cmdPalette"></div>
```

- [ ] **Step 4: Add command palette CSS**

At the end of `static/css/style.css`, add:

```css
/* ===== Command palette ===== */
.cmd-palette {
  position: absolute;
  bottom: 100%;
  left: 0;
  right: 0;
  background: var(--surface);
  border-top: 1px solid var(--border);
  max-height: 320px;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
  z-index: 20;
  display: none;
}
.cmd-palette.visible { display: block; }
.cmd-item {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 10px 16px;
  cursor: pointer;
  touch-action: manipulation;
  transition: background 100ms;
}
.cmd-item:active { background: var(--surface2); }
.cmd-item-name {
  font-family: var(--mono);
  font-size: 0.85rem;
  color: var(--accent);
  font-weight: 600;
  white-space: nowrap;
}
.cmd-item-desc {
  font-size: 0.8rem;
  color: var(--text-dim);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cmd-btn {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: none;
  border: none;
  color: var(--text-dim);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  touch-action: manipulation;
  font-family: var(--mono);
  font-size: 1rem;
  font-weight: 700;
  transition: color 150ms;
}
.cmd-btn:active { color: var(--text); }
```

- [ ] **Step 5: Add command palette JS**

In `static/js/app.js`, add element references after existing declarations (around line 52):

```javascript
  var cmdBtn = document.getElementById('cmdBtn');
  var cmdPalette = document.getElementById('cmdPalette');
  var commandList = []; // populated from /api/commands
```

Then add the command palette section BEFORE `// ========== Settings ==========` (before line 1215):

```javascript
  // ========== Command Palette ==========
  function fetchCommands() {
    fetch('/api/commands')
      .then(function(r) { return r.json(); })
      .then(function(data) { commandList = data.commands || []; })
      .catch(function() {});
  }

  function showPalette(filter) {
    var items = commandList;
    if (filter) {
      var f = filter.toLowerCase();
      items = items.filter(function(c) {
        return c.name.toLowerCase().indexOf(f) >= 0 || c.desc.toLowerCase().indexOf(f) >= 0;
      });
    }
    if (items.length === 0) {
      hidePalette();
      return;
    }
    while (cmdPalette.firstChild) cmdPalette.removeChild(cmdPalette.firstChild);
    var max = Math.min(items.length, 8);
    for (var i = 0; i < max; i++) {
      var item = document.createElement('div');
      item.className = 'cmd-item';
      var nameEl = document.createElement('span');
      nameEl.className = 'cmd-item-name';
      nameEl.textContent = items[i].name;
      var descEl = document.createElement('span');
      descEl.className = 'cmd-item-desc';
      descEl.textContent = items[i].desc;
      item.appendChild(nameEl);
      item.appendChild(descEl);
      (function(cmd) {
        item.addEventListener('click', function() {
          textInput.value = cmd.name + ' ';
          textInput.focus();
          hidePalette();
          toggleSendMic();
        });
      })(items[i]);
      cmdPalette.appendChild(item);
    }
    if (items.length > max) {
      var more = document.createElement('div');
      more.className = 'cmd-item';
      more.innerHTML = '<span class="cmd-item-desc">... ' + (items.length - max) + ' more</span>';
      cmdPalette.appendChild(more);
    }
    cmdPalette.classList.add('visible');
  }

  function hidePalette() {
    cmdPalette.classList.remove('visible');
  }

  // Autocomplete on typing /
  textInput.addEventListener('input', function() {
    var val = textInput.value;
    if (val.startsWith('/') && val.indexOf('\n') === -1) {
      var filter = val.substring(1);
      showPalette(filter ? '/' + filter : '');
    } else {
      hidePalette();
    }
  });

  // Command button opens full palette
  cmdBtn.addEventListener('click', function() {
    if (cmdPalette.classList.contains('visible')) {
      hidePalette();
    } else {
      showPalette('');
    }
  });

  // Dismiss palette on outside tap
  document.addEventListener('click', function(e) {
    if (!cmdPalette.contains(e.target) && e.target !== cmdBtn && e.target !== textInput) {
      hidePalette();
    }
  });

  // Fetch commands on load and when entering a session
  fetchCommands();
```

- [ ] **Step 6: Rebuild and test**

```bash
docker compose -f /home/ubuntu/compose/claude-chat-compose.yml build --no-cache && docker compose -f /home/ubuntu/compose/claude-chat-compose.yml up -d
```

Test endpoint:
```bash
curl -s http://localhost:8800/api/commands | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'{len(d[\"commands\"])} commands'); [print(f'  {c[\"name\"]}: {c[\"desc\"][:40]}') for c in d['commands'][:5]]"
```

Playwright test:
```python
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 390, 'height': 844})
    errors = []
    page.on('pageerror', lambda err: errors.append(str(err)))
    page.goto('http://localhost:8800', wait_until='networkidle')
    page.wait_for_timeout(2000)
    # Check command button exists
    cmd_btn = page.query_selector('#cmdBtn')
    assert cmd_btn, 'Command button missing'
    # Click into session first
    cards = page.query_selector_all('.session-card')
    if cards:
        cards[0].click()
        page.wait_for_timeout(2000)
        # Type / to trigger palette
        page.fill('#textInput', '/')
        page.wait_for_timeout(500)
        palette = page.query_selector('.cmd-palette.visible')
        items = page.query_selector_all('.cmd-item')
        print(f'Palette visible: {bool(palette)}, Items: {len(items)}')
        # Clear input
        page.fill('#textInput', '')
        page.wait_for_timeout(300)
        palette_gone = not page.query_selector('.cmd-palette.visible')
        print(f'Palette hidden after clear: {palette_gone}')
    print(f'JS errors: {len(errors)}')
    if errors: print(errors)
    browser.close()
```

- [ ] **Step 7: Commit**

```bash
git add app.py static/js/app.js static/css/style.css static/index.html Dockerfile
git commit -m "feat: add command palette with autocomplete and skill discovery

Type / to trigger autocomplete popup, or tap the / button for full list.
Built-in commands hardcoded, custom skills discovered from ~/.claude/skills.
GET /api/commands endpoint with 60s cache. Added pyyaml dependency.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Command Result Cards

**Files:**
- Modify: `static/js/app.js` (update `appendMessage` to detect slash commands and render result cards)
- Modify: `static/css/style.css` (add `.cmd-pill`, `.cmd-result-card`, `.cmd-result-header`, `.cmd-result-body` styles)

**Context:** This is frontend-only. The `appendMessage` function is at line 565 in `app.js`. The `renderMessages` function is at line 403. User messages starting with `/` should get pill styling, and the following assistant message should be wrapped in a collapsible result card.

Detection is stateless: for each assistant message at index `i` in the messages array, look backwards (skipping `role === 'tool'`) to find the preceding user message. If it starts with `/`, this assistant message gets the card treatment.

- [ ] **Step 1: Add command result card CSS**

At the end of `static/css/style.css`, add:

```css
/* ===== Command result cards ===== */
.cmd-pill {
  display: inline;
  font-family: var(--mono);
  font-weight: 600;
  background: rgba(0,0,0,0.2);
  padding: 1px 7px;
  border-radius: 8px;
  font-size: 0.85em;
}
.cmd-result-card {
  border-radius: 4px 16px 16px 16px;
  overflow: hidden;
  max-width: 92%;
  align-self: flex-start;
  animation: msgIn 150ms ease-out;
}
.cmd-result-header {
  padding: 6px 14px;
  background: var(--accent-glow);
  border-bottom: 1px solid color-mix(in srgb, var(--accent) 15%, transparent);
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  touch-action: manipulation;
}
.cmd-result-name {
  color: var(--accent);
  font-size: 0.75rem;
  font-weight: 600;
  font-family: var(--mono);
}
.cmd-result-status {
  color: var(--text-muted);
  font-size: 0.65rem;
}
.cmd-result-toggle {
  margin-left: auto;
  color: var(--text-muted);
  font-size: 0.7rem;
  transition: transform 200ms;
}
.cmd-result-toggle.collapsed { transform: rotate(-90deg); }
.cmd-result-body {
  background: var(--surface2);
  padding: 12px 14px;
}
.cmd-result-body.collapsed { display: none; }
```

- [ ] **Step 2: Update `appendMessage` for slash command user messages**

In `static/js/app.js`, find the user message branch in `appendMessage` (around line 567):

```javascript
    if (m.role === 'user') {
      el = document.createElement('div');
      el.className = 'msg msg-user';
      el.textContent = m.content || m.text || '';
```

Replace with:

```javascript
    if (m.role === 'user') {
      el = document.createElement('div');
      el.className = 'msg msg-user';
      var userContent = m.content || m.text || '';
      if (userContent.startsWith('/')) {
        var spaceIdx = userContent.indexOf(' ');
        var cmdName = spaceIdx > 0 ? userContent.substring(0, spaceIdx) : userContent;
        var cmdArgs = spaceIdx > 0 ? userContent.substring(spaceIdx) : '';
        var pill = document.createElement('span');
        pill.className = 'cmd-pill';
        pill.textContent = cmdName;
        el.appendChild(pill);
        if (cmdArgs) el.appendChild(document.createTextNode(cmdArgs));
      } else {
        el.textContent = userContent;
      }
```

- [ ] **Step 3: Update `renderMessages` to pass message index context**

In `static/js/app.js`, find `renderMessages` (line 403). Currently it calls `appendMessage(m, false)`. Change it to pass the full messages array and index so `appendMessage` can look backwards:

Change `appendMessage(m, false)` to `appendMessage(m, false, messages, i)` where `i` is the forEach index. Find:

```javascript
    messages.forEach(function(m) {
      appendMessage(m, false);
    });
```

Replace with:

```javascript
    messages.forEach(function(m, i) {
      appendMessage(m, false, messages, i);
    });
```

Also update the pending messages loop similarly:

```javascript
    pendingMessages.forEach(function(pm) {
      appendMessage(pm, false, null, -1);
    });
```

- [ ] **Step 4: Update `appendMessage` signature and add command result card logic**

Change `appendMessage` function signature from `function appendMessage(m, animate)` to `function appendMessage(m, animate, allMsgs, msgIdx)`.

In the assistant message branch (after `} else if (m.role === 'assistant') {`), BEFORE creating the `el` element, add slash command detection:

```javascript
    } else if (m.role === 'assistant') {
      // Check if preceding user message was a slash command
      var isCommandResult = false;
      var commandName = '';
      if (allMsgs && msgIdx > 0) {
        for (var pi = msgIdx - 1; pi >= 0; pi--) {
          if (allMsgs[pi].role === 'tool') continue;
          if (allMsgs[pi].role === 'user') {
            var uc = (allMsgs[pi].content || allMsgs[pi].text || '').trim();
            if (uc.startsWith('/')) {
              isCommandResult = true;
              var si = uc.indexOf(' ');
              commandName = si > 0 ? uc.substring(0, si) : uc;
              // Only first assistant message after command gets card treatment
              var alreadyHandled = false;
              for (var ci = pi + 1; ci < msgIdx; ci++) {
                if (allMsgs[ci].role === 'assistant') { alreadyHandled = true; break; }
                if (allMsgs[ci].role === 'user') break;
              }
              if (alreadyHandled) isCommandResult = false;
            }
          }
          break;
        }
      }

      if (isCommandResult) {
        // Render as command result card
        el = document.createElement('div');
        el.className = 'cmd-result-card';
        var header = document.createElement('div');
        header.className = 'cmd-result-header';
        var hName = document.createElement('span');
        hName.className = 'cmd-result-name';
        hName.textContent = commandName;
        var hStatus = document.createElement('span');
        hStatus.className = 'cmd-result-status';
        hStatus.textContent = 'completed';
        var hToggle = document.createElement('span');
        hToggle.className = 'cmd-result-toggle';
        hToggle.textContent = '\u25BC';
        header.appendChild(hName);
        header.appendChild(hStatus);
        header.appendChild(hToggle);
        var body = document.createElement('div');
        body.className = 'cmd-result-body';
        var textSpan = document.createElement('div');
        textSpan.className = 'msg-assistant-text';
        var content = m.content || m.text || '';
        textSpan.appendChild(renderMarkdown(content));
        body.appendChild(textSpan);
        header.addEventListener('click', function() {
          body.classList.toggle('collapsed');
          hToggle.classList.toggle('collapsed');
        });
        el.appendChild(header);
        el.appendChild(body);
        // Copy/TTS actions inside body
        var actions = document.createElement('div');
        actions.className = 'msg-actions';
        actions.style.padding = '0 14px 8px';
        // (reuse copy/tts button creation from normal assistant branch)
        var msgCopyBtn = document.createElement('button');
        msgCopyBtn.className = 'msg-action-btn msg-copy-btn';
        msgCopyBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>';
        (function(c) { msgCopyBtn.addEventListener('click', function(e) { e.stopPropagation(); copyToClipboard(c); }); })(content);
        actions.appendChild(msgCopyBtn);
        body.appendChild(actions);
        if (!animate) el.style.animation = 'none';
      } else {
        // Normal assistant message (existing code follows)
```

Make sure the existing assistant message code is now inside the `else` block and closes properly with an extra `}` before the `} else if (m.role === 'tool')` branch.

- [ ] **Step 5: Also update the `sendMessage` call to `appendMessage`**

In `sendMessage` (around line 812), find:
```javascript
    appendMessage(msg, true);
```

Change to:
```javascript
    appendMessage(msg, true, null, -1);
```

- [ ] **Step 6: Rebuild and test**

```bash
docker compose -f /home/ubuntu/compose/claude-chat-compose.yml build --no-cache && docker compose -f /home/ubuntu/compose/claude-chat-compose.yml up -d
```

Playwright test:
```python
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 390, 'height': 844})
    errors = []
    page.on('pageerror', lambda err: errors.append(str(err)))
    page.goto('http://localhost:8800', wait_until='networkidle')
    page.wait_for_timeout(2000)
    cards = page.query_selector_all('.session-card')
    if cards:
        cards[0].click()
        page.wait_for_timeout(3000)
    msgs = page.query_selector_all('.msg')
    pills = page.query_selector_all('.cmd-pill')
    result_cards = page.query_selector_all('.cmd-result-card')
    print(f'Messages: {len(msgs)}, Cmd pills: {len(pills)}, Result cards: {len(result_cards)}, Errors: {len(errors)}')
    if errors: print(errors)
    browser.close()
```

- [ ] **Step 7: Commit**

```bash
git add static/js/app.js static/css/style.css
git commit -m "feat: add command result cards for slash command output

User messages starting with / render with a command pill. The following
assistant response is wrapped in a collapsible card with accent header.
Stateless backward-lookup detection, no mutable tracking state.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Session Renaming

**Files:**
- Modify: `app.py` (add `TITLES_FILE`, title persistence on startup, `PUT /api/sessions/{name}/title` endpoint)
- Modify: `static/js/app.js` (add inline title editing on tap)

**Context:** `title_cache` already exists at line 56 in `app.py`. Auto-generated titles from LLM are stored there. We add file persistence so custom titles survive restarts. The chat header title element is `#chatTitle` (a `<span>` in `index.html` line 39).

- [ ] **Step 1: Add title persistence to app.py**

In `app.py`, after the `title_cache` declaration (line 56), add:

```python
TITLES_FILE = os.path.join(os.environ.get("UPLOAD_DIR", "/uploads"), "titles.json")
```

In the `lifespan` function (around line 60-64), add title loading right after `http_client` is created:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    http_client = httpx.AsyncClient(timeout=10.0)
    # Load persisted titles
    if os.path.exists(TITLES_FILE):
        try:
            with open(TITLES_FILE) as f:
                title_cache.update(json.load(f))
        except Exception:
            pass
    yield
    await http_client.aclose()
```

- [ ] **Step 2: Add title update endpoint**

After the dismiss endpoint (around line 640), add:

```python
@app.put("/api/sessions/{name}/title")
async def set_session_title(name: str, body: dict):
    """Set a custom title for a session."""
    validate_session_name(name)
    title = (body.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title must not be empty")
    title_cache[name] = title[:60]
    # Persist to disk
    try:
        existing = {}
        if os.path.exists(TITLES_FILE):
            with open(TITLES_FILE) as f:
                existing = json.load(f)
        existing[name] = title[:60]
        tmp = TITLES_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(existing, f)
        os.replace(tmp, TITLES_FILE)
    except Exception:
        pass
    return {"title": title_cache[name]}
```

- [ ] **Step 3: Add inline title editing JS**

In `static/js/app.js`, add title editing section BEFORE `// ========== Settings ==========`:

```javascript
  // ========== Session Title Editing ==========
  var isEditingTitle = false;

  chatTitle.addEventListener('click', function() {
    if (isEditingTitle || !currentSession) return;
    isEditingTitle = true;
    var original = chatTitle.textContent;
    var input = document.createElement('input');
    input.type = 'text';
    input.value = original;
    input.style.cssText = 'background:var(--surface2);color:var(--text);border:1px solid var(--accent);border-radius:8px;padding:4px 8px;font-size:0.9rem;font-family:inherit;outline:none;width:100%;text-align:center;';
    chatTitle.textContent = '';
    chatTitle.appendChild(input);
    input.focus();
    input.select();

    function save() {
      var newTitle = input.value.trim();
      if (newTitle && newTitle !== original) {
        chatTitle.textContent = newTitle;
        fetch('/api/sessions/' + encodeURIComponent(currentSession) + '/title', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: newTitle })
        }).catch(function() {});
      } else {
        chatTitle.textContent = original;
      }
      isEditingTitle = false;
    }

    input.addEventListener('blur', save);
    input.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
      if (e.key === 'Escape') { input.value = original; input.blur(); }
    });
  });
```

- [ ] **Step 4: Rebuild and test**

```bash
docker compose -f /home/ubuntu/compose/claude-chat-compose.yml build --no-cache && docker compose -f /home/ubuntu/compose/claude-chat-compose.yml up -d
```

Test with curl:
```bash
curl -s -X PUT http://localhost:8800/api/sessions/cc/title \
  -H 'Content-Type: application/json' \
  -d '{"title":"My Custom Title"}'
# Expected: {"title":"My Custom Title"}

# Verify persistence
curl -s http://localhost:8800/api/sessions | python3 -c "import sys,json; [print(f'{s[\"name\"]}: {s[\"title\"]}') for s in json.load(sys.stdin)]"

# Reset
curl -s -X PUT http://localhost:8800/api/sessions/cc/title \
  -H 'Content-Type: application/json' \
  -d '{"title":"cc"}'
```

Playwright test:
```python
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 390, 'height': 844})
    errors = []
    page.on('pageerror', lambda err: errors.append(str(err)))
    page.goto('http://localhost:8800', wait_until='networkidle')
    page.wait_for_timeout(2000)
    cards = page.query_selector_all('.session-card')
    if cards:
        cards[0].click()
        page.wait_for_timeout(2000)
        title = page.query_selector('#chatTitle')
        assert title, 'Title element missing'
        title.click()
        page.wait_for_timeout(300)
        inp = page.query_selector('#chatTitle input')
        print(f'Edit input appeared: {bool(inp)}')
    print(f'JS errors: {len(errors)}')
    if errors: print(errors)
    browser.close()
```

- [ ] **Step 5: Commit**

```bash
git add app.py static/js/app.js
git commit -m "feat: add session renaming with persistent titles

Tap chat header title to edit inline. Custom titles saved to
titles.json (survives container restarts). PUT /api/sessions/{name}/title
endpoint with atomic file writes.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Session Creation with Presets

**Files:**
- Modify: `app.py` (add `POST /api/sessions`, `GET /api/config`, `_is_allowed_path`, `_load_config`, add `new-session` to `ALLOWED_COMMANDS`)
- Modify: `static/js/app.js` (add new session panel handlers, preset rendering)
- Modify: `static/css/style.css` (add `.new-btn`, `.preset-card` styles, new session panel styles)
- Modify: `static/index.html` (add "+" button in header, add new session panel HTML)
- Modify: compose file `~/compose/claude-chat-compose.yml` (add config volume mount)
- Create: `/srv/appdata/claude-chat/config/config.json` (preset configuration)

**Context:** The session list header already has a gear button (line 22 in index.html). The "+" button goes next to it. The new session panel follows the same pattern as the settings panel (slide-up, outside `.app-shell`). `ALLOWED_COMMANDS` is at line 25 in `app.py`.

- [ ] **Step 1: Create config directory and default presets**

```bash
mkdir -p /srv/appdata/claude-chat/config
cat > /srv/appdata/claude-chat/config/config.json << 'EOF'
{
  "presets": [
    { "name": "Home", "path": "/home/ubuntu", "persistent": true },
    { "name": "AI Hub", "path": "/home/ubuntu/docker/ai-hub" },
    { "name": "Claude Chat", "path": "/home/ubuntu/docker/claude-chat" },
    { "name": "HA", "path": "/home/ubuntu/docker/homeassistant" }
  ]
}
EOF
```

- [ ] **Step 2: Add config volume mount to compose file**

In `~/compose/claude-chat-compose.yml`, add to the `volumes` section:

```yaml
      - /srv/appdata/claude-chat/config:/config:ro
```

- [ ] **Step 3: Add `new-session` to ALLOWED_COMMANDS and add backend endpoints**

In `app.py`, add `"new-session"` to the `ALLOWED_COMMANDS` set (line 25).

After the title endpoint, add:

```python
# ---------------------------------------------------------------------------
# Session creation
# ---------------------------------------------------------------------------
CONFIG_FILE = "/config/config.json"


def _load_config() -> dict:
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except Exception:
        return {"presets": []}


def _is_allowed_path(path: str) -> bool:
    config = _load_config()
    allowed_paths = {p["path"] for p in config.get("presets", [])}
    if path in allowed_paths:
        return True
    return path.startswith("/home/ubuntu/")


@app.get("/api/config")
async def get_config():
    return _load_config()


@app.post("/api/sessions")
async def create_session(body: dict):
    path = body.get("path", "/home/ubuntu")
    name = body.get("name", "")

    if not _is_allowed_path(path):
        raise HTTPException(status_code=400, detail=f"Path not allowed: {path}")

    if not name:
        base = os.path.basename(path) or "s"
        name = base[:10]
        existing = {s["name"] for s in discover_sessions()}
        if name in existing:
            i = 1
            while f"{name}{i}" in existing:
                i += 1
            name = f"{name}{i}"

    validate_session_name(name)
    if _session_exists(name):
        raise HTTPException(status_code=409, detail=f"Session {name} already exists")

    run_tmux("new-session", "-d", "-s", name, "-c", path,
             "/home/ubuntu/.local/bin/claude")

    return {"created": True, "name": name, "path": path}
```

- [ ] **Step 4: Add "+" button and new session panel HTML**

In `static/index.html`, after the gear button (line 22), add:

```html
      <button class="new-btn" id="newBtn" title="New session">+</button>
```

After the settings panel closing `</div>` (line 75), add:

```html

<!-- New session panel (outside app-shell) -->
<div class="new-session-backdrop" id="newSessionBackdrop"></div>
<div class="new-session-panel" id="newSessionPanel">
  <div class="settings-handle"></div>
  <h3 class="settings-title">New Session</h3>
  <div id="presetList"></div>
  <div style="margin-top:12px;display:flex;gap:8px;">
    <input type="text" id="customPath" placeholder="Custom path..." style="flex:1;background:var(--surface2);color:var(--text);border:1px solid var(--border-medium);border-radius:8px;padding:8px 12px;font-size:0.85rem;font-family:inherit;outline:none;">
    <button id="customLaunch" style="background:var(--accent);color:white;border:none;border-radius:8px;padding:8px 16px;font-size:0.85rem;font-weight:600;cursor:pointer;touch-action:manipulation;">Launch</button>
  </div>
</div>
```

- [ ] **Step 5: Add new session panel CSS**

At the end of `static/css/style.css`, add:

```css
/* ===== New session panel ===== */
.new-session-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.5);
  z-index: 50;
  opacity: 0;
  pointer-events: none;
  transition: opacity 200ms;
}
.new-session-backdrop.visible {
  opacity: 1;
  pointer-events: auto;
}
.new-session-panel {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  background: var(--surface);
  border-radius: 20px 20px 0 0;
  padding: 12px 20px calc(20px + env(safe-area-inset-bottom));
  z-index: 51;
  transform: translateY(100%);
  transition: transform 300ms ease-out;
  max-height: 70vh;
  overflow-y: auto;
}
.new-session-panel.visible { transform: translateY(0); }
.new-btn {
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
  flex-shrink: 0;
  font-size: 1.4rem;
  font-weight: 300;
  transition: color 150ms;
}
.new-btn:active { color: var(--text); }
.preset-card {
  background: var(--surface2);
  border-radius: var(--radius-sm);
  padding: 12px 14px;
  margin-bottom: 8px;
  cursor: pointer;
  touch-action: manipulation;
  transition: transform 100ms, background 100ms;
}
.preset-card:active {
  transform: scale(0.98);
  background: var(--bg);
}
.preset-card-name {
  font-size: 0.9rem;
  font-weight: 600;
}
.preset-card-path {
  font-size: 0.75rem;
  color: var(--text-dim);
  margin-top: 2px;
  font-family: var(--mono);
}
```

- [ ] **Step 6: Add new session panel JS**

In `static/js/app.js`, add element references (around line 52):

```javascript
  var newBtn = document.getElementById('newBtn');
  var newSessionBackdrop = document.getElementById('newSessionBackdrop');
  var newSessionPanel = document.getElementById('newSessionPanel');
  var presetList = document.getElementById('presetList');
  var customPath = document.getElementById('customPath');
  var customLaunch = document.getElementById('customLaunch');
```

Add the new session section BEFORE `// ========== Settings ==========`:

```javascript
  // ========== New Session ==========
  function openNewSession() {
    // Fetch presets
    fetch('/api/config')
      .then(function(r) { return r.json(); })
      .then(function(config) {
        while (presetList.firstChild) presetList.removeChild(presetList.firstChild);
        var presets = config.presets || [];
        presets.forEach(function(p) {
          var card = document.createElement('div');
          card.className = 'preset-card';
          var name = document.createElement('div');
          name.className = 'preset-card-name';
          name.textContent = p.name;
          var path = document.createElement('div');
          path.className = 'preset-card-path';
          path.textContent = p.path;
          card.appendChild(name);
          card.appendChild(path);
          card.addEventListener('click', function() {
            createSession(p.path, '');
          });
          presetList.appendChild(card);
        });
      })
      .catch(function() {});
    customPath.value = '';
    newSessionBackdrop.classList.add('visible');
    newSessionPanel.classList.add('visible');
  }

  function closeNewSession() {
    newSessionBackdrop.classList.remove('visible');
    newSessionPanel.classList.remove('visible');
  }

  function createSession(path, name) {
    closeNewSession();
    showActionToast('Creating session...', 'info');
    fetch('/api/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: path, name: name })
    })
    .then(function(r) {
      if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || 'Failed'); });
      return r.json();
    })
    .then(function(data) {
      showActionToast('Session ' + data.name + ' created', 'success');
      loadSessions();
    })
    .catch(function(err) {
      showActionToast(err.message || 'Failed to create session', 'error');
    });
  }

  newBtn.addEventListener('click', openNewSession);
  newSessionBackdrop.addEventListener('click', closeNewSession);
  customLaunch.addEventListener('click', function() {
    var p = customPath.value.trim();
    if (p) createSession(p, '');
  });
```

- [ ] **Step 7: Rebuild and test**

```bash
docker compose -f /home/ubuntu/compose/claude-chat-compose.yml build --no-cache && docker compose -f /home/ubuntu/compose/claude-chat-compose.yml up -d
```

Test with curl:
```bash
# Check config
curl -s http://localhost:8800/api/config | python3 -m json.tool

# Create a test session
curl -s -X POST http://localhost:8800/api/sessions \
  -H 'Content-Type: application/json' \
  -d '{"path":"/tmp","name":"test-create"}'
# Expected: {"created":true,"name":"test-create","path":"/tmp"}

# Verify it exists
curl -s http://localhost:8800/api/sessions | python3 -c "import sys,json; [print(s['name']) for s in json.load(sys.stdin)]"

# Clean up
curl -s -X DELETE http://localhost:8800/api/sessions/test-create
```

Playwright test:
```python
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 390, 'height': 844})
    errors = []
    page.on('pageerror', lambda err: errors.append(str(err)))
    page.goto('http://localhost:8800', wait_until='networkidle')
    page.wait_for_timeout(2000)
    new_btn = page.query_selector('#newBtn')
    assert new_btn, 'New button missing'
    new_btn.click()
    page.wait_for_timeout(500)
    panel = page.query_selector('.new-session-panel.visible')
    presets = page.query_selector_all('.preset-card')
    print(f'Panel visible: {bool(panel)}, Presets: {len(presets)}')
    page.click('.new-session-backdrop')
    page.wait_for_timeout(300)
    print(f'JS errors: {len(errors)}')
    if errors: print(errors)
    browser.close()
```

- [ ] **Step 8: Commit**

```bash
git add app.py static/js/app.js static/css/style.css static/index.html
git commit -m "feat: add session creation with directory presets

New + button opens slide-up panel with preset directories from config.json.
Custom path input for ad-hoc sessions. POST /api/sessions creates tmux
session with claude. Path validated against preset allowlist.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

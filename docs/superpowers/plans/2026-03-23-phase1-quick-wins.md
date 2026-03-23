# Phase 1: Quick Wins Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four high-value, low-effort features: keyboard shortcuts modal, copy full conversation, session templates with initial commands, and export conversation as Markdown/JSON.

**Architecture:** All four features are independent and can be built in any order. Each adds a small amount to app.py (~20-50 lines) and app.js (~50-100 lines). No new dependencies. No database. No architectural changes.

**Tech Stack:** Python/FastAPI (backend), vanilla JavaScript (frontend), CSS custom properties

---

## File Structure

| File | Changes |
|------|---------|
| `app.py` | Add `/api/sessions/{name}/export` endpoint (~30 lines) |
| `static/js/app.js` | Add shortcuts modal, copy-all, template UI, export button (~250 lines) |
| `static/css/style.css` | Add shortcuts modal styles (~40 lines) |
| `static/index.html` | Add shortcuts modal container (~15 lines) |

---

### Task 1: Keyboard Shortcuts Modal

**Files:**
- Modify: `static/index.html:93` (add modal HTML after app-shell closing div)
- Modify: `static/js/app.js:2946-3050` (add shortcut to open modal, wire close)
- Modify: `static/css/style.css` (add modal styles at end)

- [ ] **Step 1: Add modal HTML to index.html**

Insert after the history panel (after line ~120), before the closing `</body>`:

```html
<!-- Shortcuts modal -->
<div class="shortcuts-backdrop" id="shortcutsBackdrop"></div>
<div class="shortcuts-panel" id="shortcutsPanel">
  <div class="settings-handle"></div>
  <h3 class="settings-title">Keyboard Shortcuts</h3>
  <div class="shortcuts-grid">
    <div class="shortcut-section">
      <div class="shortcut-section-title">Navigation</div>
      <div class="shortcut-row"><kbd>Esc</kbd><span>Back / close panel</span></div>
      <div class="shortcut-row"><kbd>&#8593;</kbd> <kbd>&#8595;</kbd><span>Navigate session list</span></div>
      <div class="shortcut-row"><kbd>Enter</kbd><span>Open selected session</span></div>
    </div>
    <div class="shortcut-section">
      <div class="shortcut-section-title">Chat</div>
      <div class="shortcut-row"><kbd>Ctrl/&#8984; K</kbd><span>Focus message input</span></div>
      <div class="shortcut-row"><kbd>Enter</kbd><span>Send message</span></div>
      <div class="shortcut-row"><kbd>Shift Enter</kbd><span>New line</span></div>
      <div class="shortcut-row"><kbd>/</kbd><span>Open command palette</span></div>
    </div>
    <div class="shortcut-section">
      <div class="shortcut-section-title">Special Keys (sent to session)</div>
      <div class="shortcut-row"><kbd>Esc</kbd><span>Cancel / dismiss</span></div>
      <div class="shortcut-row"><kbd>Tab</kbd><span>Accept suggestion</span></div>
      <div class="shortcut-row"><kbd>&#8679;Tab</kbd><span>Reject suggestion</span></div>
      <div class="shortcut-row"><kbd>^C</kbd><span>Interrupt</span></div>
    </div>
    <div class="shortcut-section">
      <div class="shortcut-section-title">Quick Access</div>
      <div class="shortcut-row"><kbd>Ctrl/&#8984; Shift E</kbd><span>Export conversation</span></div>
      <div class="shortcut-row"><kbd>Ctrl/&#8984; Shift C</kbd><span>Copy all messages</span></div>
      <div class="shortcut-row"><kbd>?</kbd><span>This help panel</span></div>
    </div>
  </div>
</div>
```

- [ ] **Step 2: Add CSS styles for shortcuts modal**

Append to `static/css/style.css`. Follow existing panel patterns (settings-panel, history-panel):

```css
/* Shortcuts modal */
.shortcuts-backdrop {
  position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 200;
  opacity: 0; pointer-events: none; transition: opacity 0.2s;
}
.shortcuts-backdrop.visible { opacity: 1; pointer-events: auto; }
.shortcuts-panel {
  position: fixed; bottom: 0; left: 50%; transform: translateX(-50%) translateY(100%);
  width: min(500px, 95vw); max-height: 80vh; overflow-y: auto;
  background: var(--surface); border-radius: var(--radius) var(--radius) 0 0;
  padding: 12px 20px 24px; z-index: 201; transition: transform 0.3s ease;
}
.shortcuts-panel.visible { transform: translateX(-50%) translateY(0); }
.shortcuts-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 16px;
}
@media (max-width: 500px) {
  .shortcuts-grid { grid-template-columns: 1fr; }
}
.shortcut-section-title {
  font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em;
  color: var(--text-muted); margin-bottom: 6px; font-weight: 600;
}
.shortcut-row {
  display: flex; align-items: center; justify-content: space-between;
  padding: 4px 0; font-size: 0.82rem; color: var(--text-dim);
}
.shortcut-row kbd {
  background: var(--surface2); border: 1px solid var(--border-medium);
  border-radius: 4px; padding: 2px 6px; font-size: 0.75rem;
  font-family: inherit; min-width: 24px; text-align: center;
  color: var(--text);
}
```

- [ ] **Step 3: Wire up JS — open/close and keyboard trigger**

In `static/js/app.js`, add DOM refs near line 210 (after `var historyPanel`):

```javascript
var shortcutsBackdrop = document.getElementById('shortcutsBackdrop');
var shortcutsPanel = document.getElementById('shortcutsPanel');
```

Add open/close functions near line 2945 (after `closeHistory`):

```javascript
function openShortcuts() {
  shortcutsBackdrop.classList.add('visible');
  shortcutsPanel.classList.add('visible');
}
function closeShortcuts() {
  shortcutsBackdrop.classList.remove('visible');
  shortcutsPanel.classList.remove('visible');
}
shortcutsBackdrop.addEventListener('click', closeShortcuts);
```

In the existing `keydown` handler (line ~2947), add Escape handling for shortcuts panel and the `?` trigger. Inside the Escape block (before the `if (settingsOpen)` check):

```javascript
var shortcutsOpen = shortcutsPanel.classList.contains('visible');
if (shortcutsOpen) {
  closeShortcuts();
  e.preventDefault();
  return;
}
```

After the `Cmd/Ctrl + K` block (~line 3003), add:

```javascript
// ? key: open keyboard shortcuts (when not in input)
if (e.key === '?' && !isInput) {
  e.preventDefault();
  openShortcuts();
  return;
}
```

- [ ] **Step 4: Test manually**

Open `http://localhost:8800`, press `?` — shortcuts panel should slide up from bottom. Press `Esc` to close. Verify on mobile viewport too.

- [ ] **Step 5: Commit**

```bash
git add static/index.html static/js/app.js static/css/style.css
git commit -m "feat: keyboard shortcuts modal (press ? to open)"
```

---

### Task 2: Copy Full Conversation

**Files:**
- Modify: `static/js/app.js` (add `copyConversation()` function + header button, ~40 lines)
- Modify: `static/index.html:42-44` (add copy button to chat header)

- [ ] **Step 1: Add copy button to chat header in index.html**

In the chat header (line ~43), add a copy button before the refresh button:

```html
<button class="refresh-btn" id="copyAllBtn" title="Copy conversation"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg></button>
```

- [ ] **Step 2: Add copyConversation function in app.js**

Add DOM ref near line 200:

```javascript
var copyAllBtn = document.getElementById('copyAllBtn');
```

Add function near the clipboard helpers section (~line 235):

```javascript
function copyConversation() {
  if (!currentSession) return;
  authFetch('/api/sessions/' + encodeURIComponent(currentSession))
    .then(function(r) { return r.json(); })
    .then(function(data) {
      var lines = [];
      (data.messages || []).forEach(function(m) {
        if (m.role === 'user') {
          lines.push('**User:**\n' + m.content + '\n');
        } else if (m.role === 'assistant') {
          lines.push('**Assistant:**\n' + m.content + '\n');
        } else if (m.role === 'tool') {
          var result = (m.tool_results || []).join('\n  ');
          lines.push('**' + (m.tool || 'Tool') + '** ' + m.content + (result ? '\n  ' + result : '') + '\n');
        }
      });
      var md = '# ' + (data.title || data.name) + '\n\n' + lines.join('\n');
      copyToClipboard(md);
    })
    .catch(function() {
      showActionToast('Failed to copy', 'error');
    });
}

copyAllBtn.addEventListener('click', copyConversation);
```

- [ ] **Step 3: Add Ctrl/Cmd+Shift+C keyboard shortcut**

In the keydown handler, after the `Cmd/Ctrl + K` block:

```javascript
// Cmd/Ctrl + Shift + C: copy full conversation
if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === 'C') {
  e.preventDefault();
  copyConversation();
  return;
}
```

- [ ] **Step 4: Test manually**

Open a session, click the copy button in the header. Paste into a text editor — should be formatted Markdown with User/Assistant/Tool labels. Test Ctrl+Shift+C shortcut too.

- [ ] **Step 5: Commit**

```bash
git add static/index.html static/js/app.js
git commit -m "feat: copy full conversation as markdown (button + Ctrl+Shift+C)"
```

---

### Task 3: Export Conversation as Markdown/JSON

**Files:**
- Modify: `app.py:609-630` (add export endpoint after `get_session`)
- Modify: `static/js/app.js` (add export function + menu, ~60 lines)

- [ ] **Step 1: Add export endpoint to app.py**

After the `get_session` endpoint (line ~631), add:

```python
@app.get("/api/sessions/{name}/export")
async def export_session(name: str, format: str = "markdown"):
    validate_session_name(name)
    if not _is_claude_session(name):
        raise HTTPException(status_code=404, detail="Session not found")

    raw = run_tmux("capture-pane", "-t", name, "-p", "-J", "-S", "-10000")
    messages = parse_messages(raw)
    title = title_cache.get(name, name)

    if format == "json":
        return Response(
            content=json.dumps({"title": title, "session": name, "messages": messages}, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{name}.json"'},
        )

    # Default: Markdown
    lines = [f"# {title}\n"]
    for m in messages:
        if m["role"] == "user":
            lines.append(f"**User:**\n{m['content']}\n")
        elif m["role"] == "assistant":
            lines.append(f"**Assistant:**\n{m['content']}\n")
        elif m["role"] == "tool":
            results = "\n  ".join(m.get("tool_results", []))
            lines.append(f"**{m.get('tool', 'Tool')}** {m['content']}")
            if results:
                lines.append(f"  {results}")
            lines.append("")

    md = "\n".join(lines)
    return Response(
        content=md,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{name}.md"'},
    )
```

- [ ] **Step 2: Add export button + dropdown to chat header in index.html**

Add after the copy button (added in Task 2):

```html
<button class="refresh-btn" id="exportBtn" title="Export conversation"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg></button>
```

- [ ] **Step 3: Add export function in app.js**

Add DOM ref:

```javascript
var exportBtn = document.getElementById('exportBtn');
```

Add export function near the `copyConversation` function:

```javascript
function exportConversation(format) {
  if (!currentSession) return;
  var url = '/api/sessions/' + encodeURIComponent(currentSession) + '/export?format=' + format;
  // Use authFetch to get the data, then trigger download
  authFetch(url)
    .then(function(r) {
      var filename = currentSession + '.' + (format === 'json' ? 'json' : 'md');
      return r.blob().then(function(blob) {
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(a.href);
        showActionToast('Exported as ' + format.toUpperCase(), 'success');
      });
    })
    .catch(function() {
      showActionToast('Export failed', 'error');
    });
}

exportBtn.addEventListener('click', function() {
  // Simple toggle: tap once for markdown, long-press for JSON
  // Or show a tiny dropdown
  var existing = document.querySelector('.export-dropdown');
  if (existing) { existing.remove(); return; }

  var dd = document.createElement('div');
  dd.className = 'export-dropdown';
  dd.style.cssText = 'position:absolute;top:100%;right:0;background:var(--surface2);border:1px solid var(--border-medium);border-radius:8px;padding:4px;z-index:100;min-width:130px;box-shadow:0 4px 20px rgba(0,0,0,0.3);';

  var mdBtn = document.createElement('button');
  mdBtn.textContent = 'Markdown (.md)';
  mdBtn.style.cssText = 'display:block;width:100%;text-align:left;background:none;border:none;color:var(--text);padding:8px 12px;font-size:0.82rem;cursor:pointer;border-radius:6px;font-family:inherit;';
  mdBtn.addEventListener('click', function() { dd.remove(); exportConversation('markdown'); });
  mdBtn.addEventListener('mouseenter', function() { this.style.background = 'var(--surface)'; });
  mdBtn.addEventListener('mouseleave', function() { this.style.background = 'none'; });

  var jsonBtn = document.createElement('button');
  jsonBtn.textContent = 'JSON (.json)';
  jsonBtn.style.cssText = mdBtn.style.cssText;
  jsonBtn.addEventListener('click', function() { dd.remove(); exportConversation('json'); });
  jsonBtn.addEventListener('mouseenter', function() { this.style.background = 'var(--surface)'; });
  jsonBtn.addEventListener('mouseleave', function() { this.style.background = 'none'; });

  dd.appendChild(mdBtn);
  dd.appendChild(jsonBtn);
  exportBtn.style.position = 'relative';
  exportBtn.appendChild(dd);

  // Close on outside click
  setTimeout(function() {
    document.addEventListener('click', function closer(e) {
      if (!dd.contains(e.target) && e.target !== exportBtn) {
        dd.remove();
        document.removeEventListener('click', closer);
      }
    });
  }, 0);
});
```

- [ ] **Step 4: Add Ctrl/Cmd+Shift+E keyboard shortcut**

In the keydown handler:

```javascript
// Cmd/Ctrl + Shift + E: export conversation as markdown
if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === 'E') {
  e.preventDefault();
  exportConversation('markdown');
  return;
}
```

- [ ] **Step 5: Test manually**

Open a session, click export button — dropdown shows "Markdown" and "JSON". Click each — file should download. Check file contents. Test Ctrl+Shift+E shortcut.

- [ ] **Step 6: Commit**

```bash
git add app.py static/index.html static/js/app.js
git commit -m "feat: export conversation as Markdown or JSON"
```

---

### Task 4: Session Templates with Initial Commands

**Files:**
- Modify: `app.py:1038-1063` (extend create_session to accept initial_command, modify config format)
- Modify: `static/js/app.js:2601-2662` (extend new session UI to show template descriptions + modes)

- [ ] **Step 1: Extend backend to support initial commands**

In `app.py`, modify the `create_session` endpoint (line ~1038) to accept and send an initial command after session creation:

```python
@app.post("/api/sessions")
async def create_session(body: dict):
    path = os.path.realpath(body.get("path", "/home/ubuntu"))
    name = body.get("name", "")
    initial_command = body.get("initial_command", "")
    mode = body.get("mode", "")  # plan, code, ask

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

    claude_cmd = "/home/ubuntu/.local/bin/claude"
    if mode and mode in ("plan", "code", "ask"):
        claude_cmd += f" --mode {mode}"

    run_tmux("new-session", "-d", "-s", name, "-c", path, claude_cmd)

    # Send initial command after a brief delay for Claude to start
    if initial_command:
        await asyncio.sleep(2)
        run_tmux("send-keys", "-t", name, "-l", initial_command)
        run_tmux("send-keys", "-t", name, "Enter")

    return {"created": True, "name": name, "path": path}
```

- [ ] **Step 2: Extend config.json format to support templates**

The config file at `/config/config.json` already supports `presets`. Extend each preset to optionally include `description`, `mode`, and `initial_command`:

```json
{
  "presets": [
    {
      "name": "Code Review",
      "path": "/home/ubuntu",
      "description": "Start a code review session",
      "mode": "code",
      "initial_command": "/review"
    },
    {
      "name": "Bug Fix",
      "path": "/home/ubuntu",
      "description": "Debug and fix issues",
      "mode": "code"
    },
    {
      "name": "Plan Architecture",
      "path": "/home/ubuntu",
      "description": "Design before building",
      "mode": "plan"
    }
  ]
}
```

No backend changes needed — the config is passed through as-is.

- [ ] **Step 3: Update frontend to use extended preset fields**

In `static/js/app.js`, modify the `openNewSession` function (line ~2602). Replace the preset card creation loop:

```javascript
presets.forEach(function(p) {
  var card = document.createElement('div');
  card.className = 'preset-card';
  var name = document.createElement('div');
  name.className = 'preset-card-name';
  name.textContent = p.name;
  card.appendChild(name);
  if (p.description) {
    var desc = document.createElement('div');
    desc.className = 'preset-card-path';
    desc.textContent = p.description;
    card.appendChild(desc);
  }
  if (p.mode) {
    var mode = document.createElement('span');
    mode.style.cssText = 'display:inline-block;font-size:0.7rem;background:var(--accent);color:white;padding:2px 6px;border-radius:4px;margin-top:4px;text-transform:uppercase;letter-spacing:0.03em;';
    mode.textContent = p.mode;
    card.appendChild(mode);
  }
  var path = document.createElement('div');
  path.className = 'preset-card-path';
  path.textContent = p.path;
  path.style.fontSize = '0.7rem';
  path.style.opacity = '0.5';
  card.appendChild(path);
  card.addEventListener('click', function() {
    createSession(p.path, '', p.initial_command || '', p.mode || '');
  });
  presetList.appendChild(card);
});
```

Update `createSession` to pass the new fields:

```javascript
function createSession(path, name, initialCommand, mode) {
  closeNewSession();
  showActionToast('Creating session...', 'info');
  var payload = { path: path, name: name };
  if (initialCommand) payload.initial_command = initialCommand;
  if (mode) payload.mode = mode;
  authFetch('/api/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
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
```

Also update the custom path launch (line ~2659) to pass empty strings for new params:

```javascript
customLaunch.addEventListener('click', function() {
  var p = customPath.value.trim();
  if (p) createSession(p, '', '', '');
});
```

- [ ] **Step 4: Test manually**

1. Add a preset to `/config/config.json` with `mode` and `initial_command`
2. Open new session panel, verify preset shows description and mode badge
3. Click preset — session should be created and initial command sent
4. Verify the custom path launcher still works

- [ ] **Step 5: Commit**

```bash
git add app.py static/js/app.js
git commit -m "feat: session templates with mode and initial command support"
```

---

### Task 5: Version Bump and Final Verification

- [ ] **Step 1: Bump cache version**

In `static/index.html`, bump `?v=30` to `?v=31` on the CSS and JS links.
In `static/sw.js`, bump the version string from `v30` to `v31`.

- [ ] **Step 2: Full smoke test**

1. Press `?` — shortcuts modal opens with all shortcuts listed
2. Open a session — copy button and export button visible in header
3. Click copy button — conversation copied as markdown
4. Click export button — dropdown with Markdown/JSON options
5. Export both formats — files download correctly
6. Press Ctrl+Shift+C — copies conversation
7. Press Ctrl+Shift+E — exports as markdown
8. Click `+` — new session panel shows presets with descriptions/mode badges
9. All existing features still work (polling, voice, themes, auth)

- [ ] **Step 3: Commit version bump**

```bash
git add static/index.html static/sw.js
git commit -m "chore: bump cache version to v29 for Phase 1 features"
```

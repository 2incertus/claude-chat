# Phase B: Polish & Power Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add markdown rendering, dead session UX improvements, settings panel, and auto-scroll enhancements to claude-chat.

**Architecture:** Four independent features, each developed in an isolated git worktree branch. Features touch overlapping files (`app.js`, `style.css`) but different sections. Merge order: Task 3 (settings/theme) first (introduces CSS variables other tasks reference), then Tasks 1, 2, 4 in any order.

**Tech Stack:** Python/FastAPI (backend), vanilla JS/CSS (frontend in static files), Docker, Playwright (testing)

**Spec:** `docs/superpowers/specs/2026-03-21-phase-b-polish-and-power-design.md`

---

### Task 1: Markdown Rendering

**Files:**
- Modify: `static/js/app.js` (add `renderMarkdown()` function before `appendMessage`, rewrite `appendMessage` assistant branch)
- Modify: `static/css/style.css` (change `.msg-assistant-text` white-space, add markdown element styles)

**Context:** Assistant messages currently render as raw text. The `appendMessage` function (lines ~408-521 in `app.js`) has an indentation-based code block detector that should be entirely replaced. The new `renderMarkdown(text)` function returns a DocumentFragment.

- [ ] **Step 1: Add markdown CSS styles**

In `static/css/style.css`, find `.msg-assistant-text` (line 291-293):
```css
.msg-assistant-text {
  white-space: pre-wrap;
}
```

Change `white-space: pre-wrap` to `white-space: normal`.

Then add after `.msg-assistant-text`:

```css
.msg-assistant-text p { margin: 4px 0; }
.msg-assistant-text h1,
.msg-assistant-text h2,
.msg-assistant-text h3 {
  font-weight: 600;
  margin: 12px 0 4px 0;
  line-height: 1.3;
}
.msg-assistant-text h1 { font-size: 1.1rem; }
.msg-assistant-text h2 { font-size: 1rem; }
.msg-assistant-text h3 { font-size: 0.92rem; }
.msg-assistant-text ul,
.msg-assistant-text ol {
  padding-left: 20px;
  margin: 4px 0;
}
.msg-assistant-text li { margin: 2px 0; }
.inline-code {
  background: var(--code-bg);
  font-family: var(--mono);
  font-size: 0.85em;
  padding: 1px 5px;
  border-radius: 4px;
  border: 1px solid rgba(255,255,255,0.06);
}
.msg-assistant-text a {
  color: var(--accent);
  text-decoration: none;
}
.msg-assistant-text a:hover { text-decoration: underline; }
.msg-assistant-text hr {
  border: none;
  border-top: 1px solid rgba(255,255,255,0.08);
  margin: 8px 0;
}
.msg-assistant-text strong { font-weight: 600; }
.msg-assistant-text em { font-style: italic; }
```

Note: uses `rgba()` directly here. If Task 3 (settings/theme) merges first, these will be updated to `var(--border)` during merge conflict resolution.

- [ ] **Step 2: Write `renderMarkdown()` function**

In `static/js/app.js`, add this function BEFORE the `appendMessage` function (before line ~408). This is the full implementation:

```javascript
  // ========== Markdown Renderer ==========
  function renderMarkdown(text) {
    var frag = document.createDocumentFragment();

    // Escape HTML entities first (security)
    text = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

    // Split into blocks, preserving fenced code blocks
    var blocks = [];
    var lines = text.split('\n');
    var i = 0;
    while (i < lines.length) {
      var line = lines[i];
      // Fenced code block
      if (/^```/.test(line)) {
        var lang = line.replace(/^```\s*/, '').trim();
        var codeLines = [];
        i++;
        while (i < lines.length && !/^```/.test(lines[i])) {
          codeLines.push(lines[i]);
          i++;
        }
        i++; // skip closing ```
        blocks.push({ type: 'code', content: codeLines.join('\n'), lang: lang });
        continue;
      }
      // Blank line = block separator
      if (!line.trim()) {
        i++;
        continue;
      }
      // Collect consecutive non-blank, non-fence lines
      var group = [];
      while (i < lines.length && lines[i].trim() && !/^```/.test(lines[i])) {
        group.push(lines[i]);
        i++;
      }
      blocks.push({ type: 'lines', lines: group });
    }

    // Process each block
    for (var b = 0; b < blocks.length; b++) {
      var block = blocks[b];

      if (block.type === 'code') {
        var pre = document.createElement('pre');
        pre.className = 'code-block';
        var code = document.createElement('code');
        // Unescape for code display (we escaped earlier for safety)
        code.textContent = block.content.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>');
        pre.appendChild(code);
        // Copy button
        var copyBtn = document.createElement('button');
        copyBtn.className = 'code-copy-btn';
        copyBtn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>';
        copyBtn.title = 'Copy code';
        (function(codeText) {
          copyBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            copyToClipboard(codeText);
          });
        })(block.content.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>'));
        pre.appendChild(copyBtn);
        frag.appendChild(pre);
        continue;
      }

      // Process line groups
      var groupLines = block.lines;
      var li = 0;
      while (li < groupLines.length) {
        var gl = groupLines[li];

        // Header
        var headerMatch = gl.match(/^(#{1,3})\s+(.+)/);
        if (headerMatch) {
          var level = headerMatch[1].length;
          var h = document.createElement('h' + level);
          h.appendChild(applyInline(headerMatch[2]));
          frag.appendChild(h);
          li++;
          continue;
        }

        // Horizontal rule
        if (/^[-*]{3,}\s*$/.test(gl) && !/\S/.test(gl.replace(/[-*]/g, ''))) {
          frag.appendChild(document.createElement('hr'));
          li++;
          continue;
        }

        // Bullet list
        if (/^[\-*]\s+/.test(gl)) {
          var ul = document.createElement('ul');
          while (li < groupLines.length && /^[\-*]\s+/.test(groupLines[li])) {
            var liEl = document.createElement('li');
            liEl.appendChild(applyInline(groupLines[li].replace(/^[\-*]\s+/, '')));
            ul.appendChild(liEl);
            li++;
          }
          frag.appendChild(ul);
          continue;
        }

        // Numbered list
        if (/^\d+\.\s+/.test(gl)) {
          var ol = document.createElement('ol');
          while (li < groupLines.length && /^\d+\.\s+/.test(groupLines[li])) {
            var liEl = document.createElement('li');
            liEl.appendChild(applyInline(groupLines[li].replace(/^\d+\.\s+/, '')));
            ol.appendChild(liEl);
            li++;
          }
          frag.appendChild(ol);
          continue;
        }

        // Paragraph -- join consecutive lines
        var pLines = [];
        while (li < groupLines.length &&
               !groupLines[li].match(/^#{1,3}\s+/) &&
               !/^[-*]{3,}\s*$/.test(groupLines[li]) &&
               !/^[\-*]\s+/.test(groupLines[li]) &&
               !/^\d+\.\s+/.test(groupLines[li])) {
          pLines.push(groupLines[li]);
          li++;
        }
        if (pLines.length > 0) {
          var p = document.createElement('p');
          p.appendChild(applyInline(pLines.join(' ')));
          frag.appendChild(p);
        }
      }
    }

    return frag;
  }

  function applyInline(text) {
    var frag = document.createDocumentFragment();
    // Process inline formatting using regex replacements
    // Order: inline code first (greedy), then bold, italic, links
    var html = text
      .replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/\*([^*]+)\*/g, '<em>$1</em>')
      .replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    var span = document.createElement('span');
    span.innerHTML = html;
    while (span.firstChild) {
      frag.appendChild(span.firstChild);
    }
    return frag;
  }
```

- [ ] **Step 3: Replace `appendMessage` assistant branch**

In `static/js/app.js`, find the assistant message branch in `appendMessage` (starts around line 415 with `} else if (m.role === 'assistant') {`). Replace the ENTIRE assistant branch -- everything from `} else if (m.role === 'assistant') {` up to the line before `} else if (m.role === 'tool') {` -- with:

```javascript
    } else if (m.role === 'assistant') {
      el = document.createElement('div');
      el.className = 'msg msg-assistant';
      var textSpan = document.createElement('div');
      textSpan.className = 'msg-assistant-text';
      var content = m.content || m.text || '';
      textSpan.appendChild(renderMarkdown(content));
      el.appendChild(textSpan);
      // Action row
      var actions = document.createElement('div');
      actions.className = 'msg-actions';
      var msgCopyBtn = document.createElement('button');
      msgCopyBtn.className = 'msg-action-btn msg-copy-btn';
      msgCopyBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>';
      msgCopyBtn.title = 'Copy message';
      (function(msgContent) {
        msgCopyBtn.addEventListener('click', function(e) {
          e.stopPropagation();
          copyToClipboard(msgContent);
        });
      })(content);
      actions.appendChild(msgCopyBtn);
      var ttsBtn = document.createElement('button');
      ttsBtn.className = 'msg-action-btn msg-tts-btn';
      ttsBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>';
      ttsBtn.title = 'Read aloud';
      (function(msgText, btn) {
        btn.addEventListener('click', function(e) {
          e.stopPropagation();
          toggleTTS(msgText, btn);
        });
      })(content, ttsBtn);
      actions.appendChild(ttsBtn);
      el.appendChild(actions);
      if (!animate) el.style.animation = 'none';
```

- [ ] **Step 4: Rebuild and test**

```bash
docker compose -f /home/ubuntu/compose/claude-chat-compose.yml build --no-cache && docker compose -f /home/ubuntu/compose/claude-chat-compose.yml up -d
```

Wait 3 seconds, then run Playwright test:

```python
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    errors = []
    page.on('pageerror', lambda err: errors.append(str(err)))
    page.goto('http://localhost:8800', wait_until='networkidle')
    page.wait_for_timeout(2000)
    cards = page.query_selector_all('.session-card')
    if cards:
        cards[0].click()
        page.wait_for_timeout(3000)
    # Check markdown elements rendered
    strongs = page.query_selector_all('.msg-assistant-text strong')
    codes = page.query_selector_all('.msg-assistant-text .inline-code')
    code_blocks = page.query_selector_all('.code-block')
    paras = page.query_selector_all('.msg-assistant-text p')
    msgs = page.query_selector_all('.msg')
    print(f'Messages: {len(msgs)}, Paragraphs: {len(paras)}, Bold: {len(strongs)}, InlineCode: {len(codes)}, CodeBlocks: {len(code_blocks)}, Errors: {len(errors)}')
    if errors: print(errors)
    browser.close()
```

Expected: Messages > 0, Paragraphs > 0, zero JS errors. Bold/InlineCode/CodeBlocks counts depend on session content.

- [ ] **Step 5: Commit**

```bash
git add static/js/app.js static/css/style.css
git commit -m "feat: add markdown rendering for assistant messages

Replace raw text rendering with custom markdown parser. Supports headers,
bold, italic, inline code, fenced code blocks, lists, links, and rules.
HTML entities escaped for security. Removes old indentation-based code
block detection."
```

---

### Task 2: Dead Session UX

**Files:**
- Modify: `app.py` (add `death_cache`, update dead session block in `list_sessions` ~line 430-442)
- Modify: `static/js/app.js` (update `renderSessionList` ~line 258, remove dead preview gate)
- Modify: `static/css/style.css` (add `.session-card-dead-label` style)

**Context:** Dead sessions currently show as muted cards with just name/cwd and a respawn button. The `list_sessions` endpoint (line 430 in `app.py`) returns empty preview and "dead" as `last_activity` for dead sessions. The frontend gates preview rendering with `s.state !== 'dead'` (line 258 in `app.js`).

- [ ] **Step 1: Add death_cache and update dead session block in app.py**

In `app.py`, after the `title_cache` declaration (line 56), add:

```python
death_cache: dict[str, float] = {}
```

Then find the dead session block in `list_sessions` (starts around line 430 with `if s["state"] == "dead":`). Replace the entire block through the `continue` statement with:

```python
        # Track death time
        if s["state"] == "dead":
            if name not in death_cache:
                death_cache[name] = time.time()
        elif name in death_cache:
            del death_cache[name]

        if s["state"] == "dead":
            preview = ""
            try:
                raw = run_tmux("capture-pane", "-t", name, "-p", "-J", "-S", "-50")
                msgs = parse_messages(raw)
                asst = [m for m in msgs if m["role"] == "assistant"]
                if asst:
                    preview = asst[-1]["content"][:120]
            except RuntimeError:
                pass

            died_at = death_cache.get(name, time.time())
            result.append({
                "name": name,
                "pid": s["pid"],
                "title": title_cache.get(name, name),
                "cwd": s["cwd"],
                "last_activity": time_ago(int(died_at * 1000)),
                "status": "dead",
                "state": "dead",
                "preview": preview,
            })
            continue
```

- [ ] **Step 2: Show preview on dead cards in app.js**

In `static/js/app.js`, find the preview rendering gate (around line 258):

```javascript
      if (s.preview && s.state !== 'dead') {
```

Change to:

```javascript
      if (s.preview) {
```

- [ ] **Step 3: Add EXITED label to dead cards in app.js**

In `static/js/app.js`, find the dead session status dot rendering. In `renderSessionList`, where the status dot is created (around line 243):

```javascript
      var dot = document.createElement('div');
      dot.className = 'session-card-status' + (s.state === 'dead' ? '' : (s.status === 'working' ? ' working' : ''));
```

After this block, add:

```javascript
      // Add EXITED label for dead sessions
      if (s.state === 'dead') {
        var deadLabel = document.createElement('span');
        deadLabel.className = 'session-card-dead-label';
        deadLabel.textContent = 'EXITED';
        meta.appendChild(deadLabel);
      }
```

- [ ] **Step 4: Add dead label CSS**

In `static/css/style.css`, after `.session-card.dead .session-card-status` (around line 589), add:

```css
.session-card-dead-label {
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--red);
  opacity: 0.7;
  font-weight: 600;
}
```

- [ ] **Step 5: Rebuild and test**

```bash
docker compose -f /home/ubuntu/compose/claude-chat-compose.yml build --no-cache && docker compose -f /home/ubuntu/compose/claude-chat-compose.yml up -d
```

Test with curl:
```bash
# Create a dead test session
tmux new-session -d -s test-dead -c /tmp
tmux send-keys -t test-dead 'echo hello world' Enter
sleep 1

# Check API returns preview and time for dead session
curl -s http://localhost:8800/api/sessions | python3 -c "
import sys, json
for s in json.load(sys.stdin):
    if s['state'] == 'dead':
        print(f'Dead: {s[\"name\"]} preview={s[\"preview\"][:50]!r} time={s[\"last_activity\"]}')"

# Cleanup
tmux kill-session -t test-dead 2>/dev/null
```

Expected: dead sessions show non-empty preview and time like "just now" or "1m ago".

- [ ] **Step 6: Commit**

```bash
git add app.py static/js/app.js static/css/style.css
git commit -m "feat: improve dead session UX with preview and death time

Dead sessions now show last assistant message as preview, time since
death (via ephemeral death_cache), and an EXITED label. Removes the
preview gate that hid content on dead cards."
```

---

### Task 3: Settings Panel (merge first -- introduces CSS variables)

**Files:**
- Modify: `static/index.html` (add gear button, settings panel HTML)
- Modify: `static/css/style.css` (add `--border`/`--border-medium` variables, theme definitions, settings panel styles, gear button styles, migrate all hardcoded border colors)
- Modify: `static/js/app.js` (add settings state, UI handlers, poll speed integration, defaultNtfy integration)

**Context:** This task introduces the `--border` and `--border-medium` CSS custom properties that other tasks may reference. It should be merged FIRST into main to avoid merge conflicts. The current CSS has ~15 instances of hardcoded `rgba(255,255,255,0.06/0.08/0.1)` for borders that all need migration.

- [ ] **Step 1: Add CSS custom properties and theme definitions**

In `static/css/style.css`, find the `:root` block (lines 2-18). Add two new variables after `--mono`:

```css
  --border: rgba(255,255,255,0.06);
  --border-medium: rgba(255,255,255,0.1);
```

Then, after the closing `}` of `:root` (line 18), add theme overrides:

```css
:root[data-theme="oled"] {
  --bg: #000000;
  --surface: #0A0A0A;
  --surface2: #141414;
}
:root[data-theme="light"] {
  --bg: #F2F0ED;
  --surface: #FFFFFF;
  --surface2: #E8E6E3;
  --text: #1A1A1A;
  --text-dim: rgba(26, 26, 26, 0.5);
  --text-muted: rgba(26, 26, 26, 0.25);
  --code-bg: #F5F3F0;
  --border: rgba(0,0,0,0.08);
  --border-medium: rgba(0,0,0,0.12);
}
```

- [ ] **Step 2: Migrate hardcoded border colors throughout style.css**

Replace ALL instances in `static/css/style.css`:

- `rgba(255,255,255,0.06)` -> `var(--border)` (about 5 instances: header border, chat feed borders, code block border, settings row border)
- `rgba(255,255,255,0.08)` -> `var(--border)` (about 3 instances: preview bar border, code-copy-btn bg)
- `rgba(255,255,255,0.1)` -> `var(--border-medium)` (about 4 instances: text input border, preview text border, settings select/toggle borders)
- `rgba(255,255,255,0.15)` should stay as-is (these are hover/active states, not borders)

Use find-and-replace carefully -- check each instance. Do NOT replace values inside `box-shadow`, `background`, or hover/active states.

- [ ] **Step 3: Add gear button and settings panel CSS**

In `static/css/style.css`, add after the scrollbar styling section at the end:

```css
/* ===== Gear button ===== */
.gear-btn {
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
  transition: color 150ms;
}
.gear-btn:active { color: var(--text); }

/* ===== Settings panel ===== */
.settings-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.5);
  z-index: 50;
  opacity: 0;
  pointer-events: none;
  transition: opacity 200ms;
}
.settings-backdrop.visible {
  opacity: 1;
  pointer-events: auto;
}
.settings-panel {
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
  max-height: 60vh;
  overflow-y: auto;
}
.settings-panel.visible { transform: translateY(0); }
.settings-handle {
  width: 36px;
  height: 4px;
  background: var(--text-muted);
  border-radius: 2px;
  margin: 0 auto 16px;
}
.settings-title {
  font-size: 1rem;
  font-weight: 600;
  margin-bottom: 16px;
}
.settings-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 0;
  border-bottom: 1px solid var(--border);
}
.settings-row:last-child { border-bottom: none; }
.settings-label { font-size: 0.88rem; }
.settings-select {
  background: var(--surface2);
  color: var(--text);
  border: 1px solid var(--border-medium);
  border-radius: 8px;
  padding: 6px 10px;
  font-size: 0.82rem;
  font-family: inherit;
  outline: none;
  min-width: 100px;
}
.settings-toggle {
  width: 44px;
  height: 24px;
  border-radius: 12px;
  background: var(--surface2);
  border: 1px solid var(--border-medium);
  cursor: pointer;
  position: relative;
  transition: background 200ms;
}
.settings-toggle.on {
  background: var(--accent);
  border-color: var(--accent);
}
.settings-toggle::after {
  content: '';
  position: absolute;
  top: 2px;
  left: 2px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: white;
  transition: transform 200ms;
}
.settings-toggle.on::after { transform: translateX(20px); }
```

- [ ] **Step 4: Add gear button and settings HTML to index.html**

In `static/index.html`, find the `#screenList` header (line 18-22). After `<div class="header-spacer"></div>`, add the gear button:

```html
      <button class="gear-btn" id="gearBtn" title="Settings"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg></button>
```

Before the closing `</div>` of `.app-shell` (line 66), add:

```html
  <!-- Settings -->
  <div class="settings-backdrop" id="settingsBackdrop"></div>
  <div class="settings-panel" id="settingsPanel">
    <div class="settings-handle"></div>
    <h3 class="settings-title">Settings</h3>
  </div>
```

- [ ] **Step 5: Add settings JS**

In `static/js/app.js`, add element references after the existing element declarations (after line ~52):

```javascript
  var gearBtn = document.getElementById('gearBtn');
  var settingsBackdrop = document.getElementById('settingsBackdrop');
  var settingsPanel = document.getElementById('settingsPanel');
  var inputArea = document.getElementById('inputArea');
```

Then add the full settings section BEFORE the `// ========== Init ==========` section (before the last ~5 lines):

```javascript
  // ========== Settings ==========
  var POLL_SPEEDS = {
    fast:   { active: 1000, warm: 3000, idle: 5000 },
    normal: { active: 2000, warm: 5000, idle: 10000 },
    saver:  { active: 5000, warm: 15000, idle: 15000 }
  };
  var pollSpeedSetting = 'normal';

  function getSettings() {
    try { return JSON.parse(localStorage.getItem('claude_chat_settings') || '{}'); } catch(e) { return {}; }
  }

  function saveSetting(key, value) {
    var s = getSettings();
    s[key] = value;
    localStorage.setItem('claude_chat_settings', JSON.stringify(s));
    applySetting(key, value);
  }

  function applySetting(key, value) {
    if (key === 'theme') {
      if (value && value !== 'dark') {
        document.documentElement.setAttribute('data-theme', value);
      } else {
        document.documentElement.removeAttribute('data-theme');
      }
    } else if (key === 'pollSpeed') {
      pollSpeedSetting = value || 'normal';
    } else if (key === 'chatVoice') {
      localStorage.setItem('chatVoice', value || '');
    }
  }

  function loadSettings() {
    var s = getSettings();
    if (s.theme) applySetting('theme', s.theme);
    if (s.pollSpeed) applySetting('pollSpeed', s.pollSpeed);
    if (s.chatVoice) applySetting('chatVoice', s.chatVoice);
  }

  function openSettings() {
    renderSettingsPanel();
    settingsBackdrop.classList.add('visible');
    settingsPanel.classList.add('visible');
  }

  function closeSettings() {
    settingsBackdrop.classList.remove('visible');
    settingsPanel.classList.remove('visible');
  }

  function renderSettingsPanel() {
    // Clear existing rows
    var existing = settingsPanel.querySelectorAll('.settings-row');
    for (var i = 0; i < existing.length; i++) existing[i].remove();

    var s = getSettings();

    // Theme
    var themeRow = createSettingsRow('Theme', 'select', s.theme || 'dark', [
      { value: 'dark', label: 'Dark' },
      { value: 'oled', label: 'OLED Black' },
      { value: 'light', label: 'Light' }
    ], function(v) { saveSetting('theme', v); });
    settingsPanel.appendChild(themeRow);

    // Poll Speed
    var pollRow = createSettingsRow('Poll Speed', 'select', s.pollSpeed || 'normal', [
      { value: 'fast', label: 'Fast' },
      { value: 'normal', label: 'Normal' },
      { value: 'saver', label: 'Battery Saver' }
    ], function(v) { saveSetting('pollSpeed', v); });
    settingsPanel.appendChild(pollRow);

    // TTS Voice
    var voices = window.speechSynthesis ? speechSynthesis.getVoices() : [];
    var voiceOptions = [{ value: '', label: 'System Default' }];
    for (var vi = 0; vi < voices.length; vi++) {
      voiceOptions.push({ value: voices[vi].name, label: voices[vi].name });
    }
    var voiceRow = createSettingsRow('TTS Voice', 'select', s.chatVoice || '', voiceOptions, function(v) { saveSetting('chatVoice', v); });
    settingsPanel.appendChild(voiceRow);

    // Default Notifications
    var ntfyRow = createSettingsRow('Default Notifications', 'toggle', !!s.defaultNtfy, null, function(v) { saveSetting('defaultNtfy', v); });
    settingsPanel.appendChild(ntfyRow);
  }

  function createSettingsRow(label, type, currentValue, options, onChange) {
    var row = document.createElement('div');
    row.className = 'settings-row';
    var lbl = document.createElement('span');
    lbl.className = 'settings-label';
    lbl.textContent = label;
    row.appendChild(lbl);

    if (type === 'select') {
      var sel = document.createElement('select');
      sel.className = 'settings-select';
      for (var i = 0; i < options.length; i++) {
        var opt = document.createElement('option');
        opt.value = options[i].value;
        opt.textContent = options[i].label;
        if (options[i].value === currentValue) opt.selected = true;
        sel.appendChild(opt);
      }
      sel.addEventListener('change', function() { onChange(sel.value); });
      row.appendChild(sel);
    } else if (type === 'toggle') {
      var tog = document.createElement('div');
      tog.className = 'settings-toggle' + (currentValue ? ' on' : '');
      tog.addEventListener('click', function() {
        var isOn = tog.classList.toggle('on');
        onChange(isOn);
      });
      row.appendChild(tog);
    }
    return row;
  }

  gearBtn.addEventListener('click', openSettings);
  settingsBackdrop.addEventListener('click', closeSettings);
```

- [ ] **Step 6: Update schedulePoll to use poll speed setting**

In `static/js/app.js`, find the `schedulePoll` function (around line 580-587):

```javascript
  function schedulePoll() {
    if (!currentSession) return;
    var interval;
    if (idleCount < 3) interval = 2000;
    else if (idleCount < 6) interval = 5000;
    else interval = 10000;
    pollTimer = setTimeout(doPoll, interval);
  }
```

Replace with:

```javascript
  function schedulePoll() {
    if (!currentSession) return;
    var speeds = POLL_SPEEDS[pollSpeedSetting] || POLL_SPEEDS.normal;
    var interval;
    if (idleCount < 3) interval = speeds.active;
    else if (idleCount < 6) interval = speeds.warm;
    else interval = speeds.idle;
    pollTimer = setTimeout(doPoll, interval);
  }
```

Note: `POLL_SPEEDS` and `pollSpeedSetting` are defined in the Settings section added in Step 5. They are accessible because everything is inside the same IIFE.

- [ ] **Step 7: Update isNtfyEnabled for defaultNtfy**

In `static/js/app.js`, find the `isNtfyEnabled` function (around line 825):

```javascript
  function isNtfyEnabled(session) {
    try {
      var s = JSON.parse(localStorage.getItem('ntfy_sessions') || '{}');
      return !!s[session];
    } catch(e) { return false; }
  }
```

Replace with:

```javascript
  function isNtfyEnabled(session) {
    try {
      var s = JSON.parse(localStorage.getItem('ntfy_sessions') || '{}');
      if (session in s) return !!s[session];
      // Not explicitly set -- use default
      var settings = getSettings();
      return !!settings.defaultNtfy;
    } catch(e) { return false; }
  }
```

- [ ] **Step 8: Add loadSettings() call to init**

In `static/js/app.js`, find the `// ========== Init ==========` section at the bottom. Add `loadSettings();` BEFORE `loadSessions();`:

```javascript
  // ========== Init ==========
  loadSettings();
  loadSessions();
  startSessionListPolling();
```

Also load voices asynchronously (some browsers load voices lazily):

```javascript
  if (window.speechSynthesis) {
    speechSynthesis.addEventListener('voiceschanged', function() {});
  }
```

- [ ] **Step 9: Rebuild and test**

```bash
docker compose -f /home/ubuntu/compose/claude-chat-compose.yml build --no-cache && docker compose -f /home/ubuntu/compose/claude-chat-compose.yml up -d
```

Playwright test:

```python
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    errors = []
    page.on('pageerror', lambda err: errors.append(str(err)))
    page.goto('http://localhost:8800', wait_until='networkidle')
    page.wait_for_timeout(2000)

    # Gear button exists
    gear = page.query_selector('#gearBtn')
    assert gear, 'Gear button missing'

    # Open settings
    gear.click()
    page.wait_for_timeout(500)
    panel = page.query_selector('.settings-panel.visible')
    assert panel, 'Settings panel did not open'

    # Settings rows exist
    rows = page.query_selector_all('.settings-row')
    assert len(rows) == 4, f'Expected 4 settings rows, got {len(rows)}'

    # Switch theme to OLED
    selects = page.query_selector_all('.settings-select')
    selects[0].select_option('oled')
    page.wait_for_timeout(200)
    theme = page.evaluate('document.documentElement.getAttribute("data-theme")')
    assert theme == 'oled', f'Theme not applied: {theme}'

    # Switch to light
    selects[0].select_option('light')
    page.wait_for_timeout(200)
    theme = page.evaluate('document.documentElement.getAttribute("data-theme")')
    assert theme == 'light', f'Theme not applied: {theme}'

    # Close settings
    page.click('.settings-backdrop')
    page.wait_for_timeout(300)

    # Check localStorage
    stored = page.evaluate('JSON.parse(localStorage.getItem("claude_chat_settings") || "{}")')
    assert stored.get('theme') == 'light', f'Theme not stored: {stored}'

    # Reset to dark for other tests
    page.evaluate('localStorage.removeItem("claude_chat_settings")')

    print(f'Settings test PASSED. JS errors: {len(errors)}')
    if errors: print(errors)
    browser.close()
```

- [ ] **Step 10: Commit**

```bash
git add static/index.html static/css/style.css static/js/app.js
git commit -m "feat: add settings panel with theme, poll speed, TTS voice, notifications

Slide-up settings panel with gear icon. Three themes: Dark, OLED Black,
Light. Configurable poll speed (Fast/Normal/Battery Saver). TTS voice
selector. Default notifications toggle. Migrates all hardcoded border
colors to CSS custom properties for theme support."
```

---

### Task 4: Auto-scroll Improvements

**Files:**
- Modify: `static/js/app.js` (update `scrollToBottom`, `showSessionList`, `loadSession` callback, add pill position logic)
- Modify: `static/css/style.css` (remove hardcoded `bottom: 160px` from `.new-msg-pill`)

**Context:** The current `scrollToBottom` (line ~611 in `app.js`) uses `scrollTop = scrollHeight` for instant jumps. The "new messages" pill has `bottom: 160px` hardcoded in CSS (line ~406).

- [ ] **Step 1: Update scrollToBottom for smooth scrolling**

In `static/js/app.js`, find `scrollToBottom` (around line 611):

```javascript
  function scrollToBottom(force) {
    if (force || isUserNearBottom) {
      requestAnimationFrame(function() {
        chatFeed.scrollTop = chatFeed.scrollHeight;
      });
      newMsgPill.classList.remove('visible');
    }
  }
```

Replace with:

```javascript
  function scrollToBottom(force) {
    if (force || isUserNearBottom) {
      requestAnimationFrame(function() {
        if (force && lastMessageCount === 0) {
          // Initial load -- instant scroll, no animation
          chatFeed.scrollTop = chatFeed.scrollHeight;
        } else {
          chatFeed.scrollTo({ top: chatFeed.scrollHeight, behavior: 'smooth' });
        }
      });
      newMsgPill.classList.remove('visible');
    }
  }
```

- [ ] **Step 2: Add scroll position memory**

In `static/js/app.js`, add a state variable after the existing state declarations (after line ~14):

```javascript
  var sessionScrollPositions = {};
```

In `showSessionList()` (around line 87), add scroll position saving BEFORE `currentSession = null`:

```javascript
    // Save scroll position before leaving
    if (currentSession) {
      sessionScrollPositions[currentSession] = chatFeed.scrollTop;
    }
```

In `loadSession()` callback (around line 355-372), find where `scrollToBottom(true)` is called after `renderMessages`. Replace the `scrollToBottom(true)` call with:

```javascript
        var savedPos = sessionScrollPositions[name];
        if (savedPos !== undefined) {
          chatFeed.scrollTop = savedPos;
        } else {
          scrollToBottom(true);
        }
```

- [ ] **Step 3: Dynamic pill positioning**

In `static/css/style.css`, find `.new-msg-pill` (around line 403-425). Change `bottom: 160px;` to `bottom: 80px;` (JS will override this dynamically, but this is a safe fallback).

In `static/js/app.js`, add a pill position updater. Add this function after `scrollToBottom`:

```javascript
  function updatePillPosition() {
    var area = document.getElementById('inputArea');
    if (area) {
      newMsgPill.style.bottom = (area.offsetHeight + 20) + 'px';
    }
  }
```

Call `updatePillPosition()` in two places:
1. At the end of `showSessionView()` (after `startPolling()`)
2. Add a resize listener in the Init section:

```javascript
  window.addEventListener('resize', updatePillPosition);
```

- [ ] **Step 4: Rebuild and test**

```bash
docker compose -f /home/ubuntu/compose/claude-chat-compose.yml build --no-cache && docker compose -f /home/ubuntu/compose/claude-chat-compose.yml up -d
```

Playwright test:

```python
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    errors = []
    page.on('pageerror', lambda err: errors.append(str(err)))
    page.goto('http://localhost:8800', wait_until='networkidle')
    page.wait_for_timeout(2000)

    cards = page.query_selector_all('.session-card')
    if cards:
        cards[0].click()
        page.wait_for_timeout(3000)

        # Check scroll position is at bottom
        at_bottom = page.evaluate('''() => {
            var f = document.getElementById("chatFeed");
            return (f.scrollHeight - f.scrollTop - f.clientHeight) < 50;
        }''')
        assert at_bottom, 'Not scrolled to bottom on initial load'

        # Check pill position is dynamic (not exactly 160px)
        pill_bottom = page.evaluate('''() => {
            var pill = document.getElementById("newMsgPill");
            return pill.style.bottom;
        }''')
        print(f'Pill bottom: {pill_bottom}')

    print(f'Scroll test PASSED. JS errors: {len(errors)}')
    if errors: print(errors)
    browser.close()
```

- [ ] **Step 5: Commit**

```bash
git add static/js/app.js static/css/style.css
git commit -m "feat: smooth scrolling, scroll position memory, dynamic pill

Use smooth scrolling for new messages (instant on initial load). Save
and restore scroll position per session. Position new-messages pill
dynamically based on input area height."
```

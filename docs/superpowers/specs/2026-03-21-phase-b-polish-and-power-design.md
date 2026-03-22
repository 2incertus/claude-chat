# Phase B: Polish & Power

## Goal

Transform claude-chat from functional to refined with four features: markdown rendering, improved dead session UX, a settings panel, and auto-scroll improvements.

## Implementation Strategy

Each feature is developed in an isolated git worktree by a parallel subagent. Main branch stays clean until all features are reviewed and merged sequentially.

---

## Feature 1: Markdown Rendering (Custom Mini-Parser)

### Current state
- Assistant messages render as raw text via `textContent`
- Code blocks detected by indentation heuristic (`codeRe` regex)
- No formatting for headers, bold, italic, lists, links, or fenced code blocks

### Target state
- A `renderMarkdown(text)` function converts markdown to HTML
- Supports: `#`-`###` headers, `**bold**`, `*italic*`, `` `inline code` ``, fenced code blocks (triple backtick), bullet lists (`- ` / `* `), numbered lists (`1. `), links `[text](url)`, and horizontal rules (`---`)
- Fenced code blocks get the existing `.code-block` styling with copy button
- The existing indentation-based code detection is removed (fenced blocks replace it)
- Output is sanitized: no raw `<script>`, `<iframe>`, `<img onerror>`, etc.

### Implementation

**New function `renderMarkdown(text)` in `app.js`:**

Returns a DocumentFragment (not innerHTML string) for safety. Pipeline:

1. Escape all `<` and `>` in the source text to `&lt;` / `&gt;` first
2. Split text into blocks by blank lines
3. Identify fenced code blocks (``` delimiters) first -- these are pass-through (no inline parsing). The optional language identifier after opening backticks (e.g., `python`) is stripped and not rendered.
4. For each non-code block:
   - Detect headers (`# ` through `### `)
   - Detect list items (`- `, `* `, `1. `) -- consecutive list items grouped into `<ul>` / `<ol>`
   - Detect horizontal rules (`---` or `***` on a line by itself)
   - Everything else is a paragraph. Within a paragraph block, consecutive non-blank lines are joined with a single space (undoes tmux hard wrapping). Single blank lines between blocks create paragraph breaks (`<p>` boundaries).
5. Within paragraphs, headers, and list items, apply inline formatting:
   - `` `code` `` -> `<code>` with `.inline-code` class (matched first, greedy)
   - `**text**` -> `<strong>`
   - `*text*` -> `<em>`
   - `[text](url)` -> `<a>` (only http/https URLs, `target="_blank"`, `rel="noopener"`)
   - Nesting is not supported -- each delimiter is matched greedily in the order listed above
6. Return DocumentFragment

**CSS requirement:** Remove `white-space: pre-wrap` from `.msg-assistant-text` (currently at style.css line 292). Replace with `white-space: normal`. The markdown renderer handles all whitespace via block-level elements.

**Sanitization rules:**
- No HTML tags pass through -- all `<` and `>` in source text are escaped to `&lt;` / `&gt;` before markdown parsing
- Links only allow `http://` and `https://` protocols
- No `javascript:` URLs

**CSS additions to `style.css`:**

```css
/* Markdown elements inside assistant messages */
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
.msg-assistant-text li {
  margin: 2px 0;
}
.inline-code {
  background: var(--code-bg);
  font-family: var(--mono);
  font-size: 0.85em;
  padding: 1px 5px;
  border-radius: 4px;
  border: 1px solid var(--border);
}
.msg-assistant-text a {
  color: var(--accent);
  text-decoration: none;
}
.msg-assistant-text a:hover {
  text-decoration: underline;
}
.msg-assistant-text hr {
  border: none;
  border-top: 1px solid var(--border);
  margin: 8px 0;
}
.msg-assistant-text strong { font-weight: 600; }
.msg-assistant-text em { font-style: italic; }
```

**Changes to `appendMessage` in `app.js`:**
- Remove the entire indentation-based `codeRe` / `codeBuf` / `inCode` code block detection
- Replace with: `textSpan.appendChild(renderMarkdown(content))`
- The `renderMarkdown` function handles fenced code blocks internally, creating `<pre class="code-block">` elements with copy buttons (reusing existing copy button logic)

---

## Feature 2: Dead Session UX

### Current state
- Dead cards show: session name, cwd, muted opacity (0.5), red left border, respawn button
- No preview text, no time info, no context about what the session was doing

### Target state
- Dead cards show the last assistant message as preview (same as active cards)
- Dead cards show "Died Xm ago" using a death timestamp cache
- Dead cards show a subtle "EXITED" label instead of a status dot

### Backend changes (`app.py`)

**Death timestamp tracking:** Add a module-level dict `death_cache: dict[str, float] = {}` that records the first time a session is seen as dead. In `list_sessions`, when iterating sessions: if `state == "dead"` and `name not in death_cache`, set `death_cache[name] = time.time()`. If a session goes back to active, remove it from `death_cache`. This is ephemeral (lost on container restart), which is acceptable.

In `list_sessions`, for dead sessions, capture the pane output and extract a preview:

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

No new endpoints needed.

### Frontend changes

In `renderSessionList` (`app.js`):
- Show preview text on dead cards (currently gated by `s.state !== 'dead'`)
- Change: remove the `&& s.state !== 'dead'` check on the preview rendering

In `style.css`:
- Add a `.session-card-dead-label` for a subtle "EXITED" text label

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

---

## Feature 3: Settings Panel

### Interaction
- Gear icon button in the session list header (right side)
- Tapping opens a slide-up panel (covers bottom 60% of screen)
- Dark semi-transparent backdrop
- Panel has a drag handle at top for dismiss (or tap backdrop)
- All settings saved to `localStorage` key `claude_chat_settings`

### Settings

| Setting | Type | Default | Key |
|---------|------|---------|-----|
| TTS Voice | Dropdown | System default | `chatVoice` (matches existing localStorage key used in `toggleTTS`) |
| Default Notifications | Toggle | Off | `defaultNtfy` (when on, new sessions start with ntfy enabled -- the bell icon defaults to on for sessions not explicitly toggled) |
| Theme | 3-option | Dark | `theme` |
| Poll Speed | 3-option | Normal | `pollSpeed` |

### Theme definitions

All existing hardcoded `rgba(255,255,255,0.06)`, `rgba(255,255,255,0.08)`, `rgba(255,255,255,0.1)` border/separator values in the CSS must be replaced with the new `--border` and `--border-medium` custom properties. This is required for light theme to work.

```css
/* Add to existing :root */
:root {
  --border: rgba(255,255,255,0.06);
  --border-medium: rgba(255,255,255,0.1);
}

/* OLED black */
:root[data-theme="oled"] {
  --bg: #000000;
  --surface: #0A0A0A;
  --surface2: #141414;
}

/* Light */
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

**Migration:** All `rgba(255,255,255,0.06)` -> `var(--border)`, all `rgba(255,255,255,0.08)` -> `var(--border)`, all `rgba(255,255,255,0.1)` -> `var(--border-medium)` throughout `style.css`. This includes existing styles (headers, cards, inputs, code blocks) and all new styles in this spec.

### Poll speed values
- Fast: `idleCount < 3 ? 1000 : idleCount < 6 ? 3000 : 5000`
- Normal (current): `idleCount < 3 ? 2000 : idleCount < 6 ? 5000 : 10000`
- Battery saver: `idleCount < 3 ? 5000 : 15000`

### HTML structure (added to `index.html`)

Gear button in `#screenList` header, after `<div class="header-spacer"></div>`:

```html
<button class="gear-btn" id="gearBtn" title="Settings"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg></button>
```

Settings panel and backdrop at the end of `<div class="app-shell">`:

```html
<div class="settings-backdrop" id="settingsBackdrop"></div>
<div class="settings-panel" id="settingsPanel">
  <div class="settings-handle"></div>
  <h3 class="settings-title">Settings</h3>
  <!-- settings rows rendered by JS -->
</div>
```

### CSS

```css
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
.settings-panel.visible {
  transform: translateY(0);
}
.settings-handle {
  width: 36px;
  height: 4px;
  background: rgba(255,255,255,0.2);
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
.settings-label {
  font-size: 0.88rem;
  color: var(--text);
}
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
.settings-toggle.on::after {
  transform: translateX(20px);
}
```

### JS

- `loadSettings()` -- read from localStorage, apply theme, set poll speed
- `saveSettings(key, value)` -- update localStorage and apply immediately
- `openSettings()` / `closeSettings()` -- panel animation (tap backdrop to close; the handle is visual only, not a drag target)
- `renderSettingsPanel()` -- create settings rows dynamically
- TTS voice dropdown populated from `speechSynthesis.getVoices()`
- Theme applied by setting `document.documentElement.dataset.theme`
- Poll speed integration: add a global `var pollSpeedSetting = 'normal'` variable. `schedulePoll()` reads this variable to select the interval table. `loadSettings()` sets it on init, `saveSettings('pollSpeed', val)` updates it immediately. The three interval tables are defined as objects:
  ```javascript
  var POLL_SPEEDS = {
    fast:   { active: 1000, warm: 3000, idle: 5000 },
    normal: { active: 2000, warm: 5000, idle: 10000 },
    saver:  { active: 5000, warm: 15000, idle: 15000 }
  };
  ```
  `schedulePoll()` selects `active` when `idleCount < 3`, `warm` when `< 6`, else `idle`.
- Settings loaded on app init (before first render)
- `defaultNtfy` integration: in `showSessionView()`, if the session has not been explicitly toggled (not in `ntfy_sessions` localStorage), apply the default. Check `isNtfyEnabled` returns `undefined` (key missing) vs `false` (explicitly off).

---

## Feature 4: Auto-scroll Improvements

### Current issues
- `scrollToBottom` uses `scrollTop = scrollHeight` (instant jump)
- No scroll position memory between sessions
- "New messages" pill hardcoded at `bottom: 160px`

### Changes

**Smooth scrolling:**
```javascript
function scrollToBottom(force) {
  if (force || isUserNearBottom) {
    requestAnimationFrame(function() {
      chatFeed.scrollTo({ top: chatFeed.scrollHeight, behavior: 'smooth' });
    });
    newMsgPill.classList.remove('visible');
  }
}
```

Exception: on initial session load (`force === true` with no previous messages), use instant scroll (no animation) since there's nothing to animate from.

**Scroll position memory:**
```javascript
var sessionScrollPositions = {};

// In showSessionList():
if (currentSession) {
  sessionScrollPositions[currentSession] = chatFeed.scrollTop;
}

// In loadSession() callback, after renderMessages():
var savedPos = sessionScrollPositions[name];
if (savedPos !== undefined) {
  chatFeed.scrollTop = savedPos;
} else {
  scrollToBottom(true);
}
```

**Scroll position memory note:** `sessionScrollPositions` is in-memory only -- positions are lost on page reload. This is intentional; persisting to localStorage would add complexity for minimal benefit since the PWA stays open.

**Dynamic pill position:**
- Remove hardcoded `bottom: 160px` from CSS
- Set dynamically in JS: `newMsgPill.style.bottom = (inputArea.offsetHeight + 20) + 'px'`
- Recalculate on window resize and input area changes

---

## Files modified/created

- `static/js/app.js` -- markdown parser, dead session preview, settings panel JS, scroll improvements
- `static/css/style.css` -- markdown styles, dead label, settings panel styles, theme variants
- `static/index.html` -- settings panel HTML, gear icon button
- `app.py` -- dead session preview in list_sessions

## Testing

- Playwright: markdown renders headers, bold, code blocks, lists correctly
- Playwright: dead sessions show preview text
- Playwright: settings panel opens/closes, theme switches
- Playwright: no JS errors after all interactions
- Manual: smooth scrolling feels natural on mobile
- Manual: theme persists across page reloads
- Manual: TTS voice selection works

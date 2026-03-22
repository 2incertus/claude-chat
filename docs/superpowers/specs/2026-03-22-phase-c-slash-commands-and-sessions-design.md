# Phase C: Slash Commands + Session Management

## Goal

Add a command palette for discovering and executing slash commands, visual rendering of command results in the chat feed, session renaming, and session creation with preset directories.

## Implementation Strategy

Same as Phase B -- features developed in isolated git worktrees by parallel subagents, merged sequentially.

---

## Feature 1: Command Palette

### Command sources

**Built-in commands (hardcoded):**

```javascript
var BUILTIN_COMMANDS = [
  { name: '/compact', desc: 'Compress conversation context' },
  { name: '/clear', desc: 'Clear conversation history' },
  { name: '/help', desc: 'Show available commands' },
  { name: '/doctor', desc: 'Check Claude Code health' },
  { name: '/config', desc: 'View or change settings' },
  { name: '/cost', desc: 'Show token usage and cost' },
  { name: '/memory', desc: 'Edit CLAUDE.md memory files' },
  { name: '/login', desc: 'Log in to your account' },
  { name: '/logout', desc: 'Log out of your account' },
  { name: '/status', desc: 'Show session status' },
  { name: '/review', desc: 'Review recent changes' },
  { name: '/bug', desc: 'Report a bug' },
  { name: '/init', desc: 'Initialize project CLAUDE.md' },
];
```

**Custom skills (dynamic discovery):**

New backend endpoint `GET /api/commands` scans for custom skills:

1. Read `~/.claude/settings.json` and `~/.claude/settings.local.json` for skill definitions
2. Scan `~/.claude/plugins/` for installed plugin skill manifests
3. Scan `~/.claude/skills/` for user-created skills
4. For each skill, extract `name` and `description` from the frontmatter
5. Return merged list: builtins + custom skills
6. Cache the result for 60 seconds (skills don't change mid-session)

Response format:
```json
{
  "commands": [
    { "name": "/compact", "desc": "Compress conversation context", "source": "builtin" },
    { "name": "/deploy", "desc": "Deploy a Docker service", "source": "skill" },
    ...
  ]
}
```

### UI: Autocomplete popup

- Triggered when user types `/` as the first character in the text input
- Popup appears above the text input (below the chat feed)
- Shows a filtered list of matching commands as the user types
- Each row: command name (monospace, accent color) + description (dim text)
- Tap a command to insert it into the text input (cursor placed after it, ready for arguments)
- Dismiss: tap outside, press Escape, delete the `/`, or type text that matches zero commands (auto-dismiss when no results)
- Max 8 visible items, scrollable if more

### UI: Command button

- Small `/` button added to the left of the text input, next to the attach button
- Tap opens the full command list (same popup but unfiltered)
- Provides discoverability for users who don't know about typing `/`

### CSS

```css
.cmd-palette {
  position: absolute;
  bottom: 100%;
  left: 0;
  right: 0;
  background: var(--surface);
  border-top: 1px solid var(--border);
  max-height: 320px;
  overflow-y: auto;
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
}
.cmd-btn:active { color: var(--text); }
```

### Backend

New endpoint in `app.py`:

```python
import glob
import yaml  # add PyYAML to Dockerfile pip install

commands_cache: dict = {"commands": [], "ts": 0}

@app.get("/api/commands")
async def list_commands():
    now = time.time()
    if commands_cache["ts"] and (now - commands_cache["ts"]) < 60:
        return commands_cache

    builtins = [
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

    skills = []
    # Scan skill directories for frontmatter
    # Scan user skills: ~/.claude/skills/<skill-name>/SKILL.md
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
                        "desc": front.get("description", "")[:100],
                        "source": "skill",
                    })
        except Exception:
            continue

    commands_cache["commands"] = builtins + skills
    commands_cache["ts"] = now
    return {"commands": commands_cache["commands"]}
```

Note: `CLAUDE_DATA_DIR` is already defined and mounted as `/claude-data` (maps to `~/.claude`). PyYAML needs to be added to the Dockerfile: `pip install ... pyyaml`.

---

## Feature 2: Command Result Cards

### Detection

In `parse_messages` or in the frontend rendering, detect when a user message starts with `/`. The next assistant message after a slash command gets wrapped in a command result card.

Frontend-only detection (no backend changes):
- In `renderMessages`, track whether the previous message was a user message starting with `/`
- If so, wrap the next assistant message in a `.cmd-result-card` container

### Rendering

User message starting with `/`:
- The `/command` portion renders in a pill: monospace, slightly highlighted background
- Any text after the command renders normally as arguments

Assistant response after a slash command:
- Wrapped in `.cmd-result-card`: subtle border, header bar with command name + "completed" label
- Collapsible: tap the header bar to toggle content visibility
- Expanded by default

### CSS

```css
/* User message slash command pill */
.cmd-pill {
  display: inline;
  font-family: var(--mono);
  font-weight: 600;
  background: rgba(0,0,0,0.2);
  padding: 1px 7px;
  border-radius: 8px;
  font-size: 0.85em;
}

/* Command result card */
.cmd-result-card {
  border-radius: 4px 16px 16px 16px;
  overflow: hidden;
  max-width: 92%;
  align-self: flex-start;
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
.cmd-result-toggle.collapsed {
  transform: rotate(-90deg);
}
.cmd-result-body {
  background: var(--surface2);
  padding: 12px 14px;
}
.cmd-result-body.collapsed {
  display: none;
}
```

### JS changes to `appendMessage`

In the user message branch: if `content.startsWith('/')`, split into command name and args, render command as `.cmd-pill` span.

Detection approach: for each assistant message, look backwards through the messages array (skipping tool messages) to find the preceding user message. If that user message starts with `/`, wrap this assistant message in a command result card. This is stateless per-message -- no mutable tracking variables needed. Extract the command name from the preceding user message for the card header.

Edge cases:
- If `/clear` produces no assistant response, nothing to wrap -- no issue
- Tool messages between user and assistant are skipped (they're already hidden in rendering)
- Multiple consecutive assistant messages after a command: only the first one gets the card treatment

---

## Feature 3: Session Renaming

### Storage

`/srv/appdata/claude-chat/titles.json` -- a JSON object mapping tmux session names to custom titles:

```json
{
  "cc": "Claude Chat Development",
  "ha": "Home Assistant Work"
}
```

### Backend

On startup, load `titles.json` into `title_cache` (already exists).

New endpoint:

```python
TITLES_FILE = os.path.join(os.environ.get("UPLOAD_DIR", "/uploads"), "titles.json")
# Stored inside the uploads volume: /srv/appdata/claude-chat/uploads/titles.json on host

@app.put("/api/sessions/{name}/title")
async def set_session_title(name: str, body: dict):
    validate_session_name(name)
    title = body.get("title", "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title must not be empty")
    title_cache[name] = title[:60]
    # Persist
    try:
        existing = {}
        if os.path.exists(TITLES_FILE):
            with open(TITLES_FILE) as f:
                existing = json.load(f)
        existing[name] = title[:60]
        with open(TITLES_FILE, "w") as f:
            json.dump(existing, f)
    except Exception:
        pass  # cache is primary, file is best-effort
    return {"title": title_cache[name]}
```

On startup (in lifespan), load `titles.json` into `title_cache`:

```python
if os.path.exists(TITLES_FILE):
    try:
        with open(TITLES_FILE) as f:
            title_cache.update(json.load(f))
    except Exception:
        pass
```

### Frontend

- Tap the session title in the chat header (`#chatTitle`)
- Title becomes an editable input field (contenteditable or replace with `<input>`)
- Press Enter or tap away to save
- Calls `PUT /api/sessions/{name}/title`
- Escape cancels edit

---

## Feature 4: Session Creation

### Preset configuration

`/srv/appdata/claude-chat/config.json`:

```json
{
  "presets": [
    { "name": "Home", "path": "/home/ubuntu", "persistent": true },
    { "name": "AI Hub", "path": "/home/ubuntu/docker/ai-hub" },
    { "name": "Claude Chat", "path": "/home/ubuntu/docker/claude-chat" },
    { "name": "n8n", "path": "/home/ubuntu/compose" },
    { "name": "HA", "path": "/home/ubuntu/docker/homeassistant", "persistent": true }
  ]
}
```

### Backend

New endpoint:

```python
CONFIG_FILE = "/config/config.json"  # mounted volume

def _load_config() -> dict:
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except Exception:
        return {"presets": []}

def _is_allowed_path(path: str) -> bool:
    """Validate path against preset allowlist.

    Since the container filesystem differs from the host, we cannot use
    os.path.isdir(). Instead, only allow paths that appear in the presets
    list or are under /home/ubuntu/ (the user's home).
    """
    config = _load_config()
    allowed_paths = {p["path"] for p in config.get("presets", [])}
    if path in allowed_paths:
        return True
    # Allow any path under /home/ubuntu/ as a safety net
    return path.startswith("/home/ubuntu/")

@app.post("/api/sessions")
async def create_session(body: dict):
    path = body.get("path", "/home/ubuntu")
    name = body.get("name", "")

    # Validate path against allowlist (can't check host fs from container)
    if not _is_allowed_path(path):
        raise HTTPException(status_code=400, detail=f"Path not allowed: {path}")

    # Generate session name if not provided
    if not name:
        base = os.path.basename(path) or "s"
        name = base[:10]
        # Deduplicate
        existing = {s["name"] for s in discover_sessions()}
        if name in existing:
            i = 1
            while f"{name}{i}" in existing:
                i += 1
            name = f"{name}{i}"

    validate_session_name(name)
    if _session_exists(name):
        raise HTTPException(status_code=409, detail=f"Session {name} already exists")

    # Create tmux session with claude via run_tmux
    run_tmux("new-session", "-d", "-s", name, "-c", path,
             "/home/ubuntu/.local/bin/claude")

    return {"created": True, "name": name, "path": path}


@app.get("/api/config")
async def get_config():
    return _load_config()
```

Add `"new-session"` to `ALLOWED_COMMANDS` set at the top of `app.py`.

### Frontend

- "+" button in session list header, next to the gear icon
- Tap opens a slide-up panel (same pattern as settings)
- Shows preset directories as tappable cards
- Custom path input at the bottom with a "Launch" button
- Creating a session: POST to `/api/sessions`, show loading spinner, then refresh session list
- For persistent presets: if a preset is configured as persistent and no matching session is running, show a subtle "Launch" chip on the session list (not a separate panel)

### HTML additions to `index.html`

```html
<!-- New session panel -->
<div class="new-session-backdrop" id="newSessionBackdrop"></div>
<div class="new-session-panel" id="newSessionPanel">
  <div class="settings-handle"></div>
  <h3 class="settings-title">New Session</h3>
  <!-- preset list and custom path input rendered by JS -->
</div>
```

### CSS (reuses settings panel patterns)

```css
.new-session-backdrop { /* same as .settings-backdrop */ }
.new-session-panel { /* same as .settings-panel */ }
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
```

### Volume mount

Add to `claude-chat-compose.yml`:

```yaml
    volumes:
      - /srv/appdata/claude-chat/config:/config:ro
```

Create default config:

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

### Dockerfile

Add `pyyaml` to pip install:

```dockerfile
RUN pip install --no-cache-dir fastapi uvicorn httpx python-multipart pyyaml
```

---

## Files modified/created

- `app.py` -- commands endpoint, title endpoint, session creation endpoint, config endpoint, titles.json loading, new-session in ALLOWED_COMMANDS
- `static/js/app.js` -- command palette UI, autocomplete, command result card rendering, session rename inline editing, new session panel
- `static/css/style.css` -- command palette, command pill, result card, preset card, new-session panel styles
- `static/index.html` -- command button, new session panel HTML, "+" button
- `Dockerfile` -- add pyyaml
- `docker-compose (compose file)` -- add config volume mount

## Testing

- Playwright: command palette appears when typing `/` in input
- Playwright: command button opens full list
- Playwright: tapping command inserts it into input
- Playwright: `/api/commands` returns builtin + skill commands
- Playwright: user message starting with `/` renders with command pill
- Playwright: session title editable on tap
- Playwright: `PUT /api/sessions/{name}/title` persists title
- curl: `POST /api/sessions` creates new tmux session
- curl: `GET /api/config` returns presets
- Manual: command result card collapses/expands on tap
- Manual: new session panel shows presets and launches session

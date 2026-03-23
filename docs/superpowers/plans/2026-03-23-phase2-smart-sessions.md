# Phase 2: Smart Sessions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four features that make session management smarter at scale: cost/token display, message starring, session folders/groups, and auto-tagging via LLM.

**Architecture:** These features add lightweight persistence (localStorage for starring/folders, extend titles.json for tags) and surface data Claude Code already tracks. No new databases. The auto-tagging extends the existing LiteLLM title generation. Cost display parses `/cost` output from the tmux pane.

**Tech Stack:** Python/FastAPI (backend), vanilla JavaScript (frontend), CSS custom properties, LiteLLM (tagging)

**Prerequisite:** Phase 1 must be complete (this plan references buttons/patterns added there).

---

## File Structure

| File | Changes |
|------|---------|
| `app.py` | Extend title generation to include tags, add cost parsing (~60 lines) |
| `static/js/app.js` | Starring UI, folder UI, cost badge, tag pills (~300 lines) |
| `static/css/style.css` | Tag pills, folder headers, star icon, cost badge (~80 lines) |
| `static/index.html` | Cost badge container in header (~5 lines) |

**Note:** app.js will reach ~3,400 lines after this phase. Phase 3 should begin with a modularization pass if it exceeds 3,500.

---

### Task 1: Cost/Token Display

**Files:**
- Modify: `app.py:235-329` (add cost parsing to message parser or session endpoint)
- Modify: `static/js/app.js` (add cost badge to chat header, ~40 lines)
- Modify: `static/css/style.css` (cost badge styles, ~15 lines)
- Modify: `static/index.html:42-44` (add cost badge container)

**How it works:** Claude Code outputs cost info when you run `/cost`. The app already captures all pane output. We parse the last occurrence of cost data from the raw tmux output and surface it as a badge in the chat header. We also detect the status-bar cost format that Claude Code shows (`$ X.XX`).

- [ ] **Step 1: Add cost extraction to app.py**

Add a helper function near the message parsing section (after `parse_messages`, line ~330):

```python
COST_RE = re.compile(r"\$\s*(\d+\.?\d*)")
TOKEN_RE = re.compile(r"(\d[\d,]+)\s*tokens?", re.IGNORECASE)
CTX_RE = re.compile(r"CTX\s+(\d+)%")

def extract_cost_info(raw: str) -> dict | None:
    """Extract cost/token info from the last few lines of pane output."""
    lines = raw.strip().splitlines()
    # Scan last 50 lines for cost markers
    tail = lines[-50:] if len(lines) > 50 else lines
    cost = None
    tokens = None
    ctx_pct = None

    for line in reversed(tail):
        if cost is None:
            m = COST_RE.search(line)
            if m:
                cost = float(m.group(1))
        if tokens is None:
            m = TOKEN_RE.search(line)
            if m:
                tokens = int(m.group(1).replace(",", ""))
        if ctx_pct is None:
            m = CTX_RE.search(line)
            if m:
                ctx_pct = int(m.group(1))

    if cost is not None or tokens is not None or ctx_pct is not None:
        return {"cost": cost, "tokens": tokens, "context_pct": ctx_pct}
    return None
```

- [ ] **Step 2: Include cost info in session response**

In the `get_session` endpoint (line ~609), add cost extraction to the response:

```python
# After: status = get_session_status(raw)
cost_info = extract_cost_info(raw)

# Add to return dict:
# "cost_info": cost_info,
```

Also add to `list_sessions` response for each session to show cost in the session card.

- [ ] **Step 3: Add cost badge HTML to chat header**

In `static/index.html`, add inside the chat header (after the session title span):

```html
<span class="cost-badge" id="costBadge" style="display:none;" title="Session cost"></span>
```

- [ ] **Step 4: Add cost badge CSS**

```css
.cost-badge {
  font-size: 0.7rem; color: var(--text-muted); background: var(--surface2);
  padding: 2px 8px; border-radius: 10px; font-family: 'SF Mono', monospace;
  white-space: nowrap;
}
```

- [ ] **Step 5: Update cost badge from poll response in app.js**

Add DOM ref:

```javascript
var costBadge = document.getElementById('costBadge');
```

In the message rendering function (where poll response is processed), update cost badge:

```javascript
function updateCostBadge(costInfo) {
  if (!costInfo) { costBadge.style.display = 'none'; return; }
  var parts = [];
  if (costInfo.cost != null) parts.push('$' + costInfo.cost.toFixed(2));
  if (costInfo.context_pct != null) parts.push('CTX ' + costInfo.context_pct + '%');
  if (parts.length > 0) {
    costBadge.textContent = parts.join(' · ');
    costBadge.style.display = '';
  } else {
    costBadge.style.display = 'none';
  }
}
```

Call `updateCostBadge(data.cost_info)` in the poll response handler.

- [ ] **Step 6: Test manually**

Open a session that has used `/cost`. Verify the badge shows cost and/or CTX percentage.

- [ ] **Step 7: Commit**

```bash
git add app.py static/index.html static/js/app.js static/css/style.css
git commit -m "feat: cost and context usage badge in chat header"
```

---

### Task 2: Message Starring/Pinning

**Files:**
- Modify: `static/js/app.js` (add star button to messages, localStorage persistence, star filter, ~80 lines)
- Modify: `static/css/style.css` (star button styles, starred message highlight, ~25 lines)

**How it works:** Each message gets a unique ID derived from `role + timestamp + first 20 chars of content`. Users click a star icon on any message to pin it. Starred message IDs are stored in localStorage per session. A "Show starred" toggle filters the chat feed to show only starred messages.

- [ ] **Step 1: Add message ID generation**

In `app.js`, add a helper near the clipboard section:

```javascript
function msgId(msg) {
  return msg.role + ':' + (msg.ts || 0) + ':' + (msg.content || '').substring(0, 20);
}

function getStarredMessages(sessionName) {
  try { return JSON.parse(localStorage.getItem('starred_' + sessionName) || '[]'); } catch(e) { return []; }
}

function setStarredMessages(sessionName, ids) {
  localStorage.setItem('starred_' + sessionName, JSON.stringify(ids));
}

function toggleStar(sessionName, id) {
  var starred = getStarredMessages(sessionName);
  var idx = starred.indexOf(id);
  if (idx >= 0) starred.splice(idx, 1);
  else starred.push(id);
  setStarredMessages(sessionName, starred);
  return idx < 0; // returns true if now starred
}
```

- [ ] **Step 2: Add star button to message rendering**

In the message rendering code, for both user and assistant messages, add a star button alongside the existing copy button. Inside the `msg-actions` div creation:

```javascript
var id = msgId(msg);
var starred = getStarredMessages(currentSession);
var isStarred = starred.indexOf(id) >= 0;

var starBtn = document.createElement('button');
starBtn.className = 'msg-action-btn msg-star-btn' + (isStarred ? ' starred' : '');
starBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="' + (isStarred ? 'var(--accent)' : 'none') + '" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>';
starBtn.title = isStarred ? 'Unstar' : 'Star message';
(function(mId, btn) {
  btn.addEventListener('click', function(e) {
    e.stopPropagation();
    var nowStarred = toggleStar(currentSession, mId);
    btn.classList.toggle('starred', nowStarred);
    btn.querySelector('svg').setAttribute('fill', nowStarred ? 'var(--accent)' : 'none');
    btn.title = nowStarred ? 'Unstar' : 'Star message';
  });
})(id, starBtn);
actions.appendChild(starBtn);
```

- [ ] **Step 3: Add star button CSS**

```css
.msg-star-btn.starred { color: var(--accent); }
.msg-star-btn:hover { color: var(--accent); }
```

- [ ] **Step 4: Add "Show starred only" toggle to chat header**

Add a star filter button in the chat header (next to the bell button):

```javascript
var starFilterBtn = document.createElement('button');
// ... toggle that adds .starred-only class to chatFeed
// When active, hide all messages that don't have .msg-starred class
```

CSS:
```css
.chat-feed.starred-only .msg:not(.msg-starred) { display: none; }
```

- [ ] **Step 5: Test manually**

1. Open a session, hover over messages — star button appears
2. Click star — fills with accent color, message gets subtle highlight
3. Click star filter in header — only starred messages shown
4. Refresh page — stars persist (localStorage)
5. Navigate away and back — stars still there

- [ ] **Step 6: Commit**

```bash
git add static/js/app.js static/css/style.css
git commit -m "feat: star/pin individual messages with persistent filter"
```

---

### Task 3: Session Folders/Groups

**Files:**
- Modify: `static/js/app.js` (folder assignment UI, grouped rendering, ~100 lines)
- Modify: `static/css/style.css` (folder header styles, ~30 lines)

**How it works:** Sessions are assigned to folders via a context menu (long-press on mobile, right-click on desktop). Folder assignments stored in localStorage. Session list renders with collapsible folder headers. Default folders: "Active", "Monitoring", "Archive". Users can create custom folders.

- [ ] **Step 1: Add folder data model**

```javascript
var DEFAULT_FOLDERS = ['Active', 'Monitoring', 'Archive'];

function getSessionFolders() {
  try { return JSON.parse(localStorage.getItem('session_folders') || '{}'); } catch(e) { return {}; }
}

function setSessionFolder(sessionName, folder) {
  var folders = getSessionFolders();
  if (folder) folders[sessionName] = folder;
  else delete folders[sessionName];
  localStorage.setItem('session_folders', JSON.stringify(folders));
}

function getCustomFolders() {
  try { return JSON.parse(localStorage.getItem('custom_folders') || '[]'); } catch(e) { return []; }
}

function addCustomFolder(name) {
  var folders = getCustomFolders();
  if (folders.indexOf(name) < 0) folders.push(name);
  localStorage.setItem('custom_folders', JSON.stringify(folders));
}

function getAllFolders() {
  return DEFAULT_FOLDERS.concat(getCustomFolders());
}
```

- [ ] **Step 2: Modify session list rendering to group by folder**

In the `renderSessions` function (line ~420-600), after sorting sessions, group them by folder:

```javascript
// After sorting, group by folder
var folders = getSessionFolders();
var grouped = {};
var ungrouped = [];

sortedSessions.forEach(function(s) {
  var folder = folders[s.name];
  if (folder) {
    if (!grouped[folder]) grouped[folder] = [];
    grouped[folder].push(s);
  } else {
    ungrouped.push(s);
  }
});

// Render ungrouped first, then each folder with a collapsible header
```

- [ ] **Step 3: Add folder header rendering**

```javascript
function renderFolderHeader(folderName, count) {
  var header = document.createElement('div');
  header.className = 'folder-header';
  header.innerHTML = '<span class="folder-chevron">&#9656;</span> ' + folderName + ' <span class="folder-count">' + count + '</span>';
  header.addEventListener('click', function() {
    header.classList.toggle('collapsed');
    var next = header.nextElementSibling;
    while (next && !next.classList.contains('folder-header')) {
      next.style.display = header.classList.contains('collapsed') ? 'none' : '';
      next = next.nextElementSibling;
    }
  });
  return header;
}
```

- [ ] **Step 4: Add folder assignment context menu**

Add to session card swipe actions or as a new button in the action panel:

```javascript
// In the session card action buttons area, add a folder button
var folderBtn = document.createElement('button');
folderBtn.className = 'card-action';
folderBtn.textContent = 'Move to...';
folderBtn.style.cssText = 'background:var(--surface2);color:var(--text);';
folderBtn.addEventListener('click', function() {
  showFolderPicker(s.name);
});
```

Folder picker as a small modal listing all folders + "New folder" option.

- [ ] **Step 5: Add CSS for folder headers**

```css
.folder-header {
  padding: 8px 16px; font-size: 0.75rem; font-weight: 600;
  color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em;
  cursor: pointer; user-select: none; display: flex; align-items: center; gap: 6px;
}
.folder-header:hover { color: var(--text); }
.folder-chevron { transition: transform 0.2s; display: inline-block; font-size: 0.6rem; }
.folder-header.collapsed .folder-chevron { transform: rotate(0deg); }
.folder-header:not(.collapsed) .folder-chevron { transform: rotate(90deg); }
.folder-count {
  background: var(--surface2); padding: 1px 6px; border-radius: 8px; font-size: 0.65rem;
}
```

- [ ] **Step 6: Test manually**

1. Long-press/right-click session card — "Move to..." option appears
2. Select "Active" — session moves under Active folder header
3. Click folder header — collapses/expands
4. Create custom folder — appears in list
5. Refresh — folder assignments persist

- [ ] **Step 7: Commit**

```bash
git add static/js/app.js static/css/style.css
git commit -m "feat: session folders with collapsible groups"
```

---

### Task 4: Auto-Tagging Sessions via LLM

**Files:**
- Modify: `app.py:387-418` (extend generate_title to also generate tags)
- Modify: `static/js/app.js` (render tag pills on session cards, ~40 lines)
- Modify: `static/css/style.css` (tag pill styles, ~20 lines)

**How it works:** The existing `generate_title()` function calls LiteLLM with the first 3 user messages to generate a title. We extend the prompt to also return 1-3 tags. Tags are stored alongside titles in `titles.json`. Session cards render tags as small colored pills.

- [ ] **Step 1: Extend generate_title in app.py**

Modify the `generate_title` function (line ~387) to request tags:

```python
async def generate_title(name: str, messages: list[dict]):
    """Generate title AND tags from conversation content."""
    user_msgs = [m["content"][:200] for m in messages if m["role"] == "user"][:3]
    if not user_msgs:
        return

    snippet = " | ".join(user_msgs)
    try:
        r = await http_client.post(
            LITELLM_URL,
            json={
                "model": "glm-4-air",
                "messages": [
                    {"role": "system", "content": "Generate a short title (max 6 words) and 1-3 tags for this AI coding conversation. Tags should be lowercase single words like: python, docker, frontend, debug, refactor, deploy, test, api, css, database, infra, review. Respond in format: TITLE: <title>\\nTAGS: <tag1>, <tag2>"},
                    {"role": "user", "content": snippet},
                ],
                "max_tokens": 40,
                "temperature": 0.3,
            },
            timeout=8.0,
        )
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"].strip()

        # Parse title and tags
        title = text
        tags = []
        if "TITLE:" in text:
            parts = text.split("\n")
            for part in parts:
                part = part.strip()
                if part.startswith("TITLE:"):
                    title = part[6:].strip().strip('"')
                elif part.startswith("TAGS:"):
                    tags = [t.strip().lower() for t in part[5:].split(",") if t.strip()]

        if len(title) > 50:
            title = title[:50]
        tags = tags[:3]  # max 3 tags

        async with _title_lock:
            title_cache[name] = title
            # Store tags in a separate cache
            tag_cache[name] = tags
            _save_titles()
    except Exception:
        pass
```

Update the title persistence to include tags:

```python
tag_cache: dict[str, list[str]] = {}

def _save_titles():
    """Save titles and tags to disk."""
    data = {}
    for name, title in title_cache.items():
        data[name] = {"title": title, "tags": tag_cache.get(name, [])}
    tmp = TITLES_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, TITLES_FILE)
```

Update title loading in `lifespan` to load tags too:

```python
# In lifespan, when loading titles:
if os.path.exists(TITLES_FILE):
    try:
        with open(TITLES_FILE) as f:
            raw = json.load(f)
        for name, val in raw.items():
            if isinstance(val, dict):
                title_cache[name] = val.get("title", name)
                tag_cache[name] = val.get("tags", [])
            else:
                # Backward compat: old format was just string
                title_cache[name] = val
    except Exception:
        pass
```

- [ ] **Step 2: Include tags in session list API response**

In `list_sessions` (line ~570), add tags to each session dict:

```python
# Add to each session result:
"tags": tag_cache.get(s["name"], []),
```

- [ ] **Step 3: Render tag pills on session cards in app.js**

In the session card creation code (line ~550), after the preview text:

```javascript
var tags = s.tags || [];
if (tags.length > 0) {
  var tagRow = document.createElement('div');
  tagRow.className = 'session-card-tags';
  tags.forEach(function(tag) {
    var pill = document.createElement('span');
    pill.className = 'tag-pill';
    pill.textContent = tag;
    tagRow.appendChild(pill);
  });
  card.appendChild(tagRow);
}
```

- [ ] **Step 4: Add tag pill CSS**

```css
.session-card-tags { display: flex; gap: 4px; padding: 4px 0 0; flex-wrap: wrap; }
.tag-pill {
  font-size: 0.65rem; padding: 1px 6px; border-radius: 6px;
  background: var(--surface2); color: var(--text-muted); border: 1px solid var(--border-subtle);
  white-space: nowrap;
}
```

- [ ] **Step 5: Handle backward compatibility**

The `_save_titles` and loading code handles both old format (string) and new format (dict with title + tags). Existing titles.json files will be migrated on first save.

- [ ] **Step 6: Test manually**

1. Create a new session and send a message — after title generation, tags should appear
2. Existing sessions should show titles (tags empty until next title refresh)
3. Tags render as small pills below session card
4. Multiple tags wrap correctly on narrow screens

- [ ] **Step 7: Commit**

```bash
git add app.py static/js/app.js static/css/style.css
git commit -m "feat: auto-tag sessions via LLM with tag pills on cards"
```

---

### Task 5: Version Bump and Integration Test

- [ ] **Step 1: Bump cache version**

In `static/index.html`, bump CSS version query param.
In `static/sw.js`, bump version string.

- [ ] **Step 2: Full smoke test**

1. Cost badge shows in chat header for sessions that have cost data
2. Star button appears on message hover, persists across page loads
3. "Show starred" filter works
4. Folder headers appear in session list, collapse/expand works
5. Session can be moved between folders
6. New sessions auto-generate tags as pills
7. All Phase 1 features still work (shortcuts, copy, export, templates)
8. Mobile layout not broken
9. All three themes work

- [ ] **Step 3: Commit**

```bash
git add static/index.html static/sw.js
git commit -m "chore: bump cache version for Phase 2 features"
```

# Phase A: Code Split + Session Management

## Goal

Split the monolithic single-file app into separate backend and frontend files, and add session kill/respawn/hide functionality.

## Part 1: Code Split

### Current state
- `app.py` contains ~1900 lines: Python backend + all HTML/CSS/JS inline in a `INDEX_HTML` triple-quoted string
- JS inside Python strings requires double-escaping (`\\n` instead of `\n`), causing repeated bugs

### Target state
- `app.py` (~300 lines): Pure API backend, serves static files
- `static/index.html`: HTML shell
- `static/css/style.css`: All CSS
- `static/js/app.js`: All JavaScript (no more escape sequence issues)

### Implementation
- FastAPI mounts `StaticFiles` at `/static`
- Index route serves `static/index.html` via `FileResponse` with headers `{"Cache-Control": "no-cache, no-store, must-revalidate"}` (matches current behavior)
- Remove `INDEX_HTML` variable entirely
- Dockerfile updated to `COPY static/ ./static/`
- All existing functionality preserved -- this is a pure extraction, no behavior changes
- No `aiofiles` dependency needed -- `FileResponse` does sync reads which is fine for a single small HTML file

## Part 2: Session Lifecycle

### Session states

```
Active (Claude running) --> Dead (Ctrl+C, Claude exited, tmux alive) --> Dismissed (tmux killed, gone)
     ^                                    |
     |                                    |
     +---------- Respawn ----------------+
```

### Kill flow
1. User swipes left on a session card, reveals red "Kill" button
2. User taps "Kill"
3. Frontend calls `POST /api/sessions/{name}/kill`
4. Backend (async endpoint) sends `Ctrl+C` to the tmux pane (`tmux send-keys -t name C-c`)
5. `await asyncio.sleep(2)` (non-blocking -- must NOT use `time.sleep`)
6. Check if Claude is still running via `pane_current_command`
7. If still running, send another `Ctrl+C`
8. Return `{"killed": true, "state": "dead"}` or `{"killed": false, "state": "active", "message": "Claude did not exit after 2 attempts"}` (frontend can show a force-kill option if needed)
9. Session card transitions to "dead" state

### Dead session display
- Muted opacity (0.5)
- Red left border (3px solid var(--red))
- Red status dot (not pulsing)
- "Respawn" button visible on the card
- Swipe left reveals "Dismiss" button (context-sensitive: active sessions show "Kill", dead sessions show "Dismiss" -- same gesture, different action based on `state`)

### Respawn flow
1. User taps "Respawn" on a dead session card
2. Frontend calls `POST /api/sessions/{name}/respawn`
3. Backend sends `claude --continue` + Enter to the tmux session
4. Session card transitions back to "active" state (normal display, polling resumes)
5. Claude Code resumes the same conversation in the same directory
6. Note: `claude --continue` resumes the most recent conversation in the pane's CWD. If the CWD changed before Claude exited, it may start a new conversation. This is an acceptable edge case.

### Dismiss flow (full cleanup)
1. User swipes left on a dead session card, reveals "Dismiss" button
2. Frontend calls `DELETE /api/sessions/{name}`
3. Backend runs `tmux kill-session -t name`
4. Card is removed from the list
5. Session name added to `localStorage` dismissed list (in case tmux data lingers)

### Hide flow (for active sessions)
- User can also swipe right on any session card to hide it temporarily
- Adds session name to `localStorage` key `hidden_sessions`
- Card disappears from list
- "Show hidden" toggle at bottom of session list to reveal them
- Toggle state is UI-only (resets on page reload -- hidden sessions stay hidden, but the toggle resets to "off")

### Backend changes

New endpoints:
- `POST /api/sessions/{name}/kill` -- sends Ctrl+C to Claude (must be `async def`, use `asyncio.sleep`)
- `POST /api/sessions/{name}/respawn` -- sends `claude --continue` Enter
- `DELETE /api/sessions/{name}` -- kills the tmux session entirely

New allowed tmux commands (add to `ALLOWED_COMMANDS` set at top of file):
- `kill-session` (new -- required for Dismiss flow)

Session validation changes:
- Replace `_is_claude_session(name)` with `_session_exists(name)` for kill/respawn/delete endpoints
- `_session_exists` checks if the tmux session exists at all (not just if Claude is running)
- Keep `_is_claude_session` for send/poll endpoints (those only make sense for active Claude sessions)

### Session discovery changes
- `discover_sessions()` returns ALL tmux sessions (not just ones running Claude)
- Each session gets a `state` field: `active` (pane_current_command == 'claude') or `dead` (anything else)
- Dead sessions are only included if the tmux session name doesn't start with `-` (same filter as active)
- No persistent state needed -- dead session detection is purely based on current tmux state. If the container restarts, it just re-reads tmux. Any tmux session not running Claude is treated as dead. Since this server is single-user (homelab), non-Claude tmux sessions showing as "dead" is acceptable.
- `state` field appears on both `/api/sessions` (list) and `/api/sessions/{name}` (detail) responses

### Frontend changes
- Session cards render differently based on `state` field from API
- Swipe gesture handler on `.session-card` elements (swipe left is context-sensitive based on state)
- "Kill" button (red, revealed on swipe left for active sessions)
- "Respawn" button (visible on dead session cards, not hidden behind swipe)
- "Dismiss" button (revealed on swipe left for dead sessions)
- Hidden sessions filtered from render, toggle to show

## Files modified/created

- `app.py` -- remove INDEX_HTML, add StaticFiles, add new endpoints, update discover_sessions, add `_session_exists`, add `kill-session` to ALLOWED_COMMANDS
- `static/index.html` -- extracted HTML
- `static/css/style.css` -- extracted CSS + dead session styles + swipe action styles
- `static/js/app.js` -- extracted JS + kill/respawn/dismiss/hide handlers + swipe gesture
- `Dockerfile` -- add COPY static/

## Testing

- Playwright: page loads from static files, no JS errors
- Playwright: sessions render, messages load (regression)
- Playwright: dead sessions show with muted styling and respawn button
- Playwright: kill endpoint returns success
- curl: POST /api/sessions/{name}/kill returns success
- curl: POST /api/sessions/{name}/respawn returns success
- curl: DELETE /api/sessions/{name} returns success
- Manual: kill a session, verify card goes dead, respawn it, verify Claude resumes conversation

# Copy from Replies + ntfy Notifications

## Goal

Add three copy mechanisms for assistant messages and per-session ntfy push notifications when Claude finishes working.

## Feature 1: Copy from Replies

### 1a. Copy entire message

- Each assistant message bubble gets a copy icon button in the bottom-right, next to the existing TTS button (copy at `right: 48px`, TTS stays at `right: 8px`).
- On tap: copies the full plaintext content to clipboard via `navigator.clipboard.writeText()`.
- Shows brief "Copied!" feedback via the existing upload toast element.
- Fallback for non-HTTPS contexts: create a temporary textarea, select, `document.execCommand('copy')`, remove textarea.

### 1b. Copy code blocks

- Each `<pre class="code-block">` element gets a small copy button in its top-right corner.
- On tap: copies only the code block's text content.
- Same "Copied!" toast feedback.
- The `.code-block` wrapper gets `position: relative`. The copy button uses `position: sticky; top: 6px; float: right;` so it doesn't scroll away with horizontal overflow and doesn't obscure content.

### 1c. Text selection

- The current CSS has no `user-select: none` on assistant messages, so native text selection (long-press on mobile) already works. Verify this with Playwright and ensure no future CSS breaks it.
- If any selection-blocking CSS is found, remove it from `.msg-assistant` and `.msg-assistant-text`.

### Implementation notes

- All changes are frontend-only (inline JS/CSS in `INDEX_HTML`).
- Copy buttons use SVG clipboard icon, consistent with existing icon style (stroke-based, 14px).
- Remember: JS inside Python triple-quoted strings requires `\\n` not `\n`, etc.

## Feature 2: ntfy Notifications

### User interaction

- Bell icon in the `#screenChat` header div, between the title and status dot.
- Tap toggles notifications for the current session.
- Visual states: outline bell SVG (off), filled bell SVG (on).
- State stored in `localStorage` key `ntfy_sessions` as a JSON object mapping session names to `true/false`. Defaults to off if key is missing.
- Bell state is read from localStorage and rendered when entering a session.

### Notification trigger

- Frontend tracks `previousStatus` per session (object mapping session name to last known status).
- On each poll response, compare `data.status` to `previousStatus[sessionName]`.
- If transition is `working` -> `idle` AND notifications are enabled for that session:
  - Extract last assistant message. Use `data.messages` if `has_changes` is true. Otherwise, use the last `.msg-assistant` element from the DOM as fallback.
  - Truncate to 200 chars at a word boundary, append "..." if truncated.
  - POST to ntfy.
- **Cooldown**: Don't send another notification for the same session within 30 seconds of the last one.
- Notifications only fire for the currently-viewed session (polling only runs for the active session).

### ntfy integration

- **Endpoint**: Route through backend proxy at `POST /api/ntfy` to avoid CORS issues.
- **Backend endpoint** (new, ~10 lines):
  - Accepts JSON `{ "title": "...", "body": "...", "tags": "robot" }`.
  - Forwards as POST to `http://host.docker.internal:8180/ai-hub` (internal ntfy, no Cloudflare tunnel needed).
  - Returns the ntfy response status.
- **Notification content**:
  - Title: `Claude finished in [session title]`
  - Body: Last assistant message, truncated to 200 chars at word boundary.
  - Tags: `robot`

### Backend changes

- One new endpoint: `POST /api/ntfy` -- a simple proxy that forwards to the internal ntfy server. This avoids CORS issues and keeps the ntfy endpoint off the public frontend.

## Files modified

- `/home/ubuntu/docker/claude-chat/app.py`:
  - CSS: copy button styles for messages and code blocks.
  - JS: copy handlers, bell toggle, ntfy notification logic, status tracking.
  - Python: one new `/api/ntfy` proxy endpoint.

## Testing

- Playwright: verify copy buttons exist on assistant messages and code blocks.
- Playwright: verify clicking copy button changes toast text to "Copied!".
- Playwright: verify bell icon exists in chat header and toggles on click.
- Playwright: verify localStorage is updated when bell is toggled.
- Playwright: verify text selection is not blocked on assistant messages (check computed `user-select` style).
- curl: verify `/api/ntfy` proxy endpoint forwards correctly.
- Manual: verify ntfy notification arrives when Claude session goes from working to idle.

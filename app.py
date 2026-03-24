import os
import re
import json
import glob
import hashlib
import secrets
import subprocess
import asyncio
import time
import httpx
import yaml
import aiosqlite
import uuid
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SOCKET = os.environ.get("TMUX_SOCKET", "/tmp/tmux-1000/default")

# ---------------------------------------------------------------------------
# Auth (PIN-based) -- set PIN_HASH env var to enable, omit to disable
# ---------------------------------------------------------------------------
PIN_HASH = os.environ.get("PIN_HASH", "")  # SHA-256 hex digest of the PIN
AUTH_ENABLED = bool(PIN_HASH)
valid_tokens: dict[str, float] = {}  # token -> creation timestamp
TOKEN_TTL = 86400  # 24 hours
TOKEN_MAX = 50
CLAUDE_DATA_DIR = os.environ.get("CLAUDE_DATA_DIR", "/claude-data")
LITELLM_URL = "http://host.docker.internal:4000/v1/chat/completions"

SESSION_NAME_RE = re.compile(r"^[a-zA-Z0-9_][a-zA-Z0-9_-]*$")

ALLOWED_COMMANDS = {
    "list-sessions",
    "list-panes",
    "capture-pane",
    "send-keys",
    "display-message",
    "kill-session",
    "set-option",
    "respawn-pane",
    "new-session",
}

# ---------------------------------------------------------------------------
# Message parsing
# ---------------------------------------------------------------------------
MARKERS = {
    "user":       re.compile(r"^❯\s*(.*)"),
    "assistant":  re.compile(r"^●\s*(.*)"),
    "status":     re.compile(r"^✻\s*(.*)"),
    "divider":    re.compile(r"^─{10,}"),
    "tool_result": re.compile(r"^\s*⎿\s*(.*)"),
}

TOOL_CALL_RE = re.compile(
    r"^●\s*(Bash|Read|Write|Edit|Grep|Glob|Agent|Skill|Explore|TaskCreate|TaskUpdate"
    r"|TaskList|TaskGet|TaskOutput|TaskStop|ToolSearch|NotebookEdit|WebFetch|WebSearch"
    r"|EnterPlanMode|ExitPlanMode|SendMessage|AskUserQuestion)\s*\("
)

# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------
http_client: httpx.AsyncClient | None = None
title_cache: dict[str, str] = {}
death_cache: dict[str, float] = {}
DB_PATH = os.path.join(os.environ.get("UPLOAD_DIR", "/uploads"), "claude-chat.db")
db: aiosqlite.Connection | None = None


# ---------------------------------------------------------------------------
# Structured Logging
# ---------------------------------------------------------------------------

class StructuredFormatter(logging.Formatter):
    """JSON-line formatter for structured log entries."""
    def format(self, record):
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec='milliseconds')
        entry = {
            "ts": ts,
            "level": record.levelname,
            "category": getattr(record, "category", "system"),
            "action": getattr(record, "action", "unknown"),
            "session": getattr(record, "session", None),
            "duration_ms": getattr(record, "duration_ms", None),
            "source": "backend",
            "request_id": getattr(record, "request_id", None),
            "connection_id": getattr(record, "connection_id", None),
            "meta": getattr(record, "meta", None),
        }
        return json.dumps({k: v for k, v in entry.items() if v is not None})


class LogRateLimiter:
    """Prevent log storms by batching high-frequency entries.
    Uses lazy emission: summary emitted on next call after window expires."""
    def __init__(self, window_sec=5, max_per_window=50):
        self.window_sec = window_sec
        self.max_per_window = max_per_window
        self.counts: dict[tuple, dict] = {}

    def check(self, category: str, action: str) -> tuple[bool, dict | None]:
        """Returns (should_log, summary_or_none)."""
        key = (category, action)
        now = time.time()
        summary = None

        if key in self.counts:
            bucket = self.counts[key]
            if now - bucket["start"] > self.window_sec:
                if bucket["suppressed"] > 0:
                    summary = {
                        "suppressed_count": bucket["suppressed"],
                        "window_sec": self.window_sec,
                    }
                self.counts[key] = {"start": now, "count": 1, "suppressed": 0}
                return True, summary
            else:
                bucket["count"] += 1
                if bucket["count"] > self.max_per_window:
                    bucket["suppressed"] += 1
                    return False, None
                return True, None
        else:
            self.counts[key] = {"start": now, "count": 1, "suppressed": 0}
            return True, None


_rate_limiter = LogRateLimiter()
_logger = logging.getLogger("claude-chat")
_logger.setLevel(logging.DEBUG)
_logger.propagate = False


def _setup_logging():
    """Configure file + stdout handlers. Called during lifespan startup."""
    log_dir = os.path.join(os.environ.get("UPLOAD_DIR", "/uploads"), "logs")
    os.makedirs(log_dir, exist_ok=True)

    formatter = StructuredFormatter()

    # Rotating file handler: 10MB x 10 = 100MB cap
    fh = RotatingFileHandler(
        os.path.join(log_dir, "claude-chat.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=9,
    )
    fh.setFormatter(formatter)
    _logger.addHandler(fh)

    # Stdout handler (Promtail picks this up for Loki)
    sh = logging.StreamHandler()
    sh.setFormatter(formatter)
    _logger.addHandler(sh)


def log(category: str, action: str, level: str = "INFO", session: str = None,
        duration_ms: int = None, request_id: str = None, connection_id: str = None,
        **meta):
    """Convenience wrapper for structured logging throughout the app."""
    should_log, summary = _rate_limiter.check(category, action)

    # Emit rate-limit summary from previous window if any
    if summary:
        _logger.log(logging.WARNING, "", extra={
            "category": category,
            "action": f"{action}_rate_limited",
            "session": None,
            "duration_ms": None,
            "request_id": None,
            "connection_id": None,
            "meta": summary,
        })

    if not should_log:
        return

    _logger.log(getattr(logging, level, logging.INFO), "", extra={
        "category": category,
        "action": action,
        "session": session,
        "duration_ms": duration_ms,
        "request_id": request_id,
        "connection_id": connection_id,
        "meta": meta if meta else None,
    })


async def _save_title(session_name: str, title: str):
    title_cache[session_name] = title
    await db.execute(
        "INSERT OR REPLACE INTO titles (session_name, title) VALUES (?, ?)",
        (session_name, title)
    )
    await db.commit()


async def _index_messages(session_name: str, messages: list[dict], chash: str):
    """Index messages for search. Idempotent via content_hash."""
    async with db.execute(
        "SELECT 1 FROM messages WHERE session_name = ? AND content_hash = ? LIMIT 1",
        (session_name, chash)
    ) as cursor:
        if await cursor.fetchone():
            return
    await db.execute("DELETE FROM messages WHERE session_name = ?", (session_name,))
    for m in messages:
        await db.execute(
            "INSERT INTO messages (session_name, role, content, tool, tool_results, ts, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_name, m["role"], m["content"], m.get("tool", ""),
             json.dumps(m.get("tool_results", [])), m.get("ts", 0), chash)
        )
    await db.commit()


async def init_db():
    global db
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS titles (
            session_name TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            updated_at INTEGER DEFAULT (strftime('%s', 'now'))
        );
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_name TEXT NOT NULL,
            title TEXT,
            preview TEXT,
            dismissed_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at INTEGER DEFAULT (strftime('%s', 'now'))
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_name TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            tool TEXT,
            tool_results TEXT,
            ts INTEGER,
            content_hash TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_name);
        CREATE INDEX IF NOT EXISTS idx_messages_content ON messages(content);
        CREATE INDEX IF NOT EXISTS idx_history_dismissed ON history(dismissed_at);
    """)
    await db.commit()


async def _migrate_json_to_sqlite():
    """One-time migration from JSON files to SQLite."""
    titles_file = os.path.join(os.environ.get("UPLOAD_DIR", "/uploads"), "titles.json")
    if os.path.exists(titles_file):
        try:
            with open(titles_file) as f:
                raw = json.load(f)
            for name, val in raw.items():
                title = val.get("title", val) if isinstance(val, dict) else val
                await db.execute(
                    "INSERT OR IGNORE INTO titles (session_name, title) VALUES (?, ?)",
                    (name, title)
                )
            await db.commit()
            os.rename(titles_file, titles_file + ".migrated")
            log("system", "db_migrate", source="titles.json", records=len(raw))
        except Exception:
            pass

    history_file = os.path.join(os.environ.get("UPLOAD_DIR", "/uploads"), "history.json")
    if os.path.exists(history_file):
        try:
            with open(history_file) as f:
                entries = json.load(f)
            for e in entries:
                await db.execute(
                    "INSERT INTO history (session_name, title, preview, dismissed_at) VALUES (?, ?, ?, ?)",
                    (e.get("name", ""), e.get("title", ""), e.get("preview", ""), e.get("dismissed_at", 0))
                )
            await db.commit()
            os.rename(history_file, history_file + ".migrated")
            log("system", "db_migrate", source="history.json", records=len(entries))
        except Exception:
            pass

    settings_file = os.path.join(os.environ.get("UPLOAD_DIR", "/uploads"), "settings.json")
    if os.path.exists(settings_file):
        try:
            with open(settings_file) as f:
                data = json.load(f)
            for key, val in data.items():
                await db.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                    (key, json.dumps(val))
                )
            await db.commit()
            os.rename(settings_file, settings_file + ".migrated")
            log("system", "db_migrate", source="settings.json", records=len(data))
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    _setup_logging()
    log("system", "startup", auth_enabled=AUTH_ENABLED,
        upload_dir=os.environ.get("UPLOAD_DIR", "/uploads"),
        claude_data_dir=CLAUDE_DATA_DIR)
    http_client = httpx.AsyncClient(timeout=10.0)
    await init_db()
    await _migrate_json_to_sqlite()
    # Load titles into in-memory cache from SQLite
    async with db.execute("SELECT session_name, title FROM titles") as cursor:
        async for row in cursor:
            title_cache[row["session_name"]] = row["title"]
    log("system", "startup_complete", titles_loaded=len(title_cache))
    yield
    log("system", "shutdown")
    if db:
        await db.close()
    await http_client.aclose()


app = FastAPI(title="Claude Chat", lifespan=lifespan)


class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response


class AuthMiddleware:
    """Raw ASGI middleware — require Bearer token on /api/ routes.
    Uses raw ASGI instead of BaseHTTPMiddleware to support WebSocket."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if not AUTH_ENABLED or scope["type"] == "websocket":
            await self.app(scope, receive, send)
            return

        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        if not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return
        if path in ("/api/auth", "/api/auth/check") or path == "/health":
            await self.app(scope, receive, send)
            return

        # Check Bearer token from headers
        headers = dict(scope.get("headers", []))
        auth_header = (headers.get(b"authorization", b"")).decode()
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if token in valid_tokens and (time.time() - valid_tokens[token]) < TOKEN_TTL:
                await self.app(scope, receive, send)
                return
            elif token in valid_tokens:
                del valid_tokens[token]
                log("auth", "auth_token_validated", level="WARNING", result="expired")

        log("auth", "auth_token_validated", level="WARNING", result="invalid")
        response = JSONResponse({"detail": "Unauthorized"}, status_code=401)
        await response(scope, receive, send)


app.add_middleware(AuthMiddleware)
app.add_middleware(NoCacheStaticMiddleware)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log every HTTP request with timing."""
    req_id = str(uuid.uuid4())[:8]
    request.state.request_id = req_id
    t0 = time.perf_counter()
    response = await call_next(request)
    elapsed = int((time.perf_counter() - t0) * 1000)
    # Skip static files, health checks, and log endpoint from logging
    path = request.url.path
    if not path.startswith("/static/") and path not in ("/health", "/api/log"):
        log("http", "request", request_id=req_id,
            method=request.method, path=path,
            status=response.status_code, duration_ms=elapsed)
    return response

app.mount("/static", StaticFiles(directory="static"), name="static")

# ---------------------------------------------------------------------------
# WebSocket connection manager
# ---------------------------------------------------------------------------

class ConnectionManager:
    def __init__(self):
        self.connections: dict[str, list[WebSocket]] = {}

    async def connect(self, session_name: str, ws: WebSocket):
        await ws.accept()
        if session_name not in self.connections:
            self.connections[session_name] = []
        self.connections[session_name].append(ws)

    def disconnect(self, session_name: str, ws: WebSocket):
        if session_name in self.connections:
            self.connections[session_name] = [c for c in self.connections[session_name] if c is not ws]
            if not self.connections[session_name]:
                del self.connections[session_name]

ws_manager = ConnectionManager()

# ---------------------------------------------------------------------------
# tmux helpers
# ---------------------------------------------------------------------------

def run_tmux(*args: str) -> str:
    """Run a tmux subcommand via the host socket. Whitelist-enforced."""
    if not args:
        raise RuntimeError("run_tmux called with no arguments")
    if args[0] not in ALLOWED_COMMANDS:
        raise RuntimeError(f"tmux command not allowed: {args[0]}")
    cmd = ["tmux", "-S", SOCKET] + list(args)
    t0 = time.perf_counter()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = int((time.perf_counter() - t0) * 1000)
    if result.returncode != 0:
        log("tmux", "tmux_error", level="ERROR",
            command=args[0], args=list(args[1:4]),
            returncode=result.returncode, stderr=result.stderr.strip()[:200],
            duration_ms=elapsed)
        raise RuntimeError(
            f"tmux {args[0]} failed (rc={result.returncode}): {result.stderr.strip()}"
        )
    log("tmux", "tmux_command", command=args[0], duration_ms=elapsed,
        output_len=len(result.stdout))
    return result.stdout


def validate_session_name(name: str) -> None:
    if not SESSION_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail=f"Invalid session name: {name!r}")


# ---------------------------------------------------------------------------
# Session discovery
# ---------------------------------------------------------------------------

def discover_sessions() -> list[dict]:
    """Return list of all tmux sessions with a state field.

    state='active' if pane_current_command == 'claude', else state='dead'.
    Sessions with names starting with '-' are always skipped.
    """
    try:
        raw = run_tmux(
            "list-panes", "-a",
            "-F", "#{session_name}\t#{pane_pid}\t#{pane_current_command}\t#{pane_current_path}\t#{pane_dead}"
        )
    except RuntimeError:
        log("session", "session_discovery", level="ERROR", error="tmux list-panes failed")
        return []

    sessions = []
    seen_pids: set[str] = set()
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        sname, pid_str, cmd, cwd, pane_dead = parts[0], parts[1], parts[2], parts[3], parts[4]
        # Skip names starting with '-' -- they break tmux -t flag parsing
        if sname.startswith("-"):
            continue
        # Skip sessions sharing a PID with an already-seen session
        # (happens when worktree agents create duplicate tmux sessions)
        if cmd == "claude" and pid_str in seen_pids:
            continue
        if cmd == "claude":
            seen_pids.add(pid_str)

        # Active only if claude is running AND pane is alive
        state = "active" if (cmd == "claude" and pane_dead != "1") else "dead"

        meta: dict = {}
        if state == "active":
            try:
                pid = int(pid_str)
                meta_path = os.path.join(CLAUDE_DATA_DIR, "sessions", f"{pid}.json")
                with open(meta_path) as f:
                    meta = json.load(f)
            except Exception:
                pass  # soft failure -- metadata is optional

        sessions.append({
            "name": sname,
            "pid": pid_str,
            "cwd": meta.get("cwd", cwd),
            "session_id": meta.get("sessionId", ""),
            "started_at": meta.get("startedAt", 0),
            "state": state,
        })

    active = sum(1 for s in sessions if s["state"] == "active")
    dead = sum(1 for s in sessions if s["state"] == "dead")
    log("session", "session_discovery", total=len(sessions), active=active, dead=dead)
    return sessions


def _is_claude_session(name: str) -> bool:
    """Return True if the named session has a pane running 'claude'."""
    for s in discover_sessions():
        if s["name"] == name and s.get("state") == "active":
            return True
    return False


def _session_exists(name: str) -> bool:
    """Return True if a tmux session with this name exists (regardless of what's running)."""
    try:
        raw = run_tmux("list-sessions", "-F", "#{session_name}")
        return name in raw.splitlines()
    except RuntimeError:
        return False


# ---------------------------------------------------------------------------
# Message parsing
# ---------------------------------------------------------------------------

def parse_messages(output: str) -> list[dict]:
    """
    Parse tmux capture-pane output into structured message dicts.

    Roles: user | assistant | tool
    Tool calls are collapsed into a single tool message with a tool_results list.
    """
    lines = output.splitlines()
    messages: list[dict] = []
    current: dict | None = None
    in_tool: bool = False

    def flush():
        nonlocal current, in_tool
        if current:
            # trim trailing whitespace from content
            current["content"] = current["content"].rstrip()
            messages.append(current)
        current = None
        in_tool = False

    for line in lines:
        # ── divider resets context
        if MARKERS["divider"].match(line):
            flush()
            continue

        # ── tool result line (⎿) -- attach to current or most recent tool message
        tool_result_m = MARKERS["tool_result"].match(line)
        if tool_result_m:
            result_text = tool_result_m.group(1).strip()
            # Check current first (unflushed tool message), then search flushed
            if current and current["role"] == "tool":
                if result_text:
                    current.setdefault("tool_results", []).append(result_text)
                # Stay in tool mode so subsequent lines don't leak into content
            else:
                for msg in reversed(messages):
                    if msg["role"] == "tool":
                        if result_text:
                            msg.setdefault("tool_results", []).append(result_text)
                        break
                in_tool = False
            continue

        # ── user message
        user_m = MARKERS["user"].match(line)
        if user_m:
            flush()
            text = user_m.group(1).strip()
            current = {"role": "user", "content": text, "ts": int(time.time() * 1000)}
            in_tool = False
            continue

        # ── tool call (● Bash(...) etc.)
        if TOOL_CALL_RE.match(line):
            flush()
            tool_name_m = re.match(r"^●\s*(\w+)\s*\((.*)$", line)
            tool_name = tool_name_m.group(1) if tool_name_m else "Tool"
            tool_args = tool_name_m.group(2).rstrip(")").strip() if tool_name_m else ""
            current = {
                "role": "tool",
                "tool": tool_name,
                "content": tool_args,
                "tool_results": [],
                "ts": int(time.time() * 1000),
            }
            in_tool = True
            continue

        # ── assistant message (● but not a tool call)
        assistant_m = MARKERS["assistant"].match(line)
        if assistant_m:
            # Always start a new assistant message when we see ● (not a tool call)
            # Even if in_tool is True, this is a new assistant response
            flush()
            text = assistant_m.group(1).strip()
            current = {"role": "assistant", "content": text, "ts": int(time.time() * 1000)}
            in_tool = False
            continue

        # ── status line (✻) -- skip
        if MARKERS["status"].match(line):
            continue

        # ── continuation line
        if current is not None:
            stripped = line.rstrip()
            if in_tool:
                # skip continuation lines inside tool calls
                continue
            # append to current message content
            current["content"] += "\n" + stripped

    flush()

    # filter out empty messages and misclassified tool output
    # (Claude Code wraps lines at narrow pane widths, breaking tool markers)
    _TOOL_LEAK_RE = re.compile(
        r"^(Updated?|Read?|Write?|Bash?|Edit|Grep?|Glob?|Explore|"
        r"Agent|Skill|Task\w*|Tool\w*|Notebook\w*|Search?|Web\w*|Send\w*)\("
    )
    _BG_CMD_RE = re.compile(r"Background command ")
    _WIBBLE_RE = re.compile(r"^\w+ing(?:\.\.\.|…)\s*\(\d+s\)")

    def _is_visible(m):
        if not m.get("content", "").strip() and m["role"] != "tool":
            return False
        c = m["content"].strip()
        # Filter background command messages regardless of role
        if _BG_CMD_RE.search(c):
            return False
        # Filter "Wibbling... (0s)" style Claude Code status messages
        if _WIBBLE_RE.match(c):
            return False
        if m["role"] == "assistant":
            if _TOOL_LEAK_RE.match(c):
                return False
        # Filter user messages that are ONLY background command text
        # (can happen when bg cmd output gets parsed as continuation of user msg)
        if m["role"] == "user":
            # Check each line -- if ALL non-empty lines are bg cmd or wibble, hide it
            lines = [l.strip() for l in c.split("\n") if l.strip()]
            if lines and all(_BG_CMD_RE.search(l) or _WIBBLE_RE.match(l) for l in lines):
                return False
        return True

    return [m for m in messages if _is_visible(m)]


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def content_hash(text: str) -> str:
    tail = text[-200:] if len(text) > 200 else text
    return hashlib.md5(tail.encode()).hexdigest()[:8]


def time_ago(epoch_ms: int) -> str:
    if not epoch_ms:
        return "unknown"
    delta = time.time() - epoch_ms / 1000
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"


async def generate_title(session_name: str, messages: list[dict]) -> tuple[str, list[str]]:
    """Generate a short title and tags from the first 3 user messages via LiteLLM."""
    user_msgs = [m for m in messages if m["role"] == "user"][:3]
    if not user_msgs:
        return session_name

    snippet = " | ".join(m["content"][:200] for m in user_msgs)
    try:
        resp = await http_client.post(
            LITELLM_URL,
            json={
                "model": "glm-4.5-air",
                "max_tokens": 20,
                "messages": [
                    {"role": "system", "content": "Generate a short title (max 6 words) for this AI coding conversation. Return ONLY the title, nothing else."},
                    {"role": "user", "content": snippet},
                ],
            },
            timeout=8.0,
        )
        resp.raise_for_status()
        title = resp.json()["choices"][0]["message"]["content"].strip().strip('"\'')[:60]
        return title or session_name
    except Exception:
        return user_msgs[0]["content"][:50] if user_msgs else session_name


async def _refresh_title(session_name: str, messages: list[dict]) -> None:
    """Background task: generate title, then cache it."""
    if session_name in title_cache:
        return
    title = await generate_title(session_name, messages)
    await _save_title(session_name, title)


COST_RE = re.compile(r"\$\s*(\d+\.?\d*)")
CTX_RE = re.compile(r"CTX\s+(\d+)%")
USAGE_RE = re.compile(r"5h\s+(\d+)%.*?7d\s+(\d+)%")


def extract_cost_info(raw: str) -> dict | None:
    """Extract cost/context info from last lines of pane output."""
    lines = raw.strip().splitlines()
    tail = lines[-50:] if len(lines) > 50 else lines
    cost = None
    ctx_pct = None
    usage_5h = None
    usage_7d = None
    for line in reversed(tail):
        if cost is None:
            m = COST_RE.search(line)
            if m:
                cost = float(m.group(1))
        if ctx_pct is None:
            m = CTX_RE.search(line)
            if m:
                ctx_pct = int(m.group(1))
        if usage_5h is None:
            m = USAGE_RE.search(line)
            if m:
                usage_5h = int(m.group(1))
                usage_7d = int(m.group(2))
    if cost is not None or ctx_pct is not None or usage_5h is not None:
        return {"cost": cost, "context_pct": ctx_pct, "usage_5h": usage_5h, "usage_7d": usage_7d}
    return None


STATUS_BAR_RE = re.compile(
    r"(RAM\s+\d+%|CPU\s+\d+%|CTX\s+\d+%|tokens$|⏵⏵|bypass permissions|shift\+tab"
    r"|accept edits|don't ask|current:\s+\d|latest:\s+\d|\d+\s+tokens$"
    r"|\d+\s+shell|Press up to edit)"
)

def get_session_status(raw: str) -> str:
    """Derive session status from last few lines of capture.

    Priority: waiting_input > working > idle.
    Key insight: the ❯ prompt only appears when Claude is idle.
    If there's no ❯ in recent output, Claude is still working.
    """
    lines = [l for l in raw.splitlines() if l.strip()]
    # Filter out Claude Code status bar lines at the bottom
    content_lines = [l for l in lines if not STATUS_BAR_RE.search(l)]
    if not content_lines:
        return "idle"

    # Check last ~15 content lines for the ❯ prompt
    tail_lines = content_lines[-15:]
    tail_text = "\n".join(cl.strip() for cl in tail_lines)

    # 1. Check for AskUserQuestion / interactive prompts (highest priority)
    # Must match the full Claude Code UI chrome, not just substrings in message content.
    # AskUserQuestion shows: "Enter to select · ↑/↓ to navigate · Esc to cancel"
    if re.search(r"Enter to select.*navigate.*cancel", tail_text, re.DOTALL):
        return "waiting_input"
    if re.search(r"\([Yy]/[Nn]\)", tail_text):
        return "waiting_input"

    # 2. Check for explicit working indicators
    for cl in tail_lines[-8:]:
        stripped = cl.strip()
        # Active generation: "● Verbing…" or "● Verbing... (Ns)"
        if re.match(r"^●\s+\S+[….]", stripped):
            return "working"
        # Tool execution in progress
        if stripped.startswith("⎿  Running"):
            return "working"
        # Active tool call (● ToolName(...))
        if TOOL_CALL_RE.match(stripped):
            return "working"

    # 3. Check if ❯ prompt is visible -- if yes, Claude is idle
    has_prompt = False
    for cl in tail_lines:
        stripped = cl.strip()
        if stripped == "❯" or stripped.startswith("❯ "):
            has_prompt = True
            break
    if has_prompt:
        return "idle"

    # 4. Check for divider/status lines as last content (idle after completion)
    last_content = content_lines[-1].strip()
    if MARKERS["status"].match(last_content) or MARKERS["divider"].match(last_content):
        return "idle"

    # 5. No ❯ prompt found, no explicit idle indicator → still working
    return "working"


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

class AuthBody(BaseModel):
    pin: str


@app.post("/api/auth")
async def auth_login(body: AuthBody):
    if not AUTH_ENABLED:
        return {"token": "auth-disabled"}
    pin_hash = hashlib.sha256(body.pin.encode()).hexdigest()
    if pin_hash != PIN_HASH:
        log("auth", "auth_attempt", level="WARNING", success=False)
        raise HTTPException(status_code=401, detail="Invalid PIN")
    token = secrets.token_hex(32)
    log("auth", "auth_attempt", success=True)
    log("auth", "auth_token_issued")
    valid_tokens[token] = time.time()
    # Prune oldest if over limit
    if len(valid_tokens) > TOKEN_MAX:
        oldest = sorted(valid_tokens, key=valid_tokens.get)
        to_prune = oldest[:len(valid_tokens) - TOKEN_MAX]
        for old in to_prune:
            del valid_tokens[old]
        log("auth", "auth_token_pruned", pruned=len(to_prune))
    return {"token": token}


@app.get("/api/auth/check")
async def auth_check(request: Request):
    if not AUTH_ENABLED:
        return {"authenticated": True}
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if token in valid_tokens and (time.time() - valid_tokens[token]) < TOKEN_TTL:
            return {"authenticated": True}
    raise HTTPException(status_code=401, detail="Unauthorized")


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    try:
        run_tmux("list-sessions")
        tmux_ok = True
        sessions = discover_sessions()
        session_count = len(sessions)
    except Exception as e:
        tmux_ok = False
        session_count = 0
    log("system", "health_check", tmux_ok=tmux_ok, session_count=session_count)
    return {"status": "ok", "tmux": tmux_ok, "claude_sessions": session_count}


@app.get("/manifest.json")
def manifest():
    return JSONResponse({
        "name": "Claude Voice Chat",
        "short_name": "ClaudeChat",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0A0A0A",
        "theme_color": "#0A0A0A",
        "icons": [
            {"src": "/static/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any maskable"},
        ],
    })


@app.get("/")
def index():
    return FileResponse(
        "static/index.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )


@app.get("/api/sessions")
async def list_sessions():
    sessions = discover_sessions()
    result = []
    for s in sessions:
        name = s["name"]

        # Track death time
        if s["state"] == "dead":
            if name not in death_cache:
                death_cache[name] = time.time()
        elif name in death_cache:
            del death_cache[name]

        if s["state"] == "dead":
            preview = ""
            cost_info = None
            try:
                raw = run_tmux("capture-pane", "-t", name, "-p", "-J", "-S", "-50")
                msgs = parse_messages(raw)
                asst = [m for m in msgs if m["role"] == "assistant"]
                if asst:
                    preview = asst[-1]["content"][:120]
                cost_info = extract_cost_info(raw)
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
                "cost_info": cost_info,
            })
            continue

        try:
            raw = run_tmux("capture-pane", "-t", name, "-p", "-J", "-S", "-100")
        except RuntimeError:
            raw = ""

        messages = parse_messages(raw)
        title = title_cache.get(name, name)

        # preview: last assistant message
        asst_msgs = [m for m in messages if m["role"] == "assistant"]
        preview = asst_msgs[-1]["content"][:120] if asst_msgs else ""

        result.append({
            "name": name,
            "pid": s["pid"],
            "title": title,
            "cwd": s["cwd"],
            "last_activity": time_ago(s.get("started_at", 0)),
            "status": get_session_status(raw),
            "state": "active",
            "preview": preview,
            "cost_info": extract_cost_info(raw),
        })

    return result


@app.get("/api/sessions/{name}")
async def get_session(name: str, lines: int = 10000):
    validate_session_name(name)
    lines = min(max(lines, 1), 50000)
    if not _is_claude_session(name):
        raise HTTPException(status_code=404, detail="Session not found or not a Claude session")

    raw = run_tmux("capture-pane", "-t", name, "-p", "-J", "-S", f"-{lines}")
    messages = parse_messages(raw)
    title = title_cache.get(name, name)
    chash = content_hash(raw)
    status = get_session_status(raw)
    cost_info = extract_cost_info(raw)

    asyncio.create_task(_index_messages(name, messages, chash))

    log("message", "message_parse", session=name, count=len(messages),
        content_hash=chash, status=status)
    return {
        "name": name,
        "title": title,
        "status": status,
        "messages": messages,
        "content_hash": chash,
        "message_count": len(messages),
        "waiting_input": status == "waiting_input",
        "cost_info": cost_info,
    }


@app.get("/api/sessions/{name}/export")
async def export_session(name: str, fmt: str = "markdown"):
    validate_session_name(name)
    if not _is_claude_session(name):
        raise HTTPException(status_code=404, detail="Session not found")

    raw = run_tmux("capture-pane", "-t", name, "-p", "-J", "-S", "-10000")
    messages = parse_messages(raw)
    title = title_cache.get(name, name)

    if fmt == "json":
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


WHISPER_URL = os.environ.get("WHISPER_URL", "http://host.docker.internal:2022")


@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...)):
    """Proxy audio to Whisper STT server."""
    audio_data = await file.read()
    if len(audio_data) == 0:
        raise HTTPException(status_code=400, detail="Empty audio file")
    try:
        r = await http_client.post(
            f"{WHISPER_URL}/asr",
            params={"task": "transcribe", "language": "en", "output": "json"},
            files={"audio_file": (file.filename or "audio.webm", audio_data, file.content_type or "audio/webm")},
            timeout=30.0,
        )
        r.raise_for_status()
        return r.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Whisper timed out")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Whisper error: {str(e)}")


class SendBody(BaseModel):
    text: str


@app.post("/api/sessions/{name}/send")
async def send_to_session(name: str, body: SendBody):
    validate_session_name(name)
    if not _is_claude_session(name):
        raise HTTPException(status_code=404, detail="Session not found or not a Claude session")

    text = body.text
    if not text:
        raise HTTPException(status_code=400, detail="text must not be empty")

    # Exit copy/scroll mode if active, then small delay so Escape doesn't
    # combine with first character into an escape sequence
    run_tmux("send-keys", "-t", name, "Escape")
    await asyncio.sleep(0.05)
    # Send the text literally (prevents key injection), then Enter separately
    run_tmux("send-keys", "-t", name, "-l", text)
    run_tmux("send-keys", "-t", name, "Enter")

    log("message", "message_send", session=name, text_length=len(text))
    return {"sent": True, "session": name}


ALLOWED_KEYS = {"Escape", "Tab", "BTab", "C-c", "Up", "Down", "Enter", "C-d", "C-u"}


@app.post("/api/sessions/{name}/key")
async def send_key(name: str, body: dict):
    """Send a special key (Escape, Tab, etc.) to the tmux session."""
    validate_session_name(name)
    if not _is_claude_session(name):
        raise HTTPException(status_code=404, detail="Session not found")
    key = body.get("key", "")
    if key not in ALLOWED_KEYS:
        raise HTTPException(status_code=400, detail=f"Key not allowed: {key}")
    run_tmux("send-keys", "-t", name, key)
    log("message", "key_send", session=name, key=key)
    return {"sent": True, "key": key}


@app.post("/api/sessions/{name}/kill")
async def kill_session_endpoint(name: str):
    """Kill Claude in the tmux pane. Pane stays alive for respawn."""
    validate_session_name(name)
    if not _session_exists(name):
        raise HTTPException(status_code=404, detail="Session not found")
    if not _is_claude_session(name):
        return {"killed": True, "state": "dead"}

    # CRITICAL: set remain-on-exit so pane survives after Claude exits
    run_tmux("set-option", "-t", name, "remain-on-exit", "on")

    # Escape any menus, Ctrl+C to cancel, then /exit
    run_tmux("send-keys", "-t", name, "Escape")
    await asyncio.sleep(0.2)
    run_tmux("send-keys", "-t", name, "C-c")
    await asyncio.sleep(1)
    run_tmux("send-keys", "-t", name, "C-c")
    await asyncio.sleep(0.5)
    run_tmux("send-keys", "-t", name, "C-u")
    run_tmux("send-keys", "-t", name, "-l", "/exit")
    run_tmux("send-keys", "-t", name, "Enter")
    await asyncio.sleep(2)

    still_active = _is_claude_session(name)
    if still_active:
        run_tmux("send-keys", "-t", name, "C-d")
        await asyncio.sleep(1)
        still_active = _is_claude_session(name)

    state = "active" if still_active else "dead"
    log("session", "session_kill", session=name, success=not still_active, state=state)
    return {"killed": not still_active, "state": state}


@app.post("/api/sessions/{name}/respawn")
async def respawn_session(name: str):
    """Respawn Claude in an existing tmux session."""
    validate_session_name(name)
    if not _session_exists(name):
        raise HTTPException(status_code=404, detail="Session not found")
    if _is_claude_session(name):
        return {"respawned": False, "message": "Session already has Claude running"}

    # respawn-pane with full path (respawn-pane uses a bare shell without user PATH)
    run_tmux("respawn-pane", "-t", name, "-k", "/home/ubuntu/.local/bin/claude --continue")
    log("session", "session_respawn", session=name)
    return {"respawned": True}


@app.get("/api/sessions/{name}/health")
async def session_health(name: str):
    """Check if a session is healthy and Claude is ready for input."""
    validate_session_name(name)
    if not _session_exists(name):
        return {"exists": False, "ready": False, "status": "not_found"}

    is_claude = _is_claude_session(name)
    if not is_claude:
        return {"exists": True, "ready": False, "status": "dead", "message": "Claude is not running"}

    try:
        raw = run_tmux("capture-pane", "-t", name, "-p", "-J", "-S", "-20")
    except RuntimeError:
        return {"exists": True, "ready": False, "status": "error", "message": "Cannot read pane"}

    status = get_session_status(raw)

    if "trust this folder" in raw.lower() or "Enter to confirm" in raw:
        return {"exists": True, "ready": False, "status": "trust_prompt", "message": "Accepting workspace trust..."}

    ready = status in ("idle", "waiting_input")
    return {
        "exists": True,
        "ready": ready,
        "status": status,
        "message": "Claude is ready" if ready else "Claude is starting...",
    }


@app.delete("/api/sessions/{name}")
async def dismiss_session(name: str):
    """Kill the tmux session entirely.

    Uses kill-session directly without sending C-c first.
    Sending C-c before kill is dangerous when sessions share a Claude process
    (the C-c kills Claude in all sessions sharing that PID).
    kill-session removes just this tmux session cleanly.
    """
    validate_session_name(name)
    if not _session_exists(name):
        raise HTTPException(status_code=404, detail="Session not found")

    # Save session info to history before killing
    session_title = title_cache.get(name, name)
    preview = ""
    try:
        raw = run_tmux("capture-pane", "-t", name, "-p", "-J", "-S", "-50")
        msgs = parse_messages(raw)
        asst = [m for m in msgs if m["role"] == "assistant"]
        if asst:
            preview = asst[-1]["content"][:200]
    except RuntimeError:
        pass
    await _add_to_history(name, session_title, preview)

    run_tmux("kill-session", "-t", name)
    log("session", "session_dismiss", session=name)
    return {"dismissed": True}


@app.put("/api/sessions/{name}/title")
async def set_session_title(name: str, body: dict):
    """Set a custom title for a session."""
    validate_session_name(name)
    title = (body.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title must not be empty")
    await _save_title(name, title[:60])
    log("session", "title_set", session=name, title_length=len(title))
    return {"title": title_cache[name]}


@app.get("/api/sessions/{name}/poll")
async def poll_session(name: str, hash: str = "", lines: int = 10000):
    validate_session_name(name)
    lines = min(max(lines, 1), 50000)
    if not _is_claude_session(name):
        raise HTTPException(status_code=404, detail="Session not found or not a Claude session")

    raw = run_tmux("capture-pane", "-t", name, "-p", "-J", "-S", f"-{lines}")
    chash = content_hash(raw)
    if hash and hash != chash:
        log("message", "message_hash_change", session=name,
            old_hash=hash, new_hash=chash)
    status = get_session_status(raw)
    cost_info = extract_cost_info(raw)

    if hash and hash == chash:
        # no changes
        return {
            "has_changes": False,
            "content_hash": chash,
            "status": status,
            "waiting_input": status == "waiting_input",
            "cost_info": cost_info,
        }

    messages = parse_messages(raw)
    asyncio.create_task(_index_messages(name, messages, chash))
    return {
        "has_changes": True,
        "content_hash": chash,
        "status": status,
        "messages": messages,
        "waiting_input": status == "waiting_input",
        "cost_info": cost_info,
    }


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@app.websocket("/api/sessions/{name}/ws")
async def session_websocket(ws: WebSocket, name: str):
    token = ws.query_params.get("token", "")
    if AUTH_ENABLED and token not in valid_tokens:
        await ws.close(code=4001, reason="Unauthorized")
        return

    validate_session_name(name)
    await ws_manager.connect(name, ws)

    try:
        last_hash = ""
        while True:
            try:
                raw = run_tmux("capture-pane", "-t", name, "-p", "-J", "-S", "-10000")
            except RuntimeError:
                await ws.send_json({"type": "session_dead"})
                break

            chash = content_hash(raw)
            status = get_session_status(raw)
            cost_info = extract_cost_info(raw)

            if chash != last_hash:
                messages = parse_messages(raw)
                await ws.send_json({
                    "type": "update",
                    "has_changes": True,
                    "content_hash": chash,
                    "status": status,
                    "messages": messages,
                    "waiting_input": status == "waiting_input",
                    "cost_info": cost_info,
                })
                last_hash = chash
            else:
                await ws.send_json({
                    "type": "status",
                    "has_changes": False,
                    "content_hash": chash,
                    "status": status,
                    "waiting_input": status == "waiting_input",
                    "cost_info": cost_info,
                })

            try:
                await asyncio.wait_for(ws.receive_text(), timeout=1.5)
            except asyncio.TimeoutError:
                pass
            except WebSocketDisconnect:
                break
    finally:
        ws_manager.disconnect(name, ws)


# ---------------------------------------------------------------------------
# File upload
# ---------------------------------------------------------------------------

UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "/uploads")


@app.post("/api/upload/{session_name}")
async def upload_file(session_name: str, file: UploadFile = File(...)):
    """Upload a file and send a reference message to the Claude session."""
    validate_session_name(session_name)
    if not _is_claude_session(session_name):
        raise HTTPException(status_code=404, detail="Session not found")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    safe_name = re.sub(r'[^a-zA-Z0-9._-]', '_', file.filename or 'upload')
    filename = f"{int(time.time())}_{safe_name}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 10MB)")

    with open(filepath, "wb") as f:
        f.write(content)

    host_path = f"/srv/appdata/claude-chat/uploads/{filename}"

    return {"uploaded": True, "filename": filename, "path": host_path}


# ---------------------------------------------------------------------------
# Uploaded image serving
# ---------------------------------------------------------------------------

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
IMAGE_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


@app.get("/api/uploads/{filename}")
async def serve_upload(filename: str):
    """Serve an uploaded image file. Only image types are allowed."""
    # Validate filename to prevent path traversal attacks
    safe = os.path.basename(filename)
    if safe != filename or ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    ext = os.path.splitext(safe)[1].lower()
    if ext not in IMAGE_EXTENSIONS:
        raise HTTPException(status_code=403, detail="Only image files can be served")

    filepath = os.path.join(UPLOAD_DIR, safe)
    if not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        filepath,
        media_type=IMAGE_CONTENT_TYPES.get(ext, "application/octet-stream"),
        headers={"Cache-Control": "public, max-age=86400"},
    )


# ---------------------------------------------------------------------------
# Session history
# ---------------------------------------------------------------------------

async def _add_to_history(name: str, title: str, preview: str):
    await db.execute(
        "INSERT INTO history (session_name, title, preview, dismissed_at) VALUES (?, ?, ?, ?)",
        (name, title, preview[:200], int(time.time() * 1000))
    )
    await db.execute("""
        DELETE FROM history WHERE id NOT IN (
            SELECT id FROM history ORDER BY dismissed_at DESC LIMIT 50
        )
    """)
    await db.commit()


@app.get("/api/history")
async def get_history():
    async with db.execute(
        "SELECT session_name as name, title, preview, dismissed_at FROM history ORDER BY dismissed_at DESC LIMIT 20"
    ) as cursor:
        return [dict(row) for row in await cursor.fetchall()]


CHROMA_URL = "http://host.docker.internal:8200"
CHROMA_COLLECTION_ID = "2b629115-e79e-4de9-a9ff-3e5a7e92e12c"


@app.get("/api/search")
async def search_messages(q: str = "", limit: int = 20):
    if not q or len(q) < 2:
        return {"results": []}

    results = []

    # Primary: search ChromaDB session logs (7k+ chunks of historical sessions)
    try:
        chroma_resp = await http_client.post(
            f"{CHROMA_URL}/api/v2/tenants/default_tenant/databases/default_database"
            f"/collections/{CHROMA_COLLECTION_ID}/get",
            json={
                "where_document": {"$contains": q},
                "limit": limit,
                "include": ["documents", "metadatas"],
            },
            timeout=5.0,
        )
        if chroma_resp.status_code == 200:
            data = chroma_resp.json()
            seen = set()
            for i, doc_id in enumerate(data.get("ids", [])):
                meta = data["metadatas"][i] if data.get("metadatas") else {}
                doc = data["documents"][i] if data.get("documents") else ""
                session_id = meta.get("session_id", "")[:12]
                # Deduplicate by session (multiple chunks per session)
                if session_id in seen:
                    continue
                seen.add(session_id)
                # Extract a relevant snippet around the query
                doc_lower = doc.lower()
                q_lower = q.lower()
                idx = doc_lower.find(q_lower)
                if idx >= 0:
                    start = max(0, idx - 40)
                    snippet = doc[start:start + 150]
                else:
                    snippet = doc[:150]
                results.append({
                    "session": meta.get("session_id", ""),
                    "session_title": meta.get("first_prompt", "")[:60],
                    "role": "session",
                    "snippet": snippet,
                    "ts": 0,
                    "project": meta.get("project_path", ""),
                    "source": "history",
                })
    except Exception:
        pass

    # Secondary: search current session messages in SQLite
    try:
        async with db.execute("""
            SELECT m.session_name, m.role, m.content, m.ts,
                   t.title as session_title
            FROM messages m
            LEFT JOIN titles t ON t.session_name = m.session_name
            WHERE m.content LIKE ?
            ORDER BY m.ts DESC
            LIMIT ?
        """, (f"%{q}%", limit)) as cursor:
            for row in await cursor.fetchall():
                results.append({
                    "session": row["session_name"],
                    "session_title": row["session_title"] or row["session_name"],
                    "role": row["role"],
                    "snippet": row["content"][:150],
                    "ts": row["ts"],
                    "source": "active",
                })
    except Exception:
        pass

    return {"results": results[:limit]}


# ---------------------------------------------------------------------------
# Server-side settings (synced across devices)
# ---------------------------------------------------------------------------
SYNCED_KEYS = {
    "pinned_sessions", "session_folders", "hidden_sessions",
    "ntfy_sessions", "claude_chat_settings", "chatVoice",
}


async def _load_settings() -> dict:
    result = {}
    async with db.execute("SELECT key, value FROM settings") as cursor:
        async for row in cursor:
            try:
                result[row["key"]] = json.loads(row["value"])
            except Exception:
                result[row["key"]] = row["value"]
    return result


@app.get("/api/settings")
async def get_settings():
    return await _load_settings()


@app.put("/api/settings")
async def put_settings(body: dict):
    for key, val in body.items():
        if key in SYNCED_KEYS or key.startswith("starred_"):
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, json.dumps(val))
            )
    await db.commit()
    return {"ok": True}


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


# ---------------------------------------------------------------------------
# Session creation
# ---------------------------------------------------------------------------
CONFIG_FILE = "/config/config.json"


def _load_config() -> dict:
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

DEFAULT_PRESETS = [
    {"name": "Home", "path": "/home/ubuntu"},
    {"name": "Claude Chat", "path": "/home/ubuntu/docker/claude-chat"},
    {"name": "Docker", "path": "/home/ubuntu/docker"},
]


def _get_presets() -> list[dict]:
    config = _load_config()
    return config.get("presets", None) or DEFAULT_PRESETS


def _is_allowed_path(path: str) -> bool:
    allowed_paths = {p["path"] for p in _get_presets()}
    if path in allowed_paths:
        return True
    return path == "/home/ubuntu" or path.startswith("/home/ubuntu/")


@app.get("/api/config")
async def get_config():
    return {"presets": _get_presets()}


@app.post("/api/sessions")
async def create_session(body: dict):
    path = os.path.realpath(body.get("path", "/home/ubuntu"))
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

    # Auto-accept the "trust this folder" prompt after Claude starts
    async def _wait_and_accept_trust():
        """Wait for Claude to show trust prompt, then accept it."""
        for _ in range(10):
            await asyncio.sleep(1)
            try:
                raw = run_tmux("capture-pane", "-t", name, "-p", "-J", "-S", "-20")
                if "trust this folder" in raw.lower() or "Enter to confirm" in raw:
                    run_tmux("send-keys", "-t", name, "Enter")
                    return
                if "\u276f" in raw or "❯" in raw:
                    return  # Already trusted, Claude is ready
            except RuntimeError:
                return

    asyncio.create_task(_wait_and_accept_trust())

    log("session", "session_create", session=name, path=path)
    return {"created": True, "name": name, "path": path}

import os
import re
import json
import glob
import hashlib
import subprocess
import asyncio
import time
import httpx
import yaml
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Request
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SOCKET = os.environ.get("TMUX_SOCKET", "/tmp/tmux-1000/default")
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
    r"^●\s*(Bash|Read|Write|Edit|Grep|Glob|Agent|Skill|TaskCreate|TaskUpdate"
    r"|TaskList|TaskGet|ToolSearch|NotebookEdit)\s*\("
)

# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------
http_client: httpx.AsyncClient | None = None
title_cache: dict[str, str] = {}
death_cache: dict[str, float] = {}
TITLES_FILE = os.path.join(os.environ.get("UPLOAD_DIR", "/uploads"), "titles.json")


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


app = FastAPI(title="Claude Chat", lifespan=lifespan)


class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response


app.add_middleware(NoCacheStaticMiddleware)
app.mount("/static", StaticFiles(directory="static"), name="static")

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
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"tmux {args[0]} failed (rc={result.returncode}): {result.stderr.strip()}"
        )
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
        return []

    sessions = []
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        sname, pid_str, cmd, cwd, pane_dead = parts[0], parts[1], parts[2], parts[3], parts[4]
        # Skip names starting with '-' -- they break tmux -t flag parsing
        if sname.startswith("-"):
            continue

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
            if in_tool:
                # continuation of tool args block -- skip
                continue
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
        r"^(Updated?|Read?|Write?|Bash?|Edit|Grep?|Glob?|"
        r"Agent|Skill|Task\w*|Tool\w*|Notebook\w*|Search?)\("
    )
    _BG_CMD_RE = re.compile(r"Background command ")
    _WIBBLE_RE = re.compile(r"^\w+ing\.\.\.\s*\(\d+s\)")

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


async def generate_title(session_name: str, messages: list[dict]) -> str:
    """Generate a short title from the first 3 user messages via LiteLLM."""
    user_msgs = [m for m in messages if m["role"] == "user"][:3]
    if not user_msgs:
        return session_name

    prompt_content = "\n".join(m["content"] for m in user_msgs)
    try:
        resp = await http_client.post(
            LITELLM_URL,
            json={
                "model": "glm-4.5-air",
                "max_tokens": 20,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Generate a very short title (max 5 words) for this conversation. "
                            "Reply with ONLY the title, no punctuation or quotes."
                        ),
                    },
                    {"role": "user", "content": prompt_content},
                ],
            },
            timeout=8.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()[:60]
    except Exception:
        # fallback: first user message truncated
        return (user_msgs[0]["content"][:50] if user_msgs else session_name)


async def _refresh_title(session_name: str, messages: list[dict]) -> None:
    """Background task: generate title and cache it."""
    if session_name in title_cache:
        return
    title = await generate_title(session_name, messages)
    title_cache[session_name] = title


STATUS_BAR_RE = re.compile(
    r"(RAM\s+\d+%|CPU\s+\d+%|CTX\s+\d+%|tokens$|⏵⏵|bypass permissions|shift\+tab)"
)

def get_session_status(raw: str) -> str:
    """Derive session status from last few lines of capture."""
    lines = [l for l in raw.splitlines() if l.strip()]
    # Filter out Claude Code status bar lines at the bottom
    content_lines = [l for l in lines if not STATUS_BAR_RE.search(l)]
    if not content_lines:
        return "idle"
    tail = "\n".join(content_lines[-10:])
    # Check for active generation indicators
    # Claude Code uses random verbs: "Doing…", "Vibing…", "Churning…", "Undulating…", etc.
    # Pattern: line starts with ● followed by a capitalized word and …
    for cl in content_lines[-5:]:
        stripped = cl.strip()
        if re.match(r"^●\s+\S+…", stripped):
            return "working"
        if stripped.startswith("⎿  Running"):
            return "working"
    # Check if there's an empty user prompt (waiting for input)
    last_content = content_lines[-1].strip()
    if last_content == "❯" or MARKERS["user"].match(last_content):
        return "idle"
    if MARKERS["status"].match(last_content) or MARKERS["divider"].match(last_content):
        return "idle"
    # If last content is an assistant response or tool call, it just finished
    if MARKERS["assistant"].match(last_content) or TOOL_CALL_RE.match(last_content):
        return "idle"
    return "idle"


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
            {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
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

        try:
            raw = run_tmux("capture-pane", "-t", name, "-p", "-J", "-S", "-100")
        except RuntimeError:
            raw = ""

        messages = parse_messages(raw)
        title = title_cache.get(name)
        if not title:
            # trigger background title generation
            asyncio.create_task(_refresh_title(name, messages))
            # use first user message as temporary title
            user_msgs = [m for m in messages if m["role"] == "user"]
            title = user_msgs[0]["content"][:50] if user_msgs else name

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
        })

    return result


@app.get("/api/sessions/{name}")
async def get_session(name: str, lines: int = 10000):
    validate_session_name(name)
    if not _is_claude_session(name):
        raise HTTPException(status_code=404, detail="Session not found or not a Claude session")

    raw = run_tmux("capture-pane", "-t", name, "-p", "-J", "-S", f"-{lines}")
    messages = parse_messages(raw)
    title = title_cache.get(name, name)
    chash = content_hash(raw)

    return {
        "name": name,
        "title": title,
        "status": get_session_status(raw),
        "messages": messages,
        "content_hash": chash,
        "message_count": len(messages),
    }


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

    # Send the text literally (prevents key injection), then Enter separately
    run_tmux("send-keys", "-t", name, "-l", text)
    run_tmux("send-keys", "-t", name, "Enter")

    return {"sent": True, "session": name}


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
    return {"respawned": True}


@app.delete("/api/sessions/{name}")
async def dismiss_session(name: str):
    """Kill the tmux session entirely."""
    validate_session_name(name)
    if not _session_exists(name):
        raise HTTPException(status_code=404, detail="Session not found")
    if _is_claude_session(name):
        run_tmux("send-keys", "-t", name, "C-c")
        await asyncio.sleep(1)
    run_tmux("kill-session", "-t", name)
    return {"dismissed": True}


@app.put("/api/sessions/{name}/title")
async def set_session_title(name: str, body: dict):
    """Set a custom title for a session."""
    validate_session_name(name)
    title = (body.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title must not be empty")
    title_cache[name] = title[:60]
    # Persist to disk (atomic write)
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


@app.get("/api/sessions/{name}/poll")
async def poll_session(name: str, hash: str = "", lines: int = 10000):
    validate_session_name(name)
    if not _is_claude_session(name):
        raise HTTPException(status_code=404, detail="Session not found or not a Claude session")

    raw = run_tmux("capture-pane", "-t", name, "-p", "-J", "-S", f"-{lines}")
    chash = content_hash(raw)

    if hash and hash == chash:
        # no changes
        return {
            "has_changes": False,
            "content_hash": chash,
            "status": get_session_status(raw),
        }

    messages = parse_messages(raw)
    return {
        "has_changes": True,
        "content_hash": chash,
        "status": get_session_status(raw),
        "messages": messages,
    }


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

import os
import re
import json
import hashlib
import subprocess
import asyncio
import time
import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    http_client = httpx.AsyncClient(timeout=10.0)
    yield
    await http_client.aclose()


app = FastAPI(title="Claude Chat", lifespan=lifespan)

# ---------------------------------------------------------------------------
# Inline HTML (placeholder -- Task 3 will replace)
# ---------------------------------------------------------------------------
INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no, viewport-fit=cover">
  <title>Claude Voice Chat</title>
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="theme-color" content="#0A0A0A">
  <link rel="manifest" href="/manifest.json">
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --bg: #0A0A0A;
      --surface: #161618;
      --surface2: #1E1E20;
      --accent: #E8734A;
      --accent-glow: rgba(232, 115, 74, 0.2);
      --green: #32D74B;
      --red: #FF453A;
      --yellow: #FFD60A;
      --text: #E8E6E3;
      --text-dim: rgba(232, 230, 227, 0.5);
      --text-muted: rgba(232, 230, 227, 0.25);
      --radius: 20px;
      --radius-sm: 12px;
      --code-bg: #111113;
      --mono: ui-monospace, 'SF Mono', SFMono-Regular, Menlo, monospace;
    }
    html, body { height: 100%; overflow: hidden; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'SF Pro', 'Segoe UI', system-ui, sans-serif;
      background: var(--bg);
      color: var(--text);
      -webkit-tap-highlight-color: transparent;
      position: relative;
      overflow: hidden;
    }

    /* ===== App shell ===== */
    .app-shell {
      position: relative;
      width: 100%;
      height: 100%;
      overflow: hidden;
    }
    .screen {
      position: absolute;
      top: 0; left: 0; right: 0; bottom: 0;
      display: flex;
      flex-direction: column;
      transition: transform 200ms ease-out, opacity 200ms ease-out;
      will-change: transform, opacity;
    }
    .screen.hidden-right {
      transform: translateX(100%);
      opacity: 0;
      pointer-events: none;
    }
    .screen.hidden-left {
      transform: translateX(-30%);
      opacity: 0;
      pointer-events: none;
    }

    /* ===== Headers ===== */
    .header {
      display: flex;
      align-items: center;
      padding: 0 16px;
      height: 56px;
      min-height: 56px;
      padding-top: env(safe-area-inset-top, 0px);
      background: var(--surface);
      border-bottom: 1px solid rgba(255,255,255,0.06);
      flex-shrink: 0;
      z-index: 10;
    }
    .header-title {
      font-size: 1.1rem;
      font-weight: 600;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .header-badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      background: var(--surface2);
      color: var(--text-dim);
      font-size: 0.75rem;
      font-weight: 600;
      min-width: 24px;
      height: 24px;
      padding: 0 8px;
      border-radius: 12px;
      margin-left: 10px;
      flex-shrink: 0;
    }
    .header-spacer { flex: 1; }
    .back-btn {
      background: none;
      border: none;
      color: var(--text);
      font-size: 1.5rem;
      cursor: pointer;
      padding: 4px 12px 4px 0;
      touch-action: manipulation;
      min-width: 44px;
      min-height: 44px;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }
    .session-header-title {
      flex: 1;
      text-align: center;
      font-size: 1rem;
      font-weight: 600;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      padding: 0 8px;
    }
    .status-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: var(--text-muted);
      flex-shrink: 0;
      margin-left: 8px;
      transition: background 0.3s;
    }
    .status-dot.working {
      background: var(--green);
      animation: statusPulse 1.5s ease-in-out infinite;
    }
    @keyframes statusPulse {
      0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(34,197,94,0.5); }
      50% { opacity: 0.7; box-shadow: 0 0 0 6px rgba(34,197,94,0); }
    }
    .bell-btn {
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
      margin-left: 4px;
      flex-shrink: 0;
      transition: color 150ms;
    }
    .bell-btn.active { color: var(--accent); }
    .bell-btn:active { opacity: 0.7; }

    /* ===== Session List ===== */
    .session-list {
      flex: 1;
      overflow-y: auto;
      -webkit-overflow-scrolling: touch;
      padding: 12px 16px;
    }
    .session-card {
      background: var(--surface);
      border-radius: var(--radius);
      padding: 14px 16px;
      margin-bottom: 10px;
      cursor: pointer;
      touch-action: manipulation;
      transition: transform 100ms ease, background 150ms ease;
      position: relative;
    }
    .session-card:active {
      transform: scale(0.98);
      background: var(--surface2);
    }
    .session-card-top {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 8px;
    }
    .session-card-title {
      font-size: 0.95rem;
      font-weight: 600;
      line-height: 1.3;
      flex: 1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .session-card-meta {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-shrink: 0;
    }
    .session-card-time {
      font-size: 0.72rem;
      color: var(--text-dim);
      white-space: nowrap;
    }
    .session-card-status {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--text-muted);
      flex-shrink: 0;
    }
    .session-card-status.working {
      background: var(--green);
      animation: statusPulse 1.5s ease-in-out infinite;
    }
    .session-card-cwd {
      font-size: 0.75rem;
      color: var(--text-dim);
      margin-top: 4px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .session-card-preview {
      font-size: 0.8rem;
      color: var(--text-muted);
      margin-top: 6px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      line-height: 1.4;
    }
    .empty-state {
      flex: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      color: var(--text-dim);
      font-size: 0.9rem;
      text-align: center;
      padding: 40px 20px;
      gap: 8px;
    }
    .empty-state-icon {
      font-size: 2.5rem;
      opacity: 0.3;
      margin-bottom: 8px;
    }
    .pull-indicator {
      text-align: center;
      color: var(--text-muted);
      font-size: 0.75rem;
      padding: 8px;
      opacity: 0;
      transition: opacity 200ms;
    }
    .pull-indicator.visible { opacity: 1; }

    /* ===== Chat Feed ===== */
    .chat-feed {
      flex: 1;
      overflow-y: auto;
      -webkit-overflow-scrolling: touch;
      padding: 12px 16px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .msg {
      border-radius: var(--radius);
      font-size: 0.88rem;
      line-height: 1.55;
      word-wrap: break-word;
      overflow-wrap: break-word;
      animation: msgIn 150ms ease-out;
    }
    @keyframes msgIn {
      from { opacity: 0; transform: translateY(8px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .msg-user {
      align-self: flex-end;
      background: var(--accent);
      color: white;
      padding: 10px 14px;
      max-width: 78%;
      border-radius: 20px 20px 4px 20px;
    }
    .msg-assistant {
      align-self: flex-start;
      background: var(--surface2);
      padding: 12px 14px;
      max-width: 92%;
      border-radius: 4px 20px 20px 20px;
    }
    .msg-assistant-text {
      white-space: pre-wrap;
    }
    .msg-assistant-text .code-block {
      display: block;
      background: var(--code-bg);
      font-family: var(--mono);
      font-size: 13px;
      line-height: 1.5;
      border: 1px solid rgba(255,255,255,0.04);
      border-radius: 8px;
      padding: 10px 12px;
      margin: 6px 0;
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
      white-space: pre;
      position: relative;
    }
    .msg-actions {
      display: flex;
      gap: 2px;
      margin-top: 6px;
      justify-content: flex-end;
    }
    .msg-action-btn {
      background: none;
      border: none;
      color: var(--text-muted);
      cursor: pointer;
      padding: 4px 8px;
      touch-action: manipulation;
      min-width: 36px;
      min-height: 28px;
      display: flex;
      align-items: center;
      justify-content: center;
      border-radius: 6px;
      transition: color 150ms, background 150ms;
    }
    .msg-action-btn:active {
      background: rgba(255,255,255,0.08);
      color: var(--text-dim);
    }
    .msg-action-btn.playing {
      color: var(--accent);
    }
    .code-copy-btn {
      position: absolute;
      top: 4px;
      right: 4px;
      background: rgba(255,255,255,0.05);
      border: none;
      color: var(--text-dim);
      cursor: pointer;
      padding: 4px 6px;
      border-radius: 6px;
      opacity: 0;
      transition: opacity 150ms, background 150ms;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .code-block:hover .code-copy-btn {
      opacity: 1;
    }
    .code-copy-btn:active {
      background: rgba(255,255,255,0.15);
    }
    @media (hover: none) {
      .code-copy-btn {
        opacity: 1;
      }
    }
    .msg-tool {
      align-self: flex-start;
      background: transparent;
      border: 1px solid rgba(255,255,255,0.06);
      padding: 5px 12px;
      font-size: 0.75rem;
      font-family: var(--mono);
      color: var(--text-dim);
      border-radius: 8px;
      max-width: 90%;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    /* Typing indicator */
    .typing-indicator {
      align-self: flex-start;
      padding: 10px 16px;
      display: none;
      gap: 5px;
      align-items: center;
    }
    .typing-indicator.visible { display: flex; }
    .typing-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: var(--text-dim);
      animation: typingPulse 1.2s infinite;
    }
    .typing-dot:nth-child(2) { animation-delay: 0.2s; }
    .typing-dot:nth-child(3) { animation-delay: 0.4s; }
    @keyframes typingPulse {
      0%, 80%, 100% { opacity: 0.3; transform: scale(0.85); }
      40% { opacity: 1; transform: scale(1); }
    }

    /* New messages pill */
    .new-msg-pill {
      position: absolute;
      bottom: 160px;
      left: 50%;
      transform: translateX(-50%);
      background: var(--accent);
      color: white;
      padding: 6px 16px;
      border-radius: 20px;
      font-size: 0.78rem;
      font-weight: 600;
      cursor: pointer;
      touch-action: manipulation;
      z-index: 15;
      display: none;
      box-shadow: 0 4px 16px rgba(0,0,0,0.4);
      animation: pillIn 200ms ease-out;
    }
    .new-msg-pill.visible { display: block; }
    @keyframes pillIn {
      from { opacity: 0; transform: translateX(-50%) translateY(10px); }
      to { opacity: 1; transform: translateX(-50%) translateY(0); }
    }

    /* ===== Preview Bar ===== */
    .preview-bar {
      display: none;
      flex-shrink: 0;
      background: var(--surface);
      border-top: 1px solid rgba(255,255,255,0.08);
      padding: 10px 12px;
      gap: 8px;
      align-items: center;
      z-index: 12;
    }
    .preview-bar.visible { display: flex; }
    .preview-text {
      flex: 1;
      background: var(--surface2);
      color: var(--text);
      border: 1px solid rgba(255,255,255,0.1);
      border-radius: var(--radius-sm);
      padding: 8px 12px;
      font-size: 0.85rem;
      font-family: inherit;
      resize: none;
      min-height: 36px;
      max-height: 80px;
      overflow-y: auto;
      outline: none;
    }
    .preview-send {
      background: var(--accent);
      color: white;
      border: none;
      border-radius: var(--radius-sm);
      padding: 8px 16px;
      font-size: 0.85rem;
      font-weight: 600;
      cursor: pointer;
      touch-action: manipulation;
      min-width: 44px;
      min-height: 44px;
      flex-shrink: 0;
    }
    .preview-send:active { opacity: 0.85; }
    .preview-cancel {
      background: none;
      border: 1px solid rgba(255,255,255,0.15);
      color: var(--text-dim);
      border-radius: var(--radius-sm);
      padding: 8px 12px;
      font-size: 0.85rem;
      cursor: pointer;
      touch-action: manipulation;
      min-width: 44px;
      min-height: 44px;
      flex-shrink: 0;
    }
    .preview-cancel:active { opacity: 0.7; }

    /* ===== Mic Area ===== */
    .input-area {
      flex-shrink: 0;
      padding: 8px 12px calc(8px + env(safe-area-inset-bottom, 0px));
      background: var(--surface);
      border-top: 1px solid rgba(255,255,255,0.06);
      z-index: 12;
    }
    .text-input-row {
      display: flex;
      align-items: flex-end;
      gap: 8px;
    }
    .text-input {
      flex: 1;
      background: var(--surface2);
      color: var(--text);
      border: 1px solid rgba(255,255,255,0.1);
      border-radius: 20px;
      padding: 10px 16px;
      font-size: 0.9rem;
      font-family: inherit;
      resize: none;
      max-height: 100px;
      line-height: 1.4;
      outline: none;
    }
    .text-input:focus { border-color: var(--accent); }
    .text-input::placeholder { color: var(--text-muted); }
    .attach-btn {
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
      transition: color 150ms;
    }
    .attach-btn:active { color: var(--text); }
    .mic-inline-btn, .send-inline-btn {
      width: 36px;
      height: 36px;
      border-radius: 50%;
      border: none;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      touch-action: manipulation;
      flex-shrink: 0;
      transition: all 150ms;
    }
    .mic-inline-btn {
      background: transparent;
      color: var(--accent);
      border: 2px solid var(--accent);
    }
    .mic-inline-btn:active { transform: scale(0.9); }
    .mic-inline-btn.recording {
      border-color: var(--red);
      color: var(--red);
      animation: micRec 1s ease-in-out infinite;
    }
    @keyframes micRec {
      0%, 100% { box-shadow: 0 0 0 0 rgba(239,68,68,0.4); }
      50% { box-shadow: 0 0 0 10px transparent; }
    }
    .send-inline-btn {
      background: var(--accent);
      color: white;
    }
    .send-inline-btn:active { transform: scale(0.9); }
    .mic-label {
      margin-top: 4px;
      font-size: 0.72rem;
      color: var(--text-dim);
      text-align: center;
      min-height: 1.1em;
      max-width: 90%;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .mic-label.interim {
      color: var(--text);
      font-size: 0.82rem;
      white-space: normal;
      max-width: 100%;
    }

    /* ===== Scrollbar styling ===== */
    ::-webkit-scrollbar { width: 3px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }
  </style>
</head>
<body>
<div class="app-shell">

  <!-- ===== Screen 1: Session List ===== -->
  <div class="screen" id="screenList">
    <div class="header">
      <span class="header-title">Claude Sessions</span>
      <span class="header-badge" id="sessionCount">0</span>
      <div class="header-spacer"></div>
    </div>
    <div class="pull-indicator" id="pullIndicator">Pull to refresh</div>
    <div class="session-list" id="sessionList">
      <div class="empty-state" id="emptyState">
        <div class="empty-state-icon">&#9671;</div>
        <div>No active Claude sessions</div>
        <div style="font-size:0.78rem;color:var(--text-muted);margin-top:4px;">Start a Claude Code session in tmux to see it here</div>
      </div>
    </div>
  </div>

  <!-- ===== Screen 2: Session View ===== -->
  <div class="screen hidden-right" id="screenChat">
    <div class="header">
      <button class="back-btn" id="backBtn">&#8249;</button>
      <span class="session-header-title" id="chatTitle">Session</span>
      <button class="bell-btn" id="bellBtn" title="Notify when done"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></svg></button>
      <div class="status-dot" id="chatStatus"></div>
    </div>
    <div class="chat-feed" id="chatFeed"></div>
    <div class="typing-indicator" id="typingIndicator">
      <div class="typing-dot"></div>
      <div class="typing-dot"></div>
      <div class="typing-dot"></div>
    </div>
    <div class="new-msg-pill" id="newMsgPill">New messages</div>
    <div class="preview-bar" id="previewBar">
      <textarea class="preview-text" id="previewText" rows="1"></textarea>
      <button class="preview-send" id="previewSend">Send</button>
      <button class="preview-cancel" id="previewCancel">Cancel</button>
    </div>
    <div class="input-area" id="inputArea">
      <div class="text-input-row">
        <button class="attach-btn" id="attachBtn" title="Attach file"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/></svg></button>
        <textarea class="text-input" id="textInput" rows="1" placeholder="Message..."></textarea>
        <button class="mic-inline-btn" id="micBtn" title="Voice input"><svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 14a3 3 0 003-3V5a3 3 0 00-6 0v6a3 3 0 003 3zm5-3a5 5 0 01-10 0H5a7 7 0 0014 0h-2zm-4 7.93A7 7 0 0019 12h-2a5 5 0 01-10 0H5a7 7 0 006 6.93V22h2v-3.07z"/></svg></button>
        <button class="send-inline-btn" id="sendBtn" title="Send" style="display:none;"><svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg></button>
      </div>
      <div class="mic-label" id="micLabel"></div>
    </div>
    <input type="file" id="fileInput" style="display:none;" accept="image/*,application/pdf,.txt,.py,.js,.ts,.json,.md,.csv">
    <div id="uploadToast" style="display:none;position:fixed;bottom:100px;left:50%;transform:translateX(-50%);background:var(--surface2);color:var(--text);padding:10px 20px;border-radius:var(--radius-sm);font-size:0.85rem;z-index:50;box-shadow:0 4px 20px rgba(0,0,0,0.5);">Uploading...</div>
  </div>
</div>

<script>
(function() {
  'use strict';

  // ========== State ==========
  var currentSession = null;
  var contentHash = '';
  var pollTimer = null;
  var idleCount = 0;
  var lastMessageCount = 0;
  var isUserNearBottom = true;
  var ttsUtterance = null;
  var ttsPlayingBtn = null;
  var sessionListTimer = null;
  var pendingMessages = []; // optimistic messages awaiting server confirmation

  // Voice state
  var NativeSR = window.SpeechRecognition || window.webkitSpeechRecognition;
  var hasNativeSTT = !!NativeSR;
  var recognition = null;
  var finalTranscript = '';
  var isRecording = false;
  var isProcessing = false;

  // ========== Elements ==========
  var screenList = document.getElementById('screenList');
  var screenChat = document.getElementById('screenChat');
  var sessionListEl = document.getElementById('sessionList');
  var sessionCountEl = document.getElementById('sessionCount');
  var emptyStateEl = document.getElementById('emptyState');
  var pullIndicator = document.getElementById('pullIndicator');

  var backBtn = document.getElementById('backBtn');
  var chatTitle = document.getElementById('chatTitle');
  var chatStatus = document.getElementById('chatStatus');
  var chatFeed = document.getElementById('chatFeed');
  var typingIndicator = document.getElementById('typingIndicator');
  var newMsgPill = document.getElementById('newMsgPill');

  var previewBar = document.getElementById('previewBar');
  var previewText = document.getElementById('previewText');
  var previewSend = document.getElementById('previewSend');
  var previewCancel = document.getElementById('previewCancel');

  var micBtn = document.getElementById('micBtn');
  var micLabel = document.getElementById('micLabel');
  var textInput = document.getElementById('textInput');
  var sendBtn = document.getElementById('sendBtn');
  var attachBtn = document.getElementById('attachBtn');
  var fileInput = document.getElementById('fileInput');
  var uploadToast = document.getElementById('uploadToast');
  var bellBtn = document.getElementById('bellBtn');

  // ========== Clipboard Helpers ==========
  function fallbackCopy(text) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    ta.style.top = '-9999px';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    try { document.execCommand('copy'); } catch(e) {}
    document.body.removeChild(ta);
  }

  function copyToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).catch(function() { fallbackCopy(text); });
    } else {
      fallbackCopy(text);
    }
    showCopyToast();
  }

  function showCopyToast() {
    uploadToast.textContent = 'Copied!';
    uploadToast.style.display = 'block';
    setTimeout(function() { uploadToast.style.display = 'none'; }, 1500);
  }

  // ========== Navigation ==========
  // Per-session draft storage
  var sessionDrafts = {};

  function showSessionList() {
    // Save current draft before leaving
    if (currentSession && textInput.value.trim()) {
      sessionDrafts[currentSession] = textInput.value;
    } else if (currentSession) {
      delete sessionDrafts[currentSession];
    }
    textInput.value = '';
    currentSession = null;
    contentHash = '';
    idleCount = 0;
    lastMessageCount = 0;
    pendingMessages = [];
    stopPolling();
    stopTTS();
    hidePreview();
    screenList.className = 'screen';
    screenChat.className = 'screen hidden-right';
    loadSessions();
    startSessionListPolling();
  }

  function showSessionView(name) {
    currentSession = name;
    contentHash = '';
    idleCount = 0;
    lastMessageCount = 0;
    stopSessionListPolling();

    // Clear text input and restore any saved draft for this session
    textInput.value = sessionDrafts[name] || '';
    micLabel.textContent = '';

    // clear feed safely
    while (chatFeed.firstChild) chatFeed.removeChild(chatFeed.firstChild);
    typingIndicator.classList.remove('visible');
    newMsgPill.classList.remove('visible');
    hidePreview();
    updateBellIcon();

    screenList.className = 'screen hidden-left';
    screenChat.className = 'screen';

    loadSession(name);
    startPolling();
  }

  backBtn.addEventListener('click', function() { showSessionList(); });

  // Swipe-right to go back
  var touchStartX = 0;
  var touchStartY = 0;
  screenChat.addEventListener('touchstart', function(e) {
    var t = e.touches[0];
    touchStartX = t.clientX;
    touchStartY = t.clientY;
  }, { passive: true });
  screenChat.addEventListener('touchend', function(e) {
    var t = e.changedTouches[0];
    var dx = t.clientX - touchStartX;
    var dy = Math.abs(t.clientY - touchStartY);
    if (touchStartX < 40 && dx > 80 && dy < 60) {
      showSessionList();
    }
  }, { passive: true });

  // ========== Session List ==========
  function loadSessions() {
    fetch('/api/sessions')
      .then(function(r) { return r.json(); })
      .then(function(sessions) {
        renderSessionList(sessions);
      })
      .catch(function() {
        // silent fail, will retry
      });
  }

  function renderSessionList(sessions) {
    // Remove old cards but keep emptyState
    var cards = sessionListEl.querySelectorAll('.session-card');
    for (var i = 0; i < cards.length; i++) {
      sessionListEl.removeChild(cards[i]);
    }

    sessionCountEl.textContent = String(sessions.length);

    if (sessions.length === 0) {
      emptyStateEl.style.display = '';
      return;
    }
    emptyStateEl.style.display = 'none';

    sessions.forEach(function(s) {
      var card = document.createElement('div');
      card.className = 'session-card';
      card.setAttribute('data-name', s.name);

      var top = document.createElement('div');
      top.className = 'session-card-top';

      var title = document.createElement('div');
      title.className = 'session-card-title';
      title.textContent = s.title || s.name;

      var meta = document.createElement('div');
      meta.className = 'session-card-meta';

      var time = document.createElement('span');
      time.className = 'session-card-time';
      time.textContent = s.last_activity || '';

      var dot = document.createElement('div');
      dot.className = 'session-card-status' + (s.status === 'working' ? ' working' : '');

      meta.appendChild(time);
      meta.appendChild(dot);
      top.appendChild(title);
      top.appendChild(meta);
      card.appendChild(top);

      if (s.cwd) {
        var cwd = document.createElement('div');
        cwd.className = 'session-card-cwd';
        cwd.textContent = s.cwd;
        card.appendChild(cwd);
      }

      if (s.preview) {
        var preview = document.createElement('div');
        preview.className = 'session-card-preview';
        preview.textContent = s.preview;
        card.appendChild(preview);
      }

      card.addEventListener('click', function() {
        showSessionView(s.name);
      });

      sessionListEl.appendChild(card);
    });
  }

  // Pull-to-refresh
  var pullStartY = 0;
  var isPulling = false;
  sessionListEl.addEventListener('touchstart', function(e) {
    if (sessionListEl.scrollTop <= 0) {
      pullStartY = e.touches[0].clientY;
      isPulling = true;
    }
  }, { passive: true });
  sessionListEl.addEventListener('touchmove', function(e) {
    if (!isPulling) return;
    var dy = e.touches[0].clientY - pullStartY;
    if (dy > 50 && sessionListEl.scrollTop <= 0) {
      pullIndicator.classList.add('visible');
    }
  }, { passive: true });
  sessionListEl.addEventListener('touchend', function() {
    if (pullIndicator.classList.contains('visible')) {
      pullIndicator.classList.remove('visible');
      loadSessions();
    }
    isPulling = false;
  }, { passive: true });

  function startSessionListPolling() {
    stopSessionListPolling();
    sessionListTimer = setInterval(loadSessions, 8000);
  }
  function stopSessionListPolling() {
    if (sessionListTimer) { clearInterval(sessionListTimer); sessionListTimer = null; }
  }

  // ========== Session View ==========
  function loadSession(name) {
    fetch('/api/sessions/' + encodeURIComponent(name))
      .then(function(r) {
        if (!r.ok) throw new Error('not found');
        return r.json();
      })
      .then(function(data) {
        chatTitle.textContent = data.title || data.name;
        updateStatusDot(data.status);
        contentHash = data.content_hash || '';
        renderMessages(data.messages || []);
        lastMessageCount = (data.messages || []).length;
        scrollToBottom(true);
      })
      .catch(function() {
        chatTitle.textContent = 'Session unavailable';
      });
  }

  function updateStatusDot(status) {
    if (status === 'working') {
      chatStatus.className = 'status-dot working';
      typingIndicator.classList.add('visible');
    } else {
      chatStatus.className = 'status-dot';
      typingIndicator.classList.remove('visible');
    }
  }

  function renderMessages(messages) {
    // Clear feed
    while (chatFeed.firstChild) chatFeed.removeChild(chatFeed.firstChild);

    messages.forEach(function(m) {
      appendMessage(m, false);
    });

    // Re-append pending messages not yet in server data
    var now = Date.now();
    function normalize(s) { return (s || '').replace(/\\s+/g, ' ').trim(); }
    pendingMessages = pendingMessages.filter(function(pm) {
      if (now - pm.ts > 30000) return false; // expire after 30s
      var pmNorm = normalize(pm.content);
      var found = messages.some(function(m) {
        return m.role === 'user' && normalize(m.content).indexOf(pmNorm.substring(0, 40)) >= 0;
      });
      return !found;
    });
    pendingMessages.forEach(function(pm) {
      appendMessage(pm, false);
    });
  }

  function appendMessage(m, animate) {
    var el;
    if (m.role === 'user') {
      el = document.createElement('div');
      el.className = 'msg msg-user';
      el.textContent = m.content || m.text || '';
      if (!animate) el.style.animation = 'none';
    } else if (m.role === 'assistant') {
      el = document.createElement('div');
      el.className = 'msg msg-assistant';
      var textSpan = document.createElement('div');
      textSpan.className = 'msg-assistant-text';
      var content = m.content || m.text || '';
      // Code block detection: split into code vs prose
      var lines = content.split('\\n');
      var codeBuf = [];
      var inCode = false;
      var codeRe = new RegExp('^(\\\\s{4,}\\\\S|\\\\s*\\\\d+[\\u2192|:]\\\\s)');
      for (var li = 0; li < lines.length; li++) {
        var isCode = codeRe.test(lines[li]);
        if (isCode) {
          if (!inCode && codeBuf.length === 0) {
            // flush any preceding text
          }
          inCode = true;
          codeBuf.push(lines[li]);
        } else {
          if (inCode && codeBuf.length >= 2) {
            var pre = document.createElement('pre');
            pre.className = 'code-block';
            var code = document.createElement('code');
            code.textContent = codeBuf.join('\\n');
            pre.appendChild(code);
            var copyBtn = document.createElement('button');
            copyBtn.className = 'code-copy-btn';
            copyBtn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>';
            copyBtn.title = 'Copy code';
            (function(codeText) {
              copyBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                copyToClipboard(codeText);
              });
            })(codeBuf.join('\\n'));
            pre.appendChild(copyBtn);
            textSpan.appendChild(pre);
            codeBuf = [];
            inCode = false;
          } else if (inCode) {
            // Too few code lines, treat as text
            textSpan.appendChild(document.createTextNode(codeBuf.join('\\n') + '\\n'));
            codeBuf = [];
            inCode = false;
          }
          textSpan.appendChild(document.createTextNode(lines[li] + (li < lines.length - 1 ? '\\n' : '')));
        }
      }
      if (inCode && codeBuf.length >= 2) {
        var pre = document.createElement('pre');
        pre.className = 'code-block';
        var code = document.createElement('code');
        code.textContent = codeBuf.join('\\n');
        pre.appendChild(code);
        var copyBtn = document.createElement('button');
        copyBtn.className = 'code-copy-btn';
        copyBtn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>';
        copyBtn.title = 'Copy code';
        (function(codeText) {
          copyBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            copyToClipboard(codeText);
          });
        })(codeBuf.join('\\n'));
        pre.appendChild(copyBtn);
        textSpan.appendChild(pre);
      } else if (codeBuf.length > 0) {
        textSpan.appendChild(document.createTextNode(codeBuf.join('\\n')));
      }
      el.appendChild(textSpan);
      // Action row below text
      var actions = document.createElement('div');
      actions.className = 'msg-actions';
      // Copy button
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
      // TTS button
      var ttsBtn = document.createElement('button');
      ttsBtn.className = 'msg-action-btn msg-tts-btn';
      ttsBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>';
      ttsBtn.title = 'Read aloud';
      var msgText = content;
      ttsBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        toggleTTS(msgText, ttsBtn);
      });
      actions.appendChild(ttsBtn);
      el.appendChild(actions);
      if (!animate) el.style.animation = 'none';
    } else if (m.role === 'tool') {
      // Hide tool calls -- they're noise in a chat view
      return;
    } else {
      return;
    }
    chatFeed.appendChild(el);
  }

  // ========== Polling ==========
  function startPolling() {
    stopPolling();
    doPoll();
  }

  function stopPolling() {
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
  }

  function doPoll() {
    if (!currentSession) return;
    var url = '/api/sessions/' + encodeURIComponent(currentSession) + '/poll';
    if (contentHash) url += '?hash=' + encodeURIComponent(contentHash);

    fetch(url)
      .then(function(r) {
        if (!r.ok) throw new Error('poll fail');
        return r.json();
      })
      .then(function(data) {
        updateStatusDot(data.status);
        checkNtfyTrigger(currentSession, data.status, data.has_changes ? data.messages : null);

        if (data.has_changes && data.messages) {
          contentHash = data.content_hash || '';
          var newCount = data.messages.length;

          // Check if user is near bottom before updating
          checkScrollPosition();

          // Re-render all messages (content_hash changed)
          renderMessages(data.messages);

          // If new messages arrived and user is near bottom, scroll
          if (newCount > lastMessageCount) {
            if (isUserNearBottom) {
              scrollToBottom(false);
            } else {
              newMsgPill.classList.add('visible');
            }
          }
          lastMessageCount = newCount;
          idleCount = 0;
        } else {
          contentHash = data.content_hash || contentHash;
          idleCount++;
        }

        schedulePoll();
      })
      .catch(function() {
        idleCount++;
        schedulePoll();
      });
  }

  function schedulePoll() {
    if (!currentSession) return;
    var interval;
    if (idleCount < 3) interval = 2000;
    else if (idleCount < 6) interval = 5000;
    else interval = 10000;
    pollTimer = setTimeout(doPoll, interval);
  }

  // Pause/resume on visibility
  document.addEventListener('visibilitychange', function() {
    if (document.hidden) {
      stopPolling();
      stopSessionListPolling();
    } else {
      if (currentSession) {
        idleCount = 0;
        startPolling();
      } else {
        loadSessions();
        startSessionListPolling();
      }
    }
  });

  // ========== Scroll ==========
  function checkScrollPosition() {
    var el = chatFeed;
    isUserNearBottom = (el.scrollHeight - el.scrollTop - el.clientHeight) < 100;
  }

  function scrollToBottom(force) {
    if (force || isUserNearBottom) {
      requestAnimationFrame(function() {
        chatFeed.scrollTop = chatFeed.scrollHeight;
      });
      newMsgPill.classList.remove('visible');
    }
  }

  chatFeed.addEventListener('scroll', function() {
    checkScrollPosition();
    if (isUserNearBottom) {
      newMsgPill.classList.remove('visible');
    }
  }, { passive: true });

  newMsgPill.addEventListener('click', function() {
    chatFeed.scrollTop = chatFeed.scrollHeight;
    newMsgPill.classList.remove('visible');
  });

  // ========== TTS ==========
  function toggleTTS(text, btn) {
    if (ttsPlayingBtn === btn) {
      stopTTS();
      return;
    }
    stopTTS();
    if (!window.speechSynthesis) return;

    ttsUtterance = new SpeechSynthesisUtterance(text);
    ttsUtterance.rate = 1.0;
    ttsUtterance.pitch = 1.0;

    // Try to use a saved voice
    var savedVoice = localStorage.getItem('chatVoice');
    if (savedVoice) {
      var voices = speechSynthesis.getVoices();
      var match = voices.find(function(v) { return v.name === savedVoice; });
      if (match) ttsUtterance.voice = match;
    }

    btn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><rect x="4" y="4" width="16" height="16" rx="2"/></svg>';
    btn.classList.add('playing');
    ttsPlayingBtn = btn;

    var playSvg = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>';
    ttsUtterance.onend = function() {
      btn.innerHTML = playSvg;
      btn.classList.remove('playing');
      ttsPlayingBtn = null;
      ttsUtterance = null;
    };
    ttsUtterance.onerror = function() {
      btn.innerHTML = playSvg;
      btn.classList.remove('playing');
      ttsPlayingBtn = null;
      ttsUtterance = null;
    };

    speechSynthesis.speak(ttsUtterance);
  }

  function stopTTS() {
    if (window.speechSynthesis) speechSynthesis.cancel();
    if (ttsPlayingBtn) {
      ttsPlayingBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>';
      ttsPlayingBtn.classList.remove('playing');
      ttsPlayingBtn = null;
    }
    ttsUtterance = null;
  }

  // ========== Preview Bar ==========
  function showPreview(text) {
    previewText.value = text;
    previewBar.classList.add('visible');
    previewText.focus();
  }

  function hidePreview() {
    previewBar.classList.remove('visible');
    previewText.value = '';
  }

  previewSend.addEventListener('click', function() {
    var text = previewText.value.trim();
    if (!text || !currentSession) return;
    sendMessage(text);
    hidePreview();
  });

  previewCancel.addEventListener('click', function() {
    hidePreview();
    setMicState('idle');
  });

  function sendMessage(text) {
    if (!currentSession) return;
    // optimistically add user message and track it
    var msg = { role: 'user', content: text, ts: Date.now() };
    pendingMessages.push(msg);
    appendMessage(msg, true);
    scrollToBottom(true);

    fetch('/api/sessions/' + encodeURIComponent(currentSession) + '/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text })
    })
    .then(function(r) {
      if (!r.ok) throw new Error('send failed');
      // Reset polling to active
      idleCount = 0;
      stopPolling();
      startPolling();
    })
    .catch(function() {
      // Show error in feed
      appendMessage({ role: 'assistant', content: 'Failed to send message. Please try again.' }, true);
      scrollToBottom(true);
    });
  }

  // ========== Text Input + Send/Mic Toggle ==========
  function toggleSendMic() {
    if (textInput.value.trim()) {
      sendBtn.style.display = 'flex';
      micBtn.style.display = 'none';
    } else {
      sendBtn.style.display = 'none';
      micBtn.style.display = 'flex';
    }
  }
  textInput.addEventListener('input', toggleSendMic);

  sendBtn.addEventListener('click', function() {
    var text = textInput.value.trim();
    if (text) {
      sendMessage(text);
      textInput.value = '';
      toggleSendMic();
    }
  });

  textInput.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      var text = textInput.value.trim();
      if (text) {
        sendMessage(text);
        textInput.value = '';
        toggleSendMic();
      }
    }
  });

  // ========== File Upload ==========
  attachBtn.addEventListener('click', function() { fileInput.click(); });
  fileInput.addEventListener('change', function() {
    if (!fileInput.files || !fileInput.files[0] || !currentSession) return;
    var f = fileInput.files[0];
    uploadToast.textContent = 'Uploading ' + f.name + '...';
    uploadToast.style.display = 'block';
    var fd = new FormData();
    fd.append('file', f);
    fetch('/api/upload/' + encodeURIComponent(currentSession), { method: 'POST', body: fd })
      .then(function(r) { if (!r.ok) throw new Error('upload failed'); return r.json(); })
      .then(function(d) {
        uploadToast.textContent = 'Uploaded!';
        setTimeout(function() { uploadToast.style.display = 'none'; }, 2000);
        // Put file reference in text input so user can edit and send
        textInput.value = 'Please review the file I uploaded at ' + d.path;
        textInput.focus();
        toggleSendMic();
      })
      .catch(function() {
        uploadToast.textContent = 'Upload failed';
        setTimeout(function() { uploadToast.style.display = 'none'; }, 3000);
      });
    fileInput.value = '';
  });

  // ========== ntfy Notifications ==========
  var previousStatus = {};
  var lastNtfyTime = {};

  function isNtfyEnabled(session) {
    try {
      var s = JSON.parse(localStorage.getItem('ntfy_sessions') || '{}');
      return !!s[session];
    } catch(e) { return false; }
  }

  function setNtfyEnabled(session, enabled) {
    try {
      var s = JSON.parse(localStorage.getItem('ntfy_sessions') || '{}');
      s[session] = enabled;
      localStorage.setItem('ntfy_sessions', JSON.stringify(s));
    } catch(e) {}
  }

  function updateBellIcon() {
    if (!currentSession) return;
    var on = isNtfyEnabled(currentSession);
    bellBtn.classList.toggle('active', on);
    bellBtn.innerHTML = on
      ? '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="1"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></svg>'
      : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></svg>';
  }

  bellBtn.addEventListener('click', function() {
    if (!currentSession) return;
    var now = !isNtfyEnabled(currentSession);
    setNtfyEnabled(currentSession, now);
    updateBellIcon();
  });

  function sendNtfy(title, body) {
    fetch('/api/ntfy', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: title, body: body, tags: 'robot' })
    }).catch(function() {});
  }

  var lastAsstCount = {};

  function checkNtfyTrigger(sessionName, status, messages) {
    var prev = previousStatus[sessionName];
    previousStatus[sessionName] = status;
    if (!isNtfyEnabled(sessionName)) return;

    // Count current assistant messages
    var asstMsgs = [];
    if (messages && messages.length > 0) {
      asstMsgs = messages.filter(function(m) { return m.role === 'assistant'; });
    }
    var curCount = asstMsgs.length;
    var prevCount = lastAsstCount[sessionName] || 0;

    // Trigger on: working->idle transition OR new assistant messages while idle
    var statusTransition = (prev === 'working' && status === 'idle');
    var newMessages = (curCount > prevCount && status === 'idle' && prevCount > 0);

    if (curCount > 0) lastAsstCount[sessionName] = curCount;

    if (statusTransition || newMessages) {
      var now = Date.now();
      if (lastNtfyTime[sessionName] && (now - lastNtfyTime[sessionName]) < 30000) return;
      lastNtfyTime[sessionName] = now;
      var body = '';
      if (asstMsgs.length > 0) {
        body = (asstMsgs[asstMsgs.length - 1].content || '').substring(0, 200);
      } else {
        var domMsgs = chatFeed.querySelectorAll('.msg-assistant-text');
        if (domMsgs.length > 0) {
          body = (domMsgs[domMsgs.length - 1].textContent || '').substring(0, 200);
        }
      }
      if (body.length >= 200) {
        var sp = body.lastIndexOf(' ');
        if (sp > 150) body = body.substring(0, sp);
        body += '...';
      }
      var title = 'Claude finished in ' + (chatTitle.textContent || sessionName);
      sendNtfy(title, body);
    }
  }

  // ========== Voice Input ==========
  var mediaRecorder = null;
  var audioChunks = [];

  function setMicState(s) {
    micBtn.className = 'mic-inline-btn ' + s;
    if (s === 'idle') {
      micLabel.textContent = '';
    } else if (s === 'recording') {
      micLabel.textContent = 'Listening...';
    } else if (s === 'transcribing') {
      micLabel.textContent = 'Transcribing (server)...';
    }
  }

  micBtn.addEventListener('click', function() {
    if (isRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  });

  function startRecording() {
    if (hasNativeSTT) {
      micLabel.textContent = 'Listening (on-device)...';
      startNativeRecording();
    } else {
      micLabel.textContent = 'Recording (Whisper)...';
      startWhisperRecording();
    }
  }

  // --- Native Web Speech API path ---
  function startNativeRecording() {
    recognition = new NativeSR();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = 'en-US';

    finalTranscript = '';
    isRecording = true;
    setMicState('recording');

    recognition.onresult = function(e) {
      var interim = '';
      for (var i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) finalTranscript += e.results[i][0].transcript;
        else interim += e.results[i][0].transcript;
      }
      var display = (finalTranscript + interim).trim();
      if (display) micLabel.textContent = display;
    };

    recognition.onend = function() {
      isRecording = false;
      var text = finalTranscript.trim();
      if (text) { textInput.value = text; textInput.focus(); toggleSendMic(); }
      else { micLabel.textContent = 'No speech detected'; setTimeout(function() { micLabel.textContent = ''; }, 1500); }
      setMicState('idle');
    };

    recognition.onerror = function(e) {
      isRecording = false;
      if (e.error === 'not-allowed') {
        micLabel.textContent = 'Native mic denied, falling back to Whisper...';
        hasNativeSTT = false;
        setTimeout(function() { startWhisperRecording(); }, 500);
        return;
      }
      micLabel.textContent = e.error === 'no-speech' ? 'No speech detected' : 'Error: ' + e.error;
      setTimeout(function() { micLabel.textContent = ''; }, 2000);
      setMicState('idle');
    };

    recognition.start();
  }

  // --- Whisper fallback path (MediaRecorder + server-side STT) ---
  function startWhisperRecording() {
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function(stream) {
      isRecording = true;
      setMicState('recording');
      audioChunks = [];

      var mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus'
        : MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : 'audio/mp4';
      mediaRecorder = new MediaRecorder(stream, { mimeType: mimeType });
      mediaRecorder.ondataavailable = function(e) { if (e.data.size > 0) audioChunks.push(e.data); };
      mediaRecorder.onstop = function() {
        stream.getTracks().forEach(function(t) { t.stop(); });
        if (audioChunks.length === 0) { setMicState('idle'); return; }
        setMicState('transcribing');
        var blob = new Blob(audioChunks, { type: mimeType });
        var form = new FormData();
        form.append('file', blob, 'recording.webm');
        fetch('/api/transcribe', { method: 'POST', body: form })
          .then(function(r) { return r.json(); })
          .then(function(data) {
            var text = (data.text || '').trim();
            if (text) { textInput.value = text; textInput.focus(); toggleSendMic(); }
            else { micLabel.textContent = 'No speech detected'; setTimeout(function() { micLabel.textContent = ''; }, 1500); }
          })
          .catch(function(err) {
            micLabel.textContent = 'Transcription failed';
            setTimeout(function() { micLabel.textContent = ''; }, 2000);
          })
          .finally(function() { setMicState('idle'); });
      };
      mediaRecorder.start();

      // Auto-stop after 30 seconds
      setTimeout(function() { if (isRecording) stopRecording(); }, 30000);
    }).catch(function() {
      micLabel.textContent = 'Mic blocked - open Settings > Safari > Microphone';
      setMicState('idle');
    });
  }

  function stopRecording() {
    if (!isRecording) return;
    isRecording = false;
    if (recognition) recognition.stop();
    if (mediaRecorder && mediaRecorder.state !== 'inactive') mediaRecorder.stop();
  }

  // ========== Init ==========
  loadSessions();
  startSessionListPolling();

})();
</script>
</body>
</html>"""

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
    """Return list of sessions where pane_current_command == 'claude'."""
    try:
        raw = run_tmux(
            "list-panes", "-a",
            "-F", "#{session_name}\t#{pane_pid}\t#{pane_current_command}\t#{pane_current_path}"
        )
    except RuntimeError:
        return []

    sessions = []
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        sname, pid_str, cmd, cwd = parts[0], parts[1], parts[2], parts[3]
        if cmd != "claude":
            continue
        # Skip names starting with '-' -- they break tmux -t flag parsing
        if sname.startswith("-"):
            continue

        meta: dict = {}
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
        })

    return sessions


def _is_claude_session(name: str) -> bool:
    """Return True if the named session has a pane running 'claude'."""
    for s in discover_sessions():
        if s["name"] == name:
            return True
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
    _BG_CMD_RE = re.compile(r"^Background command ")

    def _is_visible(m):
        if not m.get("content", "").strip() and m["role"] != "tool":
            return False
        if m["role"] == "assistant":
            c = m["content"].strip()
            if _TOOL_LEAK_RE.match(c):
                return False
            if _BG_CMD_RE.match(c):
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


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(INDEX_HTML, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@app.get("/api/sessions")
async def list_sessions():
    sessions = discover_sessions()
    result = []
    for s in sessions:
        name = s["name"]
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

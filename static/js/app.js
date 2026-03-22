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
  var sessionScrollPositions = {};

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
  var showHiddenToggle = document.getElementById('showHiddenToggle');

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
    if (currentSession) {
      sessionScrollPositions[currentSession] = chatFeed.scrollTop;
    }
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

    // clear feed and show loading state
    while (chatFeed.firstChild) chatFeed.removeChild(chatFeed.firstChild);
    var loadingEl = document.createElement('div');
    loadingEl.className = 'empty-state';
    loadingEl.id = 'chatLoading';
    loadingEl.innerHTML = '<div class="typing-dot" style="animation:typingPulse 1.2s infinite"></div><div class="typing-dot" style="animation:typingPulse 1.2s infinite 0.2s"></div><div class="typing-dot" style="animation:typingPulse 1.2s infinite 0.4s"></div>';
    loadingEl.style.flexDirection = 'row';
    loadingEl.style.gap = '5px';
    chatFeed.appendChild(loadingEl);
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
    // Remove old wrappers and bare cards
    var oldWrappers = sessionListEl.querySelectorAll('.session-card-wrapper');
    for (var i = 0; i < oldWrappers.length; i++) {
      sessionListEl.removeChild(oldWrappers[i]);
    }
    var oldCards = sessionListEl.querySelectorAll('.session-card');
    for (var i = 0; i < oldCards.length; i++) {
      sessionListEl.removeChild(oldCards[i]);
    }

    // Filter hidden
    var hidden = [];
    try { hidden = JSON.parse(localStorage.getItem('hidden_sessions') || '[]'); } catch(e) {}
    var showHidden = showHiddenToggle._showHidden || false;
    var visibleSessions = showHidden ? sessions : sessions.filter(function(s) {
      return hidden.indexOf(s.name) === -1;
    });
    var hiddenCount = sessions.length - sessions.filter(function(s) { return hidden.indexOf(s.name) === -1; }).length;

    sessionCountEl.textContent = String(visibleSessions.length);

    if (visibleSessions.length === 0) {
      emptyStateEl.style.display = '';
      showHiddenToggle.style.display = hiddenCount > 0 ? '' : 'none';
      return;
    }
    emptyStateEl.style.display = 'none';
    showHiddenToggle.style.display = hiddenCount > 0 ? '' : 'none';
    showHiddenToggle.textContent = showHidden ? 'Hide hidden sessions' : 'Show ' + hiddenCount + ' hidden';

    visibleSessions.forEach(function(s) {
      var wrapper = document.createElement('div');
      wrapper.className = 'session-card-wrapper';

      // Swipe action behind card
      var actions = document.createElement('div');
      actions.className = 'swipe-actions';
      var actionBtn = document.createElement('button');
      actionBtn.className = 'swipe-action-btn ' + (s.state === 'dead' ? 'dismiss' : 'kill');
      actionBtn.textContent = s.state === 'dead' ? 'Dismiss' : 'Kill';
      actionBtn.addEventListener('click', function() {
        if (s.state === 'dead') {
          dismissSession(s.name);
        } else {
          killSession(s.name);
        }
      });
      actions.appendChild(actionBtn);
      wrapper.appendChild(actions);

      // Card
      var card = document.createElement('div');
      card.className = 'session-card' + (s.state === 'dead' ? ' dead' : '');
      card.setAttribute('data-name', s.name);

      var top = document.createElement('div');
      top.className = 'session-card-top';

      var title = document.createElement('div');
      title.className = 'session-card-title';
      title.textContent = s.title || s.name;

      var meta = document.createElement('div');
      meta.className = 'session-card-meta';

      var timeEl = document.createElement('span');
      timeEl.className = 'session-card-time';
      timeEl.textContent = s.last_activity || '';

      var dot = document.createElement('div');
      dot.className = 'session-card-status' + (s.state === 'dead' ? '' : (s.status === 'working' ? ' working' : ''));

      meta.appendChild(timeEl);
      meta.appendChild(dot);
      if (s.state === 'dead') {
        var deadLabel = document.createElement('span');
        deadLabel.className = 'session-card-dead-label';
        deadLabel.textContent = 'EXITED';
        meta.appendChild(deadLabel);
      }
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

      // Respawn button for dead sessions
      if (s.state === 'dead') {
        var respawnBtn = document.createElement('button');
        respawnBtn.className = 'respawn-btn';
        respawnBtn.textContent = 'Respawn';
        respawnBtn.addEventListener('click', function(e) {
          e.stopPropagation();
          respawnSession(s.name);
        });
        card.appendChild(respawnBtn);
      }

      // Click to open (only active sessions)
      if (s.state === 'active') {
        card.addEventListener('click', function() {
          // Immediate visual feedback
          card.style.opacity = '0.5';
          card.style.transform = 'scale(0.97)';
          showSessionView(s.name);
        });
      }

      wrapper.appendChild(card);

      // Swipe gesture
      var startX = 0, currentX = 0, swiping = false;
      card.addEventListener('touchstart', function(e) {
        startX = e.touches[0].clientX;
        currentX = startX;
        swiping = true;
        card.style.transition = 'none';
      }, { passive: true });
      card.addEventListener('touchmove', function(e) {
        if (!swiping) return;
        currentX = e.touches[0].clientX;
        var dx = currentX - startX;
        if (dx < 0) { // swipe left only
          card.style.transform = 'translateX(' + Math.max(dx, -100) + 'px)';
        }
      }, { passive: true });
      card.addEventListener('touchend', function() {
        if (!swiping) return;
        swiping = false;
        card.style.transition = 'transform 200ms ease-out';
        var dx = currentX - startX;
        if (dx < -60) {
          // Keep open to show action
          card.style.transform = 'translateX(-80px)';
        } else {
          card.style.transform = 'translateX(0)';
        }
      }, { passive: true });

      sessionListEl.appendChild(wrapper);
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
        var savedPos = sessionScrollPositions[name];
        if (savedPos !== undefined) {
          chatFeed.scrollTop = savedPos;
        } else {
          scrollToBottom(true);
        }
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
    function normalize(s) { return (s || '').replace(/\s+/g, ' ').trim().toLowerCase(); }
    pendingMessages = pendingMessages.filter(function(pm) {
      if (now - pm.ts > 30000) return false; // expire after 30s
      var pmNorm = normalize(pm.content);
      var pmSnippet = pmNorm.substring(0, 30);
      if (!pmSnippet) return false; // empty pending msg, drop it
      var found = messages.some(function(m) {
        if (m.role !== 'user') return false;
        var mNorm = normalize(m.content);
        // Primary check: first 30 chars match (after whitespace normalization + lowercase)
        if (mNorm.indexOf(pmSnippet) >= 0) return true;
        // Fallback: timestamp proximity (within 30s) AND content starts the same (first 15 chars)
        if (m.ts && Math.abs(m.ts - pm.ts) < 30000) {
          var shortSnippet = pmNorm.substring(0, 15);
          if (shortSnippet && mNorm.indexOf(shortSnippet) >= 0) return true;
        }
        return false;
      });
      return !found;
    });
    pendingMessages.forEach(function(pm) {
      appendMessage(pm, false);
    });
  }

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
      if (/^```/.test(line)) {
        var lang = line.replace(/^```\s*/, '').trim();
        var codeLines = [];
        i++;
        while (i < lines.length && !/^```/.test(lines[i])) {
          codeLines.push(lines[i]);
          i++;
        }
        i++;
        blocks.push({ type: 'code', content: codeLines.join('\n'), lang: lang });
        continue;
      }
      if (!line.trim()) { i++; continue; }
      var group = [];
      while (i < lines.length && lines[i].trim() && !/^```/.test(lines[i])) {
        group.push(lines[i]);
        i++;
      }
      blocks.push({ type: 'lines', lines: group });
    }
    for (var b = 0; b < blocks.length; b++) {
      var block = blocks[b];
      if (block.type === 'code') {
        var pre = document.createElement('pre');
        pre.className = 'code-block';
        var code = document.createElement('code');
        code.textContent = block.content.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>');
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
        })(block.content.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>'));
        pre.appendChild(copyBtn);
        frag.appendChild(pre);
        continue;
      }
      var groupLines = block.lines;
      var li = 0;
      while (li < groupLines.length) {
        var gl = groupLines[li];
        var headerMatch = gl.match(/^(#{1,3})\s+(.+)/);
        if (headerMatch) {
          var level = headerMatch[1].length;
          var h = document.createElement('h' + level);
          h.appendChild(applyInline(headerMatch[2]));
          frag.appendChild(h);
          li++;
          continue;
        }
        if (/^[-*]{3,}\s*$/.test(gl) && !/\S/.test(gl.replace(/[-*]/g, ''))) {
          frag.appendChild(document.createElement('hr'));
          li++;
          continue;
        }
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
      textSpan.appendChild(renderMarkdown(content));
      el.appendChild(textSpan);
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
        if (force && lastMessageCount === 0) {
          chatFeed.scrollTop = chatFeed.scrollHeight;
        } else {
          chatFeed.scrollTo({ top: chatFeed.scrollHeight, behavior: 'smooth' });
        }
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

  // ========== Session Management (kill / respawn / dismiss) ==========

  function findCardWrapper(name) {
    var card = sessionListEl.querySelector('.session-card[data-name="' + name + '"]');
    return card ? card.closest('.session-card-wrapper') : null;
  }

  function showActionToast(message, type) {
    var existing = document.querySelector('.action-toast');
    if (existing) existing.remove();
    var toast = document.createElement('div');
    toast.className = 'action-toast ' + (type || 'info');
    toast.textContent = message;
    document.body.appendChild(toast);
    requestAnimationFrame(function() {
      requestAnimationFrame(function() { toast.classList.add('visible'); });
    });
    setTimeout(function() {
      toast.classList.remove('visible');
      setTimeout(function() { if (toast.parentNode) toast.remove(); }, 250);
    }, 2500);
  }

  function killSession(name) {
    var wrapper = findCardWrapper(name);
    if (wrapper) {
      var btn = wrapper.querySelector('.swipe-action-btn.kill');
      if (btn) {
        btn.innerHTML = '<span class="btn-spinner"></span> Killing';
        btn.classList.add('loading');
      }
      var card = wrapper.querySelector('.session-card');
      if (card) card.classList.add('processing');
    }

    fetch('/api/sessions/' + encodeURIComponent(name) + '/kill', { method: 'POST' })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        showActionToast(data.killed ? 'Session killed' : 'Could not kill -- try again', data.killed ? 'success' : 'error');
        loadSessions();
      })
      .catch(function() {
        showActionToast('Kill failed', 'error');
        loadSessions();
      });
  }

  function respawnSession(name) {
    var wrapper = findCardWrapper(name);
    if (wrapper) {
      var btn = wrapper.querySelector('.respawn-btn');
      if (btn) {
        btn.innerHTML = '<span class="btn-spinner"></span> Respawning';
        btn.classList.add('loading');
      }
    }

    fetch('/api/sessions/' + encodeURIComponent(name) + '/respawn', { method: 'POST' })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.respawned) {
          showActionToast('Session respawned', 'success');
        } else {
          showActionToast(data.message || 'Already running', 'info');
        }
        loadSessions();
      })
      .catch(function() {
        showActionToast('Respawn failed', 'error');
        loadSessions();
      });
  }

  function dismissSession(name) {
    var wrapper = findCardWrapper(name);
    if (wrapper) {
      var btn = wrapper.querySelector('.swipe-action-btn.dismiss');
      if (btn) {
        btn.innerHTML = '<span class="btn-spinner"></span>';
        btn.classList.add('loading');
      }
      wrapper.classList.add('dismissing');
    }

    fetch('/api/sessions/' + encodeURIComponent(name), { method: 'DELETE' })
      .then(function() {
        showActionToast('Session dismissed', 'success');
        setTimeout(loadSessions, 200);
      })
      .catch(function() {
        showActionToast('Dismiss failed', 'error');
        if (wrapper) wrapper.classList.remove('dismissing');
        loadSessions();
      });
  }

  // ========== Show Hidden Toggle ==========
  showHiddenToggle.addEventListener('click', function() {
    showHiddenToggle._showHidden = !showHiddenToggle._showHidden;
    loadSessions();
  });

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

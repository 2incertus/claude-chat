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
  var longPressTimer = null;

  // Tab title / browser notification state
  var workingSessionCount = 0;
  var defaultTitle = 'Claude Voice Chat';
  var hasUnreadMessages = false;

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
  var gearBtn = document.getElementById('gearBtn');
  var settingsBackdrop = document.getElementById('settingsBackdrop');
  var settingsPanel = document.getElementById('settingsPanel');
  var cmdBtn = document.getElementById('cmdBtn');
  var cmdPalette = document.getElementById('cmdPalette');
  var commandList = [];
  var newBtn = document.getElementById('newBtn');
  var newSessionBackdrop = document.getElementById('newSessionBackdrop');
  var newSessionPanel = document.getElementById('newSessionPanel');
  var presetList = document.getElementById('presetList');
  var customPath = document.getElementById('customPath');
  var customLaunch = document.getElementById('customLaunch');

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

  // ========== Desktop Detection ==========
  function isDesktop() {
    return window.innerWidth >= 768;
  }

  // ========== Navigation ==========
  // Per-session draft storage
  var sessionDrafts = {};

  function showDesktopEmptyState() {
    // Clear chat feed and show empty state
    while (chatFeed.firstChild) chatFeed.removeChild(chatFeed.firstChild);
    var empty = document.createElement('div');
    empty.className = 'desktop-empty-state';
    var icon = document.createElement('div');
    icon.className = 'desktop-empty-state-icon';
    icon.innerHTML = '&#9671;';
    var label = document.createElement('div');
    label.textContent = 'Select a session to view';
    empty.appendChild(icon);
    empty.appendChild(label);
    chatFeed.appendChild(empty);

    // Hide input area and typing indicator on desktop when no session
    var inputArea = document.getElementById('inputArea');
    if (inputArea) inputArea.style.display = 'none';
    typingIndicator.classList.remove('visible');
    chatTitle.textContent = 'Session';
    chatStatus.className = 'status-dot';
  }

  function updateActiveCard() {
    var cards = sessionListEl.querySelectorAll('.session-card');
    for (var i = 0; i < cards.length; i++) {
      var cardName = cards[i].getAttribute('data-name');
      if (cardName === currentSession) {
        cards[i].classList.add('active');
      } else {
        cards[i].classList.remove('active');
      }
    }
  }

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
    currentSessionStatus = '';
    hasUnreadMessages = false;
    stopPolling();
    stopTTS();
    hidePreview();

    if (isDesktop()) {
      // On desktop, keep both panels visible
      screenList.className = 'screen';
      screenChat.className = 'screen';
      showDesktopEmptyState();
    } else {
      screenList.className = 'screen';
      screenChat.className = 'screen hidden-right';
    }
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

    // Show input area (may have been hidden by desktop empty state)
    var inputArea = document.getElementById('inputArea');
    if (inputArea) inputArea.style.display = '';

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

    if (isDesktop()) {
      // On desktop, keep session list visible
      screenList.className = 'screen';
      screenChat.className = 'screen';
      updateActiveCard();
    } else {
      screenList.className = 'screen hidden-left';
      screenChat.className = 'screen';
    }

    loadSession(name);
    startPolling();
    updatePillPosition();
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

  function getPinnedSessions() {
    try { return JSON.parse(localStorage.getItem('pinned_sessions') || '[]'); } catch(e) { return []; }
  }

  function setPinnedSessions(arr) {
    localStorage.setItem('pinned_sessions', JSON.stringify(arr));
  }

  function togglePin(name) {
    var pinned = getPinnedSessions();
    var idx = pinned.indexOf(name);
    if (idx >= 0) {
      pinned.splice(idx, 1);
      showActionToast('Unpinned', 'info');
    } else {
      pinned.push(name);
      showActionToast('Pinned to top', 'success');
    }
    setPinnedSessions(pinned);
    loadSessions();
  }

  function renderSessionList(sessions) {
    // Remove old batch action button
    var oldBatch = sessionListEl.parentNode.querySelector('.batch-action-btn');
    if (oldBatch) oldBatch.remove();

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

    // Count active vs total for badge
    var activeCount = visibleSessions.filter(function(s) { return s.state !== 'dead'; }).length;
    var deadCount = visibleSessions.length - activeCount;
    var anyWorking = visibleSessions.some(function(s) { return s.status === 'working'; });

    // Track working count for tab title badge
    workingSessionCount = visibleSessions.filter(function(s) { return s.status === 'working'; }).length;
    updateTabTitle();

    if (deadCount > 0) {
      sessionCountEl.textContent = activeCount + '/' + visibleSessions.length;
    } else {
      sessionCountEl.textContent = String(visibleSessions.length);
    }
    // Working dot in badge
    var existingDot = sessionCountEl.querySelector('.badge-dot');
    if (anyWorking) {
      sessionCountEl.classList.add('has-working');
      if (!existingDot) {
        var dot = document.createElement('span');
        dot.className = 'badge-dot';
        sessionCountEl.appendChild(dot);
      }
    } else {
      sessionCountEl.classList.remove('has-working');
      if (existingDot) existingDot.remove();
    }

    if (visibleSessions.length === 0) {
      emptyStateEl.style.display = '';
      showHiddenToggle.style.display = hiddenCount > 0 ? '' : 'none';
      // Remove batch dismiss btn if present
      var oldBatch = sessionListEl.parentNode.querySelector('.batch-action-btn');
      if (oldBatch) oldBatch.remove();
      return;
    }
    emptyStateEl.style.display = 'none';
    showHiddenToggle.style.display = hiddenCount > 0 ? '' : 'none';
    showHiddenToggle.textContent = showHidden ? 'Hide hidden sessions' : 'Show ' + hiddenCount + ' hidden';

    // Sort: pinned first, then by original order
    var pinned = getPinnedSessions();
    visibleSessions.sort(function(a, b) {
      var aPin = pinned.indexOf(a.name) >= 0 ? 0 : 1;
      var bPin = pinned.indexOf(b.name) >= 0 ? 0 : 1;
      return aPin - bPin;
    });

    // Batch dismiss button for dead sessions
    var oldBatchBtn = sessionListEl.parentNode.querySelector('.batch-action-btn');
    if (oldBatchBtn) oldBatchBtn.remove();
    if (deadCount > 0) {
      var batchBtn = document.createElement('button');
      batchBtn.className = 'batch-action-btn';
      batchBtn.textContent = 'Dismiss all exited (' + deadCount + ')';
      batchBtn.addEventListener('click', function() {
        batchBtn.classList.add('loading');
        batchBtn.innerHTML = '<span class="btn-spinner"></span> Dismissing...';
        var deadNames = visibleSessions.filter(function(s) { return s.state === 'dead'; }).map(function(s) { return s.name; });
        var promises = deadNames.map(function(n) {
          return fetch('/api/sessions/' + encodeURIComponent(n), { method: 'DELETE' });
        });
        Promise.all(promises).then(function() {
          showActionToast('Dismissed ' + deadNames.length + ' session' + (deadNames.length > 1 ? 's' : ''), 'success');
          loadSessions();
        }).catch(function() {
          showActionToast('Some dismissals failed', 'error');
          loadSessions();
        });
      });
      // Insert before session list
      sessionListEl.parentNode.insertBefore(batchBtn, sessionListEl);
    }

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
      var isPinned = pinned.indexOf(s.name) >= 0;
      var card = document.createElement('div');
      card.className = 'session-card' + (s.state === 'dead' ? ' dead' : '') + (isPinned ? ' pinned' : '');
      card.setAttribute('data-name', s.name);

      // Pin indicator
      if (isPinned) {
        var pinIcon = document.createElement('span');
        pinIcon.className = 'session-card-pin';
        pinIcon.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M16 12V4h1V2H7v2h1v8l-2 2v2h5.2v6h1.6v-6H18v-2l-2-2z"/></svg>';
        card.appendChild(pinIcon);
      }

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
      var dotClass = 'session-card-status';
      if (s.state !== 'dead') {
        if (s.status === 'working') dotClass += ' working';
        else if (s.status === 'waiting_input') dotClass += ' waiting';
      }
      dot.className = dotClass;

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

      // Click to open (only active sessions), skip if long-press triggered
      if (s.state === 'active') {
        card.addEventListener('click', function() {
          if (longPressTriggered) return;
          // Immediate visual feedback
          card.style.opacity = '0.5';
          card.style.transform = 'scale(0.97)';
          showSessionView(s.name);
        });
      }

      wrapper.appendChild(card);

      // Swipe gesture + long-press to pin
      var startX = 0, currentX = 0, swiping = false;
      var cardLongPress = null;
      var longPressTriggered = false;
      var startY = 0;
      card.addEventListener('touchstart', function(e) {
        startX = e.touches[0].clientX;
        startY = e.touches[0].clientY;
        currentX = startX;
        swiping = true;
        longPressTriggered = false;
        card.style.transition = 'none';
        // Long-press timer
        cardLongPress = setTimeout(function() {
          longPressTriggered = true;
          togglePin(s.name);
        }, 500);
      }, { passive: true });
      card.addEventListener('touchmove', function(e) {
        if (!swiping) return;
        currentX = e.touches[0].clientX;
        var dx = currentX - startX;
        var dy = Math.abs(e.touches[0].clientY - startY);
        // Cancel long-press if finger moves
        if ((Math.abs(dx) > 10 || dy > 10) && cardLongPress) {
          clearTimeout(cardLongPress);
          cardLongPress = null;
        }
        if (dx < 0) { // swipe left only
          card.style.transform = 'translateX(' + Math.max(dx, -100) + 'px)';
        }
      }, { passive: true });
      card.addEventListener('touchend', function() {
        if (cardLongPress) { clearTimeout(cardLongPress); cardLongPress = null; }
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

    // On desktop, highlight the active session card after re-render
    if (isDesktop() && currentSession) {
      updateActiveCard();
    }
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
        if (!isEditingTitle) chatTitle.textContent = data.title || data.name;
        updateStatusDot(data.status);
        updateWaitingInput(data.waiting_input);
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

  var currentSessionStatus = '';
  function updateStatusDot(status) {
    var prevSessionStatus = currentSessionStatus;
    currentSessionStatus = status;
    if (status === 'working') {
      chatStatus.className = 'status-dot working';
      typingIndicator.classList.add('visible');
    } else if (status === 'waiting_input') {
      chatStatus.className = 'status-dot waiting';
      typingIndicator.classList.remove('visible');
    } else {
      chatStatus.className = 'status-dot';
      typingIndicator.classList.remove('visible');
    }
    // Update working count estimate for tab title
    if (prevSessionStatus === 'working' && status !== 'working') {
      workingSessionCount = Math.max(0, workingSessionCount - 1);
      updateTabTitle();
    } else if (prevSessionStatus !== 'working' && status === 'working') {
      workingSessionCount = Math.max(1, workingSessionCount + 1);
      updateTabTitle();
    }
  }

  function updateWaitingInput(waiting) {
    var inputArea = document.getElementById('inputArea');
    if (!inputArea) return;
    var label = document.getElementById('waitingInputLabel');
    if (waiting) {
      inputArea.classList.add('waiting-input');
      if (!label) {
        label = document.createElement('div');
        label.id = 'waitingInputLabel';
        label.className = 'waiting-input-label';
        label.textContent = 'Claude is waiting for your response';
        inputArea.insertBefore(label, inputArea.firstChild);
      }
      textInput.focus();
    } else {
      inputArea.classList.remove('waiting-input');
      if (label) {
        label.parentNode.removeChild(label);
      }
    }
  }

  function renderMessages(messages) {
    // Clear feed
    while (chatFeed.firstChild) chatFeed.removeChild(chatFeed.firstChild);

    // Group consecutive tool calls into collapsible activity blocks
    var i = 0;
    while (i < messages.length) {
      var m = messages[i];
      if (m.role === 'tool') {
        // Collect consecutive tool messages
        var toolGroup = [];
        while (i < messages.length && messages[i].role === 'tool') {
          toolGroup.push(messages[i]);
          i++;
        }
        appendToolGroup(toolGroup);
      } else {
        appendMessage(m, false, messages, i);
        i++;
      }
    }

    // Re-append pending messages not yet in server data
    var now = Date.now();
    var hadConfirmed = false;
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
      if (found && pm._pending) hadConfirmed = true;
      return !found;
    });
    // Show brief "Sent" confirmation when a pending message was just confirmed
    if (hadConfirmed) {
      showSentConfirmation();
    }
    pendingMessages.forEach(function(pm) {
      appendMessage(pm, false, null, -1);
    });
  }

  // ========== Markdown Renderer ==========
  function renderMarkdown(text) {
    var frag = document.createDocumentFragment();
    // Escape HTML entities first (security)
    text = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
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
      // Detect markdown tables (lines starting with |)
      if (/^\|/.test(line)) {
        var tableLines = [];
        while (i < lines.length && /^\|/.test(lines[i])) {
          tableLines.push(lines[i]);
          i++;
        }
        blocks.push({ type: 'table', lines: tableLines });
        continue;
      }
      var group = [];
      while (i < lines.length && lines[i].trim() && !/^```/.test(lines[i]) && !/^\|/.test(lines[i])) {
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
      if (block.type === 'table') {
        var tableWrap = document.createElement('div');
        tableWrap.className = 'table-wrap';
        var table = document.createElement('table');
        var tLines = block.lines;
        for (var ti = 0; ti < tLines.length; ti++) {
          var tl = tLines[ti].replace(/^\|/, '').replace(/\|$/, '');
          var cells = tl.split('|');
          // Skip separator rows (|---|---|)
          if (cells.length > 0 && /^[\s\-:]+$/.test(cells.join(''))) continue;
          var row = document.createElement('tr');
          var isHeader = ti === 0;
          for (var ci = 0; ci < cells.length; ci++) {
            var cell = document.createElement(isHeader ? 'th' : 'td');
            cell.appendChild(applyInline(cells[ci].trim()));
            row.appendChild(cell);
          }
          if (isHeader) {
            var thead = document.createElement('thead');
            thead.appendChild(row);
            table.appendChild(thead);
          } else {
            var tbody = table.querySelector('tbody');
            if (!tbody) { tbody = document.createElement('tbody'); table.appendChild(tbody); }
            tbody.appendChild(row);
          }
        }
        tableWrap.appendChild(table);
        frag.appendChild(tableWrap);
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

  function appendToolGroup(tools) {
    // Separate Agent/Skill calls from regular tools
    var agents = [];
    var regular = [];
    for (var t = 0; t < tools.length; t++) {
      if (tools[t].tool === 'Agent' || tools[t].tool === 'Skill') {
        agents.push(tools[t]);
      } else {
        regular.push(tools[t]);
      }
    }

    // Render Agent/Skill calls as individual collapsible cards
    for (var a = 0; a < agents.length; a++) {
      appendMessage(agents[a], false, null, -1);
    }

    // Group regular tools into a single collapsible activity block
    if (regular.length === 0) return;

    var block = document.createElement('div');
    block.className = 'tool-activity-block';

    var header = document.createElement('div');
    header.className = 'tool-activity-header';

    // Build summary: unique tool names
    var toolNames = {};
    for (var r = 0; r < regular.length; r++) {
      var tn = regular[r].tool || 'tool';
      toolNames[tn] = (toolNames[tn] || 0) + 1;
    }
    var parts = [];
    for (var name in toolNames) {
      parts.push(name + (toolNames[name] > 1 ? ' \u00d7' + toolNames[name] : ''));
    }

    var icon = document.createElement('span');
    icon.className = 'tool-activity-icon';
    icon.textContent = '\u2699';

    var summary = document.createElement('span');
    summary.className = 'tool-activity-summary';
    summary.textContent = parts.join(', ');

    var count = document.createElement('span');
    count.className = 'tool-activity-count';
    count.textContent = regular.length + (regular.length === 1 ? ' action' : ' actions');

    var toggle = document.createElement('span');
    toggle.className = 'tool-activity-toggle collapsed';
    toggle.textContent = '\u25BC';

    header.appendChild(icon);
    header.appendChild(summary);
    header.appendChild(count);
    header.appendChild(toggle);

    var body = document.createElement('div');
    body.className = 'tool-activity-body collapsed';

    for (var r = 0; r < regular.length; r++) {
      var item = document.createElement('div');
      item.className = 'tool-activity-item';
      var toolContent = (regular[r].content || '').split('\\n')[0].split('\n')[0].trim();
      var toolSummary = toolContent.length > 70 ? toolContent.substring(0, 70) + '\u2026' : toolContent;
      item.textContent = (regular[r].tool || 'tool') + '(' + toolSummary + ')';
      body.appendChild(item);
    }

    header.addEventListener('click', function() {
      body.classList.toggle('collapsed');
      toggle.classList.toggle('collapsed');
    });

    block.appendChild(header);
    block.appendChild(body);
    block.style.animation = 'none';
    chatFeed.appendChild(block);
  }

  function appendMessage(m, animate, allMsgs, msgIdx) {
    var el;
    if (m.role === 'user') {
      // Wrap user messages in a container to allow status indicator below
      var wrapper = document.createElement('div');
      wrapper.className = 'msg-user-wrapper';
      el = document.createElement('div');
      el.className = 'msg msg-user';
      var userContent = m.content || m.text || '';
      if (userContent.startsWith('/')) {
        var spaceIdx = userContent.indexOf(' ');
        var cmdName = spaceIdx > 0 ? userContent.substring(0, spaceIdx) : userContent;
        var cmdArgs = spaceIdx > 0 ? userContent.substring(spaceIdx) : '';
        var pill = document.createElement('span');
        pill.className = 'cmd-pill';
        pill.textContent = cmdName;
        el.appendChild(pill);
        if (cmdArgs) el.appendChild(document.createTextNode(cmdArgs));
      } else {
        el.textContent = userContent;
      }
      if (m._pending) {
        var statusEl = document.createElement('div');
        statusEl.className = 'msg-status msg-status-pending';
        statusEl.textContent = 'Sending\u2026';
        wrapper.appendChild(el);
        wrapper.appendChild(statusEl);
        if (!animate) wrapper.style.animation = 'none';
        chatFeed.appendChild(wrapper);
        return;
      }
      if (!animate) el.style.animation = 'none';
    } else if (m.role === 'assistant') {
      // Check if preceding user message was a slash command
      var isCommandResult = false;
      var commandName = '';
      if (allMsgs && msgIdx > 0) {
        for (var pi = msgIdx - 1; pi >= 0; pi--) {
          if (allMsgs[pi].role === 'tool') continue;
          if (allMsgs[pi].role === 'user') {
            var uc = (allMsgs[pi].content || allMsgs[pi].text || '').trim();
            if (uc.startsWith('/')) {
              isCommandResult = true;
              var si = uc.indexOf(' ');
              commandName = si > 0 ? uc.substring(0, si) : uc;
              // Only first assistant message after command gets card
              var alreadyHandled = false;
              for (var ci = pi + 1; ci < msgIdx; ci++) {
                if (allMsgs[ci].role === 'assistant') { alreadyHandled = true; break; }
                if (allMsgs[ci].role === 'user') break;
              }
              if (alreadyHandled) isCommandResult = false;
            }
          }
          break;
        }
      }

      var content = m.content || m.text || '';

      // Detect agent status messages: 'Agent "name" completed/launched'
      var agentStatusMatch = content.match(/^Agent\s+"([^"]+)"\s*(completed|launched|failed)/i);
      if (!agentStatusMatch) agentStatusMatch = content.match(/^Agent\s+[\u201c]([^\u201d]+)[\u201d]\s*(completed|launched|failed)/i);
      if (agentStatusMatch) {
        el = document.createElement('div');
        el.className = 'agent-status-chip';
        var chipIcon = document.createElement('span');
        chipIcon.className = 'agent-status-icon';
        chipIcon.textContent = '\u25C7';
        var chipLabel = document.createElement('span');
        chipLabel.className = 'agent-status-label';
        chipLabel.textContent = 'Agent';
        var chipName = document.createElement('span');
        chipName.className = 'agent-status-name';
        chipName.textContent = agentStatusMatch[1];
        var chipStatus = document.createElement('span');
        chipStatus.className = 'agent-status-state ' + agentStatusMatch[2].toLowerCase();
        chipStatus.textContent = agentStatusMatch[2].toLowerCase();
        el.appendChild(chipIcon);
        el.appendChild(chipLabel);
        el.appendChild(chipName);
        el.appendChild(chipStatus);
        if (!animate) el.style.animation = 'none';
        chatFeed.appendChild(el);
        return;
      }

      if (isCommandResult) {
        el = document.createElement('div');
        el.className = 'cmd-result-card';
        var header = document.createElement('div');
        header.className = 'cmd-result-header';
        var hName = document.createElement('span');
        hName.className = 'cmd-result-name';
        hName.textContent = commandName;
        var hStatus = document.createElement('span');
        hStatus.className = 'cmd-result-status';
        hStatus.textContent = 'completed';
        var hToggle = document.createElement('span');
        hToggle.className = 'cmd-result-toggle';
        hToggle.textContent = '\u25BC';
        header.appendChild(hName);
        header.appendChild(hStatus);
        header.appendChild(hToggle);
        var body = document.createElement('div');
        body.className = 'cmd-result-body';
        var textSpan = document.createElement('div');
        textSpan.className = 'msg-assistant-text';
        textSpan.appendChild(renderMarkdown(content));
        body.appendChild(textSpan);
        var actions = document.createElement('div');
        actions.className = 'msg-actions';
        actions.style.padding = '0 14px 8px';
        var msgCopyBtn = document.createElement('button');
        msgCopyBtn.className = 'msg-action-btn msg-copy-btn';
        msgCopyBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>';
        (function(c) { msgCopyBtn.addEventListener('click', function(e) { e.stopPropagation(); copyToClipboard(c); }); })(content);
        actions.appendChild(msgCopyBtn);
        body.appendChild(actions);
        header.addEventListener('click', function() {
          body.classList.toggle('collapsed');
          hToggle.classList.toggle('collapsed');
        });
        el.appendChild(header);
        el.appendChild(body);
        if (!animate) el.style.animation = 'none';
      } else {
        // Normal assistant message -- keep existing rendering code
        el = document.createElement('div');
        el.className = 'msg msg-assistant';
        var textSpan = document.createElement('div');
        textSpan.className = 'msg-assistant-text';
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
      }
    } else if (m.role === 'tool') {
      if (m.tool === 'Agent' || m.tool === 'Skill') {
        // Agent/Skill calls get collapsible cards
        el = document.createElement('div');
        el.className = 'agent-result-card';
        var agentHeader = document.createElement('div');
        agentHeader.className = 'agent-result-header';
        var agentIcon = document.createElement('span');
        agentIcon.className = 'agent-result-icon';
        agentIcon.textContent = '\u25C7';
        var agentLabel = document.createElement('span');
        agentLabel.className = 'agent-result-label';
        agentLabel.textContent = m.tool || 'Agent';
        var agentDesc = document.createElement('span');
        agentDesc.className = 'agent-result-desc';
        var agentContent = m.content || '';
        agentDesc.textContent = agentContent.length > 80 ? agentContent.substring(0, 80) + '...' : agentContent;
        agentDesc.title = agentContent.length > 80 ? agentContent : '';
        var agentToggle = document.createElement('span');
        agentToggle.className = 'agent-result-toggle collapsed';
        agentToggle.textContent = '\u25BC';
        agentHeader.appendChild(agentIcon);
        agentHeader.appendChild(agentLabel);
        agentHeader.appendChild(agentDesc);
        agentHeader.appendChild(agentToggle);
        var agentBody = document.createElement('div');
        agentBody.className = 'agent-result-body collapsed';
        var agentText = document.createElement('div');
        agentText.className = 'msg-assistant-text';
        agentText.appendChild(renderMarkdown(agentContent));
        agentBody.appendChild(agentText);
        if (m.tool_results) {
          var toolResults = document.createElement('div');
          toolResults.className = 'agent-tool-results';
          var resultsArr = Array.isArray(m.tool_results) ? m.tool_results : [m.tool_results];
          // Separate backgrounded agent entries from regular results
          var bgAgents = [];
          var regularResults = [];
          for (var ri = 0; ri < resultsArr.length; ri++) {
            var rItem = typeof resultsArr[ri] === 'string' ? resultsArr[ri] : JSON.stringify(resultsArr[ri]);
            if (rItem.indexOf('Backgrounded agent') === 0 || rItem.indexOf('Backgrounded agent') >= 0 && rItem.indexOf('\u21b3') >= 0) {
              bgAgents.push(rItem);
            } else {
              regularResults.push(rItem);
            }
          }
          if (bgAgents.length > 0) {
            var bgLabel = document.createElement('div');
            bgLabel.className = 'agent-tool-results-label';
            bgLabel.textContent = 'Sub-agents (' + bgAgents.length + ')';
            toolResults.appendChild(bgLabel);
            for (var bi = 0; bi < bgAgents.length; bi++) {
              var subItem = document.createElement('div');
              subItem.className = 'agent-sub-item';
              var diamondIcon = document.createElement('span');
              diamondIcon.className = 'agent-sub-item-icon';
              diamondIcon.textContent = '\u25C7';
              var subDesc = document.createElement('span');
              subDesc.className = 'agent-sub-item-desc';
              subDesc.textContent = bgAgents[bi];
              subItem.appendChild(diamondIcon);
              subItem.appendChild(subDesc);
              toolResults.appendChild(subItem);
            }
          }
          if (regularResults.length > 0) {
            var trLabel = document.createElement('div');
            trLabel.className = 'agent-tool-results-label';
            trLabel.textContent = 'Tool Results';
            toolResults.appendChild(trLabel);
            var trContent = document.createElement('pre');
            trContent.className = 'code-block';
            trContent.style.margin = '4px 0 0';
            trContent.style.fontSize = '12px';
            trContent.textContent = regularResults.join('\n');
            toolResults.appendChild(trContent);
          }
          agentBody.appendChild(toolResults);
        }
        agentHeader.addEventListener('click', function() {
          agentBody.classList.toggle('collapsed');
          agentToggle.classList.toggle('collapsed');
        });
        el.appendChild(agentHeader);
        el.appendChild(agentBody);
        if (!animate) el.style.animation = 'none';
      } else {
        // Regular tool calls handled by appendToolGroup, skip here
        return;
      }
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
        updateWaitingInput(data.waiting_input);
        checkNtfyTrigger(currentSession, data.status, data.has_changes ? data.messages : null);

        if (data.has_changes && data.messages) {
          contentHash = data.content_hash || '';
          var newCount = data.messages.length;

          // Check if user is near bottom before updating
          checkScrollPosition();

          // Re-render all messages (content_hash changed)
          stopTTS(); // prevent dangling ttsPlayingBtn reference
          renderMessages(data.messages);

          // If new messages arrived and user is near bottom, scroll
          if (newCount > lastMessageCount) {
            if (isUserNearBottom) {
              scrollToBottom(false);
              hasUnreadMessages = false;
            } else {
              newMsgPill.classList.add('visible');
              hasUnreadMessages = true;
            }
            updateTabTitle();
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
    var speeds = POLL_SPEEDS[pollSpeedSetting] || POLL_SPEEDS.normal;
    var interval;
    if (idleCount < 3) interval = speeds.active;
    else if (idleCount < 6) interval = speeds.warm;
    else interval = speeds.idle;
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

  function updatePillPosition() {
    var area = document.getElementById('inputArea');
    if (area) {
      newMsgPill.style.bottom = (area.offsetHeight + 20) + 'px';
    }
  }

  chatFeed.addEventListener('scroll', function() {
    checkScrollPosition();
    if (isUserNearBottom) {
      newMsgPill.classList.remove('visible');
      if (hasUnreadMessages) {
        hasUnreadMessages = false;
        updateTabTitle();
      }
    }
  }, { passive: true });

  newMsgPill.addEventListener('click', function() {
    chatFeed.scrollTop = chatFeed.scrollHeight;
    newMsgPill.classList.remove('visible');
    hasUnreadMessages = false;
    updateTabTitle();
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
    var msg = { role: 'user', content: text, ts: Date.now(), _pending: true };
    pendingMessages.push(msg);
    appendMessage(msg, true, null, -1);
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

  function showSentConfirmation() {
    var existing = document.querySelector('.msg-sent-toast');
    if (existing) existing.remove();
    var toast = document.createElement('div');
    toast.className = 'msg-sent-toast';
    toast.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg> Sent';
    document.body.appendChild(toast);
    requestAnimationFrame(function() {
      requestAnimationFrame(function() { toast.classList.add('visible'); });
    });
    setTimeout(function() {
      toast.classList.remove('visible');
      setTimeout(function() { if (toast.parentNode) toast.remove(); }, 300);
    }, 2000);
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
  textInput.addEventListener('input', function() {
    requestAnimationFrame(function() {
      textInput.style.height = 'auto';
      textInput.style.height = Math.min(textInput.scrollHeight, 100) + 'px';
    });
    toggleSendMic();
  });

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

  // ========== Tab Title Badge ==========
  function updateTabTitle() {
    var title = defaultTitle;
    if (workingSessionCount > 0) {
      title = '(' + workingSessionCount + ') ' + defaultTitle;
    } else if (hasUnreadMessages) {
      title = '\u25CF ' + defaultTitle;
    }
    document.title = title;
  }

  // ========== Browser Push Notifications ==========
  function requestBrowserNotifPermission() {
    if (!('Notification' in window)) return;
    if (Notification.permission === 'default') {
      Notification.requestPermission().then(function() {});
    }
  }

  function showBrowserNotification(sessionName, sessionTitle) {
    if (!('Notification' in window)) return;
    if (Notification.permission !== 'granted') return;
    if (!document.hidden) return;

    var title = (sessionTitle || sessionName) + ' finished working';
    var notif = new Notification(title, {
      body: 'Session is now idle',
      icon: '/static/icon.svg',
      tag: 'claude-chat-' + sessionName
    });
    notif.onclick = function() {
      window.focus();
      notif.close();
      showSessionView(sessionName);
    };
  }

  // ========== Notification Sound ==========
  function playNotificationChime() {
    var s = getSettings();
    if (!s.notifSound) return;
    try {
      var ctx = new (window.AudioContext || window.webkitAudioContext)();
      var gain = ctx.createGain();
      gain.gain.value = 0.1;
      gain.connect(ctx.destination);

      // First tone: 800Hz for 100ms
      var osc1 = ctx.createOscillator();
      osc1.type = 'sine';
      osc1.frequency.value = 800;
      osc1.connect(gain);
      osc1.start(ctx.currentTime);
      osc1.stop(ctx.currentTime + 0.1);

      // Second tone: 1000Hz for 100ms after first
      var osc2 = ctx.createOscillator();
      osc2.type = 'sine';
      osc2.frequency.value = 1000;
      osc2.connect(gain);
      osc2.start(ctx.currentTime + 0.1);
      osc2.stop(ctx.currentTime + 0.2);

      // Clean up after playback
      osc2.onended = function() {
        gain.disconnect();
        ctx.close();
      };
    } catch(e) {}
  }

  // ========== ntfy Notifications ==========
  var previousStatus = {};
  var lastNtfyTime = {};

  function isNtfyEnabled(session) {
    try {
      var s = JSON.parse(localStorage.getItem('ntfy_sessions') || '{}');
      if (session in s) return !!s[session];
      var settings = getSettings();
      return !!settings.defaultNtfy;
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
    if (now) {
      requestBrowserNotifPermission();
    }
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

      // Browser push notification (only when tab is hidden)
      if (statusTransition) {
        showBrowserNotification(sessionName, chatTitle.textContent || sessionName);
        playNotificationChime();
      }
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

  // ========== Session Title Editing ==========
  var isEditingTitle = false;

  chatTitle.addEventListener('click', function() {
    if (isEditingTitle || !currentSession) return;
    isEditingTitle = true;
    var original = chatTitle.textContent;
    var input = document.createElement('input');
    input.type = 'text';
    input.value = original;
    input.style.cssText = 'background:var(--surface2);color:var(--text);border:1px solid var(--accent);border-radius:8px;padding:4px 8px;font-size:0.9rem;font-family:inherit;outline:none;width:100%;text-align:center;';
    chatTitle.textContent = '';
    chatTitle.appendChild(input);
    input.focus();
    input.select();

    function save() {
      var newTitle = input.value.trim();
      if (newTitle && newTitle !== original) {
        chatTitle.textContent = newTitle;
        fetch('/api/sessions/' + encodeURIComponent(currentSession) + '/title', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: newTitle })
        }).catch(function() {});
      } else {
        chatTitle.textContent = original;
      }
      isEditingTitle = false;
    }

    input.addEventListener('blur', save);
    input.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
      if (e.key === 'Escape') { input.value = original; input.blur(); }
    });
  });

  // ========== Command Palette ==========
  function fetchCommands() {
    fetch('/api/commands')
      .then(function(r) { return r.json(); })
      .then(function(data) { commandList = data.commands || []; })
      .catch(function() {});
  }

  function showPalette(filter) {
    var items = commandList;
    if (filter) {
      var f = filter.toLowerCase();
      items = items.filter(function(c) {
        return c.name.toLowerCase().indexOf(f) >= 0 || c.desc.toLowerCase().indexOf(f) >= 0;
      });
    }
    if (items.length === 0) {
      hidePalette();
      return;
    }
    while (cmdPalette.firstChild) cmdPalette.removeChild(cmdPalette.firstChild);
    for (var i = 0; i < items.length; i++) {
      var item = document.createElement('div');
      item.className = 'cmd-item';
      var nameEl = document.createElement('span');
      nameEl.className = 'cmd-item-name';
      nameEl.textContent = items[i].name;
      var descEl = document.createElement('span');
      descEl.className = 'cmd-item-desc';
      descEl.textContent = items[i].desc;
      item.appendChild(nameEl);
      item.appendChild(descEl);
      (function(cmd) {
        item.addEventListener('click', function() {
          textInput.value = cmd.name + ' ';
          textInput.focus();
          hidePalette();
          toggleSendMic();
        });
      })(items[i]);
      cmdPalette.appendChild(item);
    }
    cmdPalette.classList.add('visible');
  }

  function hidePalette() {
    cmdPalette.classList.remove('visible');
  }

  textInput.addEventListener('input', function() {
    var val = textInput.value;
    if (val.startsWith('/') && val.indexOf('\n') === -1) {
      var filter = val.substring(1);
      showPalette(filter ? '/' + filter : '');
    } else {
      hidePalette();
    }
  });

  cmdBtn.addEventListener('click', function() {
    if (cmdPalette.classList.contains('visible')) {
      hidePalette();
    } else {
      showPalette('');
    }
  });

  document.addEventListener('click', function(e) {
    if (!cmdPalette.contains(e.target) && e.target !== cmdBtn && e.target !== textInput) {
      hidePalette();
    }
  });

  fetchCommands();

  // ========== New Session ==========
  function openNewSession() {
    fetch('/api/config')
      .then(function(r) { return r.json(); })
      .then(function(config) {
        while (presetList.firstChild) presetList.removeChild(presetList.firstChild);
        var presets = config.presets || [];
        presets.forEach(function(p) {
          var card = document.createElement('div');
          card.className = 'preset-card';
          var name = document.createElement('div');
          name.className = 'preset-card-name';
          name.textContent = p.name;
          var path = document.createElement('div');
          path.className = 'preset-card-path';
          path.textContent = p.path;
          card.appendChild(name);
          card.appendChild(path);
          card.addEventListener('click', function() {
            createSession(p.path, '');
          });
          presetList.appendChild(card);
        });
      })
      .catch(function() {});
    customPath.value = '';
    newSessionBackdrop.classList.add('visible');
    newSessionPanel.classList.add('visible');
  }

  function closeNewSession() {
    newSessionBackdrop.classList.remove('visible');
    newSessionPanel.classList.remove('visible');
  }

  function createSession(path, name) {
    closeNewSession();
    showActionToast('Creating session...', 'info');
    fetch('/api/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: path, name: name })
    })
    .then(function(r) {
      if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || 'Failed'); });
      return r.json();
    })
    .then(function(data) {
      showActionToast('Session ' + data.name + ' created', 'success');
      loadSessions();
    })
    .catch(function(err) {
      showActionToast(err.message || 'Failed to create session', 'error');
    });
  }

  newBtn.addEventListener('click', openNewSession);
  newSessionBackdrop.addEventListener('click', closeNewSession);
  customLaunch.addEventListener('click', function() {
    var p = customPath.value.trim();
    if (p) createSession(p, '');
  });

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
      var metaTheme = document.querySelector('meta[name="theme-color"]');
      if (metaTheme) {
        metaTheme.setAttribute('content', value === 'oled' ? '#000000' : value === 'light' ? '#F2F0ED' : '#0A0A0A');
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
    var existing = settingsPanel.querySelectorAll('.settings-row');
    for (var i = 0; i < existing.length; i++) existing[i].remove();
    var s = getSettings();

    var themeRow = createSettingsRow('Theme', 'select', s.theme || 'dark', [
      { value: 'dark', label: 'Dark' },
      { value: 'oled', label: 'OLED Black' },
      { value: 'light', label: 'Light' }
    ], function(v) { saveSetting('theme', v); });
    settingsPanel.appendChild(themeRow);

    var pollRow = createSettingsRow('Poll Speed', 'select', s.pollSpeed || 'normal', [
      { value: 'fast', label: 'Fast' },
      { value: 'normal', label: 'Normal' },
      { value: 'saver', label: 'Battery Saver' }
    ], function(v) { saveSetting('pollSpeed', v); });
    settingsPanel.appendChild(pollRow);

    var voices = window.speechSynthesis ? speechSynthesis.getVoices() : [];
    var voiceOptions = [{ value: '', label: 'System Default' }];
    for (var vi = 0; vi < voices.length; vi++) {
      voiceOptions.push({ value: voices[vi].name, label: voices[vi].name });
    }
    var voiceRow = createSettingsRow('TTS Voice', 'select', s.chatVoice || '', voiceOptions, function(v) { saveSetting('chatVoice', v); });
    settingsPanel.appendChild(voiceRow);

    var ntfyRow = createSettingsRow('Default Notifications', 'toggle', !!s.defaultNtfy, null, function(v) { saveSetting('defaultNtfy', v); });
    settingsPanel.appendChild(ntfyRow);

    var soundRow = createSettingsRow('Notification Sound', 'toggle', !!s.notifSound, null, function(v) { saveSetting('notifSound', v); });
    settingsPanel.appendChild(soundRow);
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

  // ========== Keyboard Navigation ==========
  document.addEventListener('keydown', function(e) {
    var tag = (e.target.tagName || '').toLowerCase();
    var isInput = (tag === 'input' || tag === 'textarea' || tag === 'select');
    var settingsOpen = settingsPanel.classList.contains('visible');
    var newSessionOpen = newSessionPanel.classList.contains('visible');
    var paletteOpen = cmdPalette.classList.contains('visible');

    // Escape: close settings/new-session/command-palette, or go back to session list
    if (e.key === 'Escape') {
      if (settingsOpen) {
        closeSettings();
        e.preventDefault();
        return;
      }
      if (newSessionOpen) {
        closeNewSession();
        e.preventDefault();
        return;
      }
      if (paletteOpen) {
        hidePalette();
        e.preventDefault();
        return;
      }
      // If editing title, let the title handler deal with it
      if (isEditingTitle) return;
      // If text input is focused, blur it first
      if (isInput) {
        e.target.blur();
        e.preventDefault();
        return;
      }
      // Go back to session list (on mobile) or deselect on desktop
      if (currentSession) {
        showSessionList();
        e.preventDefault();
        return;
      }
    }

    // Don't handle other shortcuts when typing in inputs
    if (isInput) return;

    // Cmd/Ctrl + K: focus text input
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();
      if (currentSession) {
        textInput.focus();
      }
      return;
    }

    // Up/Down arrow: navigate session cards when session list is visible
    if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      var cards = sessionListEl.querySelectorAll('.session-card');
      if (cards.length === 0) return;

      // Find currently focused card
      var focusedIdx = -1;
      for (var i = 0; i < cards.length; i++) {
        if (cards[i].classList.contains('kb-focused')) {
          focusedIdx = i;
          break;
        }
      }

      // Remove old focus
      if (focusedIdx >= 0) {
        cards[focusedIdx].classList.remove('kb-focused');
      }

      // Calculate new index
      var newIdx;
      if (e.key === 'ArrowDown') {
        newIdx = (focusedIdx < 0) ? 0 : Math.min(focusedIdx + 1, cards.length - 1);
      } else {
        newIdx = (focusedIdx < 0) ? cards.length - 1 : Math.max(focusedIdx - 1, 0);
      }

      cards[newIdx].classList.add('kb-focused');
      cards[newIdx].scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      e.preventDefault();
      return;
    }

    // Enter: open focused session card
    if (e.key === 'Enter') {
      var focused = sessionListEl.querySelector('.session-card.kb-focused');
      if (focused) {
        var sessionName = focused.getAttribute('data-name');
        if (sessionName) {
          showSessionView(sessionName);
          e.preventDefault();
        }
      }
      return;
    }
  });

  // ========== Init ==========
  window.addEventListener('resize', function() {
    updatePillPosition();
    // Handle layout changes on resize (e.g. rotating tablet)
    if (isDesktop()) {
      // Ensure both panels visible on desktop
      screenList.className = 'screen';
      screenChat.className = 'screen';
      if (!currentSession) {
        showDesktopEmptyState();
      }
    } else {
      // Restore mobile layout
      if (currentSession) {
        screenList.className = 'screen hidden-left';
        screenChat.className = 'screen';
      } else {
        screenList.className = 'screen';
        screenChat.className = 'screen hidden-right';
      }
    }
  });
  loadSettings();
  loadSessions();
  startSessionListPolling();

  // On desktop, show empty state on initial load
  if (isDesktop()) {
    screenList.className = 'screen';
    screenChat.className = 'screen';
    showDesktopEmptyState();
  }

})();

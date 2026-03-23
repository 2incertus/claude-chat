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

  // Auth state
  var authToken = localStorage.getItem('auth_token') || '';

  // Voice state
  var NativeSR = window.SpeechRecognition || window.webkitSpeechRecognition;
  var hasNativeSTT = !!NativeSR;
  var recognition = null;
  var finalTranscript = '';
  var isRecording = false;
  var isProcessing = false;

  // ========== Auth Helpers ==========
  function authFetch(url, options) {
    options = options || {};
    if (!options.headers) {
      options.headers = {};
    }
    if (authToken) {
      options.headers['Authorization'] = 'Bearer ' + authToken;
    }
    return fetch(url, options);
  }

  function showLoginScreen() {
    var existing = document.querySelector('.login-screen');
    if (existing) existing.remove();

    var screen = document.createElement('div');
    screen.className = 'login-screen';

    var card = document.createElement('div');
    card.className = 'login-card';

    var titleEl = document.createElement('div');
    titleEl.className = 'login-title';
    titleEl.textContent = 'Claude Chat';

    var pinInput = document.createElement('input');
    pinInput.className = 'login-input';
    pinInput.type = 'tel';
    pinInput.placeholder = '\u2022\u2022\u2022\u2022';
    pinInput.maxLength = 6;
    pinInput.inputMode = 'numeric';
    pinInput.pattern = '[0-9]*';
    pinInput.autocomplete = 'off';
    pinInput.style.webkitTextSecurity = 'disc';
    pinInput.style.letterSpacing = '8px';
    pinInput.style.textAlign = 'center';
    pinInput.style.fontSize = '1.5rem';

    var errorEl = document.createElement('div');
    errorEl.className = 'login-error';
    errorEl.style.visibility = 'hidden';
    errorEl.textContent = 'Invalid PIN';

    var btn = document.createElement('button');
    btn.className = 'login-btn';
    btn.textContent = 'Enter';

    function doLogin() {
      var pin = pinInput.value.trim();
      if (!pin) return;
      btn.textContent = 'Checking...';
      btn.disabled = true;
      fetch('/api/auth', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pin: pin })
      })
      .then(function(r) {
        if (!r.ok) throw new Error('Invalid PIN');
        return r.json();
      })
      .then(function(data) {
        authToken = data.token;
        localStorage.setItem('auth_token', authToken);
        screen.remove();
        initApp();
      })
      .catch(function() {
        errorEl.style.visibility = 'visible';
        pinInput.classList.add('shake');
        btn.textContent = 'Enter';
        btn.disabled = false;
        pinInput.value = '';
        pinInput.focus();
        setTimeout(function() {
          pinInput.classList.remove('shake');
        }, 500);
      });
    }

    btn.addEventListener('click', doLogin);
    pinInput.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') { e.preventDefault(); doLogin(); }
    });

    card.appendChild(titleEl);
    card.appendChild(pinInput);
    card.appendChild(errorEl);
    card.appendChild(btn);
    screen.appendChild(card);
    document.body.appendChild(screen);
    pinInput.focus();
  }

  function logout() {
    authToken = '';
    localStorage.removeItem('auth_token');
    stopPolling();
    stopSessionListPolling();
    showLoginScreen();
  }

  function checkAuthAndInit() {
    if (!authToken) {
      fetch('/api/auth/check')
        .then(function(r) {
          if (r.ok) {
            initApp();
          } else {
            showLoginScreen();
          }
        })
        .catch(function() {
          initApp();
        });
      return;
    }
    fetch('/api/auth/check', {
      headers: { 'Authorization': 'Bearer ' + authToken }
    })
    .then(function(r) {
      if (r.ok) {
        initApp();
      } else {
        authToken = '';
        localStorage.removeItem('auth_token');
        showLoginScreen();
      }
    })
    .catch(function() {
      initApp();
    });
  }

  // ========== Elements ==========
  var screenList = document.getElementById('screenList');
  var screenChat = document.getElementById('screenChat');
  var sessionListEl = document.getElementById('sessionList');
  var sessionCountEl = document.getElementById('sessionCount');
  var emptyStateEl = document.getElementById('emptyState');
  var pullIndicator = document.getElementById('pullIndicator');
  var showHiddenToggle = document.getElementById('showHiddenToggle');
  var searchInput = document.getElementById('searchInput');
  var searchFilters = document.getElementById('searchFilters');
  var activeStatusFilter = 'all';

  var backBtn = document.getElementById('backBtn');
  var chatTitle = document.getElementById('chatTitle');
  var costBadge = document.getElementById('costBadge');
  var bottomInfo = document.getElementById('bottomInfo');
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
  var refreshBtn = document.getElementById('refreshBtn');
  var copyAllBtn = document.getElementById('copyAllBtn');
  var exportBtn = document.getElementById('exportBtn');
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
  var starFilterBtn = document.getElementById('starFilterBtn');
  var starFilterActive = false;

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

  // ========== Star/Pin Helpers ==========
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
    return idx < 0;
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
    updateCostBadge(null);

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
    starFilterActive = false;
    chatFeed.classList.remove('starred-only');
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
    authFetch('/api/sessions')
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

  // ========== Session Folder Helpers ==========
  function getSessionFolders() {
    try { return JSON.parse(localStorage.getItem('session_folders') || '{}'); } catch(e) { return {}; }
  }
  function setSessionFolder(sessionName, folder) {
    var folders = getSessionFolders();
    if (folder) folders[sessionName] = folder;
    else delete folders[sessionName];
    localStorage.setItem('session_folders', JSON.stringify(folders));
  }
  function getCollapsedFolders() {
    try { return JSON.parse(localStorage.getItem('collapsed_folders') || '[]'); } catch(e) { return []; }
  }
  function toggleFolderCollapsed(folderName) {
    var collapsed = getCollapsedFolders();
    var idx = collapsed.indexOf(folderName);
    if (idx >= 0) collapsed.splice(idx, 1);
    else collapsed.push(folderName);
    localStorage.setItem('collapsed_folders', JSON.stringify(collapsed));
    return idx < 0;
  }

  function createFolderHeader(name, count, isCollapsed) {
    var header = document.createElement('div');
    header.className = 'folder-header' + (isCollapsed ? ' collapsed' : '');
    header.setAttribute('data-folder', name);
    var chevron = document.createElement('span');
    chevron.className = 'folder-chevron';
    chevron.textContent = '\u25B6';
    var label = document.createElement('span');
    label.textContent = ' ' + name + ' ';
    var badge = document.createElement('span');
    badge.className = 'folder-count';
    badge.textContent = count;
    header.appendChild(chevron);
    header.appendChild(label);
    header.appendChild(badge);
    header.addEventListener('click', function() {
      var nowCollapsed = toggleFolderCollapsed(name);
      header.classList.toggle('collapsed', nowCollapsed);
      var next = header.nextElementSibling;
      while (next && !next.classList.contains('folder-header')) {
        next.style.display = nowCollapsed ? 'none' : '';
        next = next.nextElementSibling;
      }
    });
    return header;
  }

  function showFolderPicker(sessionName, anchorEl) {
    var existing = document.querySelector('.folder-picker-overlay');
    if (existing) existing.remove();

    var overlay = document.createElement('div');
    overlay.className = 'folder-picker-overlay';
    overlay.addEventListener('click', function() { overlay.remove(); });

    var picker = document.createElement('div');
    picker.className = 'folder-picker';
    picker.addEventListener('click', function(e) { e.stopPropagation(); });

    var titleEl = document.createElement('div');
    titleEl.className = 'folder-picker-title';
    titleEl.textContent = 'Move to folder';
    picker.appendChild(titleEl);

    var currentFolder = getSessionFolders()[sessionName] || '';
    var defaults = ['Active', 'Monitoring', 'Archive'];
    // Collect all unique folder names already in use
    var allFolders = getSessionFolders();
    var customFolders = [];
    Object.keys(allFolders).forEach(function(k) {
      var f = allFolders[k];
      if (f && defaults.indexOf(f) < 0 && customFolders.indexOf(f) < 0) customFolders.push(f);
    });
    var presets = [''].concat(defaults).concat(customFolders.sort());
    presets.forEach(function(f) {
      var btn = document.createElement('button');
      btn.className = 'folder-picker-option' + (currentFolder === f ? ' selected' : '');
      btn.textContent = f || 'None';
      btn.addEventListener('click', function() {
        setSessionFolder(sessionName, f);
        overlay.remove();
        showActionToast(f ? 'Moved to ' + f : 'Removed from folder', 'success');
        loadSessions();
      });
      picker.appendChild(btn);
    });

    var sep = document.createElement('div');
    sep.className = 'folder-picker-sep';
    picker.appendChild(sep);

    var customRow = document.createElement('div');
    customRow.className = 'folder-picker-custom';
    var customInput = document.createElement('input');
    customInput.type = 'text';
    customInput.placeholder = 'Custom folder...';
    customInput.className = 'folder-picker-input';
    var customBtn = document.createElement('button');
    customBtn.className = 'folder-picker-go';
    customBtn.textContent = 'Go';
    customBtn.addEventListener('click', function() {
      var val = customInput.value.trim();
      if (val) {
        setSessionFolder(sessionName, val);
        overlay.remove();
        showActionToast('Moved to ' + val, 'success');
        loadSessions();
      }
    });
    customInput.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') customBtn.click();
    });
    customRow.appendChild(customInput);
    customRow.appendChild(customBtn);
    picker.appendChild(customRow);

    overlay.appendChild(picker);
    document.body.appendChild(overlay);
    customInput.focus();
  }

  function renderSessionList(sessions) {
    // Remove old batch action button
    var oldBatch = sessionListEl.parentNode.querySelector('.batch-action-btn');
    if (oldBatch) oldBatch.remove();

    // Remove old groups, folder headers, wrappers, and bare cards
    var oldGroups = sessionListEl.querySelectorAll('.session-group');
    for (var i = 0; i < oldGroups.length; i++) {
      sessionListEl.removeChild(oldGroups[i]);
    }
    var oldFolderHeaders = sessionListEl.querySelectorAll('.folder-header');
    for (var i = 0; i < oldFolderHeaders.length; i++) {
      sessionListEl.removeChild(oldFolderHeaders[i]);
    }
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

    // Apply search filter
    var searchQuery = (searchInput.value || '').trim().toLowerCase();
    if (searchQuery) {
      visibleSessions = visibleSessions.filter(function(s) {
        return (s.name && s.name.toLowerCase().indexOf(searchQuery) !== -1) ||
               (s.title && s.title.toLowerCase().indexOf(searchQuery) !== -1) ||
               (s.cwd && s.cwd.toLowerCase().indexOf(searchQuery) !== -1) ||
               (s.preview && s.preview.toLowerCase().indexOf(searchQuery) !== -1);
      });
    }

    // Apply status filter
    if (activeStatusFilter !== 'all') {
      visibleSessions = visibleSessions.filter(function(s) {
        if (activeStatusFilter === 'dead') return s.state === 'dead';
        return s.status === activeStatusFilter;
      });
    }

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
          return authFetch('/api/sessions/' + encodeURIComponent(n), { method: 'DELETE' });
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

    // Helper: build a session card wrapper (card + swipe + gestures)
    function buildCardWrapper(s) {
      var wrapper = document.createElement('div');
      wrapper.className = 'session-card-wrapper';

      var actions = document.createElement('div');
      actions.className = 'swipe-actions';
      var actionBtn = document.createElement('button');
      actionBtn.className = 'swipe-action-btn ' + (s.state === 'dead' ? 'dismiss' : 'kill');
      actionBtn.textContent = s.state === 'dead' ? 'Dismiss' : 'Kill';
      actionBtn.addEventListener('click', function() {
        if (s.state === 'dead') { dismissSession(s.name); } else { killSession(s.name); }
      });
      actions.appendChild(actionBtn);
      var folderBtn = document.createElement('button');
      folderBtn.className = 'swipe-action-btn folder';
      folderBtn.textContent = 'Folder';
      folderBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        // Reset swipe position
        var cardEl = wrapper.querySelector('.session-card');
        if (cardEl) {
          cardEl.style.transition = 'transform 200ms ease-out';
          cardEl.style.transform = 'translateX(0)';
        }
        showFolderPicker(s.name, folderBtn);
      });
      actions.appendChild(folderBtn);
      wrapper.appendChild(actions);

      var isPinned = pinned.indexOf(s.name) >= 0;
      var card = document.createElement('div');
      card.className = 'session-card' + (s.state === 'dead' ? ' dead' : '') + (isPinned ? ' pinned' : '');
      card.setAttribute('data-name', s.name);

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

      if (s.preview) {
        var preview = document.createElement('div');
        preview.className = 'session-card-preview';
        preview.textContent = s.preview;
        card.appendChild(preview);
      }

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

      if (s.state === 'dead') {
        var respawnBtn = document.createElement('button');
        respawnBtn.className = 'respawn-btn';
        respawnBtn.textContent = 'Respawn';
        respawnBtn.addEventListener('click', function(e) { e.stopPropagation(); respawnSession(s.name); });
        card.appendChild(respawnBtn);
      }

      if (s.state === 'active') {
        card.addEventListener('click', function() {
          if (longPressTriggered) return;
          card.style.opacity = '0.5';
          card.style.transform = 'scale(0.97)';
          showSessionView(s.name);
        });
      }

      wrapper.appendChild(card);

      // Swipe + long-press gestures
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
        cardLongPress = setTimeout(function() { longPressTriggered = true; togglePin(s.name); }, 500);
      }, { passive: true });
      card.addEventListener('touchmove', function(e) {
        if (!swiping) return;
        currentX = e.touches[0].clientX;
        var dx = currentX - startX;
        var dy = Math.abs(e.touches[0].clientY - startY);
        if ((Math.abs(dx) > 10 || dy > 10) && cardLongPress) { clearTimeout(cardLongPress); cardLongPress = null; }
        if (dx < 0) card.style.transform = 'translateX(' + Math.max(dx, -160) + 'px)';
      }, { passive: true });
      card.addEventListener('touchend', function() {
        if (cardLongPress) { clearTimeout(cardLongPress); cardLongPress = null; }
        if (!swiping) return;
        swiping = false;
        card.style.transition = 'transform 200ms ease-out';
        var dx = currentX - startX;
        card.style.transform = dx < -60 ? 'translateX(-140px)' : 'translateX(0)';
      }, { passive: true });

      return wrapper;
    }

    // Group sessions by cwd
    var groups = {};
    var groupOrder = [];
    visibleSessions.forEach(function(s) {
      var key = s.cwd || 'Other';
      if (!groups[key]) { groups[key] = []; groupOrder.push(key); }
      groups[key].push(s);
    });

    // Retrieve collapsed state
    var collapsedGroups = {};
    try { collapsedGroups = JSON.parse(localStorage.getItem('collapsed_groups') || '{}'); } catch(e) {}

    // Build all card wrappers keyed by session name
    var allWrappers = [];
    visibleSessions.forEach(function(s) {
      allWrappers.push({ session: s, wrapper: buildCardWrapper(s) });
    });

    // Separate sessions by folder assignment
    var sessionFolders = getSessionFolders();
    var ungrouped = [];
    var folderGroups = {};
    var folderOrder = [];
    allWrappers.forEach(function(item) {
      var folder = sessionFolders[item.session.name];
      if (folder) {
        if (!folderGroups[folder]) { folderGroups[folder] = []; folderOrder.push(folder); }
        folderGroups[folder].push(item);
      } else {
        ungrouped.push(item);
      }
    });

    var hasFolders = folderOrder.length > 0;
    var collapsedFoldersList = getCollapsedFolders();

    if (!hasFolders) {
      // No folder assignments -- use original cwd grouping
      if (groupOrder.length <= 1) {
        visibleSessions.forEach(function(s) {
          var match = allWrappers.filter(function(w) { return w.session === s; })[0];
          if (match) sessionListEl.appendChild(match.wrapper);
        });
      } else {
        groupOrder.forEach(function(groupPath) {
          var groupSessions = groups[groupPath];
          var groupEl = document.createElement('div');
          groupEl.className = 'session-group' + (collapsedGroups[groupPath] ? ' collapsed' : '');

          var header = document.createElement('div');
          header.className = 'session-group-header';
          var chevron = document.createElement('span');
          chevron.className = 'session-group-chevron';
          chevron.textContent = '\u25BC';
          var pathEl = document.createElement('span');
          pathEl.className = 'session-group-path';
          var displayPath = groupPath.replace(/^\/home\/[^/]+\//, '~/');
          pathEl.textContent = displayPath;
          var countEl = document.createElement('span');
          countEl.className = 'session-group-count';
          countEl.textContent = '(' + groupSessions.length + ')';
          header.appendChild(chevron);
          header.appendChild(pathEl);
          header.appendChild(countEl);

          header.addEventListener('click', function() {
            var isCollapsed = groupEl.classList.toggle('collapsed');
            collapsedGroups[groupPath] = isCollapsed;
            try { localStorage.setItem('collapsed_groups', JSON.stringify(collapsedGroups)); } catch(e) {}
          });

          groupEl.appendChild(header);

          var itemsEl = document.createElement('div');
          itemsEl.className = 'session-group-items';
          groupSessions.forEach(function(s) {
            var match = allWrappers.filter(function(w) { return w.session === s; })[0];
            if (match) itemsEl.appendChild(match.wrapper);
          });
          groupEl.appendChild(itemsEl);
          sessionListEl.appendChild(groupEl);
        });
      }
    } else {
      // Folder-based grouping: ungrouped first, then each folder
      ungrouped.forEach(function(item) {
        sessionListEl.appendChild(item.wrapper);
      });

      folderOrder.forEach(function(folderName) {
        var items = folderGroups[folderName];
        var isCollapsed = collapsedFoldersList.indexOf(folderName) >= 0;
        var fHeader = createFolderHeader(folderName, items.length, isCollapsed);
        sessionListEl.appendChild(fHeader);
        items.forEach(function(item) {
          item.wrapper.style.display = isCollapsed ? 'none' : '';
          sessionListEl.appendChild(item.wrapper);
        });
      });
    }

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
    authFetch('/api/sessions/' + encodeURIComponent(name))
      .then(function(r) {
        if (!r.ok) throw new Error('not found');
        return r.json();
      })
      .then(function(data) {
        if (!isEditingTitle) chatTitle.textContent = data.title || data.name;
        updateStatusDot(data.status);
        updateWaitingInput(data.waiting_input);
        updateCostBadge(data.cost_info);
        contentHash = data.content_hash || '';
        renderMessages(data.messages || []);
        lastMessageCount = (data.messages || []).length;
        updateStarFilterBtn();
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

  function updateCostBadge(costInfo) {
    if (!costBadge) return;
    if (!costInfo) {
      if (bottomInfo) bottomInfo.style.display = 'none';
      return;
    }
    var parts = [];
    if (costInfo.cost != null) parts.push('$' + costInfo.cost.toFixed(2));
    if (costInfo.context_pct != null) parts.push('CTX ' + costInfo.context_pct + '%');
    if (parts.length === 0) {
      if (bottomInfo) bottomInfo.style.display = 'none';
      return;
    }
    costBadge.textContent = parts.join(' \u00b7 ');
    if (bottomInfo) bottomInfo.style.display = '';
  }

  function updateWaitingInput(waiting) {
    var inputArea = document.getElementById('inputArea');
    if (!inputArea) return;
    var label = document.getElementById('waitingInputLabel');
    var optionsBar = document.getElementById('waitingOptionsBar');
    if (waiting) {
      inputArea.classList.add('waiting-input');
      if (!label) {
        label = document.createElement('div');
        label.id = 'waitingInputLabel';
        label.className = 'waiting-input-label';
        label.textContent = 'Claude is waiting for your response';
        inputArea.insertBefore(label, inputArea.firstChild);
      }
      // Scan chat feed for numbered options to make interactive
      if (!optionsBar) {
        var options = extractWaitingOptions();
        if (options.length >= 2) {
          optionsBar = document.createElement('div');
          optionsBar.id = 'waitingOptionsBar';
          optionsBar.className = 'waiting-options-bar';
          var selectedNums = [];
          var sendRow = document.createElement('div');
          sendRow.className = 'quick-reply-send-row';
          sendRow.style.display = 'none';
          var sendBtn = document.createElement('button');
          sendBtn.className = 'quick-reply-send-btn';
          sendBtn.textContent = 'Send';
          sendRow.appendChild(sendBtn);
          for (var oi = 0; oi < options.length; oi++) {
            var oBtn = document.createElement('button');
            oBtn.className = 'quick-reply-btn';
            var oNum = document.createElement('span');
            oNum.className = 'quick-reply-num';
            oNum.textContent = options[oi].num;
            var oText = document.createElement('span');
            oText.className = 'quick-reply-text';
            oText.textContent = options[oi].text.length > 40 ? options[oi].text.substring(0, 40) + '\u2026' : options[oi].text;
            oBtn.appendChild(oNum);
            oBtn.appendChild(oText);
            (function(num, btn) {
              btn.addEventListener('click', function(e) {
                e.stopPropagation();
                var idx = selectedNums.indexOf(num);
                if (idx === -1) { selectedNums.push(num); btn.classList.add('selected'); }
                else { selectedNums.splice(idx, 1); btn.classList.remove('selected'); }
                if (selectedNums.length > 0) {
                  selectedNums.sort(function(a, b) { return parseInt(a) - parseInt(b); });
                  sendBtn.textContent = 'Send ' + selectedNums.join(', ');
                  sendRow.style.display = 'flex';
                } else {
                  sendRow.style.display = 'none';
                }
              });
            })(options[oi].num, oBtn);
            optionsBar.appendChild(oBtn);
          }
          sendBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            if (currentSession && selectedNums.length > 0) {
              sendMessage(selectedNums.join(', '));
            }
          });
          optionsBar.appendChild(sendRow);
          // Insert after the label
          if (label.nextSibling) {
            inputArea.insertBefore(optionsBar, label.nextSibling);
          } else {
            inputArea.appendChild(optionsBar);
          }
        }
      }
      textInput.focus();
    } else {
      inputArea.classList.remove('waiting-input');
      if (label) label.parentNode.removeChild(label);
      if (optionsBar) optionsBar.parentNode.removeChild(optionsBar);
    }
  }

  function extractWaitingOptions() {
    // Scan last few elements in chat feed for numbered options.
    // renderMarkdown converts "1. text" into <ol><li>, so check both:
    // 1) <ol> elements with <li> children (rendered lists)
    // 2) Raw text with numbered patterns (fallback)
    var results = [];
    var children = chatFeed.children;
    for (var i = Math.max(0, children.length - 5); i < children.length; i++) {
      // Check for rendered <ol> lists
      var ols = children[i].querySelectorAll('ol');
      for (var oi = 0; oi < ols.length; oi++) {
        var startNum = parseInt(ols[oi].getAttribute('start') || '1', 10);
        var lis = ols[oi].querySelectorAll('li');
        for (var li = 0; li < lis.length; li++) {
          var liText = (lis[li].textContent || '').trim();
          if (liText) results.push({ num: String(startNum + li), text: liText });
        }
      }
      // Fallback: raw text patterns (for non-rendered content)
      if (ols.length === 0) {
        var text = children[i].textContent || '';
        var lines = text.split('\n');
        for (var lj = 0; lj < lines.length; lj++) {
          var match = lines[lj].match(/^\s*(\d+)[.)]\s+(.+)/);
          if (match) results.push({ num: match[1], text: match[2].trim() });
        }
      }
    }
    // Deduplicate by num, keep last occurrence
    var seen = {};
    var deduped = [];
    for (var di = results.length - 1; di >= 0; di--) {
      if (!seen[results[di].num]) {
        seen[results[di].num] = true;
        deduped.unshift(results[di]);
      }
    }
    return deduped.length <= 12 ? deduped : [];
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

  // ========== Syntax Highlighting ==========
  function escHtml(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function highlightSyntax(text, lang) {
    // Tokenize raw text, then HTML-escape each piece individually
    var tokens = [];
    // Order: strings first (so # inside strings is not treated as comment),
    // then comments, then numbers, then keywords
    var re = /("""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\/\/[^\n]*|#[^\n]*|\b\d+\.?\d*\b|\b(?:function|var|const|let|if|else|for|while|return|import|from|class|def|async|await|try|catch|throw|new|this|self|None|True|False|null|true|false|undefined|export|default|switch|case|break|continue|yield|elif|except|finally|with|as|in|not|and|or|is|lambda|pass|raise|del|global|nonlocal|assert|void|typeof|instanceof|static|extends|super|implements|interface|enum|type|struct|fn|pub|mut|use|mod|crate|impl|trait|where|match|loop|ref|move)\b)/g;

    var lastIndex = 0;
    var m;
    while ((m = re.exec(text)) !== null) {
      if (m.index > lastIndex) {
        tokens.push(escHtml(text.substring(lastIndex, m.index)));
      }
      var tok = m[0];
      var cls = '';
      var c0 = tok.charAt(0);
      if (c0 === '"' || c0 === "'") {
        cls = 'syn-str';
      } else if (c0 === '/' && tok.charAt(1) === '/') {
        cls = 'syn-cmt';
      } else if (c0 === '#' && lang !== 'css' && lang !== 'html') {
        cls = 'syn-cmt';
      } else if (/^\d/.test(tok)) {
        cls = 'syn-num';
      } else {
        cls = 'syn-kw';
      }
      tokens.push('<span class="' + cls + '">' + escHtml(tok) + '</span>');
      lastIndex = re.lastIndex;
    }
    if (lastIndex < text.length) {
      tokens.push(escHtml(text.substring(lastIndex)));
    }
    return tokens.join('');
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
        var rawCode = block.content.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>');
        code.innerHTML = highlightSyntax(rawCode, block.lang || '');
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
        // Hoist tbody creation before row loop to avoid repeated querySelector calls
        var thead = document.createElement('thead');
        var tbody = document.createElement('tbody');
        var hasHeader = false;
        var hasBody = false;
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
            thead.appendChild(row);
            hasHeader = true;
          } else {
            tbody.appendChild(row);
            hasBody = true;
          }
        }
        if (hasHeader) table.appendChild(thead);
        if (hasBody) table.appendChild(tbody);
        tableWrap.appendChild(table);
        frag.appendChild(tableWrap);
        continue;
      }
      var groupLines = block.lines;
      // Trim leading whitespace - tmux output often indents content
      for (var gi = 0; gi < groupLines.length; gi++) {
        groupLines[gi] = groupLines[gi].replace(/^\s+/, '');
      }
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
          var startNum = parseInt(gl.match(/^(\d+)\./)[1], 10);
          if (startNum !== 1) ol.setAttribute('start', startNum);
          while (li < groupLines.length && /^\d+\.\s+/.test(groupLines[li])) {
            var liEl = document.createElement('li');
            liEl.appendChild(applyInline(groupLines[li].replace(/^\d+\.\s+/, '')));
            ol.appendChild(liEl);
            li++;
          }
          frag.appendChild(ol);
          continue;
        }
        // Task/checklist items: lines with check/cross marks or - [x]/- [ ] or ending with ... check
        var taskRe = /[\u2713\u2714\u2717\u2718]|^- \[[ xX]\]/;
        if (taskRe.test(gl) || /\.\.\.\s*[\u2713\u2714]/.test(gl)) {
          var taskList = document.createElement('div');
          taskList.className = 'task-list';
          while (li < groupLines.length && (taskRe.test(groupLines[li]) || /\.\.\.\s*[\u2713\u2714]/.test(groupLines[li]) || /^\.\.\.\s*\+\d+/.test(groupLines[li]))) {
            var tl = groupLines[li];
            var taskItem = document.createElement('div');
            // Determine if completed
            var isDone = /[\u2713\u2714]/.test(tl) || /\[x\]/i.test(tl);
            var isFailed = /[\u2717\u2718]/.test(tl) || /\[X\]/.test(tl) && /fail|error/i.test(tl);
            var isSummary = /^\.\.\.\s*\+\d+/.test(tl);
            if (isSummary) {
              taskItem.className = 'task-summary';
              taskItem.textContent = tl.replace(/^\.\.\.?\s*/, '');
            } else {
              taskItem.className = 'task-item' + (isDone ? ' done' : '') + (isFailed ? ' failed' : '');
              var taskCheck = document.createElement('span');
              taskCheck.className = 'task-check';
              taskCheck.textContent = isDone ? '\u2713' : (isFailed ? '\u2717' : '\u25CB');
              var taskText = document.createElement('span');
              taskText.className = 'task-text';
              // Clean the text: remove checkmark chars, checkbox syntax
              var cleanTask = tl.replace(/[\u2713\u2714\u2717\u2718]/g, '').replace(/^- \[[ xX]\]\s*/, '').replace(/\.\.\.\s*$/, '...').trim();
              taskText.textContent = cleanTask;
              taskItem.appendChild(taskCheck);
              taskItem.appendChild(taskText);
            }
            taskList.appendChild(taskItem);
            li++;
          }
          frag.appendChild(taskList);
          continue;
        }
        var pLines = [];
        while (li < groupLines.length &&
               !groupLines[li].match(/^#{1,3}\s+/) &&
               !/^[-*]{3,}\s*$/.test(groupLines[li]) &&
               !/^[\-*]\s+/.test(groupLines[li]) &&
               !/^\d+\.\s+/.test(groupLines[li]) &&
               !taskRe.test(groupLines[li]) &&
               !/\.\.\.\s*[\u2713\u2714]/.test(groupLines[li])) {
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

  // ========== Image Overlay ==========
  function showImageOverlay(src) {
    var overlay = document.createElement('div');
    overlay.className = 'image-overlay';
    var closeBtn = document.createElement('button');
    closeBtn.className = 'image-overlay-close';
    closeBtn.textContent = '\u00d7';
    closeBtn.addEventListener('click', function() {
      if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
    });
    var img = document.createElement('img');
    img.src = src;
    img.alt = 'Full size preview';
    overlay.appendChild(closeBtn);
    overlay.appendChild(img);
    overlay.addEventListener('click', function(e) {
      if (e.target === overlay) {
        if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
      }
    });
    document.body.appendChild(overlay);
  }

  function appendToolGroup(tools) {
    // Separate Agent/Skill calls from regular tools
    var agents = [];
    var regular = [];
    for (var t = 0; t < tools.length; t++) {
      if (tools[t].tool === 'Agent' || tools[t].tool === 'Skill' || tools[t].tool === 'Explore') {
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
        el.appendChild(renderMarkdown(userContent));
      }
      // Detect uploaded image paths and show inline preview
      var imgMatch = userContent.match(/\/srv\/appdata\/claude-chat\/uploads\/([^\s]+\.(?:png|jpg|jpeg|gif|webp))/i);
      var imgEl = null;
      if (imgMatch) {
        imgEl = document.createElement('img');
        imgEl.className = 'msg-image';
        imgEl.alt = imgMatch[1];
        imgEl.loading = 'lazy';
        // Load via authFetch to send Bearer token
        (function(img, filename) {
          authFetch('/api/uploads/' + encodeURIComponent(filename)).then(function(r) {
            if (r.ok) return r.blob();
          }).then(function(blob) {
            if (blob) {
              var url = URL.createObjectURL(blob);
              img.src = url;
              img.addEventListener('click', function(e) {
                e.stopPropagation();
                showImageOverlay(url);
              });
            }
          });
        })(imgEl, imgMatch[1]);
      }
      if (m._pending) {
        var statusEl = document.createElement('div');
        statusEl.className = 'msg-status msg-status-pending';
        statusEl.textContent = 'Sending\u2026';
        wrapper.appendChild(el);
        if (imgEl) wrapper.appendChild(imgEl);
        wrapper.appendChild(statusEl);
        if (!animate) wrapper.style.animation = 'none';
        chatFeed.appendChild(wrapper);
        return;
      }
      // Star button for user messages
      var uMId = msgId(m);
      var uStarredList = getStarredMessages(currentSession);
      var uIsStarred = uStarredList.indexOf(uMId) >= 0;
      var uActions = document.createElement('div');
      uActions.className = 'msg-actions';
      var uStarBtn = document.createElement('button');
      uStarBtn.className = 'msg-action-btn msg-star-btn' + (uIsStarred ? ' starred' : '');
      uStarBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="' + (uIsStarred ? 'currentColor' : 'none') + '" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>';
      uStarBtn.title = uIsStarred ? 'Unstar' : 'Star message';
      (function(id, btn, msgEl) {
        btn.addEventListener('click', function(e) {
          e.stopPropagation();
          var nowStarred = toggleStar(currentSession, id);
          btn.classList.toggle('starred', nowStarred);
          btn.querySelector('svg').setAttribute('fill', nowStarred ? 'currentColor' : 'none');
          btn.title = nowStarred ? 'Unstar' : 'Star message';
          msgEl.classList.toggle('msg-starred', nowStarred);
          updateStarFilterBtn();
        });
      })(uMId, uStarBtn, el);
      uActions.appendChild(uStarBtn);
      el.appendChild(uActions);
      if (uIsStarred) el.classList.add('msg-starred');
      // For non-pending user messages with images, use the wrapper
      if (imgEl) {
        wrapper.appendChild(el);
        wrapper.appendChild(imgEl);
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

      // Detect agent/explore status messages: 'Agent "name" completed/launched'
      var agentStatusMatch = content.match(/^(?:Agent|Explore)\s+"([^"]+)"\s*(completed|launched|failed)/i);
      if (!agentStatusMatch) agentStatusMatch = content.match(/^(?:Agent|Explore)\s+[\u201c]([^\u201d]+)[\u201d]\s*(completed|launched|failed)/i);
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
        // Star button for assistant messages
        var aMId = msgId(m);
        var aStarredList = getStarredMessages(currentSession);
        var aIsStarred = aStarredList.indexOf(aMId) >= 0;
        var aStarBtn = document.createElement('button');
        aStarBtn.className = 'msg-action-btn msg-star-btn' + (aIsStarred ? ' starred' : '');
        aStarBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="' + (aIsStarred ? 'currentColor' : 'none') + '" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>';
        aStarBtn.title = aIsStarred ? 'Unstar' : 'Star message';
        (function(id, btn, msgEl) {
          btn.addEventListener('click', function(e) {
            e.stopPropagation();
            var nowStarred = toggleStar(currentSession, id);
            btn.classList.toggle('starred', nowStarred);
            btn.querySelector('svg').setAttribute('fill', nowStarred ? 'currentColor' : 'none');
            btn.title = nowStarred ? 'Unstar' : 'Star message';
            msgEl.classList.toggle('msg-starred', nowStarred);
            updateStarFilterBtn();
          });
        })(aMId, aStarBtn, el);
        actions.appendChild(aStarBtn);
        if (aIsStarred) el.classList.add('msg-starred');
        el.appendChild(actions);

        // Detect numbered options for quick-reply buttons
        // Show when message has numbered options AND (ends with ? OR is the last assistant message)
        var contentTrimmed = content.trim();
        var endsWithQuestion = /[?:]\s*$/.test(contentTrimmed);
        var isLastAssistant = !allMsgs ? false : (msgIdx === allMsgs.length - 1) || (function() {
          for (var ni = msgIdx + 1; ni < allMsgs.length; ni++) {
            if (allMsgs[ni].role === 'assistant') return false;
            if (allMsgs[ni].role === 'user') return true;
          }
          return true;
        })();
        var allOptionLines = content.match(/^[\s]*(\d+)[.)]\s+.+/gm);
        // Only use the LAST contiguous numbered sequence (starting from 1)
        var optionLines = null;
        if (allOptionLines && (endsWithQuestion || isLastAssistant)) {
          // Walk backwards to find the last sequence starting with "1."
          var lastGroup = [];
          for (var oli = allOptionLines.length - 1; oli >= 0; oli--) {
            var olMatch = allOptionLines[oli].match(/^\s*(\d+)/);
            if (olMatch) {
              lastGroup.unshift(allOptionLines[oli]);
              if (olMatch[1] === '1') break;
            }
          }
          if (lastGroup.length >= 2 && lastGroup.length <= 12) optionLines = lastGroup;
        }
        if (optionLines) {
          var quickReplies = document.createElement('div');
          quickReplies.className = 'quick-replies';
          var selectedNums = [];
          var sendRow = document.createElement('div');
          sendRow.className = 'quick-reply-send-row';
          sendRow.style.display = 'none';
          var sendBtn = document.createElement('button');
          sendBtn.className = 'quick-reply-send-btn';
          sendBtn.textContent = 'Send';
          sendRow.appendChild(sendBtn);
          for (var qi = 0; qi < optionLines.length; qi++) {
            var optMatch = optionLines[qi].match(/^\s*(\d+)[.)]\s+(.+)/);
            if (optMatch) {
              var qBtn = document.createElement('button');
              qBtn.className = 'quick-reply-btn';
              qBtn.setAttribute('data-num', optMatch[1]);
              var qNum = document.createElement('span');
              qNum.className = 'quick-reply-num';
              qNum.textContent = optMatch[1];
              var qText = document.createElement('span');
              qText.className = 'quick-reply-text';
              var optText = optMatch[2].trim();
              qText.textContent = optText.length > 50 ? optText.substring(0, 50) + '\u2026' : optText;
              qBtn.appendChild(qNum);
              qBtn.appendChild(qText);
              (function(num, btn) {
                btn.addEventListener('click', function(e) {
                  e.stopPropagation();
                  var idx = selectedNums.indexOf(num);
                  if (idx === -1) {
                    selectedNums.push(num);
                    btn.classList.add('selected');
                  } else {
                    selectedNums.splice(idx, 1);
                    btn.classList.remove('selected');
                  }
                  if (selectedNums.length > 0) {
                    selectedNums.sort(function(a, b) { return parseInt(a) - parseInt(b); });
                    sendBtn.textContent = 'Send ' + selectedNums.join(', ');
                    sendRow.style.display = 'flex';
                  } else {
                    sendRow.style.display = 'none';
                  }
                });
              })(optMatch[1], qBtn);
              quickReplies.appendChild(qBtn);
            }
          }
          sendBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            if (currentSession && selectedNums.length > 0) {
              sendMessage(selectedNums.join(', '));
            }
          });
          quickReplies.appendChild(sendRow);
          el.appendChild(quickReplies);
        }

        if (!animate) el.style.animation = 'none';
      }
    } else if (m.role === 'tool') {
      if (m.tool === 'Agent' || m.tool === 'Skill' || m.tool === 'Explore') {
        // Agent/Skill/Explore calls get collapsible cards
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

        if (m.tool_results) {
          var resultsArr = Array.isArray(m.tool_results) ? m.tool_results : [m.tool_results];
          var bgAgents = [];
          var fileChanges = [];
          var otherResults = [];

          for (var ri = 0; ri < resultsArr.length; ri++) {
            var rItem = typeof resultsArr[ri] === 'string' ? resultsArr[ri] : JSON.stringify(resultsArr[ri]);
            if (rItem.indexOf('Backgrounded agent') >= 0 || rItem.indexOf('\u21b3') >= 0) {
              bgAgents.push(rItem);
            } else if (/^(Added|Removed|Modified|Updated|Created|Deleted|Changed)\s/i.test(rItem) || /\d+\s+(line|file)/i.test(rItem)) {
              fileChanges.push(rItem);
            } else {
              otherResults.push(rItem);
            }
          }

          // Sub-agents section
          if (bgAgents.length > 0) {
            var bgSection = document.createElement('div');
            bgSection.className = 'agent-section';
            var bgLabel = document.createElement('div');
            bgLabel.className = 'agent-section-label';
            bgLabel.textContent = '\u25C7 ' + bgAgents.length + ' sub-agent' + (bgAgents.length > 1 ? 's' : '') + ' dispatched';
            bgSection.appendChild(bgLabel);
            for (var bi = 0; bi < bgAgents.length; bi++) {
              var subItem = document.createElement('div');
              subItem.className = 'agent-sub-item';
              var diamondIcon = document.createElement('span');
              diamondIcon.className = 'agent-sub-item-icon';
              diamondIcon.textContent = '\u25C7';
              var subDesc = document.createElement('span');
              subDesc.className = 'agent-sub-item-desc';
              // Clean up the "Backgrounded agent (↳ to manage ·" prefix
              var cleanDesc = bgAgents[bi]
                .replace(/^Backgrounded agent\s*/, '')
                .replace(/^\(\u21b3\s*to manage\s*[·\u00b7]\s*/, '')
                .replace(/^["']|["']$/g, '')
                .replace(/\)$/, '')
                .trim();
              subDesc.textContent = cleanDesc || bgAgents[bi];
              subItem.appendChild(diamondIcon);
              subItem.appendChild(subDesc);
              bgSection.appendChild(subItem);
            }
            agentBody.appendChild(bgSection);
          }

          // File changes section
          if (fileChanges.length > 0) {
            var fcSection = document.createElement('div');
            fcSection.className = 'agent-section';
            var fcLabel = document.createElement('div');
            fcLabel.className = 'agent-section-label';
            fcLabel.textContent = '\u2699 Changes';
            fcSection.appendChild(fcLabel);
            for (var fi = 0; fi < fileChanges.length; fi++) {
              var fcItem = document.createElement('div');
              fcItem.className = 'agent-change-item';
              fcItem.textContent = fileChanges[fi];
              fcSection.appendChild(fcItem);
            }
            agentBody.appendChild(fcSection);
          }

          // Other results (rendered as markdown if substantive, code block if short)
          if (otherResults.length > 0) {
            var orSection = document.createElement('div');
            orSection.className = 'agent-section';
            var orText = otherResults.join('\n').trim();
            if (orText.length > 200) {
              var orLabel = document.createElement('div');
              orLabel.className = 'agent-section-label';
              orLabel.textContent = '\u2192 Output';
              orSection.appendChild(orLabel);
              var orContent = document.createElement('div');
              orContent.className = 'msg-assistant-text';
              orContent.appendChild(renderMarkdown(orText));
              orSection.appendChild(orContent);
            } else if (orText) {
              var orPre = document.createElement('div');
              orPre.className = 'agent-change-item';
              orPre.textContent = orText;
              orSection.appendChild(orPre);
            }
            agentBody.appendChild(orSection);
          }
        }

        // If no tool_results, show the prompt summary
        if (!m.tool_results || m.tool_results.length === 0) {
          var summaryText = document.createElement('div');
          summaryText.className = 'agent-section';
          var summaryLabel = document.createElement('div');
          summaryLabel.className = 'agent-section-label';
          summaryLabel.textContent = '\u2192 Task';
          summaryText.appendChild(summaryLabel);
          var summaryContent = document.createElement('div');
          summaryContent.className = 'msg-assistant-text';
          summaryContent.style.fontSize = '0.8rem';
          // Show first 200 chars of prompt as summary
          var promptSummary = agentContent.length > 200 ? agentContent.substring(0, 200) + '\u2026' : agentContent;
          summaryContent.appendChild(renderMarkdown(promptSummary));
          summaryText.appendChild(summaryContent);
          agentBody.appendChild(summaryText);
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

  function forceRefresh() {
    if (!currentSession) return;
    contentHash = '';
    idleCount = 0;
    stopPolling();
    // Full reload from session endpoint (not poll)
    authFetch('/api/sessions/' + encodeURIComponent(currentSession))
      .then(function(r) { return r.ok ? r.json() : null; })
      .then(function(data) {
        if (!data) return;
        updateStatusDot(data.status);
        updateWaitingInput(data.waiting_input);
        updateCostBadge(data.cost_info);
        contentHash = data.content_hash || '';
        renderMessages(data.messages || []);
        lastMessageCount = (data.messages || []).length;
        updateStarFilterBtn();
        scrollToBottom(false);
        startPolling();
      })
      .catch(function() { startPolling(); });
  }

  function doPoll() {
    if (!currentSession) return;
    var url = '/api/sessions/' + encodeURIComponent(currentSession) + '/poll';
    if (contentHash) url += '?hash=' + encodeURIComponent(contentHash);

    authFetch(url)
      .then(function(r) {
        if (!r.ok) throw new Error('poll fail');
        return r.json();
      })
      .then(function(data) {
        updateStatusDot(data.status);
        updateWaitingInput(data.waiting_input);
        updateCostBadge(data.cost_info);
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

  // Throttle scroll handler to once per animation frame
  var scrollThrottleTimer = null;
  chatFeed.addEventListener('scroll', function() {
    if (scrollThrottleTimer) return;
    scrollThrottleTimer = requestAnimationFrame(function() {
      scrollThrottleTimer = null;
      checkScrollPosition();
      if (isUserNearBottom) {
        newMsgPill.classList.remove('visible');
        if (hasUnreadMessages) {
          hasUnreadMessages = false;
          updateTabTitle();
        }
      }
    });
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

    authFetch('/api/sessions/' + encodeURIComponent(currentSession) + '/send', {
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

    authFetch('/api/sessions/' + encodeURIComponent(name) + '/kill', { method: 'POST' })
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

    authFetch('/api/sessions/' + encodeURIComponent(name) + '/respawn', { method: 'POST' })
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

    authFetch('/api/sessions/' + encodeURIComponent(name), { method: 'DELETE' })
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

  // ========== Search & Filter ==========
  var searchToggleBtn = document.getElementById('searchToggleBtn');
  var searchBarEl = document.getElementById('searchBar');
  searchToggleBtn.addEventListener('click', function() {
    var visible = searchBarEl.style.display !== 'none';
    searchBarEl.style.display = visible ? 'none' : '';
    searchToggleBtn.classList.toggle('active', !visible);
    if (!visible) {
      searchInput.focus();
    } else {
      // Clear search when hiding
      searchInput.value = '';
      activeStatusFilter = 'all';
      var chips = searchFilters.querySelectorAll('.filter-chip');
      for (var i = 0; i < chips.length; i++) {
        chips[i].classList.toggle('active', chips[i].getAttribute('data-filter') === 'all');
      }
      loadSessions();
    }
  });
  var searchDebounce = null;
  searchInput.addEventListener('input', function() {
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(function() { loadSessions(); }, 150);
  });
  searchFilters.addEventListener('click', function(e) {
    var chip = e.target.closest('.filter-chip');
    if (!chip) return;
    var chips = searchFilters.querySelectorAll('.filter-chip');
    for (var i = 0; i < chips.length; i++) chips[i].classList.remove('active');
    chip.classList.add('active');
    activeStatusFilter = chip.getAttribute('data-filter');
    loadSessions();
  });

  // ========== Text Input + Send/Mic Toggle ==========
  function toggleSendMic() {
    if (textInput.value.trim()) {
      sendBtn.style.display = 'flex';
      micBtn.style.display = 'flex';
      micBtn.style.width = '28px';
      micBtn.style.minWidth = '28px';
      micBtn.style.height = '28px';
      micBtn.style.minHeight = '28px';
      micBtn.style.opacity = '0.6';
    } else {
      sendBtn.style.display = 'none';
      micBtn.style.display = 'flex';
      micBtn.style.width = '';
      micBtn.style.minWidth = '';
      micBtn.style.height = '';
      micBtn.style.minHeight = '';
      micBtn.style.opacity = '';
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
      textInput.style.height = 'auto';
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
        textInput.style.height = 'auto';
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
    authFetch('/api/upload/' + encodeURIComponent(currentSession), { method: 'POST', body: fd })
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

  // Special keys toolbar
  var specialKeysEl = document.getElementById('specialKeys');
  if (specialKeysEl) {
    specialKeysEl.addEventListener('click', function(e) {
      var btn = e.target.closest('.special-key');
      if (!btn || !currentSession) return;
      var key = btn.getAttribute('data-key');
      var tmuxKey = key;
      if (key === 'shift-tab') tmuxKey = 'BTab';
      // Send key via tmux send-keys (reuse the send endpoint with special handling)
      authFetch('/api/sessions/' + encodeURIComponent(currentSession) + '/key', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: tmuxKey })
      });
      // Visual feedback
      btn.style.background = 'var(--accent)';
      btn.style.color = 'white';
      setTimeout(function() { btn.style.background = ''; btn.style.color = ''; }, 200);
    });
  }

  // Copy full conversation as markdown
  function copyConversation() {
    if (!currentSession) return;
    authFetch('/api/sessions/' + encodeURIComponent(currentSession))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var messages = (data.conversation || data.messages || []);
        var title = data.title || data.name || currentSession;
        var md = '# ' + title + '\n';
        for (var i = 0; i < messages.length; i++) {
          var m = messages[i];
          md += '\n';
          if (m.role === 'tool') {
            md += '**' + (m.tool || 'Tool') + '**';
            if (m.content) md += ' ' + m.content;
            md += '\n';
            if (m.tool_results && m.tool_results.length) {
              for (var j = 0; j < m.tool_results.length; j++) {
                md += '  ' + m.tool_results[j] + '\n';
              }
            }
          } else {
            var label = m.role === 'user' ? 'User' : 'Assistant';
            md += '**' + label + ':**\n' + (m.content || '') + '\n';
          }
        }
        copyToClipboard(md);
      })
      .catch(function() {
        showActionToast('Failed to copy', 'error');
      });
  }

  copyAllBtn.addEventListener('click', copyConversation);

  // Export conversation
  function exportConversation(format) {
    if (!currentSession) return;
    var fmt = format || 'markdown';
    var ext = fmt === 'json' ? '.json' : '.md';
    authFetch('/api/sessions/' + encodeURIComponent(currentSession) + '/export?fmt=' + fmt)
      .then(function(r) {
        if (!r.ok) throw new Error('Export failed');
        return r.blob();
      })
      .then(function(blob) {
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = currentSession + ext;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        showActionToast('Exported as ' + ext.slice(1).toUpperCase(), 'success');
      })
      .catch(function() {
        showActionToast('Export failed', 'error');
      });
  }

  function closeExportDropdown() {
    var existing = document.getElementById('exportDropdown');
    if (existing) existing.remove();
  }

  exportBtn.addEventListener('click', function(e) {
    e.stopPropagation();
    var existing = document.getElementById('exportDropdown');
    if (existing) {
      existing.remove();
      return;
    }
    var dd = document.createElement('div');
    dd.id = 'exportDropdown';
    dd.style.cssText = 'position:absolute;top:100%;right:0;margin-top:6px;background:var(--surface2);border:1px solid var(--border-medium);border-radius:8px;padding:4px 0;z-index:100;min-width:150px;box-shadow:0 4px 20px rgba(0,0,0,0.4);';
    var btnMd = document.createElement('button');
    btnMd.textContent = 'Markdown (.md)';
    btnMd.style.cssText = 'display:block;width:100%;text-align:left;padding:8px 14px;background:none;border:none;color:var(--text);font-size:0.82rem;cursor:pointer;font-family:inherit;';
    btnMd.addEventListener('mouseenter', function() { this.style.background = 'var(--surface3)'; });
    btnMd.addEventListener('mouseleave', function() { this.style.background = 'none'; });
    btnMd.addEventListener('click', function(ev) {
      ev.stopPropagation();
      closeExportDropdown();
      exportConversation('markdown');
    });
    var btnJson = document.createElement('button');
    btnJson.textContent = 'JSON (.json)';
    btnJson.style.cssText = 'display:block;width:100%;text-align:left;padding:8px 14px;background:none;border:none;color:var(--text);font-size:0.82rem;cursor:pointer;font-family:inherit;';
    btnJson.addEventListener('mouseenter', function() { this.style.background = 'var(--surface3)'; });
    btnJson.addEventListener('mouseleave', function() { this.style.background = 'none'; });
    btnJson.addEventListener('click', function(ev) {
      ev.stopPropagation();
      closeExportDropdown();
      exportConversation('json');
    });
    dd.appendChild(btnMd);
    dd.appendChild(btnJson);
    exportBtn.appendChild(dd);
  });

  document.addEventListener('click', function() {
    closeExportDropdown();
  });

  // Force refresh button
  refreshBtn.addEventListener('click', function() {
    refreshBtn.style.animation = 'btnSpin 0.5s linear';
    setTimeout(function() { refreshBtn.style.animation = ''; }, 500);
    forceRefresh();
  });

  // Star filter button
  function updateStarFilterBtn() {
    if (!currentSession) {
      starFilterBtn.style.display = 'none';
      return;
    }
    var starred = getStarredMessages(currentSession);
    starFilterBtn.style.display = starred.length > 0 ? '' : 'none';
    if (starred.length === 0 && starFilterActive) {
      starFilterActive = false;
      chatFeed.classList.remove('starred-only');
      starFilterBtn.querySelector('svg').setAttribute('fill', 'none');
    }
  }

  starFilterBtn.addEventListener('click', function() {
    starFilterActive = !starFilterActive;
    chatFeed.classList.toggle('starred-only', starFilterActive);
    starFilterBtn.querySelector('svg').setAttribute('fill', starFilterActive ? 'currentColor' : 'none');
    starFilterBtn.title = starFilterActive ? 'Show all messages' : 'Show starred only';
  });

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
    authFetch('/api/ntfy', {
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
      if (text) {
        // Append to existing text instead of replacing
        var existing = textInput.value.trim();
        textInput.value = existing ? existing + ' ' + text : text;
        textInput.focus();
        toggleSendMic();
      } else {
        micLabel.textContent = 'No speech detected';
        setTimeout(function() { micLabel.textContent = ''; }, 1500);
      }
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
        authFetch('/api/transcribe', { method: 'POST', body: form })
          .then(function(r) { return r.json(); })
          .then(function(data) {
            var text = (data.text || '').trim();
            if (text) { var ex = textInput.value.trim(); textInput.value = ex ? ex + ' ' + text : text; textInput.focus(); toggleSendMic(); }
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
        authFetch('/api/sessions/' + encodeURIComponent(currentSession) + '/title', {
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
    authFetch('/api/commands')
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

  // ========== New Session ==========
  function openNewSession() {
    authFetch('/api/config')
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
          if (p.mode) {
            var badge = document.createElement('span');
            badge.className = 'preset-mode-badge mode-' + p.mode;
            badge.textContent = p.mode;
            name.appendChild(badge);
          }
          var desc = document.createElement('div');
          desc.className = 'preset-card-path';
          desc.textContent = p.description || '';
          var path = document.createElement('div');
          path.className = 'preset-card-path';
          path.style.fontSize = '0.75em';
          path.style.opacity = '0.6';
          path.textContent = p.path;
          card.appendChild(name);
          if (p.description) card.appendChild(desc);
          card.appendChild(path);
          card.addEventListener('click', function() {
            createSession(p.path, '', p.initial_command || '', p.mode || '');
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

  function createSession(path, name, initialCommand, mode) {
    closeNewSession();
    showActionToast('Creating session...', 'info');
    var payload = { path: path, name: name };
    if (initialCommand) payload.initial_command = initialCommand;
    if (mode) payload.mode = mode;
    authFetch('/api/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
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
    if (p) createSession(p, '', '', '');
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
    } else if (key === 'accentColor') {
      if (value && value !== 'orange') {
        document.documentElement.setAttribute('data-accent', value);
      } else {
        document.documentElement.removeAttribute('data-accent');
      }
    } else if (key === 'fontSize') {
      document.body.classList.remove('font-small', 'font-large');
      if (value === 'small') {
        document.body.classList.add('font-small');
      } else if (value === 'large') {
        document.body.classList.add('font-large');
      }
    }
  }

  function loadSettings() {
    var s = getSettings();
    if (s.theme) applySetting('theme', s.theme);
    if (s.pollSpeed) applySetting('pollSpeed', s.pollSpeed);
    if (s.chatVoice) applySetting('chatVoice', s.chatVoice);
    if (s.accentColor) applySetting('accentColor', s.accentColor);
    if (s.fontSize) applySetting('fontSize', s.fontSize);
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

    // Accent Color row (swatch picker)
    var accentRow = document.createElement('div');
    accentRow.className = 'settings-row';
    var accentLabel = document.createElement('span');
    accentLabel.className = 'settings-label';
    accentLabel.textContent = 'Accent Color';
    accentRow.appendChild(accentLabel);

    var swatchRow = document.createElement('div');
    swatchRow.className = 'settings-swatch-row';
    var accentColors = ['orange', 'blue', 'green', 'purple', 'red'];
    var currentAccent = s.accentColor || 'orange';
    for (var ai = 0; ai < accentColors.length; ai++) {
      (function(color) {
        var swatch = document.createElement('div');
        swatch.className = 'settings-swatch' + (color === currentAccent ? ' active' : '');
        swatch.setAttribute('data-color', color);
        swatch.title = color.charAt(0).toUpperCase() + color.slice(1);
        swatch.addEventListener('click', function() {
          var allSwatches = swatchRow.querySelectorAll('.settings-swatch');
          for (var si = 0; si < allSwatches.length; si++) allSwatches[si].classList.remove('active');
          swatch.classList.add('active');
          saveSetting('accentColor', color);
        });
        swatchRow.appendChild(swatch);
      })(accentColors[ai]);
    }
    accentRow.appendChild(swatchRow);
    settingsPanel.appendChild(accentRow);

    // Font Size row
    var fontRow = createSettingsRow('Font Size', 'select', s.fontSize || 'default', [
      { value: 'small', label: 'Small' },
      { value: 'default', label: 'Default' },
      { value: 'large', label: 'Large' }
    ], function(v) { saveSetting('fontSize', v); });
    settingsPanel.appendChild(fontRow);

    // Log Out row
    var logoutRow = document.createElement('div');
    logoutRow.className = 'settings-row';
    var logoutLabel = document.createElement('span');
    logoutLabel.className = 'settings-label';
    logoutLabel.textContent = 'Log Out';
    logoutRow.appendChild(logoutLabel);
    var logoutBtn = document.createElement('button');
    logoutBtn.className = 'login-btn';
    logoutBtn.style.width = 'auto';
    logoutBtn.style.padding = '8px 20px';
    logoutBtn.style.fontSize = '0.82rem';
    logoutBtn.textContent = 'Log Out';
    logoutBtn.addEventListener('click', function() {
      closeSettings();
      logout();
    });
    logoutRow.appendChild(logoutBtn);
    settingsPanel.appendChild(logoutRow);
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


  // ========== Session History ==========
  var historyBtn = document.getElementById('historyBtn');
  var historyBackdrop = document.getElementById('historyBackdrop');
  var historyPanel = document.getElementById('historyPanel');
  var historyList = document.getElementById('historyList');
  var shortcutsBackdrop = document.getElementById('shortcutsBackdrop');
  var shortcutsPanel = document.getElementById('shortcutsPanel');

  function formatHistoryTime(epochMs) {
    if (!epochMs) return '';
    var d = new Date(epochMs);
    var now = new Date();
    var diffMs = now - d;
    var diffMin = Math.floor(diffMs / 60000);
    if (diffMin < 1) return 'just now';
    if (diffMin < 60) return diffMin + 'm ago';
    var diffHrs = Math.floor(diffMin / 60);
    if (diffHrs < 24) return diffHrs + 'h ago';
    var diffDays = Math.floor(diffHrs / 24);
    if (diffDays < 7) return diffDays + 'd ago';
    return d.toLocaleDateString();
  }

  function openHistory() {
    while (historyList.firstChild) historyList.removeChild(historyList.firstChild);
    var loadingEl = document.createElement('div');
    loadingEl.style.cssText = 'text-align:center;color:var(--text-muted);padding:20px;font-size:0.85rem;';
    loadingEl.textContent = 'Loading...';
    historyList.appendChild(loadingEl);
    historyBackdrop.classList.add('visible');
    historyPanel.classList.add('visible');

    authFetch('/api/history')
      .then(function(r) { return r.json(); })
      .then(function(entries) {
        while (historyList.firstChild) historyList.removeChild(historyList.firstChild);
        if (!entries || entries.length === 0) {
          var emptyEl = document.createElement('div');
          emptyEl.style.cssText = 'text-align:center;color:var(--text-muted);padding:20px;font-size:0.85rem;';
          emptyEl.textContent = 'No dismissed sessions yet';
          historyList.appendChild(emptyEl);
          return;
        }
        for (var i = 0; i < entries.length; i++) {
          var entry = entries[i];
          var item = document.createElement('div');
          item.className = 'history-item';

          var itemTop = document.createElement('div');
          itemTop.className = 'history-item-top';
          var itemTitle = document.createElement('div');
          itemTitle.className = 'history-item-title';
          itemTitle.textContent = entry.title || entry.name;
          var itemTime = document.createElement('div');
          itemTime.className = 'history-item-time';
          itemTime.textContent = formatHistoryTime(entry.dismissed_at);
          itemTop.appendChild(itemTitle);
          itemTop.appendChild(itemTime);
          item.appendChild(itemTop);

          if (entry.preview) {
            var itemPreview = document.createElement('div');
            itemPreview.className = 'history-item-preview';
            itemPreview.textContent = entry.preview;
            item.appendChild(itemPreview);
          }

          historyList.appendChild(item);
        }
      })
      .catch(function() {
        while (historyList.firstChild) historyList.removeChild(historyList.firstChild);
        var errEl = document.createElement('div');
        errEl.style.cssText = 'text-align:center;color:var(--text-muted);padding:20px;font-size:0.85rem;';
        errEl.textContent = 'Failed to load history';
        historyList.appendChild(errEl);
      });
  }

  function closeHistory() {
    historyBackdrop.classList.remove('visible');
    historyPanel.classList.remove('visible');
  }

  historyBtn.addEventListener('click', openHistory);
  historyBackdrop.addEventListener('click', closeHistory);

  // ========== Shortcuts Modal ==========
  function openShortcuts() {
    shortcutsBackdrop.classList.add('visible');
    shortcutsPanel.classList.add('visible');
  }

  function closeShortcuts() {
    shortcutsBackdrop.classList.remove('visible');
    shortcutsPanel.classList.remove('visible');
  }

  shortcutsBackdrop.addEventListener('click', closeShortcuts);

  // ========== Keyboard Navigation ==========
  document.addEventListener('keydown', function(e) {
    var tag = (e.target.tagName || '').toLowerCase();
    var isInput = (tag === 'input' || tag === 'textarea' || tag === 'select');
    var settingsOpen = settingsPanel.classList.contains('visible');
    var newSessionOpen = newSessionPanel.classList.contains('visible');
    var historyOpen = historyPanel.classList.contains('visible');
    var shortcutsOpen = shortcutsPanel.classList.contains('visible');
    var paletteOpen = cmdPalette.classList.contains('visible');

    // Escape: close settings/new-session/command-palette, or go back to session list
    if (e.key === 'Escape') {
      if (shortcutsOpen) {
        closeShortcuts();
        e.preventDefault();
        return;
      }
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
      if (historyOpen) {
        closeHistory();
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

    // Ctrl/Cmd+Shift+C: copy full conversation as markdown
    if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === 'C') {
      e.preventDefault();
      copyConversation();
      return;
    }

    // Ctrl/Cmd+Shift+E: export conversation as markdown
    if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === 'E') {
      e.preventDefault();
      exportConversation('markdown');
      return;
    }

    // Don't handle other shortcuts when typing in inputs
    if (isInput) return;

    // ?: toggle shortcuts panel
    if (e.key === '?' && !e.metaKey && !e.ctrlKey) {
      if (shortcutsOpen) {
        closeShortcuts();
      } else {
        openShortcuts();
      }
      e.preventDefault();
      return;
    }

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
  function initApp() {
    loadSessions();
    startSessionListPolling();
    fetchCommands();

    // On desktop, show empty state on initial load
    if (isDesktop()) {
      screenList.className = 'screen';
      screenChat.className = 'screen';
      showDesktopEmptyState();
    }
  }

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

  // Apply visual settings immediately (before auth)
  loadSettings();

  // Auth check, then init
  checkAuthAndInit();

})();

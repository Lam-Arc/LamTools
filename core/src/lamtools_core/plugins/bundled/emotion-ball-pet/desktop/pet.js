(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  var collapsedViewportWidth = window.innerWidth;
  var collapsedViewportHeight = window.innerHeight;
  var expandedMeasurementViewportWidth = window.innerWidth;
  var hostRequestId = 1;
  var hostRequests = new Map();
  var strictHostRequestId = 1;
  var strictHostRequests = new Map();
  var VIEW_MODE = Object.freeze({
    PET: 'pet',
    CARD: 'card',
    PANEL: 'panel'
  });
  var CARD_PRIORITY = Object.freeze({
    approval: 100,
    question: 90,
    file: 80,
    error: 70,
    reply: 50,
    success: 40,
    dock: 30,
    info: 10
  });
  var invoke = function (command, args) {
    var core = window.__TAURI__ && window.__TAURI__.core;
    if (core && typeof core.invoke === 'function') {
      return core.invoke(command, args || {}).catch(function (error) {
        console.warn('[emotion-ball-pet] Tauri command failed:', command, error);
        return null;
      });
    }
    if (window.parent === window) return Promise.resolve(null);
    var id = 'pet-' + hostRequestId++;
    return new Promise(function (resolve) {
      var timer = window.setTimeout(function () {
        hostRequests.delete(id);
        resolve(null);
      }, 5000);
      hostRequests.set(id, function (result) {
        clearTimeout(timer);
        resolve(result);
      });
      window.parent.postMessage({
        source: 'lamtools-desktop-plugin',
        id: id,
        command: command,
        args: args || {}
      }, '*');
    });
  };
  var invokeStrict = function (command, args) {
    var core = window.__TAURI__ && window.__TAURI__.core;
    if (core && typeof core.invoke === 'function') return core.invoke(command, args || {});
    if (window.parent === window) return Promise.reject(new Error('桌面插件宿主不可用'));
    var id = 'pet-strict-' + strictHostRequestId++;
    return new Promise(function (resolve, reject) {
      var timer = window.setTimeout(function () {
        strictHostRequests.delete(id);
        reject(new Error('桌面插件宿主请求超时：' + command));
      }, 60000);
      strictHostRequests.set(id, { resolve: resolve, reject: reject, timer: timer });
      window.parent.postMessage({
        source: 'lamtools-desktop-plugin',
        id: id,
        command: command,
        args: args || {}
      }, '*');
    });
  };
  window.addEventListener('message', function (event) {
    if (event.source !== window.parent) return;
    var message = event.data;
    if (!message || message.source !== 'lamtools-desktop-host') return;
    if (message.type === 'file-drag-enter') {
      setFileDragActive(true);
      return;
    }
    if (message.type === 'file-drag-leave') {
      setFileDragActive(false);
      return;
    }
    if (message.type === 'files-dropped') {
      handleFilesDropped(message.files, message.dropId);
      return;
    }
    if (message.type === 'file-drop-error') {
      setFileDragActive(false);
      showError(message.message || '读取拖放文件失败');
      return;
    }
    var strictPending = strictHostRequests.get(message.id);
    if (strictPending) {
      strictHostRequests.delete(message.id);
      clearTimeout(strictPending.timer);
      if (message.error) strictPending.reject(new Error(String(message.error)));
      else strictPending.resolve(message.result);
      return;
    }
    var resolve = hostRequests.get(message.id);
    if (!resolve) return;
    hostRequests.delete(message.id);
    if (message.error) console.warn('[emotion-ball-pet] host command failed:', message.error);
    resolve(message.result);
  });

  var elements = {
    approvalActions: $('approvalActions'),
    approvalOptions: $('approvalOptions'),
    approveButton: $('approveButton'),
    attentionDot: $('attentionDot'),
    denyButton: $('denyButton'),
    guidanceForm: $('guidanceForm'),
    guidanceInput: $('guidanceInput'),
    guidanceSubmitButton: $('guidanceSubmitButton'),
    interactionCard: $('interactionCard'),
    interactionDetail: $('interactionDetail'),
    interactionDetailLabel: $('interactionDetailLabel'),
    interactionDetailValue: $('interactionDetailValue'),
    interactionKind: $('interactionKind'),
    interactionMessage: $('interactionMessage'),
    interactionTitle: $('interactionTitle'),
    petCard: $('petCard'),
    petCardActions: $('petCardActions'),
    petCardBody: $('petCardBody'),
    petCardClose: $('petCardClose'),
    petCardFiles: $('petCardFiles'),
    petCardInput: $('petCardInput'),
    petCardInputWrap: $('petCardInputWrap'),
    petCardTitle: $('petCardTitle'),
    petComposer: $('petComposer'),
    petComposerInput: $('petComposerInput'),
    petComposerSend: $('petComposerSend'),
    petPanel: $('petPanel'),
    petShell: document.querySelector('.pet-shell'),
    petToggle: $('petToggle'),
    queuePreviewSecond: $('queuePreviewSecond'),
    queuePreviewThird: $('queuePreviewThird'),
    statusBadge: $('statusBadge')
  };

  var ball = window.EmotionBall.create($('ball'), {
    emotion: '05',
    idle: true,
    lite: true,
    eyeScale: 1.08,
    autostart: !reducedMotion.matches
  });
  if (reducedMotion.matches) ball.renderStatic();

  var state = {
    viewMode: VIEW_MODE.PET,
    sessionId: '',
    socket: null,
    rpcId: 1,
    pendingRpc: new Map(),
    connectionGeneration: 0,
    reconnectAttempt: 0,
    reconnectTimer: 0,
    connected: false,
    sessionRecoveryAttempted: false,
    connectionPromise: null,
    clientMessageId: 1,
    running: false,
    interaction: null,
    interactionGuidance: '',
    replyItemId: '',
    replyText: '',
    terminalCardShown: false,
    autoExpandedRequestId: '',
    suppressedRequestId: '',
    expansionGeneration: 0,
    expansionPending: false,
    idleTimer: 0
  };
  var dragGesture = null;
  var suppressPetToggleClick = false;
  var pointerPassthrough = null;
  var pointerPassthroughTimer = 0;
  var activeCard = null;
  var suspendedCard = null;
  var cardDismissTimer = 0;
  var isFileDragActive = false;
  var pendingFiles = [];
  var pendingDropId = '';
  var pendingImportedFiles = [];
  var fileInstruction = '';
  var fileSendInFlight = false;
  var desktopDragInFlight = false;
  var dockDetectionTimer = 0;

  function isInteractiveRenderedPoint(x, y) {
    if (!Number.isFinite(x) || !Number.isFinite(y)) return false;
    var target = document.elementFromPoint(x, y);
    return target instanceof Element && !!target.closest('[data-pet-hit-surface]');
  }

  async function pollPointerPassthrough() {
    var cursor = await invoke('get_desktop_plugin_cursor_position');
    if (cursor && Number.isFinite(cursor.x) && Number.isFinite(cursor.y)) {
      var nextPassthrough = !isInteractiveRenderedPoint(cursor.x, cursor.y);
      if (nextPassthrough !== pointerPassthrough) {
        var applied = await invoke('set_desktop_plugin_cursor_passthrough', {
          passthrough: nextPassthrough
        });
        if (applied === nextPassthrough) pointerPassthrough = nextPassthrough;
      }
    }
    pointerPassthroughTimer = window.setTimeout(pollPointerPassthrough, 16);
  }

  function setEmotion(id) {
    ball.setEmotion(id);
    if (reducedMotion.matches) ball.renderStatic();
  }

  function setStatus(text, tone, emotionId) {
    elements.statusBadge.textContent = text;
    elements.statusBadge.dataset.tone = tone || 'idle';
    if (emotionId) setEmotion(emotionId);
  }

  function cardPriority(card) {
    return CARD_PRIORITY[String(card && card.kind || 'info')] || 0;
  }

  function clearCardTimer() {
    if (cardDismissTimer) window.clearTimeout(cardDismissTimer);
    cardDismissTimer = 0;
  }

  function clearCardVisual() {
    clearCardTimer();
    activeCard = null;
    renderCard(null);
  }

  function isInteractionCard(card) {
    return !!card && (card.kind === 'approval' || card.kind === 'question');
  }

  function restoreSuspendedCard() {
    if (!suspendedCard) return false;
    var card = suspendedCard;
    suspendedCard = null;
    if (card.kind === 'file') {
      if (pendingFiles.length === 0) return false;
      showPendingFileCard();
      return true;
    }
    return showCard(card);
  }

  function setFileDragActive(active) {
    isFileDragActive = !!active;
    document.body.dataset.fileDrag = isFileDragActive ? 'true' : 'false';
    if (isFileDragActive) {
      setStatus('释放以添加文件', 'waiting', '35');
      return;
    }
    if (state.interaction) {
      setStatus('等待你的输入', 'waiting', '35');
    } else if (state.running) {
      setStatus('正在处理', 'idle', '32');
    } else if (state.connected) {
      setStatus('待命中', 'idle', '02');
    }
  }

  function normalizeDroppedFiles(files, dropId) {
    var normalizedDropId = String(dropId || '').trim();
    return (Array.isArray(files) ? files : []).map(function (file, index) {
      var raw = file && typeof file === 'object' ? file : { path: file };
      var path = String(raw.path || '').trim();
      var suppliedName = String(raw.name || '').trim();
      if (!suppliedName && !path) return null;
      var normalizedPath = path.replace(/[\\/]+$/, '');
      var separator = Math.max(normalizedPath.lastIndexOf('\\'), normalizedPath.lastIndexOf('/'));
      var name = suppliedName || normalizedPath.slice(separator + 1) || normalizedPath;
      if (!name) return null;
      return {
        name: name,
        index: Number.isInteger(raw.index) ? raw.index : index,
        dropId: normalizedDropId
      };
    }).filter(Boolean);
  }

  function discardPendingDrop() {
    var dropId = pendingDropId;
    pendingDropId = '';
    if (dropId) void invoke('discard_dropped_files', { dropId: dropId });
  }

  function cancelPendingFiles() {
    discardPendingDrop();
    pendingFiles = [];
    pendingImportedFiles = [];
    fileInstruction = '';
    fileSendInFlight = false;
    if (activeCard && activeCard.kind === 'file') hideCard('file-cancelled');
  }

  function showPendingFileCard(options) {
    options = options || {};
    if (pendingFiles.length === 0) {
      cancelPendingFiles();
      return;
    }
    var sending = options.sending === true;
    showCard({
      kind: 'file',
      title: options.title || '已添加 ' + pendingFiles.length + ' 个文件',
      body: options.body || '想让我怎么处理？',
      files: pendingFiles.slice(),
      autoDismissMs: null,
      input: true,
      inputValue: fileInstruction,
      inputPlaceholder: '输入指令（可选）…',
      onInput: function (value) { fileInstruction = String(value || ''); },
      onRemoveFile: function (index) {
        if (fileSendInFlight) return;
        pendingFiles.splice(index, 1);
        pendingImportedFiles.splice(index, 1);
        showPendingFileCard();
      },
      disableFileEdits: sending,
      actions: [
        { id: 'cancel-files', label: '取消', onClick: cancelPendingFiles, disabled: sending },
        { id: 'send-files', label: '发送', tone: 'primary', onClick: sendPendingFiles, disabled: sending }
      ]
    });
  }

  function handleFilesDropped(files, dropId) {
    setFileDragActive(false);
    discardPendingDrop();
    pendingDropId = String(dropId || '').trim();
    pendingFiles = normalizeDroppedFiles(files, pendingDropId);
    pendingImportedFiles = [];
    fileInstruction = '';
    if (!pendingDropId || pendingFiles.length === 0) {
      pendingDropId = '';
      showError('没有可用的拖放文件');
      return;
    }
    showPendingFileCard();
  }

  function renderCard(card) {
    if (!card) {
      elements.petCardTitle.textContent = '';
      elements.petCardBody.textContent = '';
      elements.petCardFiles.replaceChildren();
      elements.petCardFiles.hidden = true;
      elements.petCardInput.value = '';
      elements.petCardInput.disabled = false;
      elements.petCardInputWrap.hidden = true;
      elements.petCardActions.replaceChildren();
      return;
    }
    elements.petCardTitle.textContent = String(card.title || '桌宠提示');
    elements.petCardBody.textContent = String(card.body || '');
    elements.petCardFiles.replaceChildren();
    var files = Array.isArray(card.files) ? card.files : [];
    files.forEach(function (file, index) {
      var row = document.createElement('div');
      row.className = 'pet-card-file';
      var name = document.createElement('span');
      name.className = 'pet-card-file-name';
      name.textContent = String(file && typeof file === 'object' ? file.name || file.path || '' : file || '');
      row.appendChild(name);
      if (typeof card.onRemoveFile === 'function') {
        var remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'pet-card-file-remove';
        remove.textContent = '×';
        remove.disabled = card.disableFileEdits === true;
        remove.setAttribute('aria-label', '删除 ' + name.textContent);
        remove.addEventListener('click', function () { card.onRemoveFile(index); });
        row.appendChild(remove);
      }
      elements.petCardFiles.appendChild(row);
    });
    elements.petCardFiles.hidden = files.length === 0;
    var inputEnabled = card.input === true || typeof card.onInput === 'function';
    elements.petCardInputWrap.hidden = !inputEnabled;
    elements.petCardInput.disabled = card.disableFileEdits === true;
    elements.petCardInput.placeholder = String(card.inputPlaceholder || '输入内容…');
    if (typeof card.inputValue === 'string' && elements.petCardInput.value !== card.inputValue) {
      elements.petCardInput.value = card.inputValue;
    }
    elements.petCardActions.replaceChildren();
    (Array.isArray(card.actions) ? card.actions : []).forEach(function (action) {
      if (!action || typeof action !== 'object') return;
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'button ' + (action.tone === 'primary' ? 'primary' : 'secondary');
      button.textContent = String(action.label || action.id || '操作');
      button.disabled = action.disabled === true;
      button.addEventListener('click', function () {
        if (typeof action.onClick === 'function') action.onClick();
      });
      elements.petCardActions.appendChild(button);
    });
  }

  function showCard(card) {
    if (!card || typeof card !== 'object') return false;
    var kind = String(card.kind || 'info');
    if (state.viewMode === VIEW_MODE.PANEL && ['reply', 'success', 'info'].includes(kind)) return false;
    if (activeCard && cardPriority(card) < cardPriority(activeCard)) return false;
    if (activeCard && cardPriority(card) > cardPriority(activeCard)) suspendedCard = activeCard;
    clearCardTimer();
    activeCard = Object.assign({ kind: 'info', title: '桌宠提示', body: '', files: [], actions: [] }, card);
    renderCard(activeCard);
    void setViewMode(VIEW_MODE.CARD, { reason: 'card' });
    var timeout = Number(activeCard.autoDismissMs);
    if (Number.isFinite(timeout) && timeout > 0) {
      cardDismissTimer = window.setTimeout(function () { hideCard('timeout'); }, timeout);
    }
    return true;
  }

  function hideCard(reason) {
    var keepSuspendedCard = isInteractionCard(activeCard);
    clearCardVisual();
    if (!keepSuspendedCard) suspendedCard = null;
    if (state.viewMode === VIEW_MODE.CARD) void setViewMode(VIEW_MODE.PET, { reason: reason || 'dismiss' });
  }

  function promoteCardToPanel() {
    clearCardVisual();
    if (state.viewMode !== VIEW_MODE.PANEL) void setViewMode(VIEW_MODE.PANEL, { reason: 'card-detail' });
  }

  function delay(milliseconds) {
    return new Promise(function (resolve) { window.setTimeout(resolve, milliseconds); });
  }

  function nextFrame() {
    return new Promise(function (resolve) { requestAnimationFrame(function () { requestAnimationFrame(resolve); }); });
  }

  function rememberCollapsedViewport() {
    collapsedViewportWidth = window.innerWidth;
    collapsedViewportHeight = window.innerHeight;
    document.documentElement.style.setProperty('--pet-collapsed-width', window.innerWidth + 'px');
    document.documentElement.style.setProperty('--pet-collapsed-height', window.innerHeight + 'px');
  }

  function boxWidth(style) {
    return parseFloat(style.paddingLeft || '0')
      + parseFloat(style.paddingRight || '0')
      + parseFloat(style.borderLeftWidth || '0')
      + parseFloat(style.borderRightWidth || '0');
  }

  function textWidth(element, text) {
    var style = getComputedStyle(element);
    var canvas = textWidth.canvas || (textWidth.canvas = document.createElement('canvas'));
    var context = canvas.getContext('2d');
    context.font = style.font || [style.fontWeight, style.fontSize, style.fontFamily].join(' ');
    var lines = String(text == null ? element.textContent : text).split('\n');
    var width = lines.reduce(function (maximum, line) {
      return Math.max(maximum, context.measureText(line).width);
    }, 0);
    return width + boxWidth(style);
  }

  function preferredInteractionWidth(panel) {
    var candidates = [];
    var heading = panel.querySelector('.interaction-heading');
    var headingStyle = getComputedStyle(heading);
    candidates.push(
      textWidth(heading.querySelector('#interactionTitle'))
      + textWidth(heading.querySelector('#interactionKind'))
      + parseFloat(headingStyle.columnGap || headingStyle.gap || '0')
    );
    candidates.push(textWidth(panel.querySelector('.interaction-message')));

    var detail = panel.querySelector('.interaction-detail');
    if (!detail.hidden) candidates.push(textWidth(detail.querySelector('.interaction-detail-value')));

    panel.querySelectorAll('.approval-option').forEach(function (option) {
      var label = option.querySelector('.approval-option-label');
      var description = option.querySelector('.approval-option-description');
      candidates.push(
        Math.max(textWidth(label), description ? textWidth(description) : 0)
        + boxWidth(getComputedStyle(option))
      );
    });

    var actions = panel.querySelector('.approval-actions');
    if (!actions.hidden) {
      var actionStyle = getComputedStyle(actions);
      var actionWidth = Array.from(actions.querySelectorAll('.button')).reduce(function (sum, button) {
        return sum + textWidth(button);
      }, 0);
      candidates.push(actionWidth + parseFloat(actionStyle.columnGap || actionStyle.gap || '0'));
    }

    var form = panel.querySelector('.guidance-form');
    if (!form.hidden) {
      var formStyle = getComputedStyle(form);
      var input = form.querySelector('textarea');
      var submit = form.querySelector('.button');
      candidates.push(
        textWidth(input, input.getAttribute('placeholder') || '')
        + textWidth(submit)
        + parseFloat(formStyle.columnGap || formStyle.gap || '0')
      );
    }
    return Math.ceil(Math.max.apply(Math, candidates));
  }

  function syncQueueLayers() {
    [elements.queuePreviewSecond, elements.queuePreviewThird].forEach(function (preview) {
      preview.hidden = true;
    });
  }

  function measureInteractionPanel() {
    var placementStyle = getComputedStyle(elements.petPanel);
    var leftInset = Number.isFinite(parseFloat(placementStyle.left)) ? parseFloat(placementStyle.left) : 0;
    var rightInset = Number.isFinite(parseFloat(placementStyle.right)) ? parseFloat(placementStyle.right) : 0;
    var bottomInset = Number.isFinite(parseFloat(placementStyle.bottom)) ? parseFloat(placementStyle.bottom) : 0;
    var horizontalEdgeSpace = leftInset + rightInset;
    var verticalEdgeSpace = bottomInset * 2;
    var baseInset = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--space-2')) || 0;
    var maximumPanelWidth = expandedMeasurementViewportWidth - baseInset * 2;
    var measurement = elements.petPanel.cloneNode(true);
    measurement.removeAttribute('id');
    measurement.removeAttribute('hidden');
    measurement.setAttribute('aria-hidden', 'true');
    measurement.style.position = 'fixed';
    measurement.style.top = '0';
    measurement.style.right = 'auto';
    measurement.style.bottom = 'auto';
    measurement.style.left = '-10000px';
    measurement.style.width = 'fit-content';
    measurement.style.height = 'auto';
    measurement.style.minWidth = '0';
    measurement.style.maxWidth = Math.max(1, maximumPanelWidth) + 'px';
    measurement.style.maxHeight = 'none';
    measurement.style.opacity = '0';
    measurement.style.visibility = 'hidden';
    measurement.style.transform = 'none';
    measurement.style.transition = 'none';
    measurement.style.pointerEvents = 'none';
    document.body.appendChild(measurement);

    var panelStyle = getComputedStyle(measurement);
    var panelChromeWidth =
      boxWidth(panelStyle);
    var panelChromeHeight =
      parseFloat(panelStyle.paddingTop || '0')
      + parseFloat(panelStyle.paddingBottom || '0')
      + parseFloat(panelStyle.borderTopWidth || '0')
      + parseFloat(panelStyle.borderBottomWidth || '0');
    var content = measurement.querySelector('.interaction-region');
    var preferredPanelWidth = Math.min(
      maximumPanelWidth,
      preferredInteractionWidth(measurement) + panelChromeWidth
    );
    measurement.style.width = preferredPanelWidth + 'px';
    measurement.style.maxWidth = 'none';
    var size = {
      width: Math.ceil(Math.max(collapsedViewportWidth, preferredPanelWidth + horizontalEdgeSpace)),
      height: Math.ceil(Math.max(collapsedViewportHeight, content.scrollHeight + panelChromeHeight + verticalEdgeSpace))
    };
    measurement.remove();
    return size;
  }

  function applyAnchor(anchor, verticalAnchor) {
    var normalized = anchor === 'left' ? 'left' : 'right';
    var normalizedVertical = verticalAnchor === 'top' ? 'top' : 'bottom';
    document.body.classList.toggle('anchor-left', normalized === 'left');
    document.body.classList.toggle('anchor-right', normalized === 'right');
    document.body.classList.toggle('anchor-top', normalizedVertical === 'top');
    document.body.classList.toggle('anchor-bottom', normalizedVertical === 'bottom');
  }

  async function setViewMode(nextMode, options) {
    var mode = String(nextMode || '').trim().toLowerCase();
    if (![VIEW_MODE.PET, VIEW_MODE.CARD, VIEW_MODE.PANEL].includes(mode)) {
      throw new Error('未知桌宠视图模式：' + mode);
    }
    var userInitiated = !!(options && options.userInitiated);
    if (userInitiated && mode === VIEW_MODE.PET && state.interaction) {
      state.suppressedRequestId = state.interaction.requestId;
    }
    if (state.viewMode === mode && !state.expansionPending) return;

    var generation = ++state.expansionGeneration;
    state.expansionPending = true;
    state.viewMode = mode;
    document.body.dataset.viewMode = mode;
    document.body.classList.toggle('is-collapsed', mode === VIEW_MODE.PET);
    document.body.classList.toggle('is-window-open', mode !== VIEW_MODE.PET);
    document.body.classList.toggle('is-card-visible', mode !== VIEW_MODE.PET);
    elements.petToggle.setAttribute('aria-expanded', String(mode === VIEW_MODE.PANEL));
    elements.petCard.hidden = mode !== VIEW_MODE.CARD;
    elements.petPanel.hidden = mode !== VIEW_MODE.PANEL;
    if (mode === VIEW_MODE.PANEL) elements.interactionCard.scrollTop = 0;
    try {
      var preview = await invoke('get_desktop_plugin_view_mode_transition', {
        mode: mode
      });
      if (generation !== state.expansionGeneration) return;
      if (preview && (preview.anchor || preview.verticalAnchor)) {
        applyAnchor(preview.anchor, preview.verticalAnchor);
      }
      var transition = await invoke('set_desktop_plugin_view_mode', {
        mode: mode,
        reducedMotion: reducedMotion.matches
      });
      if (generation !== state.expansionGeneration) return;
      if (transition && (transition.anchor || transition.verticalAnchor)) {
        applyAnchor(transition.anchor, transition.verticalAnchor);
      }
      if (mode === VIEW_MODE.PANEL) syncQueueLayers();
    } finally {
      if (generation === state.expansionGeneration) state.expansionPending = false;
    }
  }

  function setExpanded(expanded, options) {
    return setViewMode(expanded ? VIEW_MODE.PANEL : VIEW_MODE.PET, options);
  }

  function scheduleIdle() {
    clearTimeout(state.idleTimer);
    state.idleTimer = window.setTimeout(function () {
      if (!state.running && !state.interaction && state.connected) setStatus('待命中', 'idle', '02');
    }, 2200);
  }

  function resetReplyBuffer() {
    state.replyItemId = '';
    state.replyText = '';
    state.terminalCardShown = false;
  }

  function contentText(value) {
    if (typeof value === 'string') return value;
    if (Array.isArray(value)) {
      return value.map(function (part) {
        if (typeof part === 'string') return part;
        if (!part || typeof part !== 'object') return '';
        return String(part.text || part.content || '');
      }).join('');
    }
    if (value && typeof value === 'object') return String(value.text || value.content || '');
    return value == null ? '' : String(value);
  }

  function replySummary(text) {
    var lines = String(text || '').trim().split(/\r?\n/).map(function (line) {
      return line.trim();
    }).filter(Boolean).slice(0, 4);
    var summary = lines.join('\n');
    if (summary.length > 360) summary = summary.slice(0, 357).trimEnd() + '…';
    return summary || 'Agent 已完成回答。';
  }

  function updateReplyBuffer(itemId, payload) {
    if (!payload || payload.type === 'compaction' || payload.type === 'userMessage') return;
    var payloadType = String(payload.type || '').toLowerCase();
    if (payloadType && payloadType !== 'agentmessage' && payloadType !== 'assistantmessage') return;
    var normalizedItemId = String(itemId || '').trim();
    if (normalizedItemId && state.replyItemId && normalizedItemId !== state.replyItemId) {
      state.replyText = '';
    }
    if (normalizedItemId) state.replyItemId = normalizedItemId;
    var delta = contentText(payload.delta);
    if (delta) {
      state.replyText += delta;
      return;
    }
    var content = contentText(payload.content).trim();
    if (!content) return;
    if (state.replyText && content.startsWith(state.replyText)) {
      state.replyText = content;
    } else if (content !== state.replyText) {
      state.replyText = content;
    }
  }

  function showTerminalCard() {
    if (state.terminalCardShown) return;
    state.terminalCardShown = true;
    var reply = state.replyText.trim();
    if (reply) {
      if (state.viewMode !== VIEW_MODE.PANEL) {
        showCard({
          kind: 'reply',
          title: 'Agent 回复',
          body: replySummary(reply),
          autoDismissMs: 8000,
          actions: [{ id: 'reply-details', label: '查看完整', onClick: promoteCardToPanel }]
        });
      }
      return;
    }
    if (state.viewMode !== VIEW_MODE.PANEL) {
      showCard({
        kind: 'success',
        title: '处理完成',
        body: '✓ 已完成',
        autoDismissMs: 5000
      });
    }
  }

  function errorMessage(error) {
    return error instanceof Error ? error.message : String(error || '未知错误');
  }

  function showError(error) {
    state.running = false;
    var message = errorMessage(error);
    setStatus('连接或执行失败', 'error', '34');
    console.warn('[emotion-ball-pet]', message);
    if (state.viewMode !== VIEW_MODE.PANEL) {
      showCard({
        kind: 'error',
        title: '处理失败',
        body: message,
        autoDismissMs: 10000,
        actions: [{ id: 'error-details', label: '查看详情', onClick: promoteCardToPanel }]
      });
    }
  }

  function sendSocket(payload) {
    if (!state.socket || state.socket.readyState !== WebSocket.OPEN) {
      throw new Error('Core App Server 尚未连接');
    }
    state.socket.send(JSON.stringify(payload));
  }

  function rpcRequest(method, params, timeoutMs) {
    var id = state.rpcId++;
    return new Promise(function (resolve, reject) {
      var timer = window.setTimeout(function () {
        state.pendingRpc.delete(id);
        reject(new Error('请求超时：' + method));
      }, timeoutMs || 30000);
      state.pendingRpc.set(id, {
        resolve: function (value) { clearTimeout(timer); resolve(value || {}); },
        reject: function (error) { clearTimeout(timer); reject(error); }
      });
      try {
        sendSocket({ id: id, method: method, params: params || {} });
      } catch (error) {
        clearTimeout(timer);
        state.pendingRpc.delete(id);
        reject(error);
      }
    });
  }

  function closeSocket() {
    state.connectionGeneration += 1;
    state.connected = false;
    clearTimeout(state.reconnectTimer);
    state.reconnectTimer = 0;
    if (state.socket) state.socket.close();
    state.socket = null;
    state.pendingRpc.forEach(function (entry) {
      entry.reject(new Error('Core App Server 连接已关闭'));
    });
    state.pendingRpc.clear();
  }

  function scheduleReconnect(generation) {
    if (!state.sessionId || state.reconnectTimer || generation !== state.connectionGeneration) return;
    var delay = Math.min(10000, 500 * Math.pow(2, state.reconnectAttempt++));
    state.reconnectTimer = window.setTimeout(function () {
      state.reconnectTimer = 0;
      if (generation === state.connectionGeneration) startPetConnection(true);
    }, delay);
  }

  async function connectSession(sessionId, reconnecting) {
    if (!sessionId) return;
    closeSocket();
    state.sessionId = sessionId;
    var generation = state.connectionGeneration;
    setStatus(reconnecting ? '正在重新连接' : '正在连接会话', 'idle', reconnecting ? '36' : '05');
    try {
      var url = new URL('/api/core/app-server', window.location.origin);
      url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
      var socket = new WebSocket(url.toString());
      state.socket = socket;
      await new Promise(function (resolve, reject) {
        socket.onopen = resolve;
        socket.onerror = function () { reject(new Error('Core App Server WebSocket 连接失败')); };
        socket.onmessage = handleSocketMessage;
        socket.onclose = function () {
          if (generation !== state.connectionGeneration) return;
          state.connected = false;
          setStatus('连接已断开', 'error', '34');
          scheduleReconnect(generation);
        };
      });
      if (generation !== state.connectionGeneration) {
        socket.close();
        return;
      }
      await rpcRequest('initialize', {
        clientInfo: { name: 'emotion_ball_pet', title: 'Emotion Ball Pet', version: '0.1.0' },
        threadId: sessionId,
        lastSeenSeq: 0
      });
      sendSocket({ method: 'initialized', params: {} });
      var resumed = await rpcRequest('thread/resume', {
        thread_id: sessionId,
        last_seen_seq: 0
      }, 60000);
      if (resumed.snapshot) applySnapshot(resumed.snapshot);
      state.connected = true;
      state.reconnectAttempt = 0;
      state.sessionRecoveryAttempted = false;
      if (!state.interaction && !state.running) setStatus('待命中', 'idle', '02');
    } catch (error) {
      if (generation !== state.connectionGeneration) return;
      if (isSessionNotFoundError(error) && !state.sessionRecoveryAttempted) {
        state.sessionRecoveryAttempted = true;
        try {
          var recoveredSessionId = await ensurePetSession();
          await connectSession(recoveredSessionId, false);
          return;
        } catch (recoveryError) {
          error = recoveryError;
        }
      }
      showError(error);
      scheduleReconnect(generation);
    }
  }

  function isSessionNotFoundError(error) {
    return /session|thread/i.test(errorMessage(error)) && /not found|missing|不存在|404/i.test(errorMessage(error));
  }

  async function ensurePetSession() {
    var response = await fetch('/api/core/desktop-plugins/emotion-ball-pet/session', {
      method: 'POST',
      headers: { 'Accept': 'application/json' },
      cache: 'no-store'
    });
    if (!response.ok) throw new Error('无法建立桌宠专属会话（HTTP ' + response.status + '）');
    var data = await response.json();
    var sessionId = String(data && data.session_id || '').trim();
    if (!sessionId) throw new Error('桌宠专属会话响应缺少 session_id');
    state.sessionId = sessionId;
    return sessionId;
  }

  function startPetConnection(reconnecting) {
    if (state.connectionPromise) return state.connectionPromise;
    var session = state.sessionId
      ? Promise.resolve(state.sessionId)
      : ensurePetSession();
    state.connectionPromise = session
      .then(function (sessionId) { return connectSession(sessionId, !!reconnecting); })
      .finally(function () { state.connectionPromise = null; });
    return state.connectionPromise;
  }

  async function sendPetTurn(options) {
    options = options || {};
    var text = String(options.text || '').trim();
    var attachments = Array.isArray(options.attachments) ? options.attachments : [];
    var input = [];
    if (text) input.push({ type: 'text', text: text });
    attachments.forEach(function (attachment) {
      if (!attachment || typeof attachment !== 'object') return;
      var id = String(attachment.attachment_id || attachment.id || '').trim();
      if (!id) return;
      input.push({
        type: 'attachment',
        attachment_id: id,
        filename: attachment.filename || '',
        mime_type: attachment.mime_type || '',
        preview_type: attachment.preview_type || '',
        size: attachment.size
      });
    });
    if (input.length === 0) throw new Error('请输入消息内容');
    if (!state.connected || !state.socket || state.socket.readyState !== WebSocket.OPEN) {
      await startPetConnection(false);
    }
    if (!state.connected || !state.socket || state.socket.readyState !== WebSocket.OPEN) {
      throw new Error('Core App Server 尚未连接');
    }
    resetReplyBuffer();
    var response = await rpcRequest('turn/start', {
      thread_id: state.sessionId,
      client_message_id: 'pet-' + Date.now() + '-' + state.clientMessageId++,
      input: input
    }, 60000);
    state.running = true;
    setStatus('正在处理', 'idle', '32');
    return response;
  }

  function base64ToBytes(value) {
    var binary = atob(String(value || ''));
    var bytes = new Uint8Array(binary.length);
    for (var index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
    return bytes;
  }

  async function importPendingDrop() {
    if (!pendingDropId) throw new Error('拖放文件引用已失效');
    if (pendingImportedFiles.length >= pendingFiles.length && pendingImportedFiles.length > 0) {
      return pendingImportedFiles;
    }
    var result = await invokeStrict('import_dropped_files', { dropId: pendingDropId });
    if (!result || !Array.isArray(result.files)) throw new Error('无法读取拖放文件');
    pendingImportedFiles = result.files;
    if (pendingImportedFiles.length < pendingFiles.length) {
      throw new Error('拖放文件读取不完整');
    }
    return pendingImportedFiles;
  }

  async function uploadPendingFiles() {
    var imported = await importPendingDrop();
    for (var index = 0; index < pendingFiles.length; index += 1) {
      var pending = pendingFiles[index];
      if (pending.attachment && pending.attachment.id) continue;
      var importedIndex = Number.isInteger(pending.index) ? pending.index : index;
      var file = imported[importedIndex];
      if (!file || !file.dataBase64) throw new Error('拖放文件读取不完整');
      var filename = String(file.name || pending.name || 'attachment');
      var blob = new Blob([base64ToBytes(file.dataBase64)], { type: 'application/octet-stream' });
      var body = new FormData();
      body.append('file', blob, filename);
      var response = await fetch('/api/core/sessions/' + encodeURIComponent(state.sessionId) + '/attachments', {
        method: 'POST',
        body: body
      });
      if (!response.ok) throw new Error('附件上传失败（HTTP ' + response.status + '）：' + filename);
      pending.attachment = await response.json();
    }
    return pendingFiles.map(function (pending) { return pending.attachment; });
  }

  async function sendPendingFiles() {
    if (fileSendInFlight || pendingFiles.length === 0) return;
    fileSendInFlight = true;
    showPendingFileCard({
      sending: true,
      title: '正在添加文件…',
      body: '正在添加文件…'
    });
    try {
      if (!state.connected || !state.socket || state.socket.readyState !== WebSocket.OPEN) {
        await startPetConnection(false);
      }
      if (!state.connected || !state.sessionId) throw new Error('Core App Server 尚未连接');
      var attachments = await uploadPendingFiles();
      await sendPetTurn({
        text: fileInstruction.trim() || '请查看这些文件。',
        attachments: attachments
      });
      pendingFiles = [];
      pendingImportedFiles = [];
      discardPendingDrop();
      fileInstruction = '';
      hideCard('file-sent');
    } catch (error) {
      showError(error);
      showPendingFileCard({
        title: '文件发送失败',
        body: '文件和指令已保留，可修正后重试。\n' + errorMessage(error)
      });
    } finally {
      fileSendInFlight = false;
    }
  }

  function showDockCard(zone) {
    var normalizedZone = zone === 'left' ? 'left' : zone === 'right' ? 'right' : '';
    if (!normalizedZone) return;
    var label = normalizedZone === 'left' ? '左侧' : '右侧';
    showCard({
      kind: 'dock',
      title: '固定桌宠位置？',
      body: '要将桌宠固定在屏幕' + label + '吗？',
      actions: [
        { id: 'dock-cancel', label: '取消', onClick: function () { hideCard('dock-cancelled'); } },
        { id: 'dock-confirm', label: '固定', tone: 'primary', onClick: function () {
          invokeStrict('set_desktop_plugin_dock', { dock: normalizedZone })
            .then(function () {
              setStatus('已固定在' + label, 'done', '33');
              hideCard('dock-confirmed');
            })
            .catch(showError);
        } }
      ]
    });
  }

  function scheduleDockDetection() {
    if (dockDetectionTimer) window.clearTimeout(dockDetectionTimer);
    dockDetectionTimer = window.setTimeout(function () {
      dockDetectionTimer = 0;
      invoke('get_desktop_plugin_dock_zone').then(function (zone) {
        if (zone === 'left' || zone === 'right') showDockCard(zone);
      });
    }, 360);
  }

  function handleSocketMessage(messageEvent) {
    var message;
    try {
      message = JSON.parse(messageEvent.data);
    } catch (error) {
      showError('收到无法解析的 App Server 消息');
      return;
    }
    if (message.id !== undefined && typeof message.method === 'string') {
      if (message.params && typeof message.params === 'object') applyEvent(message.params);
      return;
    }
    if (message.id !== undefined) {
      var pending = state.pendingRpc.get(message.id);
      if (!pending) return;
      state.pendingRpc.delete(message.id);
      if (message.error) pending.reject(new Error(message.error.message || 'Core 请求失败'));
      else pending.resolve(message.result || {});
      return;
    }
    if (message.method === 'thread/snapshot' && message.params) {
      applySnapshot(message.params);
    } else if (message.params) {
      applyEvent(message.params);
    }
  }

  function runtimeSnapshot(snapshot) {
    return snapshot && snapshot.core && typeof snapshot.core === 'object' ? snapshot.core : snapshot || {};
  }

  function pendingInteraction(snapshot) {
    var runtime = runtimeSnapshot(snapshot);
    var requests = Object.assign({}, snapshot && snapshot.requests || {}, runtime.requests || {});
    var openRequests = Object.keys(requests).map(function (id) {
      var request = requests[id] || {};
      var status = String(request.status || '').toLowerCase();
      if (['approved', 'denied', 'resolved', 'completed', 'cancelled'].includes(status)) return null;
      return { requestId: request.request_id || id, request: request };
    }).filter(Boolean);
    if (openRequests.length === 0) return null;
    var openRequestIds = new Set(openRequests.map(function (entry) { return entry.requestId; }));
    var items = runtime.items || {};
    var order = runtime.item_order || [];
    for (var index = 0; index < order.length; index += 1) {
      var item = items[order[index]] || {};
      var payload = item.payload || {};
      var isApproval = item.kind === 'approval_request' || item.last_kind === 'approval_request' || payload.type === 'serverRequest';
      if (!isApproval) continue;
      var id = payload.request_id || item.request_id || '';
      if (!id) continue;
      if (!openRequestIds.has(id)) continue;
      var toolName = String(payload.tool_name || item.tool_name || '');
      return {
        requestId: id,
        type: toolName === 'question' || String(payload.kind || '').toLowerCase() === 'question' ? 'question' : 'approval',
        message: payload.message || payload.title || 'Agent 请求执行下一步操作。',
        options: Array.isArray(payload.options) ? payload.options : [],
        arguments: payload.arguments || item.arguments || {},
        toolName: toolName
      };
    }
    var oldest = openRequests[0];
    var oldestRequest = oldest.request || {};
    var oldestToolName = String(oldestRequest.tool_name || '');
    return {
      requestId: oldest.requestId,
      type: oldestToolName === 'question' || String(oldestRequest.kind || '').toLowerCase() === 'question' ? 'question' : 'approval',
      message: oldestRequest.message || oldestRequest.title || 'Agent 请求执行下一步操作。',
      options: Array.isArray(oldestRequest.options) ? oldestRequest.options : [],
      arguments: oldestRequest.arguments || {},
      toolName: oldestToolName
    };
  }

  function applySnapshot(snapshot) {
    showInteraction(pendingInteraction(snapshot));
    var status = String(runtimeSnapshot(snapshot).status || snapshot.status || '');
    applyRunStatus(status, { announce: false });
  }

  function applyEvent(event) {
    var method = event.method || '';
    var value = event.payload || {};
    if (method === 'turn/accepted') {
      resetReplyBuffer();
      state.running = true;
      setStatus('已收到问题', 'idle', '31');
      return;
    }
    if (method !== 'core/runItem') return;
    var kind = value.kind || '';
    var payload = value.payload || {};
    if (kind === 'message') {
      updateReplyBuffer(value.item_id || value.itemId, payload);
      state.running = true;
      setStatus('正在回答', 'idle', '39');
    } else if (kind === 'approval_request') {
      var toolName = String(payload.tool_name || value.tool_name || '');
      var interaction = {
        requestId: payload.request_id || value.request_id,
        type: toolName === 'question' || String(payload.kind || '').toLowerCase() === 'question' ? 'question' : 'approval',
        message: payload.message || 'Agent 请求执行下一步操作。',
        options: Array.isArray(payload.options) ? payload.options : [],
        arguments: payload.arguments || value.arguments || {},
        toolName: toolName
      };
      if (!state.interaction || state.interaction.requestId === interaction.requestId) showInteraction(interaction);
    } else if (kind === 'tool_call') {
      state.running = true;
      var name = String(payload.tool_name || value.tool_name || '');
      setStatus(name.includes('search') || name.includes('web') ? '正在检索资料' : '正在处理任务', 'idle', name.includes('search') || name.includes('web') ? '40' : '32');
    } else if (kind === 'status') {
      applyRunStatus(payload.status || value.status || '', { announce: true, payload: payload });
    } else if (kind === 'error') {
      showError(payload.message || value.message || 'Agent 执行失败');
    }
  }

  function applyRunStatus(rawStatus, options) {
    var status = String(rawStatus || '').toLowerCase();
    if (!status) return;
    options = options || {};
    var announce = options.announce === true;
    if (status === 'running') {
      state.running = true;
      setStatus('正在思考', 'idle', '30');
    } else if (status === 'waiting') {
      state.running = false;
      setStatus('等待你的输入', 'waiting', '35');
    } else if (status === 'failed') {
      state.running = false;
      setStatus('任务失败', 'error', '34');
      if (announce) {
        var failurePayload = options.payload && typeof options.payload === 'object' ? options.payload : {};
        showError(failurePayload.message || failurePayload.error || failurePayload.raw_end_reason || 'Agent 执行失败');
      }
    } else if (status === 'cancelled') {
      state.running = false;
      setStatus('任务已停止', 'error', '41');
    } else if (status === 'completed' || status === 'idle') {
      state.running = false;
      if (!state.interaction) {
        setStatus(status === 'completed' ? '回答完成' : '待命中', status === 'completed' ? 'done' : 'idle', status === 'completed' ? '33' : '02');
        if (status === 'completed') {
          if (announce) showTerminalCard();
          scheduleIdle();
        }
      }
    }
  }

  function interactionCardData(interaction, isQuestion, presentation) {
    var requestId = interaction.requestId;
    var body = presentation.message;
    if (presentation.detail) body += '\n\n' + presentation.detailLabel + '\n' + presentation.detail;
    var card = {
      kind: isQuestion ? 'question' : 'approval',
      title: isQuestion ? '需要你的回答' : '需要批准',
      body: body,
      actions: []
    };
    if (isQuestion) {
      card.input = true;
      card.inputValue = state.interactionGuidance;
      card.inputPlaceholder = '补充回答（可选）…';
      card.onInput = function (value) {
        if (state.interaction && state.interaction.requestId === requestId) {
          state.interactionGuidance = String(value || '');
        }
      };
      (Array.isArray(interaction.options) ? interaction.options : []).forEach(function (raw, index) {
        if (!raw || typeof raw !== 'object') return;
        var label = String(raw.label || raw.title || raw.id || '选项 ' + (index + 1));
        var description = String(raw.description || raw.detail || '');
        var response = String(raw.response || ('我选择：' + label + (description ? '\n原因/说明：' + description : '')));
        card.actions.push({
          id: 'question-option-' + index,
          label: label,
          onClick: function () {
            if (state.interaction && state.interaction.requestId === requestId) {
              void respondApproval('other_guidance', response);
            }
          }
        });
      });
      card.actions.push({
        id: 'question-submit',
        label: '提交回答',
        tone: 'primary',
        onClick: function () {
          if (!state.interaction || state.interaction.requestId !== requestId) return;
          var guidance = elements.petCardInput.value.trim();
          if (guidance) void respondApproval('other_guidance', guidance);
        }
      });
      card.actions.push({ id: 'question-details', label: '查看详情', onClick: promoteCardToPanel });
      return card;
    }
    card.actions = [
      { id: 'approval-deny', label: '拒绝', onClick: function () {
        if (state.interaction && state.interaction.requestId === requestId) void respondApproval('deny');
      } },
      { id: 'approval-allow', label: '允许一次', tone: 'primary', onClick: function () {
        if (state.interaction && state.interaction.requestId === requestId) void respondApproval('approve_once');
      } },
      { id: 'approval-details', label: '查看详情', onClick: promoteCardToPanel }
    ];
    return card;
  }

  function showInteraction(interaction) {
    var previousRequestId = state.interaction && state.interaction.requestId;
    if (!interaction && isInteractionCard(activeCard)) {
      clearCardVisual();
      if (!restoreSuspendedCard() && state.viewMode === VIEW_MODE.CARD) {
        void setViewMode(VIEW_MODE.PET, { reason: 'interaction-cleared' });
      }
    } else if (!interaction && suspendedCard) {
      restoreSuspendedCard();
    }
    state.interaction = interaction && interaction.requestId ? interaction : null;
    if (state.interaction && previousRequestId !== state.interaction.requestId) {
      state.interactionGuidance = '';
    }
    elements.interactionCard.hidden = !state.interaction;
    elements.attentionDot.hidden = !state.interaction;
    elements.guidanceForm.hidden = true;
    elements.interactionDetail.hidden = true;
    elements.interactionCard.scrollTop = 0;
    elements.approvalOptions.replaceChildren();
    elements.approvalOptions.hidden = true;
    elements.approvalActions.hidden = false;
    document.body.classList.remove('interaction-question');
    if (!state.interaction) {
      syncQueueLayers();
      if (previousRequestId && state.viewMode !== VIEW_MODE.PET) setViewMode(VIEW_MODE.PET, { reason: 'interaction-cleared' });
      return;
    }

    var isQuestion = state.interaction.type === 'question';
    state.running = false;
    document.body.classList.toggle('interaction-question', isQuestion);
    elements.interactionTitle.textContent = isQuestion ? '需要你的回答' : '需要批准';
    elements.interactionKind.textContent = isQuestion ? 'Question' : 'Approval';
    var presentation = interactionPresentation(state.interaction, isQuestion);
    elements.interactionMessage.textContent = presentation.message;
    if (presentation.detail) {
      elements.interactionDetailLabel.textContent = presentation.detailLabel;
      elements.interactionDetailValue.textContent = presentation.detail;
      elements.interactionDetail.hidden = false;
    }
    renderInteractionOptions(state.interaction.options, isQuestion);
    if (isQuestion) {
      elements.approvalActions.hidden = true;
      elements.guidanceForm.hidden = false;
    }
    setStatus(isQuestion ? '等待你的回答' : '等待审批', 'waiting', '35');
    syncQueueLayers();
    var isNewRequest = previousRequestId !== state.interaction.requestId;
    if (isNewRequest && state.suppressedRequestId !== state.interaction.requestId) {
      state.autoExpandedRequestId = state.interaction.requestId;
      invoke('show_current_window');
      if (state.viewMode !== VIEW_MODE.PANEL) {
        showCard(interactionCardData(state.interaction, isQuestion, presentation));
      }
    }
  }

  function interactionPresentation(interaction, isQuestion) {
    var message = String(interaction.message || '');
    if (isQuestion) return { message: message || 'Agent 正在等待你的回答。', detail: '', detailLabel: '' };

    var args = interaction.arguments && typeof interaction.arguments === 'object' ? interaction.arguments : {};
    var command = String(args.command || '').trim();
    var commandPrefix = '需要授权后才能执行命令：';
    if (!command && message.startsWith(commandPrefix)) command = message.slice(commandPrefix.length).trim();
    if (command) {
      return {
        message: '允许桌宠执行下面的操作吗？',
        detail: command,
        detailLabel: '运行命令'
      };
    }
    if (interaction.toolName) {
      return {
        message: '允许桌宠执行下面的操作吗？',
        detail: interaction.toolName,
        detailLabel: '调用工具'
      };
    }
    return { message: message || '允许桌宠执行下面的操作吗？', detail: '', detailLabel: '' };
  }

  function renderInteractionOptions(options, isQuestion) {
    if (!Array.isArray(options) || options.length === 0) return;
    var standardApproval = !isQuestion && options.every(function (raw) {
      var id = String(raw && (raw.id || raw.value) || '').trim().toLowerCase();
      return ['approve', 'accept', 'approve_once', 'deny', 'decline', 'cancel'].includes(id);
    });
    if (standardApproval) return;
    options.forEach(function (raw, index) {
      if (!raw || typeof raw !== 'object') return;
      var id = String(raw.id || raw.value || 'option-' + (index + 1));
      var label = String(raw.label || raw.title || raw.id || '选项 ' + (index + 1));
      var description = String(raw.description || raw.detail || '');
      var response = String(raw.response || ('我选择：' + label + (description ? '\n原因/说明：' + description : '')));
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'approval-option';
      var labelNode = document.createElement('span');
      labelNode.className = 'approval-option-label';
      labelNode.textContent = label;
      button.appendChild(labelNode);
      if (description) {
        var descriptionNode = document.createElement('span');
        descriptionNode.className = 'approval-option-description';
        descriptionNode.textContent = description;
        button.appendChild(descriptionNode);
      }
      button.addEventListener('click', function () {
        if (isQuestion) {
          respondApproval('other_guidance', response || label);
          return;
        }
        var normalized = id.trim().toLowerCase();
        var decision = ['approve', 'accept', 'approve_once'].includes(normalized)
          ? 'approve_once'
          : ['deny', 'decline', 'cancel'].includes(normalized)
            ? 'deny'
            : normalized === 'approve_for_session' || normalized === 'acceptforsession'
              ? 'approve_for_session'
              : 'other_guidance';
        respondApproval(decision, response);
      });
      elements.approvalOptions.appendChild(button);
    });
    if (elements.approvalOptions.childElementCount > 0) {
      elements.approvalOptions.hidden = false;
      if (!isQuestion) elements.approvalActions.hidden = true;
    }
  }

  async function respondApproval(decision, guidance) {
    if (!state.interaction) return;
    var interactionType = state.interaction.type;
    var requestId = state.interaction.requestId;
    elements.approveButton.disabled = true;
    elements.denyButton.disabled = true;
    elements.guidanceSubmitButton.disabled = true;
    try {
      var response = await rpcRequest('approval/respond', {
        thread_id: state.sessionId,
        request_id: requestId,
        decision: decision,
        guidance: guidance || ''
      }, 60000);
      showInteraction(null);
      if (response.snapshot) applySnapshot(response.snapshot);
      var successText = interactionType === 'question' ? '已提交回答' : '已提交审批';
      setStatus(decision === 'deny' ? '已拒绝请求' : successText, decision === 'deny' ? 'error' : 'done', decision === 'deny' ? '38' : '33');
      scheduleIdle();
    } catch (error) {
      showError(error);
    } finally {
      elements.approveButton.disabled = false;
      elements.denyButton.disabled = false;
      elements.guidanceSubmitButton.disabled = false;
    }
  }

  elements.petToggle.addEventListener('click', function () {
    if (suppressPetToggleClick) {
      suppressPetToggleClick = false;
      return;
    }
    setViewMode(state.viewMode === VIEW_MODE.PANEL ? VIEW_MODE.PET : VIEW_MODE.PANEL, { userInitiated: true });
  });
  elements.petShell.addEventListener('pointerdown', function (event) {
    if (event.button !== 0) return;
    var target = event.target instanceof Element ? event.target : null;
    var control = target && target.closest('button, textarea, input, select, a');
    if (control && control !== elements.petToggle) return;
    dragGesture = {
      pointerId: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      fromPetToggle: !!(target && target.closest('#petToggle'))
    };
    elements.petShell.setPointerCapture(event.pointerId);
  });
  elements.petShell.addEventListener('pointermove', function (event) {
    if (!dragGesture || event.pointerId !== dragGesture.pointerId) return;
    if (Math.hypot(event.clientX - dragGesture.x, event.clientY - dragGesture.y) < 4) return;
    suppressPetToggleClick = dragGesture.fromPetToggle;
    if (suppressPetToggleClick) {
      window.setTimeout(function () { suppressPetToggleClick = false; }, 500);
    }
    dragGesture = null;
    desktopDragInFlight = true;
    elements.petShell.classList.add('is-dragging');
    invoke('start_window_dragging').finally(function () {
      desktopDragInFlight = false;
      elements.petShell.classList.remove('is-dragging');
      scheduleDockDetection();
    });
  });
  ['pointerup', 'pointercancel', 'lostpointercapture'].forEach(function (eventName) {
    elements.petShell.addEventListener(eventName, function () {
      dragGesture = null;
      elements.petShell.classList.remove('is-dragging');
      if (desktopDragInFlight) scheduleDockDetection();
    });
  });
  elements.approveButton.addEventListener('click', function () { respondApproval('approve_once'); });
  elements.denyButton.addEventListener('click', function () { respondApproval('deny'); });
  elements.petCardClose.addEventListener('click', function () { hideCard('user'); });
  elements.petCardInput.addEventListener('input', function () {
    if (activeCard && typeof activeCard.onInput === 'function') {
      activeCard.onInput(elements.petCardInput.value);
    }
  });
  elements.petComposer.addEventListener('submit', function (event) {
    event.preventDefault();
    var text = elements.petComposerInput.value.trim();
    if (!text) return;
    elements.petComposerSend.disabled = true;
    sendPetTurn({ text: text })
      .then(function () { elements.petComposerInput.value = ''; })
      .catch(showError)
      .finally(function () { elements.petComposerSend.disabled = false; });
  });
  elements.guidanceForm.addEventListener('submit', function (event) {
    event.preventDefault();
    var guidance = elements.guidanceInput.value.trim();
    if (!guidance) return;
    respondApproval('other_guidance', guidance);
    elements.guidanceInput.value = '';
  });
  elements.petToggle.addEventListener('pointermove', function (event) {
    var rect = elements.petToggle.getBoundingClientRect();
    ball.setGaze((event.clientX - rect.left) / rect.width * 2 - 1, (event.clientY - rect.top) / rect.height * 2 - 1);
  });
  elements.petToggle.addEventListener('pointerleave', function () { ball.clearGaze(); });
  reducedMotion.addEventListener('change', function (event) {
    ball.setActive(!event.matches);
    if (event.matches) ball.renderStatic();
  });
  window.addEventListener('beforeunload', function () {
    window.clearTimeout(pointerPassthroughTimer);
    window.clearTimeout(dockDetectionTimer);
    closeSocket();
  });

  rememberCollapsedViewport();
  document.body.dataset.viewMode = VIEW_MODE.PET;
  applyAnchor('right', 'bottom');
  pollPointerPassthrough();
  ensurePetSession()
    .then(function (sessionId) { return connectSession(sessionId, false); })
    .catch(showError);
  window.VIEW_MODE = VIEW_MODE;
  window.setViewMode = setViewMode;
  window.showCard = showCard;
  window.hideCard = hideCard;
  window.promoteCardToPanel = promoteCardToPanel;
  window.sendPetTurn = sendPetTurn;
  window.normalizeDroppedFiles = normalizeDroppedFiles;
})();

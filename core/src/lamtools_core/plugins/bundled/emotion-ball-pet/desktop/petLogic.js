(function (root) {
  'use strict';

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

  function cardKind(card) {
    return String(card && card.kind || 'info');
  }

  function cardPriority(card) {
    return CARD_PRIORITY[cardKind(card)] || 0;
  }

  function cardReplacement(currentCard, nextCard) {
    if (!nextCard || typeof nextCard !== 'object') {
      return { replace: false, suspend: false, defer: false };
    }
    if (!currentCard) return { replace: true, suspend: false, defer: false };
    var nextPriority = cardPriority(nextCard);
    var currentPriority = cardPriority(currentCard);
    if (nextPriority < currentPriority) {
      var currentKind = cardKind(currentCard);
      return {
        replace: false,
        suspend: false,
        defer: cardKind(nextCard) === 'file' && (currentKind === 'approval' || currentKind === 'question')
      };
    }
    return { replace: true, suspend: nextPriority > currentPriority, defer: false };
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

  function pendingSourcesReady(pendingFiles, importedFiles) {
    if (!Array.isArray(pendingFiles) || pendingFiles.length === 0 || !Array.isArray(importedFiles)) {
      return false;
    }
    return pendingFiles.every(function (pending, index) {
      if (pending && pending.attachment && pending.attachment.id) return true;
      var importedIndex = pending && Number.isInteger(pending.index) ? pending.index : index;
      var imported = importedFiles[importedIndex];
      return !!(imported && imported.dataBase64);
    });
  }

  function shouldCollapseAfterInteraction(hadInteraction, restoredCard, viewMode) {
    return !!hadInteraction && !restoredCard && String(viewMode || '') !== 'pet';
  }

  function replySummary(text) {
    var lines = String(text || '').trim().split(/\r?\n/).map(function (line) {
      return line.trim();
    }).filter(Boolean).slice(0, 4);
    var summary = lines.join('\n');
    if (summary.length > 360) summary = summary.slice(0, 357).trimEnd() + '…';
    return summary || 'Agent 已完成回答。';
  }

  function panelDetailFromCard(card) {
    if (!card || typeof card !== 'object' || !String(card.detailBody || '')) return null;
    return {
      title: String(card.detailTitle || card.title || '桌宠提示'),
      body: String(card.detailBody),
      tone: String(card.kind || 'info')
    };
  }

  root.EmotionBallPetLogic = Object.freeze({
    CARD_PRIORITY: CARD_PRIORITY,
    cardPriority: cardPriority,
    cardReplacement: cardReplacement,
    normalizeDroppedFiles: normalizeDroppedFiles,
    pendingSourcesReady: pendingSourcesReady,
    panelDetailFromCard: panelDetailFromCard,
    shouldCollapseAfterInteraction: shouldCollapseAfterInteraction,
    replySummary: replySummary
  });
})(typeof window !== 'undefined' ? window : globalThis);

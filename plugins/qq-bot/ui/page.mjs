/**
 * QQ 机器人页面 —— 扫码绑定、配置、状态和诊断。
 *
 * 视觉复用原版 dsh-qqbot 的 imqb-* / imqb2-* 类名与布局；宿主差异只在
 * 数据通道：原版同源 fetch，这里走 context.rpc（分屏页面）或窗口 RPC。
 */

const ACTIVE_POLL_MS = 2000;
const RETRY_POLL_MS = 10000;
const BOUND_POLL_MS = 30000;
const HIDDEN_POLL_MS = 5000;

export function mount(root, context) {
  let disposed = false;
  let pollTimer;
  let bindState = null;
  let config = null;
  let initialConfig = null;
  let manualMode = false;
  let busy = false;
  let targets = null;
  let bots = [];
  let selectedBotId = '';

  const shell = document.createElement('section');
  shell.className = 'qqb-page';

  const header = document.createElement('header');
  header.className = 'qqb-header';
  const title = document.createElement('div');
  title.className = 'qqb-title';
  title.textContent = 'QQ 机器人';
  const subtitle = document.createElement('p');
  subtitle.className = 'qqb-subtitle';
  subtitle.textContent = '把 LamTools 接入 QQ 私聊与群聊';
  const titleBox = document.createElement('div');
  titleBox.append(title, subtitle);
  const statusPill = document.createElement('span');
  statusPill.className = 'qqb-pill';
  statusPill.textContent = '读取中…';
  const onRefresh = () => void refreshAll();
  const refreshButton = button('刷新', onRefresh, 'qqb-btn');
  const headerActions = document.createElement('div');
  headerActions.className = 'qqb-row';
  headerActions.append(statusPill, refreshButton);
  header.append(titleBox, headerActions);

  const bindCard = card('绑定');
  const bindBody = document.createElement('div');
  bindCard.append(bindBody);

  const botsCard = card('机器人');
  const botsBody = document.createElement('div');
  botsCard.append(botsBody);

  const statusCard = card('运行状态');
  const statusBody = document.createElement('div');
  statusCard.append(statusBody);

  const configCard = card('设置');
  const configBody = document.createElement('div');
  configCard.append(configBody);

  const diagnosticsCard = card('诊断');
  diagnosticsCard.classList.add('qqb-hidden');
  const diagnosticsBody = document.createElement('pre');
  diagnosticsBody.className = 'qqb-log';
  diagnosticsCard.append(diagnosticsBody);

  shell.append(header, botsCard, bindCard, statusCard, configCard, diagnosticsCard);
  root.append(shell);

  // ── RPC ────────────────────────────────────────────────────────────────
  async function rpc(method, params = {}) {
    if (disposed) throw new Error('页面已关闭');
    return await context.rpc(method, params);
  }

  async function botRpc(method, params = {}) {
    if (!selectedBotId) throw new Error('请先选择一个机器人');
    return await rpc(method, { ...params, botId: selectedBotId });
  }

  // ── Bot list ───────────────────────────────────────────────────────────
  function renderBots() {
    botsBody.replaceChildren();
    const head = document.createElement('div');
    head.className = 'qqb-row';
    const note = document.createElement('p');
    note.className = 'imqb2-note';
    note.textContent = bots.length
      ? `共 ${bots.length} 个机器人；每个会话独立 AppID。`
      : '还没有机器人。';
    head.append(note, button('为当前会话新建机器人', () => void createBotForSession(), 'imqb-pill'));
    botsBody.append(head);

    if (!bots.length) return;
    const list = document.createElement('div');
    list.className = 'qqb-sessions';
    for (const bot of bots) {
      const row = document.createElement('div');
      row.className = 'qqb-session';
      row.style.textAlign = 'left';
      row.style.cursor = 'pointer';
      row.tabIndex = 0;
      if (bot.botId === selectedBotId) row.dataset.selected = 'true';
      const main = document.createElement('div');
      main.className = 'qqb-session-main';
      const name = document.createElement('span');
      name.className = 'qqb-session-title';
      name.textContent = bot.name || bot.botId;
      const meta = document.createElement('span');
      meta.className = 'qqb-session-meta';
      const phase = bot.phase || bot.bind?.phase || 'starting';
      const target = String(bot.targetSessionId || '').slice(0, 8) || '未绑定会话';
      meta.textContent = `AppID ${bot.appId || '—'} · 会话 ${target} · ${phase}`;
      main.append(name, meta);
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'imqb-ghost';
      remove.textContent = '删除';
      remove.addEventListener('click', (event) => {
        event.stopPropagation();
        void deleteBot(bot.botId);
      });
      row.append(main, remove);
      row.addEventListener('click', () => selectBot(bot.botId));
      list.append(row);
    }
    botsBody.append(list);
  }

  function renderNoBot() {
    statusPill.textContent = '未创建';
    statusPill.dataset.state = 'off';
    const bindNote = document.createElement('p');
    bindNote.className = 'imqb-hint';
    bindNote.textContent = '先在右侧栏或上方列表创建这个会话的机器人。';
    bindBody.replaceChildren(bindNote);
    const statusNote = document.createElement('p');
    statusNote.className = 'imqb-hint';
    statusNote.textContent = '选择机器人后显示运行状态。';
    statusBody.replaceChildren(statusNote);
    const configNote = document.createElement('p');
    configNote.className = 'imqb-hint';
    configNote.textContent = '选择机器人后显示它的独立设置。';
    configBody.replaceChildren(configNote);
  }

  async function deleteBot(botId) {
    if (!window.confirm('确定删除这个机器人吗？它的网关会停止，绑定和密钥会被移除。')) return;
    try {
      const result = await rpc('qqbot.bot.delete', { botId });
      if (!result.ok) throw new Error(result.error || '删除失败');
      if (selectedBotId === botId) {
        selectedBotId = '';
        bindState = null;
        config = null;
        initialConfig = null;
      }
      await refreshAll();
    } catch (err) {
      window.alert(String(err.message || err));
    }
  }

  function selectBot(botId) {
    if (!botId || botId === selectedBotId) return;
    selectedBotId = botId;
    bindState = null;
    config = null;
    initialConfig = null;
    manualMode = false;
    renderBots();
    void Promise.all([refreshBind(), refreshStatus(), loadConfig()]);
  }

  async function createBotForSession() {
    const sessionId = String(context.sessionId || '').trim();
    if (!sessionId) {
      window.alert('当前页面没有打开会话；请在具体会话的右侧栏创建机器人。');
      return;
    }
    try {
      const result = await rpc('qqbot.bot.create', {
        sessionId,
        projectId: context.projectId || '',
      });
      if (!result.ok) throw new Error(result.error || '创建机器人失败');
      selectedBotId = result.botId || '';
      bindState = null;
      config = null;
      initialConfig = null;
      manualMode = false;
      await refreshAll();
    } catch (err) {
      window.alert(String(err.message || err));
    }
  }

  async function loadBots() {
    try {
      const result = await rpc('qqbot.bots.list', {});
      const list = Array.isArray(result.bots) ? result.bots : [];
      const stillThere = list.some((bot) => bot.botId === selectedBotId);
      const changed = !stillThere && selectedBotId !== '';
      bots = list;
      if (!stillThere) {
        selectedBotId = list[0]?.botId || '';
        bindState = null;
        config = null;
        initialConfig = null;
        manualMode = false;
      }
      renderBots();
      if (!selectedBotId) {
        renderNoBot();
        return;
      }
      await Promise.all([refreshBind(), refreshStatus()]);
      if (changed || !config) await loadConfig();
    } catch (err) {
      const error = document.createElement('p');
      error.className = 'imqb-error';
      error.textContent = `机器人列表加载失败：${String(err.message || err)}`;
      botsBody.replaceChildren(error);
    }
  }

  // ── Bind panel ─────────────────────────────────────────────────────────
  function renderBind(state) {
    bindState = state;
    bindBody.replaceChildren();
    const phase = state?.phase || 'starting';
    if (phase === 'bound') {
      const row = document.createElement('div');
      row.className = 'imqb-status';
      const line = document.createElement('div');
      line.className = 'imqb-status-row';
      const icon = document.createElement('div');
      icon.className = 'imqb-status-icon';
      icon.textContent = '🤖';
      const meta = document.createElement('div');
      meta.className = 'imqb-status-meta';
      const t = document.createElement('p');
      t.className = 'imqb-status-title';
      t.textContent = '已绑定';
      const s = document.createElement('p');
      s.className = 'imqb-status-sub imqb-mono';
      s.textContent = `AppID ${state.appId || '—'} · 私聊与群聊已接入`;
      meta.append(t, s);
      line.append(icon, meta);
      const actions = document.createElement('div');
      actions.className = 'imqb-status-actions';
      actions.append(
        button('更换凭据', () => { manualMode = true; renderBind(state); }, 'imqb-btn imqb-btn--primary'),
        button('解绑', () => void unbind(), 'imqb-btn imqb-btn--danger'),
      );
      row.append(line, actions);
      bindBody.append(row);
      if (manualMode) bindBody.append(manualForm(state.appId));
      return;
    }
    if (manualMode || phase === 'failed') {
      if (phase === 'failed') {
        const error = document.createElement('p');
        error.className = 'imqb-error';
        error.textContent = `绑定失败：${state.reason || '未知错误'}`;
        bindBody.append(error);
      }
      bindBody.append(manualForm());
      bindBody.append(button('改用扫码绑定', () => { manualMode = false; void refreshBind(); }, 'imqb-ghost'));
      return;
    }
    if (phase === 'waiting') {
      const panel = document.createElement('div');
      panel.className = 'imqb-panel';
      if (state.qrSvg) {
        const img = document.createElement('img');
        img.className = 'imqb-qr';
        img.src = state.qrSvg;
        img.alt = 'QQ 扫码二维码';
        img.width = 220;
        img.height = 220;
        panel.append(img);
      }
      const t = document.createElement('p');
      t.className = 'imqb-title';
      t.textContent = '扫码绑定 QQ 机器人';
      const hint = document.createElement('p');
      hint.className = 'imqb-hint';
      hint.textContent = '使用手机 QQ 扫描二维码完成绑定';
      panel.append(t, hint);
      if (state.url) {
        const link = document.createElement('a');
        link.className = 'imqb-link';
        link.href = state.url;
        link.target = '_blank';
        link.rel = 'noreferrer noopener';
        link.textContent = '二维码显示异常？在浏览器中打开';
        panel.append(link);
      }
      const row = document.createElement('div');
      row.className = 'imqb-row';
      row.append(
        button('刷新二维码', () => void refreshQr(), 'imqb-pill'),
        button('手动填写', () => { manualMode = true; renderBind(state); }, 'imqb-pill'),
      );
      panel.append(row);
      bindBody.append(panel);
      return;
    }
    if (phase === 'saving') {
      const panel = document.createElement('div');
      panel.className = 'imqb-panel';
      const icon = document.createElement('div');
      icon.className = 'imqb-icon';
      icon.textContent = '🎉';
      const t = document.createElement('p');
      t.className = 'imqb-title';
      t.textContent = '扫码成功';
      const hint = document.createElement('p');
      hint.className = 'imqb-hint';
      hint.textContent = '凭据已保存，正在连接机器人…';
      panel.append(icon, t, hint);
      bindBody.append(panel);
      return;
    }
    const panel = document.createElement('div');
    panel.className = 'imqb-panel';
    const hint = document.createElement('p');
    hint.className = 'imqb-hint';
    hint.textContent = '正在获取绑定状态…';
    panel.append(hint);
    bindBody.append(panel);
  }

  function manualForm(initialAppId) {
    const form = document.createElement('form');
    form.className = 'imqb-form';
    const appId = input('QQ 机器人 AppID', initialAppId || '', 'text');
    const appSecret = input('QQ 机器人 AppSecret', '', 'password');
    const error = document.createElement('p');
    error.className = 'imqb-error';
    const submit = button(busy ? '正在保存…' : '保存', () => {}, 'imqb-btn imqb-btn--primary');
    submit.type = 'submit';
    submit.disabled = busy;
    form.append(field('AppID', appId), field('AppSecret', appSecret), error, submit);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      if (busy) return;
      busy = true;
      submit.disabled = true;
      submit.textContent = '正在保存…';
      error.textContent = '';
      void botRpc('qqbot.bind.manual', { appId: appId.value.trim(), appSecret: appSecret.value.trim() })
        .then((result) => {
          if (!result.ok) throw new Error(result.error || '保存失败');
          manualMode = false;
          return refreshBind();
        })
        .catch((err) => { error.textContent = String(err.message || err); })
        .finally(() => {
          busy = false;
          submit.disabled = false;
          submit.textContent = '保存';
        });
    });
    return form;
  }

  async function unbind() {
    if (!window.confirm('确定解绑吗？\n解绑后机器人立即下线，插件将重新进入扫码绑定流程。')) return;
    try {
      const result = await botRpc('qqbot.bind.unbind', {});
      if (!result.ok) throw new Error(result.error || '解绑失败');
      manualMode = false;
      await refreshBind();
    } catch (err) {
      window.alert(String(err.message || err));
    }
  }

  async function refreshQr() {
    try {
      await botRpc('qqbot.bind.refresh', {});
      await refreshBind();
    } catch (err) {
      window.alert(String(err.message || err));
    }
  }

  // ── Status ─────────────────────────────────────────────────────────────
  function renderStatus(status, sessions = []) {
    statusBody.replaceChildren();
    const info = status || {};
    const bound = Boolean(info.bound);
    statusPill.textContent = bound
      ? (info.gateway === 'connected' ? '已连接' : '连接中')
      : '未绑定';
    statusPill.dataset.state = bound ? (info.gateway === 'connected' ? 'ok' : 'wait') : 'off';
    const grid = document.createElement('div');
    grid.className = 'qqb-grid';
    grid.append(
      metric('绑定', bound ? '已绑定' : '未绑定'),
      metric('网关', gatewayLabel(info.gateway)),
      metric('会话', String(sessions.length || info.sessions || 0)),
      metric('版本', info.version || '—'),
    );
    statusBody.append(grid);
    if (sessions.length) statusBody.append(renderSessions(sessions));
    if (info.lastError) {
      const error = document.createElement('p');
      error.className = 'imqb-error';
      error.textContent = info.lastError;
      statusBody.append(error);
    }
    const actions = document.createElement('div');
    actions.className = 'qqb-row';
    actions.append(
      button('重启网关', () => void restartGateway(), 'imqb-pill'),
      button('查看日志', () => void showLogs(), 'imqb-pill'),
      button('诊断', () => void showDiagnostics(), 'imqb-pill'),
    );
    statusBody.append(actions);
  }

  function renderSessions(sessions) {
    const list = document.createElement('div');
    list.className = 'qqb-sessions';
    for (const session of sessions) {
      const row = document.createElement('div');
      row.className = 'qqb-session';
      const main = document.createElement('div');
      main.className = 'qqb-session-main';
      const name = document.createElement('span');
      name.className = 'qqb-session-title';
      name.textContent = session.title || `QQ-${String(session.peerId || '').slice(-6) || '未知'}`;
      const meta = document.createElement('span');
      meta.className = 'qqb-session-meta';
      const scope = session.scope === 'group' ? '群聊' : '私聊';
      const model = session.model || '后台模型';
      const state = session.running ? '生成中' : (session.lastError ? '异常' : '空闲');
      meta.textContent = `${scope} · ${model} · ${state}`;
      main.append(name, meta);
      row.append(main);
      list.append(row);
    }
    return list;
  }

  function gatewayLabel(value) {
    return ({ connected: '已连接', connecting: '连接中', stopped: '已停止', unbound: '未绑定' })[value] || value || '—';
  }

  async function restartGateway() {
    try {
      const result = await botRpc('qqbot.gateway.restart', {});
      if (!result.ok) throw new Error(result.error || '重启失败');
      await refreshAll();
    } catch (err) {
      window.alert(String(err.message || err));
    }
  }

  async function showLogs() {
    try {
      const result = await botRpc('qqbot.logs.tail', { tail: 120 });
      diagnosticsBody.textContent = (result.lines || []).join('\n') || '暂无日志';
      diagnosticsCard.classList.remove('qqb-hidden');
      diagnosticsCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    } catch (err) {
      window.alert(String(err.message || err));
    }
  }

  async function showDiagnostics() {
    try {
      const result = await botRpc('qqbot.diagnose', {});
      diagnosticsBody.textContent = JSON.stringify(result, null, 2);
      diagnosticsCard.classList.remove('qqb-hidden');
      diagnosticsCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    } catch (err) {
      window.alert(String(err.message || err));
    }
  }

  // ── Config ─────────────────────────────────────────────────────────────
  function targetSelector() {
    const wrap = document.createElement('div');
    wrap.className = 'qqb-targets';
    if (!targets) {
      const note = document.createElement('p');
      note.className = 'imqb2-note';
      note.textContent = '正在读取项目和会话…';
      wrap.append(note);
      return wrap;
    }
    if (targets.ok === false) {
      const note = document.createElement('p');
      note.className = 'imqb2-note imqb2-note--error';
      note.textContent = targets.error || '读取项目和会话失败';
      wrap.append(note);
      return wrap;
    }
    const projects = Array.isArray(targets.projects) ? targets.projects : [];
    const projectId = String(config.targetProjectId || '');
    const project = projects.find((item) => item.id === projectId);
    wrap.append(
      selectRow(
        '目标项目',
        'QQ 消息注入到该项目。留空时使用插件自己的子会话。',
        projectId,
        [{ value: '', label: '不指定（插件子会话）' }, ...projects.map((item) => ({
          value: item.id,
          label: item.name || item.id,
        }))],
        (value) => {
          config.targetProjectId = value;
          const next = projects.find((item) => item.id === value);
          if (!next || !(next.sessions || []).some((session) => session.id === config.targetSessionId)) {
            config.targetSessionId = '';
          }
          renderConfig(config);
        },
      ),
    );
    const sessions = project ? (project.sessions || []) : [];
    const sessionOptions = [{ value: '', label: '不指定（按私聊/群聊各自建子会话）' }];
    for (const session of sessions) {
      sessionOptions.push({
        value: session.id,
        label: `${session.title || session.id}${session.status ? ` · ${session.status}` : ''}`,
      });
    }
    if (config.targetSessionId && !sessions.some((session) => session.id === config.targetSessionId)) {
      sessionOptions.push({ value: config.targetSessionId, label: config.targetSessionId });
    }
    wrap.append(
      selectRow(
        '目标会话',
        '私聊和群聊都注入这个 Sunday 会话；空闲时发用户消息，运行中发即时引导，不走排队。',
        String(config.targetSessionId || ''),
        sessionOptions,
        (value) => { config.targetSessionId = value; },
      ),
    );
    return wrap;
  }

  function renderConfig(nextConfig) {
    config = nextConfig;
    if (initialConfig === null) initialConfig = JSON.parse(JSON.stringify(nextConfig));
    configBody.replaceChildren();
    const form = document.createElement('form');
    form.className = 'imqb2-form';
    const access = config.access || { c2cMode: 'open', c2cAllow: [], groupMode: 'open', groupAllow: [] };

    form.append(groupTitle('服务范围'));
    form.append(segRow('私聊', access.c2cMode, [
      ['open', '所有人'], ['allowlist', '白名单'], ['disabled', '禁用'],
    ], (value) => { access.c2cMode = value; renderConfig(config); }));
    if (access.c2cMode === 'allowlist') {
      form.append(areaRow('私聊白名单', '用户 openid，一行一个', (access.c2cAllow || []).join('\n'), (value) => {
        access.c2cAllow = value.split('\n').map((item) => item.trim()).filter(Boolean);
      }));
    }
    form.append(segRow('群聊', access.groupMode, [
      ['open', '所有人'], ['allowlist', '白名单'], ['disabled', '禁用'],
    ], (value) => { access.groupMode = value; renderConfig(config); }));
    if (access.groupMode === 'allowlist') {
      form.append(areaRow('群聊白名单', '群 openid，一行一个', (access.groupAllow || []).join('\n'), (value) => {
        access.groupAllow = value.split('\n').map((item) => item.trim()).filter(Boolean);
      }));
    }

    form.append(groupTitle('基础设置'));
    form.append(switchRow('群聊仅回复 @机器人 的消息', '关闭后群里所有消息都会触发回复。', config.requireMention !== false, (value) => { config.requireMention = value; }));
    form.append(switchRow('流式输出', '私聊里把回复分段实时推送；群聊始终静态发送。', config.streaming !== false, (value) => { config.streaming = value; }));
    form.append(switchRow('显示工具调用成功结果', '工具错误始终显示。', Boolean(config.showToolResults), (value) => { config.showToolResults = value; }));
    form.append(switchRow('调试日志', '把网关和消息细节写进插件日志。', Boolean(config.debug), (value) => { config.debug = value; }));

    form.append(groupTitle('目标会话'));
    form.append(targetSelector());

    form.append(groupTitle('模型'));
    form.append(textRow('Provider', '留空继承宿主默认。', config.provider || '', (value) => { config.provider = value; }, '留空继承宿主默认'));
    form.append(textRow('Model', '留空继承宿主默认。', config.model || '', (value) => { config.model = value; }, '留空继承宿主默认'));
    form.append(textRow('Agent Preset', '宿主 agent preset id（插件清单声明）。', config.preset || '', (value) => { config.preset = value; }, '留空使用默认'));
    form.append(segRow('默认 Agent 模式', config.agentMode || '', [
      ['', '继承'], ['auto', 'auto'], ['low', 'low'], ['medium', 'medium'], ['high', 'high'],
    ], (value) => { config.agentMode = value; }));

    form.append(groupTitle('个性化提示词'));
    form.append(areaRow('群聊额外 system prompt', '只对群聊会话生效。', config.groupPrompt || '', (value) => { config.groupPrompt = value; }, 3));
    form.append(areaRow('私聊额外 system prompt', '只对私聊会话生效。', config.directPrompt || '', (value) => { config.directPrompt = value; }, 3));

    form.append(groupTitle('限制与超时'));
    form.append(numberRow('单条消息最大字符数', config.textChunkLimit ?? 4500, (value) => { config.textChunkLimit = value; }));
    form.append(numberRow('同一条消息最多被动回复次数', config.replyLimit ?? 4, (value) => { config.replyLimit = value; }));
    form.append(numberRow('会话闲置回收（毫秒）', config.sessionIdleTimeout ?? 1800000, (value) => { config.sessionIdleTimeout = value; }));
    form.append(numberRow('每会话排队上限', config.maxQueue ?? 20, (value) => { config.maxQueue = value; }));
    form.append(numberRow('单轮处理超时（毫秒）', config.processingTimeoutMs ?? 1800000, (value) => { config.processingTimeoutMs = value; }));
    form.append(numberRow('提问等待超时（毫秒）', config.askTimeoutMs ?? 300000, (value) => { config.askTimeoutMs = value; }));
    form.append(numberRow('群历史缓冲条数', config.historyLimit ?? 10, (value) => { config.historyLimit = value; }));

    const media = config.media || {};
    form.append(groupTitle('富媒体'));
    form.append(switchRow('启用富媒体理解', '下载 QQ 图片/视频/文件到插件数据目录。', media.enabled !== false, (value) => { media.enabled = value; }));
    form.append(numberRow('单个文件上限（MB）', media.maxMB ?? 200, (value) => { media.maxMB = value; }));
    form.append(numberRow('保留时长（小时，0=永不过期）', media.ttlHours ?? 24, (value) => { media.ttlHours = value; }));

    const vision = config.vision || {};
    form.append(groupTitle('视觉理解'));
    form.append(switchRow('启用视觉模型', 'qqbot_describe_image 优先使用这里配置的模型；关闭时把图片交给主模型。', Boolean(vision.enabled), (value) => { vision.enabled = value; }));
    form.append(textRow('Provider', '视觉模型 provider。', vision.provider || '', (value) => { vision.provider = value; }));
    form.append(textRow('Model', '视觉模型 id。', vision.model || '', (value) => { vision.model = value; }));
    form.append(areaRow('默认描述提示词', '调用时没有显式 prompt 使用。', vision.defaultPrompt || '', (value) => { vision.defaultPrompt = value; }, 2));
    form.append(numberRow('图片字节上限', vision.maxBytes ?? 10485760, (value) => { vision.maxBytes = value; }));
    form.append(numberRow('输出 token 上限', vision.maxTokens ?? 1024, (value) => { vision.maxTokens = value; }));

    const sendFile = config.sendFile || {};
    form.append(groupTitle('附件发送'));
    form.append(switchRow('限制路径白名单', '只允许插件媒体目录、当前项目和额外目录。', sendFile.restrictPaths !== false, (value) => { sendFile.restrictPaths = value; }));
    form.append(areaRow('额外允许目录', '一行一个绝对路径。', (sendFile.extraRoots || []).join('\n'), (value) => {
      sendFile.extraRoots = value.split('\n').map((item) => item.trim()).filter(Boolean);
    }, 3));
    form.append(switchRow('轮末发送交付文件', '把工具声明的产物发到当前会话。', sendFile.sendPresentedFiles !== false, (value) => { sendFile.sendPresentedFiles = value; }));
    form.append(numberRow('单轮最多投递文件数', sendFile.maxFiles ?? 4, (value) => { sendFile.maxFiles = value; }));

    if (config.cwd) {
      const readOnly = document.createElement('p');
      readOnly.className = 'imqb2-readonly';
      readOnly.textContent = `Agent 工作目录（只读）：${config.cwd}`;
      form.append(readOnly);
    }

    const footer = document.createElement('div');
    footer.className = 'imqb2-footer';
    const note = document.createElement('p');
    note.className = 'imqb2-note';
    const save = button('保存设置', () => {}, 'imqb2-save');
    save.type = 'submit';
    save.disabled = true;
    footer.append(note, save);
    form.append(footer);

    const refreshDirty = () => {
      const changed = changedConfig();
      save.disabled = busy || Object.keys(changed).length === 0;
      note.textContent = Object.keys(changed).length > 0
        ? '保存后插件会按新配置生效；凭据变更会重启网关。'
        : '';
    };
    form.addEventListener('change', refreshDirty);
    form.addEventListener('input', refreshDirty);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const changed = changedConfig();
      if (busy || Object.keys(changed).length === 0) return;
      busy = true;
      save.disabled = true;
      save.textContent = '正在保存…';
      note.textContent = '';
      void botRpc('qqbot.config.update', { patch: changed })
        .then((result) => {
          if (!result.ok) throw new Error(result.error || '保存失败');
          initialConfig = JSON.parse(JSON.stringify(config));
          note.textContent = result.message || '设置已保存';
          note.className = 'imqb2-note imqb2-note--ok';
          return refreshAll();
        })
        .catch((err) => {
          note.textContent = `⚠️ ${String(err.message || err)}`;
          note.className = 'imqb2-note imqb2-note--error';
        })
        .finally(() => {
          busy = false;
          save.disabled = false;
          save.textContent = '保存设置';
        });
    });
    configBody.append(form);
  }

  function changedConfig() {
    const changed = {};
    if (!config || !initialConfig) return changed;
    for (const key of Object.keys(config)) {
      if (JSON.stringify(config[key]) !== JSON.stringify(initialConfig[key])) changed[key] = config[key];
    }
    return changed;
  }

  // ── Data loading / polling ─────────────────────────────────────────────
  async function refreshBind() {
    if (!selectedBotId) return;
    try {
      const state = await botRpc('qqbot.bind.state', {});
      if (disposed) return;
      renderBind(state);
      schedulePoll(state);
    } catch (err) {
      if (!disposed) {
        renderBind({ phase: 'failed', reason: String(err.message || err) });
        schedulePoll({ phase: 'failed' });
      }
    }
  }

  async function refreshStatus() {
    if (!selectedBotId) return;
    try {
      const [status, sessionsResult] = await Promise.all([
        botRpc('qqbot.status', {}),
        botRpc('qqbot.session.list', {}).catch(() => ({ sessions: [] })),
      ]);
      if (!disposed) renderStatus(status, sessionsResult.sessions || []);
    } catch (err) {
      if (!disposed) statusPill.textContent = '读取失败';
    }
  }

  async function loadConfig() {
    if (!selectedBotId) return;
    try {
      const result = await botRpc('qqbot.config.get', {});
      if (!disposed) renderConfig(result.config || {});
    } catch (err) {
      if (!disposed) {
        const error = document.createElement('p');
        error.className = 'imqb-error';
        error.textContent = `配置加载失败：${String(err.message || err)}`;
        configBody.replaceChildren(error);
      }
    }
  }

  async function loadTargets() {
    try {
      targets = await rpc('qqbot.targets', {});
    } catch (err) {
      targets = { ok: false, error: String(err.message || err) };
    }
    if (!disposed && config) renderConfig(config);
  }

  async function refreshAll() {
    await loadBots();
  }

  function schedulePoll(state) {
    if (pollTimer) window.clearTimeout(pollTimer);
    if (disposed) return;
    const phase = state?.phase || 'starting';
    let delay = phase === 'waiting' || phase === 'starting' || phase === 'saving'
      ? ACTIVE_POLL_MS
      : phase === 'bound'
        ? BOUND_POLL_MS
        : RETRY_POLL_MS;
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
      delay = Math.max(delay, HIDDEN_POLL_MS);
    }
    pollTimer = window.setTimeout(() => {
      void refreshAll();
    }, delay);
  }

  function onVisibility(visible) {
    if (visible) void refreshAll();
  }

  const unsubscribe = context.onVisibilityChange(onVisibility);
  context.signal.addEventListener('abort', dispose, { once: true });
  refreshButton.addEventListener('click', onRefresh);
  void refreshAll();
  void loadTargets();

  function dispose() {
    if (disposed) return;
    disposed = true;
    if (pollTimer) window.clearTimeout(pollTimer);
    pollTimer = undefined;
    unsubscribe();
    refreshButton.removeEventListener('click', onRefresh);
    context.signal.removeEventListener('abort', dispose);
    shell.remove();
  }
  return dispose;
}

// ── Small DOM helpers ──────────────────────────────────────────────────────

function card(label) {
  const section = document.createElement('section');
  section.className = 'qqb-card';
  const heading = document.createElement('h3');
  heading.className = 'qqb-card-title';
  heading.textContent = label;
  section.append(heading);
  return section;
}

function groupTitle(text) {
  const element = document.createElement('div');
  element.className = 'imqb2-group-title';
  element.textContent = text;
  return element;
}

function button(label, onClick, className) {
  const element = document.createElement('button');
  element.type = 'button';
  element.className = className || 'imqb-pill';
  element.textContent = label;
  element.addEventListener('click', onClick);
  return element;
}

function field(label, control) {
  const wrapper = document.createElement('label');
  wrapper.className = 'imqb-field';
  const text = document.createElement('span');
  text.textContent = label;
  wrapper.append(text, control);
  return wrapper;
}

function input(placeholder, value, type) {
  const element = document.createElement('input');
  element.className = 'imqb-input';
  element.placeholder = placeholder;
  element.value = value || '';
  element.type = type || 'text';
  element.autocomplete = type === 'password' ? 'new-password' : 'off';
  return element;
}

function switchRow(label, help, checked, onChange) {
  const row = document.createElement('div');
  row.className = 'imqb2-field';
  const head = document.createElement('div');
  head.className = 'imqb2-head';
  const text = document.createElement('span');
  text.className = 'imqb2-label';
  text.textContent = label;
  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = 'imqb2-switch';
  toggle.setAttribute('role', 'switch');
  toggle.setAttribute('aria-checked', checked ? 'true' : 'false');
  toggle.setAttribute('aria-label', label);
  const thumb = document.createElement('span');
  thumb.className = 'imqb2-switch-thumb';
  toggle.append(thumb);
  toggle.addEventListener('click', () => {
    const next = toggle.getAttribute('aria-checked') !== 'true';
    toggle.setAttribute('aria-checked', next ? 'true' : 'false');
    onChange(next);
  });
  head.append(text, toggle);
  row.append(head);
  if (help) {
    const note = document.createElement('p');
    note.className = 'imqb2-help';
    note.textContent = help;
    row.append(note);
  }
  return row;
}

function segRow(label, value, options, onChange) {
  const row = document.createElement('div');
  row.className = 'imqb2-field';
  const head = document.createElement('div');
  head.className = 'imqb2-head';
  const text = document.createElement('span');
  text.className = 'imqb2-label';
  text.textContent = label;
  const group = document.createElement('div');
  group.className = 'imqb2-seg';
  group.setAttribute('role', 'tablist');
  group.style.setProperty('--imqb2-seg-count', String(options.length));
  const index = Math.max(0, options.findIndex(([key]) => key === value));
  group.style.setProperty('--imqb2-seg-index', String(index));
  const indicator = document.createElement('span');
  indicator.className = 'imqb2-seg-indicator';
  group.append(indicator);
  for (const [key, textValue] of options) {
    const tab = document.createElement('button');
    tab.type = 'button';
    tab.className = 'imqb2-seg-tab';
    tab.setAttribute('role', 'tab');
    tab.setAttribute('aria-selected', key === value ? 'true' : 'false');
    tab.textContent = textValue;
    tab.addEventListener('click', () => onChange(key));
    group.append(tab);
  }
  head.append(text, group);
  row.append(head);
  return row;
}

function textRow(label, help, value, onChange, placeholder) {
  const row = document.createElement('div');
  row.className = 'imqb2-field';
  const text = document.createElement('span');
  text.className = 'imqb2-label';
  text.textContent = label;
  const control = document.createElement('input');
  control.className = 'imqb2-input';
  control.value = value || '';
  control.placeholder = placeholder || '';
  control.spellcheck = false;
  control.addEventListener('input', () => onChange(control.value));
  row.append(text, control);
  if (help) {
    const note = document.createElement('p');
    note.className = 'imqb2-hint';
    note.textContent = help;
    row.append(note);
  }
  return row;
}

function selectRow(label, help, value, options, onChange) {
  const row = document.createElement('div');
  row.className = 'imqb2-field';
  const text = document.createElement('span');
  text.className = 'imqb2-label';
  text.textContent = label;
  const control = document.createElement('select');
  control.className = 'imqb2-input';
  for (const option of options || []) {
    const item = document.createElement('option');
    item.value = option.value;
    item.textContent = option.label;
    if (option.value === value) item.selected = true;
    control.append(item);
  }
  control.addEventListener('change', () => onChange(control.value));
  row.append(text, control);
  if (help) {
    const note = document.createElement('p');
    note.className = 'imqb2-hint';
    note.textContent = help;
    row.append(note);
  }
  return row;
}

function areaRow(label, help, value, onChange, rows) {  const row = document.createElement('div');
  row.className = 'imqb2-field';
  const text = document.createElement('span');
  text.className = 'imqb2-label';
  text.textContent = label;
  const control = document.createElement('textarea');
  control.className = 'imqb2-input imqb2-textarea';
  control.rows = rows || 3;
  control.value = value || '';
  control.addEventListener('input', () => onChange(control.value));
  row.append(text, control);
  if (help) {
    const note = document.createElement('p');
    note.className = 'imqb2-hint';
    note.textContent = help;
    row.append(note);
  }
  return row;
}

function numberRow(label, value, onChange) {
  const row = document.createElement('div');
  row.className = 'imqb2-field';
  const text = document.createElement('span');
  text.className = 'imqb2-label';
  text.textContent = label;
  const control = document.createElement('input');
  control.className = 'imqb2-input';
  control.type = 'number';
  control.value = String(value ?? 0);
  control.addEventListener('input', () => {
    const parsed = Number(control.value);
    if (Number.isFinite(parsed)) onChange(parsed);
  });
  row.append(text, control);
  return row;
}

function metric(label, value) {
  const item = document.createElement('div');
  item.className = 'qqb-metric';
  const name = document.createElement('span');
  name.className = 'qqb-metric-label';
  name.textContent = label;
  const data = document.createElement('strong');
  data.className = 'qqb-metric-value';
  data.textContent = value;
  item.append(name, data);
  return item;
}

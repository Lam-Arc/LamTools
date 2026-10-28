/**
 * QQ 机器人右侧栏：按当前 Sunday 会话查看/创建独立 QQ 机器人。
 *
 * 每个会话对应自己的 botId 和 AppID；这里不再修改全局目标会话，也不复用
 * 其他会话的绑定。面板只调用 qqbot.bots.* / qqbot.bot.* / qqbot.bind.*。
 */

const POLL_MS = 2000;

export function mount(root, context) {
  let disposed = false;
  let pollTimer;
  let bot = null;
  let busy = false;
  let error = "";

  const sessionId = String(context.sessionId || "").trim();
  const projectId = String(context.projectId || "").trim();

  const shell = document.createElement("section");
  shell.className = "qqb-page qqb-side-panel";

  const header = document.createElement("header");
  header.className = "qqb-header";
  const titleBox = document.createElement("div");
  const title = document.createElement("h2");
  title.className = "qqb-title";
  title.textContent = "QQ 机器人";
  const subtitle = document.createElement("p");
  subtitle.className = "qqb-subtitle";
  subtitle.textContent = sessionId ? `当前会话 ${sessionId.slice(0, 8)}` : "请先打开一个会话";
  titleBox.append(title, subtitle);
  header.append(titleBox);
  shell.append(header);

  const body = document.createElement("div");
  body.className = "qqb-side-body";
  shell.append(body);
  root.append(shell);

  async function rpc(method, params = {}) {
    if (disposed) throw new Error("面板已关闭");
    return await context.rpc(method, params);
  }

  function button(label, onClick, className = "imqb-btn imqb-btn--primary") {
    const element = document.createElement("button");
    element.type = "button";
    element.className = className;
    element.textContent = label;
    element.disabled = busy;
    element.addEventListener("click", onClick);
    return element;
  }

  function hint(text) {
    const element = document.createElement("p");
    element.className = "imqb-hint";
    element.textContent = text;
    return element;
  }

  function titleLine(text) {
    const element = document.createElement("p");
    element.className = "imqb-title";
    element.textContent = text;
    return element;
  }

  function errorLine(text) {
    const element = document.createElement("p");
    element.className = "imqb-error";
    element.textContent = text;
    return element;
  }

  function bindOf(value) {
    const bind = value && value.bind;
    return bind && typeof bind === "object" ? bind : {};
  }

  function qrBlock(bind) {
    const panel = document.createElement("div");
    panel.className = "imqb-panel qqb-side-bind";
    if (bind?.qrSvg) {
      const image = document.createElement("img");
      image.className = "imqb-qr";
      image.src = bind.qrSvg;
      image.alt = "QQ 扫码二维码";
      image.width = 180;
      image.height = 180;
      panel.append(image);
    }
    panel.append(titleLine("扫码创建机器人"));
    panel.append(hint("扫码后，这个机器人会绑定到当前会话，并使用它自己的 AppID。"));
    if (bind?.url) {
      const link = document.createElement("a");
      link.className = "imqb-link";
      link.href = bind.url;
      link.target = "_blank";
      link.rel = "noreferrer noopener";
      link.textContent = "二维码显示异常？在浏览器中打开";
      panel.append(link);
    }
    const row = document.createElement("div");
    row.className = "imqb-row";
    row.append(button("刷新二维码", () => void refreshQr(), "imqb-pill"));
    panel.append(row);
    return panel;
  }

  function render() {
    body.replaceChildren();
    if (!sessionId) {
      const panel = document.createElement("div");
      panel.className = "imqb-panel";
      panel.append(titleLine("还没有打开会话"));
      panel.append(hint("打开一个 Sunday 会话后，右侧栏会在这里创建属于它的 QQ 机器人。"));
      body.append(panel);
      return;
    }

    if (!bot) {
      const panel = document.createElement("div");
      panel.className = "imqb-panel";
      const icon = document.createElement("div");
      icon.className = "imqb-icon";
      icon.textContent = "🤖";
      panel.append(icon);
      panel.append(titleLine("在当前会话创建机器人"));
      panel.append(hint("每个会话创建自己的 QQ 机器人；扫码后会得到独立的 AppID。"));
      if (error) panel.append(errorLine(error));
      panel.append(
        button(busy ? "正在创建…" : "在当前会话创建机器人", () => void createBot()),
      );
      body.append(panel);
      return;
    }

    const bind = bindOf(bot);
    const phase = String(bot.phase || bind.phase || "starting");
    if (phase === "bound") {
      const panel = document.createElement("div");
      panel.className = "imqb-panel";
      const icon = document.createElement("div");
      icon.className = "imqb-icon";
      icon.textContent = "🤖";
      panel.append(icon);
      panel.append(titleLine("机器人已在此会话创建"));
      panel.append(
        hint(
          `AppID ${bot.appId || "—"}。这个机器人独立运行，和其他会话的机器人互不影响。`,
        ),
      );
      body.append(panel);
      return;
    }

    if (phase === "waiting") {
      body.append(qrBlock(bind));
      return;
    }

    if (phase === "saving") {
      const panel = document.createElement("div");
      panel.className = "imqb-panel";
      const icon = document.createElement("div");
      icon.className = "imqb-icon";
      icon.textContent = "🎉";
      panel.append(icon);
      panel.append(titleLine("扫码成功"));
      panel.append(hint("凭据已保存，正在连接这个机器人…"));
      body.append(panel);
      return;
    }

    const panel = document.createElement("div");
    panel.className = "imqb-panel";
    const icon = document.createElement("div");
    icon.className = "imqb-icon";
    icon.textContent = "🤖";
    panel.append(icon);
    panel.append(titleLine(bot.name || "QQ 机器人"));
    if (phase === "failed" && bind.reason) {
      panel.append(errorLine(`绑定失败：${bind.reason}`));
    } else {
      panel.append(hint("正在准备这个机器人的绑定二维码…"));
    }
    if (error) panel.append(errorLine(error));
    panel.append(button("重新生成二维码", () => void refreshQr(), "imqb-pill"));
    body.append(panel);
  }

  async function createBot() {
    if (!sessionId || busy) return;
    busy = true;
    error = "";
    render();
    try {
      const result = await rpc("qqbot.bot.create", {
        sessionId,
        projectId,
      });
      if (!result?.ok) {
        throw new Error(result?.error || "创建机器人失败");
      }
      bot = result.bot || null;
      if (!bot) await refresh();
    } catch (cause) {
      error = String(cause?.message || cause);
    } finally {
      busy = false;
      render();
      schedulePoll();
    }
  }

  async function refreshQr() {
    if (!bot || busy) return;
    busy = true;
    error = "";
    render();
    try {
      await rpc("qqbot.bind.refresh", { botId: bot.botId });
      await refresh();
    } catch (cause) {
      error = String(cause?.message || cause);
    } finally {
      busy = false;
      render();
      schedulePoll();
    }
  }

  async function refresh() {
    if (disposed) return;
    try {
      const listed = await rpc("qqbot.bots.list", { sessionId });
      if (disposed) return;
      const found = Array.isArray(listed?.bots) ? listed.bots[0] : null;
      if (!found) {
        bot = null;
      } else {
        const current = await rpc("qqbot.bot.state", { botId: found.botId });
        if (disposed) return;
        bot = current?.bot || found;
      }
      error = "";
      render();
      schedulePoll();
    } catch (cause) {
      if (disposed) return;
      error = String(cause?.message || cause);
      render();
    }
  }

  function schedulePoll() {
    if (pollTimer) window.clearTimeout(pollTimer);
    pollTimer = undefined;
    if (disposed || !bot) return;
    const bind = bindOf(bot);
    const phase = String(bot.phase || bind.phase || "");
    if (!["starting", "waiting", "saving"].includes(phase)) return;
    pollTimer = window.setTimeout(() => void refresh(), POLL_MS);
  }

  const onVisibility = (visible) => {
    if (visible) void refresh();
  };
  const unsubscribe = context.onVisibilityChange(onVisibility);
  context.signal.addEventListener("abort", dispose, { once: true });

  render();
  void refresh();

  function dispose() {
    if (disposed) return;
    disposed = true;
    if (pollTimer) window.clearTimeout(pollTimer);
    pollTimer = undefined;
    unsubscribe();
    context.signal.removeEventListener("abort", dispose);
    shell.remove();
  }
  return dispose;
}

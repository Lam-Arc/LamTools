// Sunday 内置浏览器的页面桥（由 Rust 侧 `initialization_script` 注入，每个新文档执行一次）。
//
// user:“必须固定、可审计”+(这份脚本就是网页侧能触达的全部能力：只读页面结构、派发合成事件、
// 滚动、上报真实用户输入。没有 eval、没有任意脚本执行、没有宿主通道)。
//
// 三条硬约束（实现时不许越线）：
// 1) 页面永远拿不到宿主通道：这里不出现、也不创建任何宿主调用入口；
// 2) 不接受页面扩展能力：指令集写死在 `handle()` 的 switch 里，页面改不了；
// 3) 不信任自己的回报：Rust 侧的 URL / 标题 / 下载 / 权限一律取自 WebView2 COM，
//    这里返回的 `url` 只作提示。
//
// 协议（与 方案/内置浏览器-01-总体方案.md 附录 B 对齐，差异见交付说明）：
//   宿主 → 页面：chrome.webview 的 message 事件，载荷 { sunday: 1, id, op, args }
//   页面 → 宿主：postMessage(JSON)，载荷 { sunday: 1, id, ok, result } / { sunday: 1, id, ok: false, error }
//   页面 → 宿主事件：{ sunday: 1, op: 'event', kind: 'user-input', args: { kind } }（无 id）
(() => {
  'use strict'
  const KEY = '__sundayBridge'
  if (window[KEY]) return
  // 只留一个版本号，不给页面任何可调用的宿主能力。
  window[KEY] = { version: 1 }

  const MAX_NODES = 500
  const MAX_CHARS = 32000
  const MAX_TEXT_BLOCK = 4000
  const MAX_VISITED = 20000
  const MAX_REF_SEQ = 999999
  const INPUT_REPORT_INTERVAL = 1000
  const TEXT_TAGS = 'h1,h2,h3,h4,h5,h6,p,li,td,th,pre,blockquote,dt,dd,figcaption,caption,label,button,a'
  const INTERACTIVE_ROLES = [
    'button', 'link', 'textbox', 'searchbox', 'checkbox', 'radio', 'combobox', 'listbox',
    'menuitem', 'menuitemcheckbox', 'menuitemradio', 'option', 'tab', 'slider', 'switch',
    'spinbutton', 'treeitem'
  ]

  const refs = new WeakMap()
  const live = new Map()
  let seq = 0

  const norm = (value) => String(value == null ? '' : value).replace(/\s+/g, ' ').trim()
  const clip = (value, limit) => (value.length > limit ? value.slice(0, limit) : value)

  function send(payload) {
    try {
      if (!window.chrome || !window.chrome.webview) return
      window.chrome.webview.postMessage(JSON.stringify(payload))
    } catch (_) {
      /* 页面改坏了通道也不能抛，Rust 侧会按超时处理 */
    }
  }

  function fail(code, message) {
    const error = new Error(message)
    error.sundayCode = code
    throw error
  }

  // --- 元素基础信息 -------------------------------------------------------

  function composedParent(el) {
    if (el.parentElement) return el.parentElement
    try {
      const root = el.getRootNode ? el.getRootNode() : null
      return root && root.host ? root.host : null
    } catch (_) {
      return null
    }
  }

  function styleHidden(el) {
    let node = el
    let guard = 0
    while (node && guard++ < 64) {
      let style = null
      try {
        style = getComputedStyle(node)
      } catch (_) {
        style = null
      }
      if (style) {
        if (style.display === 'none' || style.visibility === 'hidden' || style.visibility === 'collapse') return true
        if (Number(style.opacity) === 0) return true
      }
      node = composedParent(node)
    }
    return false
  }

  function roleOf(el) {
    const explicit = (el.getAttribute('role') || '').toLowerCase()
    if (explicit) return explicit
    const tag = (el.tagName || '').toLowerCase()
    if (tag === 'a') return el.hasAttribute('href') ? 'link' : 'generic'
    if (tag === 'button' || tag === 'summary') return 'button'
    if (tag === 'select') return el.multiple ? 'listbox' : 'combobox'
    if (tag === 'textarea') return 'textbox'
    if (tag === 'input') {
      const type = (el.getAttribute('type') || 'text').toLowerCase()
      if (type === 'checkbox') return 'checkbox'
      if (type === 'radio') return 'radio'
      if (type === 'range') return 'slider'
      if (type === 'button' || type === 'submit' || type === 'reset' || type === 'image' || type === 'file') return 'button'
      if (type === 'search') return 'searchbox'
      return 'textbox'
    }
    if (el.isContentEditable) return 'textbox'
    return 'generic'
  }

  function isInteractive(el, role) {
    if (INTERACTIVE_ROLES.indexOf(role) >= 0) return true
    if (el.isContentEditable) return true
    const tabindex = el.getAttribute('tabindex')
    if (tabindex !== null && Number(tabindex) >= 0) return true
    return typeof el.onclick === 'function'
  }

  function nameOf(el) {
    const aria = norm(el.getAttribute('aria-label'))
    if (aria) return clip(aria, 160)
    const labelledby = el.getAttribute('aria-labelledby')
    if (labelledby) {
      const parts = labelledby
        .split(/\s+/)
        .map((id) => {
          const node = document.getElementById(id)
          return node ? norm(node.textContent) : ''
        })
        .filter(Boolean)
      if (parts.length) return clip(parts.join(' '), 160)
    }
    const tag = (el.tagName || '').toLowerCase()
    if (tag === 'input' || tag === 'textarea' || tag === 'select') {
      const labels = el.labels ? Array.prototype.slice.call(el.labels).map((node) => norm(node.textContent)).filter(Boolean) : []
      if (labels.length) return clip(labels.join(' '), 160)
      const placeholder = norm(el.getAttribute('placeholder'))
      if (placeholder) return clip(placeholder, 160)
      const hint = norm(el.getAttribute('alt') || el.getAttribute('title') || el.getAttribute('name'))
      if (hint) return clip(hint, 160)
      const type = (el.getAttribute('type') || '').toLowerCase()
      if (type === 'submit' || type === 'button' || type === 'reset') return clip(norm(el.value) || type, 160)
      return ''
    }
    const image = el.querySelector ? el.querySelector('img[alt]') : null
    if (image) {
      const alt = norm(image.getAttribute('alt'))
      if (alt) return clip(alt, 160)
    }
    const title = norm(el.getAttribute('title'))
    const text = norm(el.textContent)
    return clip(text || title, 160)
  }

  function valueOf(el) {
    const tag = (el.tagName || '').toLowerCase()
    if (tag === 'input') {
      const type = (el.getAttribute('type') || 'text').toLowerCase()
      if (type === 'password') return '••••'
      if (type === 'checkbox' || type === 'radio') return el.checked ? 'true' : 'false'
      return clip(String(el.value || ''), 200)
    }
    if (tag === 'textarea' || tag === 'select') return clip(String(el.value || ''), 200)
    if (el.isContentEditable) return clip(norm(el.textContent), 200)
    return null
  }

  function walk(root, visit) {
    if (!root) return
    let visited = 0
    const stack = [root]
    while (stack.length && visited < MAX_VISITED) {
      const node = stack.pop()
      let all = null
      try {
        all = node.querySelectorAll('*')
      } catch (_) {
        all = null
      }
      if (!all) continue
      for (let index = 0; index < all.length; index += 1) {
        const el = all[index]
        visited += 1
        if (visited > MAX_VISITED) break
        visit(el)
        // user:“shadow DOM 要穿透，否则 Web Component 站点快照是空的”+
        if (el.shadowRoot) stack.push(el.shadowRoot)
      }
    }
  }

  // 被浮层盖住是最常见的「点不到」原因，命中测试是唯一可靠的判断方式。
  function covered(el, rect) {
    let hit = null
    try {
      const x = Math.min(Math.max(rect.left + rect.width / 2, 0), Math.max(window.innerWidth - 1, 0))
      const y = Math.min(Math.max(rect.top + rect.height / 2, 0), Math.max(window.innerHeight - 1, 0))
      hit = document.elementFromPoint(x, y)
    } catch (_) {
      hit = null
    }
    if (!hit) return true
    if (hit === el) return false
    if (el.contains && el.contains(hit)) return false
    if (hit.contains && hit.contains(el)) return false
    return true
  }

  function storeRef(el) {
    let ref = refs.get(el)
    if (!ref) {
      seq = seq >= MAX_REF_SEQ ? 1 : seq + 1
      ref = 'e' + seq
      refs.set(el, ref)
    }
    live.set(ref, { element: el })
    return ref
  }

  function resolveRef(ref) {
    if (typeof ref !== 'string' || !/^e[0-9]{1,6}$/.test(ref)) fail('invalid_ref', 'ref 必须是 e<数字>，收到 ' + String(ref))
    const holder = live.get(ref)
    const el = holder ? holder.element : null
    if (!el || !el.isConnected) fail('stale_ref', ref + ' 已经失效（元素消失或页面换了），请重新 snapshot')
    return el
  }

  // --- snapshot -----------------------------------------------------------

  function snapshot(args) {
    const mode = args.mode === 'full' || args.mode === 'text' ? args.mode : 'interactive'
    const maxNodes = Math.min(Math.max(Number(args.maxNodes) || 200, 1), MAX_NODES)
    const maxChars = Math.min(Math.max(Number(args.maxChars) || 8000, 200), MAX_CHARS)
    const scope = args.scope === 'document' ? 'document' : 'viewport'
    const nodes = []
    let total = 0
    let omitted = 0

    const visit = (el) => {
      const role = roleOf(el)
      if (!isInteractive(el, role)) return
      if (styleHidden(el)) return
      const rect = el.getBoundingClientRect()
      if (!rect.width || !rect.height) return
      if (scope === 'viewport') {
        if (rect.bottom < 0 || rect.top > window.innerHeight || rect.right < 0 || rect.left > window.innerWidth) return
      }
      total += 1
      if (nodes.length >= maxNodes) {
        omitted += 1
        return
      }
      const hidden = scope === 'viewport' ? covered(el, rect) : false
      const ref = storeRef(el)
      const states = []
      if (el.disabled) states.push('disabled')
      if (el.readOnly) states.push('readonly')
      if (el.checked) states.push('checked')
      if (el.getAttribute && el.getAttribute('aria-expanded') === 'true') states.push('expanded')
      if (hidden) states.push('covered')
      const viewportState = rect.top < 0 || rect.bottom > window.innerHeight ? 'offscreen' : 'onscreen'
      nodes.push({
        ref,
        role,
        name: nameOf(el),
        value: valueOf(el),
        bounds: {
          x: Math.round(rect.left),
          y: Math.round(rect.top),
          w: Math.round(rect.width),
          h: Math.round(rect.height)
        },
        states: states.concat([viewportState])
      })
    }

    if (mode !== 'text') walk(document, visit)

    const text = textBlocks(mode === 'interactive' ? 'viewport' : scope, maxChars)

    // 上一轮记录过、这一轮没再出现的 ref 视为失效（页面自己删除或结构变了）。
    const current = new Set(nodes.map((node) => node.ref))
    const stale = []
    live.forEach((holder, ref) => {
      if (!holder.element.isConnected || !current.has(ref)) stale.push(ref)
    })
    stale.forEach((ref) => live.delete(ref))
    // 让页面自己标上 ref，便于人工在 devtools 里对照（不影响任何安全属性）。
    nodes.forEach((node) => {
      const holder = live.get(node.ref)
      if (!holder) return
      try {
        holder.element.setAttribute('data-sunday-ref', node.ref)
      } catch (_) {
        /* 有些元素不允许写属性，忽略 */
      }
    })

    return {
      url: location.href,
      title: document.title || '',
      loading: document.readyState !== 'complete',
      viewport: { w: window.innerWidth, h: window.innerHeight },
      scroll: { x: Math.round(window.scrollX), y: Math.round(window.scrollY) },
      refs: nodes,
      text,
      stale,
      counts: { total, returned: nodes.length, omitted }
    }
  }

  function textBlocks(scope, maxChars) {
    const blocks = []
    let used = 0
    let truncated = false
    let found = 0
    const visit = (el) => {
      if (truncated || found > 4000) return
      if (typeof el.matches !== 'function' || !el.matches(TEXT_TAGS)) return
      found += 1
      if (styleHidden(el)) return
      const rect = el.getBoundingClientRect()
      if (!rect.width || !rect.height) return
      if (scope === 'viewport' && (rect.bottom < 0 || rect.top > window.innerHeight)) return
      // 只取最内层块，避免 <li><p> 重复两遍。
      let nested = null
      try {
        nested = el.querySelector(TEXT_TAGS)
      } catch (_) {
        nested = null
      }
      if (nested) return
      const text = norm(el.textContent)
      if (!text) return
      const level = /^h[1-6]$/i.test(el.tagName) ? Number(el.tagName[1]) : 0
      const chunk = clip(text, MAX_TEXT_BLOCK)
      if (used + chunk.length > maxChars) {
        truncated = true
        return
      }
      used += chunk.length
      blocks.push({ level, text: chunk })
    }
    walk(document, visit)
    return { blocks, truncated }
  }

  // --- html（结构化取片段） ------------------------------------------------
  //
  // user:“以结构化数据作为 Agent 的主要输入”+(页面侧只做一件事：按调用方给的 CSS 选择器，
  // 把命中的 DOM 片段去掉脚本/样式后取回来。卡片识别、字段配对、去重、URL 清洗都不在这里，
  // 那些在 Python 侧按引擎分开写——换引擎只改一个适配器文件，不重编宿主二进制)。
  //
  // 选择器是**数据**不是脚本：这里没有 eval，也没有把页面内容拼进执行路径。

  const HTML_DROP_TAGS = ['script', 'style', 'noscript', 'template', 'svg', 'canvas', 'iframe', 'link', 'meta']
  const HTML_DROP_ATTRS = ['style', 'srcset', 'onerror', 'onload', 'onclick']

  function cleanHtml(el, perNodeChars) {
    let clone = null
    try {
      clone = el.cloneNode(true)
    } catch (_) {
      return ''
    }
    try {
      HTML_DROP_TAGS.forEach((tag) => {
        const items = clone.querySelectorAll ? clone.querySelectorAll(tag) : []
        for (let index = 0; index < items.length; index += 1) items[index].remove()
      })
      const all = [clone].concat(Array.prototype.slice.call(clone.querySelectorAll ? clone.querySelectorAll('*') : []))
      all.forEach((node) => {
        HTML_DROP_ATTRS.forEach((name) => {
          if (node.removeAttribute) node.removeAttribute(name)
        })
      })
    } catch (_) {
      /* 裁剪失败就按原样返回，调用方仍能解析 */
    }
    const html = String(clone.outerHTML || '')
    return html.length > perNodeChars ? html.slice(0, perNodeChars) : html
  }

  function beforeInDocumentOrder(a, b) {
    // Node.DOCUMENT_POSITION_FOLLOWING === 4：b 在 a 之后
    try {
      return (a.compareDocumentPosition(b) & 4) === 4
    } catch (_) {
      return false
    }
  }

  function extractHtml(args) {
    const raw = Array.isArray(args.selectors) ? args.selectors : []
    const selectors = []
    raw.forEach((item) => {
      if (typeof item !== 'string') return
      const text = item.trim()
      if (text && selectors.indexOf(text) < 0) selectors.push(text)
    })
    const maxNodes = Math.min(Math.max(Number(args.maxNodes) || 20, 1), 40)
    const perNodeChars = Math.min(Math.max(Number(args.perNodeChars) || 12000, 400), 40000)
    const maxChars = Math.min(Math.max(Number(args.maxChars) || 100000, 2000), 150000)
    const pageTextChars = Math.min(Math.max(Number(args.pageTextChars) || 0, 0), 8000)

    const skipped = []
    const seen = new Set()
    const candidates = []
    selectors.forEach((selector) => {
      let list = null
      try {
        list = document.querySelectorAll(selector)
      } catch (_) {
        skipped.push(selector)
        return
      }
      for (let index = 0; index < list.length; index += 1) {
        const el = list[index]
        if (seen.has(el)) continue
        seen.add(el)
        candidates.push({ el, selector })
      }
    })
    // 文档顺序才是搜索结果的真实排名，选择器顺序只决定「谁被优先认领」。
    candidates.sort((a, b) => (beforeInDocumentOrder(a.el, b.el) ? -1 : 1))

    const nodes = []
    const picked = []
    let matched = 0
    let omitted = 0
    let chars = 0
    let truncated = false
    for (let index = 0; index < candidates.length; index += 1) {
      const item = candidates[index]
      if (styleHidden(item.el)) continue
      matched += 1
      // 父子同时命中只留外层：内层是把同一条结果再算一遍。
      let nested = false
      for (let inner = 0; inner < picked.length; inner += 1) {
        if (picked[inner].contains(item.el)) {
          nested = true
          break
        }
      }
      if (nested) continue
      if (nodes.length >= maxNodes) {
        omitted += 1
        continue
      }
      const html = cleanHtml(item.el, perNodeChars)
      if (!html) continue
      if (chars + html.length > maxChars) {
        truncated = true
        omitted += 1
        continue
      }
      chars += html.length
      nodes.push({ selector: item.selector, html })
      picked.push(item.el)
    }

    let pageText = ''
    if (pageTextChars > 0) {
      try {
        const body = document.body
        const text = body ? body.innerText || body.textContent : document.documentElement.textContent
        pageText = clip(norm(text), pageTextChars)
      } catch (_) {
        pageText = ''
      }
    }

    return {
      url: location.href,
      title: document.title || '',
      readyState: document.readyState,
      nodes,
      counts: { matched, returned: nodes.length, omitted, chars, truncated },
      pageText,
      skippedSelectors: skipped
    }
  }

  // --- act ----------------------------------------------------------------

  function fire(el, type, init) {
    const options = Object.assign({ bubbles: true, cancelable: true, composed: true, view: window }, init || {})
    let event
    try {
      if (type.indexOf('pointer') === 0 && typeof PointerEvent === 'function') event = new PointerEvent(type, options)
      else if (type.indexOf('key') === 0 && typeof KeyboardEvent === 'function') event = new KeyboardEvent(type, options)
      else if (typeof MouseEvent === 'function') event = new MouseEvent(type, options)
      else event = new Event(type, options)
    } catch (_) {
      event = new Event(type, { bubbles: true, cancelable: true })
    }
    el.dispatchEvent(event)
  }

  function focusQuietly(el) {
    try {
      el.focus({ preventScroll: true })
    } catch (_) {
      try {
        el.focus()
      } catch (_) {
        /* 不可聚焦就继续，合成事件仍然会派发 */
      }
    }
  }

  function clickElement(el) {
    focusQuietly(el)
    fire(el, 'pointerover')
    fire(el, 'mouseover')
    fire(el, 'pointerdown')
    fire(el, 'mousedown')
    fire(el, 'pointerup')
    fire(el, 'mouseup')
    // native click 最接近真实点击；被页面拦掉时再补一个合成 click。
    try {
      el.click()
    } catch (_) {
      fire(el, 'click')
    }
  }

  function setValue(el, text) {
    const tag = (el.tagName || '').toLowerCase()
    if (tag === 'input' || tag === 'textarea') {
      focusQuietly(el)
      const proto = tag === 'input' ? window.HTMLInputElement && window.HTMLInputElement.prototype : window.HTMLTextAreaElement && window.HTMLTextAreaElement.prototype
      let applied = false
      if (proto) {
        const descriptor = Object.getOwnPropertyDescriptor(proto, 'value')
        // user:“要触发页面自己的 input/change，框架才更新”+(原生 setter 才会让 React/Vue 的受控组件跟上)。
        if (descriptor && descriptor.set) {
          descriptor.set.call(el, text)
          applied = true
        }
      }
      if (!applied) el.value = text
      fire(el, 'input')
      fire(el, 'change')
      return
    }
    if (el.isContentEditable) {
      focusQuietly(el)
      el.textContent = text
      fire(el, 'input')
      fire(el, 'change')
      return
    }
    fail('unsupported', '这个元素不接受文本输入')
  }

  function submitOf(el, args) {
    if (!args || !args.submit) return false
    const form = el.form || (el.closest ? el.closest('form') : null)
    if (form) {
      // user:“我手动输入之后点回车，它搜出来的结果也没有问题”+
      // (直接走表单默认按钮时，Bing 首页给的是「热门内容轮播」视图：整页只有一两条卡片，
      //  查询里的意图词等于被丢掉。真人回车走的是 form=QBRE 的搜索入口，先把这一项拨回去)。
      const wanted = String(args.formValue == null ? '' : args.formValue)
      if (wanted) {
        for (const field of form.elements) {
          if (field && field.name === 'form') field.value = wanted
        }
      }
      if (typeof form.requestSubmit === 'function') form.requestSubmit()
      else form.submit()
      return true
    }
    // user:“内置那个新标签页，我手动输入之后点回车”+
    // (有些引擎的搜索框由 JS 接管、没有外层表单：那就照人手的方式发一次回车)。
    pressKeyOn(el, 'Enter')
    return true
  }

  function pressKeyOn(el, key) {
    const target = el || document.activeElement || document.body
    if (!target) return
    fire(target, 'keydown', { key, code: key })
    fire(target, 'keypress', { key, code: key })
    fire(target, 'keyup', { key, code: key })
  }

  // 目标元素：优先 ref（snapshot 给的编号），其次 selector（页面自带的搜索框等），
  // 最后才退到当前焦点。搜索流程没有 snapshot，只认页面自己的搜索框。
  function resolveTarget(args, allowActive) {
    if (args.ref) return resolveRef(args.ref)
    const selector = String(args.selector == null ? '' : args.selector)
    if (selector) {
      let el = null
      try {
        el = document.querySelector(selector)
      } catch (_) {
        el = null
      }
      if (!el) fail('unsupported', '页面上找不到这个选择器：' + selector)
      return el
    }
    return allowActive ? document.activeElement : null
  }

  function act(args) {
    const op = args.op
    const before = location.href
    if (op === 'click') {
      const el = resolveTarget(args, false)
      if (!el) fail('unsupported', 'click 需要 ref 或 selector')
      clickElement(el)
    } else if (op === 'type') {
      const text = String(args.text == null ? '' : args.text)
      if (text.length > 4000) fail('unsupported', '一次最多输入 4000 个字符')
      const el = resolveTarget(args, true)
      if (!el) fail('unsupported', '页面上没有可输入的焦点元素')
      setValue(el, args.clear ? text : String(el.value || '') + text)
      if (args.submit) submitOf(el, args)
    } else if (op === 'clear') {
      const el = resolveTarget(args, true)
      if (!el) fail('unsupported', 'clear 需要 ref 或 selector')
      setValue(el, '')
    } else if (op === 'hover') {
      const el = resolveTarget(args, false)
      if (!el) fail('unsupported', 'hover 需要 ref 或 selector')
      const rect = el.getBoundingClientRect()
      fire(el, 'pointerover', { clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 })
      fire(el, 'mouseover')
      fire(el, 'mousemove')
    } else if (op === 'select') {
      const el = resolveTarget(args, false)
      if (!el) fail('unsupported', 'select 需要 ref 或 selector')
      if ((el.tagName || '').toLowerCase() !== 'select') fail('unsupported', '这个元素不是下拉框')
      const wanted = String(args.value == null ? '' : args.value)
      let matched = false
      for (let index = 0; index < el.options.length; index += 1) {
        const option = el.options[index]
        if (option.value === wanted || norm(option.textContent) === wanted) {
          el.selectedIndex = index
          matched = true
          break
        }
      }
      if (!matched) fail('unsupported', '下拉框里没有这个选项：' + wanted)
      fire(el, 'input')
      fire(el, 'change')
    } else if (op === 'scroll') {
      if (args.ref) {
        const el = resolveRef(args.ref)
        try {
          el.scrollIntoView({ block: 'center', inline: 'nearest' })
        } catch (_) {
          el.scrollIntoView()
        }
      } else {
        const dx = Number(args.dx) || 0
        const dy = Number(args.dy) || 0
        if (Math.abs(dx) > 20000 || Math.abs(dy) > 20000) fail('unsupported', '一次滚动距离太大')
        window.scrollBy(dx, dy)
      }
    } else if (op === 'pressKey') {
      const key = String(args.key || '')
      if (!key) fail('unsupported', '缺少按键名')
      pressKeyOn(null, key)
    } else {
      fail('unsupported', '未知操作：' + String(op))
    }
    return { url: location.href, navigated: location.href !== before, scroll: { x: Math.round(window.scrollX), y: Math.round(window.scrollY) } }
  }

  // --- waitFor ------------------------------------------------------------

  function waitFor(args, id, op) {
    const kind = args.kind || 'selector'
    const value = String(args.value == null ? '' : args.value)
    const want = args.state === 'absent' ? 'absent' : 'present'
    const timeoutMs = Math.min(Math.max(Number(args.timeoutMs) || 5000, 200), 60000)
    const started = Date.now()
    let observer = null
    let timer = 0
    let finished = false

    const finish = (ok) => {
      if (finished) return
      finished = true
      if (observer) observer.disconnect()
      if (timer) clearTimeout(timer)
      window.removeEventListener('load', check, true)
      window.removeEventListener('DOMContentLoaded', check, true)
      if (ok) {
        send({
          sunday: 1,
          id,
          op,
          ok: true,
          result: { kind, value, state: want, elapsedMs: Date.now() - started, url: location.href, readyState: document.readyState }
        })
      } else {
        send({ sunday: 1, id, op, ok: false, error: { code: 'timeout', message: '等待超时：' + kind + ' ' + value } })
      }
    }

    const test = () => {
      if (kind === 'selector') {
        try {
          return Boolean(document.querySelector(value))
        } catch (_) {
          return false
        }
      }
      if (kind === 'text') {
        const body = document.body ? String(document.body.innerText || document.body.textContent || '') : ''
        return body.indexOf(value) >= 0
      }
      if (kind === 'url') return location.href.indexOf(value) >= 0
      if (kind === 'load') return document.readyState === 'complete'
      return false
    }

    const check = () => {
      let matched = false
      try {
        matched = test()
      } catch (_) {
        matched = false
      }
      if (want === 'present' ? matched : !matched) finish(true)
    }

    if (kind !== 'load' && kind !== 'url') {
      // 事件驱动：DOM 变化才检查，不做空转轮询。
      try {
        observer = new MutationObserver(check)
        observer.observe(document.documentElement || document, {
          subtree: true,
          childList: true,
          attributes: true,
          characterData: true
        })
      } catch (_) {
        observer = null
      }
    }
    window.addEventListener('load', check, true)
    window.addEventListener('DOMContentLoaded', check, true)
    timer = setTimeout(() => finish(false), timeoutMs)
    check()
  }

  // --- 指令入口 -----------------------------------------------------------

  function handle(raw) {
    let message = raw
    if (typeof raw === 'string') {
      try {
        message = JSON.parse(raw)
      } catch (_) {
        return
      }
    }
    if (!message || message.sunday !== 1 || typeof message.id !== 'string' || typeof message.op !== 'string') return
    const args = message.args && typeof message.args === 'object' ? message.args : {}
    // user:“应答必须回带请求的 op”+(宿主侧 validate 要求 op ∈ 白名单；漏了 op 会被整条丢弃，
    // 表现为「页面没响应」的假超时——这里统一走 reply()，不再逐个手写）。
    const reply = (payload) => send(Object.assign({ sunday: 1, id: message.id, op: message.op }, payload))
    try {
      if (message.op === 'ping') {
        reply({ ok: true, result: { url: location.href, readyState: document.readyState, version: 1 } })
        return
      }
      if (message.op === 'snapshot') {
        reply({ ok: true, result: snapshot(args) })
        return
      }
      if (message.op === 'html') {
        reply({ ok: true, result: extractHtml(args) })
        return
      }
      if (message.op === 'act') {
        const result = act(args)
        reply({ ok: true, result })
        return
      }
      if (message.op === 'waitFor') {
        waitFor(args, message.id, message.op)
        return
      }
      reply({ ok: false, error: { code: 'unsupported', message: '未知指令：' + message.op } })
    } catch (error) {
      const code = error && error.sundayCode ? error.sundayCode : 'page_error'
      const text = clip(String((error && error.message) || error), 300)
      reply({ ok: false, error: { code, message: text } })
    }
  }

  // --- 用户接管信号 -------------------------------------------------------
  //
  // user:“用 isTrusted 判断接管”+(合成事件 isTrusted 恒为 false，页面伪造不了 true)。
  const INPUT_EVENTS = ['pointerdown', 'keydown', 'wheel', 'touchstart', 'input', 'change', 'paste']
  let lastInputAt = 0
  function reportInput(event) {
    if (!event.isTrusted) return
    const now = Date.now()
    if (now - lastInputAt < INPUT_REPORT_INTERVAL) return
    lastInputAt = now
    send({ sunday: 1, op: 'event', kind: 'user-input', args: { kind: String(event.type) } })
  }
  INPUT_EVENTS.forEach((type) => {
    window.addEventListener(type, reportInput, true)
  })

  try {
    window.chrome.webview.addEventListener('message', (event) => handle(event.data))
  } catch (_) {
    /* 没有 WebView2 通道时不装桥，Rust 侧表现为指令超时 */
  }
})()

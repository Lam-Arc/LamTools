<template>
  <!-- user:“这个组内的 UI 设计与风格”+(桌面设备页使用共享标题、面板与错误反馈)。 -->
  <section class="device-page" :class="{ 'device-page--desktop': isDesktop }" data-remote-connection>
    <header class="device-page__head" :class="{ 'sunday-page-heading': isDesktop }">
      <div class="device-page__intro">
        <h2 class="device-page__title" :class="{ 'sunday-page-title': isDesktop }">{{ t("设备连接") }}</h2>
        <p class="device-page__sub" :class="{ 'sunday-page-description': isDesktop }">
          {{ isDesktop
            ? t("配对后，手机可以接手这台电脑上的会话。")
            : t("选择在哪里工作：这台手机，或一台配对过的电脑。") }}
        </p>
      </div>
      <button class="device-page__refresh" type="button" :disabled="busy" @click="refresh">
        <RefreshCw :size="14" :stroke-width="2" aria-hidden="true" />
        {{ t("刷新") }}
      </button>
    </header>

    <p v-if="error" :class="isDesktop ? 'sunday-page-status sunday-page-status--error' : 'device-page__error'" role="alert">{{ error }}</p>

    <!-- 手机：设备清单。切换就发生在这里，输入框上方不再有第二个入口。 -->
    <template v-if="!isDesktop">
      <ul class="device-list">
        <li
          class="device-item"
          :class="{ 'is-active': activeId === 'local' }"
          @click="onRowClick('local')"
        >
          <span class="device-item__icon"><Smartphone :size="18" :stroke-width="1.9" aria-hidden="true" /></span>
          <span class="device-item__body">
            <span class="device-item__name">{{ t("本机") }}</span>
            <span class="device-item__meta">{{ t("这台手机 · 不需要连接") }}</span>
          </span>
          <span v-if="activeId === 'local'" class="device-item__badge is-here">{{ t("当前") }}</span>
          <button
            v-else
            class="device-item__action"
            type="button"
            :disabled="busy"
            data-device-switch="local"
            @click="switchTo('local')"
          >
            {{ t("切到本机") }}
          </button>
        </li>

        <li
          v-for="entry in paired"
          :key="entry.id"
          class="device-item"
          :class="{ 'is-active': activeId === entry.id }"
          @click="onRowClick(entry.id)"
        >
          <span class="device-item__icon"><Monitor :size="18" :stroke-width="1.9" aria-hidden="true" /></span>
          <span class="device-item__body">
            <span class="device-item__name">{{ entry.name }}</span>
            <span class="device-item__meta">
              {{ t("电脑 · 已配对") }}
              <template v-if="usable && peer === entry.id"> · {{ t("连接正常") }}</template>
              <template v-else-if="usable && peer !== entry.id"> · {{ t("未连接") }}</template>
            </span>
          </span>
          <span v-if="activeId === entry.id" class="device-item__badge is-here">{{ t("当前") }}</span>
          <button
            v-else
            class="device-item__action"
            type="button"
            :disabled="busy"
            :data-device-switch="entry.id"
            @click="switchTo(entry.id)"
          >
            {{ t("切换") }}
          </button>
        </li>

        <li v-if="paired.length === 0" class="device-list__empty">
          {{ t("还没有配对的电脑。在电脑上打开「远程连接」生成二维码，然后下方扫码。") }}
        </li>
      </ul>

      <div class="device-page__actions">
        <button
          class="device-page__button is-primary"
          type="button"
          :disabled="busy"
          data-remote-scan
          @click="scan"
        >
          <QrCode :size="16" :stroke-width="2" aria-hidden="true" />
          {{ t("扫码连接电脑") }}
        </button>
        <button
          class="device-page__button"
          type="button"
          :disabled="busy"
          data-remote-paste-toggle
          @click="pasting = !pasting"
        >
          {{ pasting ? t("收起票据") : t("粘贴票据") }}
        </button>
      </div>

      <p v-if="busy && progressText" class="device-page__progress" role="status">
        {{ progressText }}（{{ t("已等待 {0} 秒", { 0: elapsed }) }}）
      </p>

      <div v-if="pasting" class="device-page__paste">
        <textarea
          v-model="ticketInput"
          rows="3"
          spellcheck="false"
          :placeholder="t('sunday1:…')"
          data-remote-ticket-input
        />
        <button
          class="device-page__button is-primary"
          type="button"
          :disabled="busy || !ticketInput.trim()"
          @click="connect"
        >
          {{ t("连接这台电脑") }}
        </button>
      </div>

      <!-- user:“优先保证连接的稳定，减少无故断连”+(一个开关，不开就没有通知；
           开了只把进程留在前台，连接本身仍由 Rust 宿主负责)。 -->
      <label class="device-page__toggle">
        <input
          type="checkbox"
          class="sunday-checkbox"
          :checked="keepAlive"
          :disabled="busy"
          data-p2p-keepalive
          @change="onKeepAliveChange"
        />
        <span>{{ t("后台保持连接") }}</span>
      </label>
      <p class="device-page__foot">
        {{ t("开启后会显示一条低优先级通知，减少系统在后台把连接挂起。") }}
      </p>
    </template>

    <!-- 电脑：二维码就是全部入口；生成票据即开始接受连接。 -->
    <template v-else>
      <!-- user:“发布版本启动后 P2P 服务能真的起来：给出启动状况的可见状态（运行/未运行/失败原因），
           不是只写日志”+(状态就摆在这一页：进程在不在、为什么起不来、这张码还剩多久)。 -->
      <div class="device-page__service" data-p2p-service-status>
        <span class="device-page__dot" :class="{ 'is-live': running }" aria-hidden="true"></span>
        <span v-if="serviceError" class="device-page__service-text" data-p2p-service-error>
          {{ t("传输服务失败：{0}", { 0: serviceError }) }}
        </span>
        <span v-else-if="running" class="device-page__service-text">{{ t("传输服务运行中") }}</span>
        <span v-else class="device-page__service-text">{{ t("传输服务未运行") }}</span>
        <span v-if="canUseTicket" class="device-page__expiry">
          {{ t("二维码 {0} 秒后失效", { 0: expiresIn }) }}
        </span>
        <span v-else-if="ticket && !pairingSyncPending" class="device-page__expiry">{{ t("二维码已过期，请重新生成") }}</span>
      </div>
      <!-- user:"记住用户是否开启远程访问（持久化，不依赖临时状态）"+(桌面开关；
           下次启动按它决定要不要自动起传输) -->
      <!-- user:“统一与去重”+(下次启动的偏好复用共享复选框，保留原有保存逻辑)。 -->
      <label v-if="isDesktop" class="device-page__toggle">
        <input
          type="checkbox"
          class="sunday-checkbox"
          :checked="autoConnect"
          :disabled="busy || savingAutoConnect"
          data-p2p-autoconnect
          @change="onAutoConnectChange"
        />
        <span>{{ t("启动时自动开启远程访问") }}</span>
      </label>
      <!-- user:“针对远程连接/设备配对 去查修目前用户体验最差的一点，并列出接下来的候选”+
           (收到扫码申请后，把确认和拒绝直接显示在桌面二维码上方)。 -->
      <p class="sr-only" role="status">{{ pending.length ? t("有设备等待确认配对") : '' }}</p>
      <section v-if="pending.length" class="pair-approval sunday-page-panel" :aria-label="t('待确认设备')" data-p2p-pending>
        <h3 class="pair-approval__title">{{ t("待确认设备") }}</h3>
        <ul class="device-list">
          <li v-for="item in pending" :key="item.id" class="device-item">
            <span class="device-item__body">
              <span class="device-item__name" :title="item.id">{{ item.name || shortId(item.id) }}</span>
            </span>
            <button class="device-item__action" type="button" :disabled="busy" @click="confirmDevice(item.id)">{{ t("确认") }}</button>
            <button class="device-item__action" type="button" :disabled="busy" @click="rejectDevice(item.id)">{{ t("拒绝") }}</button>
          </li>
        </ul>
      </section>
      <div v-if="ticket" class="pair-card sunday-page-panel">
        <div v-if="qrSvg && canUseTicket" class="pair-card__qr" v-html="qrSvg" aria-hidden="true"></div>
        <div class="pair-card__side">
          <p class="pair-card__hint">{{ t("用 Sunday M 扫码后在这台电脑上确认配对。二维码 5 分钟内有效，每张仅供一台设备申请。") }}</p>
          <!-- user:“三项全做”+(图片生成失败时保留可手动选中的配对码，并提供重试和复制)。 -->
          <p v-if="canUseTicket && qrError" class="sunday-page-status sunday-page-status--error" role="alert" data-p2p-qr-error>
            {{ t("二维码生成失败。可以重试，或复制配对码。") }}
          </p>
          <code v-if="canUseTicket" class="pair-card__ticket" data-remote-ticket>{{ ticket }}</code>
          <p v-if="canUseTicket && copyError" class="sunday-page-status sunday-page-status--error" role="alert">{{ t("复制失败，请手动选中配对码。") }}</p>
          <div class="device-page__actions">
            <button v-if="canUseTicket && qrError" class="device-page__button" type="button" :disabled="busy || qrLoading" data-p2p-qr-retry @click="refreshQr(ticket)">{{ t("重试") }}</button>
            <button v-if="canUseTicket" class="device-page__button" type="button" :disabled="busy" data-p2p-copy @click="copyTicket">{{ copied ? t("已复制") : t("复制配对码") }}</button>
            <button class="device-page__button" type="button" :disabled="busy" data-p2p-reissue @click="createTicket">{{ t("重新生成") }}</button>
            <button class="device-page__button" type="button" :disabled="busy" data-p2p-stop @click="stopServing">{{ t("停止本次远程访问") }}</button>
          </div>
        </div>
      </div>
      <button
        v-else
        class="device-page__button is-primary is-wide"
        type="button"
        :disabled="busy"
        data-p2p-generate
        @click="createTicket"
      >
        {{ busy ? t("正在生成…") : t("生成配对二维码") }}
      </button>

      <!-- user:"只有业务真正可用才显示「已连接电脑」"+(view=connected 才说连上；
           降级必须给一句话原因，不能继续显示正常)。 -->
      <div v-if="usable" class="device-page__note" data-p2p-connected>
        {{ t("手机已连上这台电脑。") }}
        <button class="device-page__link" type="button" :disabled="busy" @click="disconnect">{{ t("断开") }}</button>
      </div>
      <div v-else-if="statusHint" class="device-page__note is-degraded" data-p2p-status-hint>
        {{ statusHint }}
        <button v-if="connected" class="device-page__link" type="button" :disabled="busy" @click="disconnect">{{ t("断开") }}</button>
      </div>

      <!-- user:“真实路径显示：区分直连/中继，默认放在连接详情里，不占据主界面”+
           (主界面只说连上没连上；走直连还是经中继收进可展开的详情)。 -->
      <details v-if="connected" class="device-page__details" data-p2p-path>
        <summary>{{ t("连接详情") }}</summary>
        <dl>
          <div>
            <dt>{{ t("当前设备") }}</dt>
            <dd>{{ currentDeviceName || (peer ? shortId(peer) : "—") }}</dd>
          </div>
          <div>
            <dt>{{ t("连接方式") }}</dt>
            <dd data-p2p-path-value>{{ pathLabel }}</dd>
          </div>
          <div v-if="rttMs > 0">
            <dt>{{ t("延迟") }}</dt>
            <dd data-p2p-rtt>{{ rttMs }} ms</dd>
          </div>
          <div>
            <dt>{{ t("会话") }}</dt>
            <dd>{{ sessionResumed ? t("已恢复") : t("未恢复") }}</dd>
          </div>
        </dl>
      </details>

      <!-- user:“设备切换：多设备时切换当前连接，状态随之更新（不要出现「切换了但状态还显示旧
           设备」）”+(在线的每台一行，点切换立即生效；当前那台永远只认宿主给的那一台)。 -->
      <ul v-if="onlineDevices.length > 1" class="device-list" data-p2p-online-devices>
        <li
          v-for="item in onlineDevices"
          :key="item.id"
          class="device-item"
          :class="{ 'is-active': item.current }"
        >
          <span class="device-item__icon"><Smartphone :size="18" :stroke-width="1.9" aria-hidden="true" /></span>
          <span class="device-item__body">
            <span class="device-item__name">{{ item.name || shortId(item.id) }}</span>
            <span class="device-item__meta">
              {{ pathText(item.path) }}
              <template v-if="item.session"> · {{ t("会话已恢复") }}</template>
            </span>
          </span>
          <span v-if="item.current" class="device-item__badge is-here">{{ t("当前") }}</span>
          <button
            v-else
            class="device-item__action"
            type="button"
            :disabled="busy"
            :data-device-current="item.id"
            @click="switchDevice(item.id)"
          >
            {{ t("切换") }}
          </button>
        </li>
      </ul>

      <!-- user:“解析失败即明确报错，不要静默”+(状态通道坏了就摆出来，不让界面继续显示旧状态)。 -->
      <p v-if="protocolError" class="device-page__error" data-p2p-protocol-error>
        {{ t("状态通道异常：{0}", { 0: protocolError }) }}
      </p>
    </template>

    <p v-if="!isDesktop" class="device-page__foot">
      {{ t("电脑上打开 Sunday，进入「远程连接」生成二维码，再用这里扫码；第一次连上之后，这台手机会记住它。") }}
    </p>

    <!-- user:“传输面板：在「远程连接」面板或文件屏里列出 transfers[]（方向、文件名、进度、
         状态），支持取消；失败可重试；完成后可「打开所在文件夹」”+
         (设备页是互传的落脚点：正在传的、传完的、收到过的都在同一块里，不用去别处找)。 -->
    <TransferPanel
      v-if="isDesktop"
      :invoke="host() ?? undefined"
      :preview-services="services ? transferPreview : undefined"
      @retry="onTransferRetry"
    />

    <!-- 没有可信设备时整块不出现，避免空状态占位。 -->
    <details v-if="devices.length || revoked.length" class="device-page__trusted">
      <summary>{{ t("可信设备") }} <span>{{ devices.length }}</span></summary>
      <ul>
        <li v-for="device in devices" :key="device.id">
          <span :title="device.id">{{ device.name || shortId(device.id) }}</span>
          <button type="button" :disabled="busy" @click="revoke(device.id)">{{ t("撤销") }}</button>
        </li>
      </ul>
      <!-- user:“允许撤销授权”+(撤销之后那台设备不该还能连；这里把被撤销的列出来，可以重新允许) -->
      <ul v-if="revoked.length">
        <li v-for="device in revoked" :key="device.id">
          <span :title="device.id">{{ device.name || shortId(device.id) }} · {{ t("已撤销") }}</span>
          <button type="button" :disabled="busy" :data-device-allow="device.id" @click="allow(device.id)">{{ t("重新允许") }}</button>
        </li>
      </ul>
    </details>
  </section>
</template>

<script setup lang="ts">
import { t } from '@/i18n/index.ts'

import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Monitor, QrCode, RefreshCw, Smartphone } from 'lucide-vue-next'
import type { RemoteConnectionServices } from '@/components/remoteConnectionServices.ts'
import TransferPanel from '@/components/TransferPanel.vue'

import {
  activateDevice,
  readDevices,
  readKeepAlivePref,
  readTicket,
  saveConnectedDevice,
  saveKeepAlivePref,
  saveTicket,
  type PairedDevice,
} from '@/app/remoteSession.ts'
import { explainStatus, isAwaitingApproval, isUsable } from '@/app/remoteReconnect.ts'

/**
 * 设备连接页。
 *
 * user:“工作环境的切换从输入框挪到设备连接那个页面”“设备连接页面你也要重做一遍，
 * 现在的样式太普通了，不易用”+(所以这一页的主体是设备清单：本机一行、每台配对过的
 * 电脑一行，行内直接切换；扫码与粘贴退到清单下面当“添加设备”，不再是首屏唯一动作)。
 *
 * 命令由宿主提供：桌面是 p2p_ticket / p2p_qr / …，手机是 p2p_scan / p2p_connect / …。
 * 这里只做界面，协议与身份都在 core/p2p。
 */
const props = defineProps<{ platform?: 'desktop' | 'mobile' | 'web'; services?: RemoteConnectionServices }>()
// user:“交互测试”+(设备页展厅的传输区不订阅真实位置或文件事件)。
const transferPreview = { open: () => undefined }

const ticket = ref('')
const qrSvg = ref('')
const qrError = ref(false)
const qrLoading = ref(false)
const copyError = ref(false)
const pairingSyncPending = ref(false)
const ticketInput = ref('')
const serving = ref(false)
/** 传输进程是否真的在跑（p2p_status 的 running）。 */
const running = ref(false)
/** 启动失败原因（进程找不到、端口被占之类），空表示没问题。 */
const serviceError = ref('')
/** 当前二维码的过期时间（Unix 秒），0 表示没有可用的码。 */
const expiresAt = ref(0)
/** 每秒走一格，用来把过期时间显示成倒计时。 */
const clock = ref(Math.floor(Date.now() / 1000))
const expiresIn = computed(() => (expiresAt.value > 0 ? Math.max(0, expiresAt.value - clock.value) : 0))
const canUseTicket = computed(() => !pairingSyncPending.value && Boolean(ticket.value) && expiresIn.value > 0)
const connected = ref(false)
/** 宿主给的分层结论（view/reason/layers）；旧宿主没有这些字段时退回 connected。 */
const view = ref('')
const reason = ref('')
/** 「启动时自动开启远程访问」开关（宿主持久化在 p2p-prefs.json）。 */
const autoConnect = ref(false)
const savingAutoConnect = ref(false)
const peer = ref('')
/** 当前连接走的是直连还是中继（宿主给的 path；空/unknown 表示还在判定）。 */
const pathKind = ref('unknown')
/** 当前选中路径的往返延迟（毫秒）；0 表示还没测出来。 */
const rttMs = ref(0)
/** 当前设备的显示名（多设备时用来分清是哪一台）。 */
const currentDeviceName = ref('')
/** 当前那台的会话是否真的恢复过（宿主按「当前设备」给，不按「有设备」猜）。 */
const sessionResumed = ref(false)
/** 已连上的设备清单（宿主的 devices）：多设备时点这里切换。 */
const onlineDevices = ref<Array<{ id: string; name: string; path: string; session: boolean; current: boolean }>>([])
/** 状态通道解析失败的原因：非空就说明传输进程与宿主的契约坏了。 */
const protocolError = ref('')
const devices = ref<Array<{ id: string; name: string }>>([])
const revoked = ref<Array<{ id: string; name: string }>>([])
/** 已经扫码、但还在等电脑确认的设备（宿主从 p2p-pairing.json 读出来）。 */
const pending = ref<Array<{ id: string; name: string; requestedAt?: number; expiresAt?: number }>>([])
/** 手机扫了码，但电脑还没确认：界面靠它自动重试。 */
const pendingApproval = ref(false)
/** 手机：后台保持连接（前台服务）；桌面不显示这个开关。 */
const keepAlive = ref(true)
let approvalTimer: number | null = null
let approvalAttempts = 0
const paired = ref<PairedDevice[]>([])
const busy = ref(false)
const error = ref('')
const pasting = ref(false)
const copied = ref(false)
let copyTimer: number | undefined
let pairingRevision = 0
let syncedPairingCodeRevision: number | undefined
let requestedPairingCodeRevision: number | undefined
let autoConnectRevision = 0
const elapsed = ref(0)
const progressText = ref('')
let progressTimer: number | null = null

const isDesktop = computed(() => (props.platform ?? 'desktop') === 'desktop')
/**
 * user:“只有业务真正可用才显示「已连接电脑」”+(view==='connected' 才算可用；
 * degraded / connecting / offline 一律不算，哪怕隧道还活着)。
 */
// 空字符串表示「这个宿主没给 view」（旧宿主），必须传 undefined 才会回退到 connected。
const usable = computed(() => isUsable({ view: view.value || undefined, reason: reason.value, connected: connected.value }))
/**
 * 不可用时的一句话原因。
 *
 * user:“对端 Core 挂掉时必须降级显示”+(只有「本来连着、现在不成立」才提示；
 * 桌面还没等到手机连的时候不该冒一句「还没有连接到电脑」)。
 */
const statusHint = computed(() => {
  if (usable.value) return ''
  if (!connected.value && view.value !== 'degraded') return ''
  return explainStatus({ view: view.value || undefined, reason: reason.value, connected: connected.value })
})
/** 当前在哪一台设备上工作：连着电脑就是对端 id，否则本机。 */
/**
 * 界面此刻真正在用的工作环境（不是隧道状态）。
 *
 * user:“我切到本机之后它又变回去了”+(以前这里用 connected && peer 推断，隧道一连上就
 * 认为当前是电脑，可界面走的是启动时选定的通道，两者能同时成立又互相矛盾)。
 * 启动流程会把实际选择写进 localStorage，这里照它显示。
 */
/** 只读一次 localStorage 不够：切换之后到重载之间，徽标要立刻跟着走。 */
function readActive(): string {
  if (props.services) return 'local'
  try {
    return localStorage.getItem('sunday.p2p.active') || 'local'
  } catch {
    return 'local'
  }
}

const activeId = ref(readActive())

/** 点整行就能切，不用先找到右边那颗按钮。 */
function onRowClick(id: string): void {
  if (busy.value || id === activeId.value) return
  void switchTo(id)
}

function host(): ((command: string, args?: Record<string, unknown>) => Promise<unknown>) | null {
  // user:“交互测试”+(隔离预览不连接或修改实际桌面设备)。
  if (props.services) return props.services.invoke
  const bridge = (window as unknown as {
    __TAURI_INTERNALS__?: { invoke: (command: string, args?: Record<string, unknown>) => Promise<unknown> }
  }).__TAURI_INTERNALS__
  return bridge ? bridge.invoke.bind(bridge) : null
}

async function call<T>(command: string, args?: Record<string, unknown>): Promise<T | null> {
  const invoke = host()
  if (!invoke) return null
  return (await invoke(command, args)) as T
}

function shortId(id: string): string {
  return id.length > 12 ? `${id.slice(0, 6)}…${id.slice(-4)}` : id
}

// user:“全部处理并继续寻找”+(重试原传输，始终交给宿主查找原接收设备)。
async function onTransferRetry(payload: { id: string }): Promise<void> {
  const invoke = host()
  if (!invoke) return
  busy.value = true
  error.value = ''
  try {
    await invoke('p2p_retry_transfer', { id: payload.id })
  } catch (cause) {
    error.value = String(cause)
  } finally {
    busy.value = false
  }
}

function loadPaired(): void {
  paired.value = props.services ? [] : readDevices()
}

interface HostStatus {
  running?: boolean
  serving?: boolean
  connected?: boolean
  peer?: string | null
  ticket?: string
  expiresAt?: number
  pairingCodeRevision?: number
  error?: string | null
  binaryError?: string | null
  view?: string
  reason?: string
  autoConnect?: boolean
}

function applyStatus(status: HostStatus, pairingIsCurrent = true, preferenceIsCurrent = true): void {
  if (typeof status.running === 'boolean' || typeof status.serving === 'boolean') {
    running.value = status.running === true || status.serving === true
    serving.value = status.serving ?? running.value
  }
  if ('error' in status || 'binaryError' in status) serviceError.value = status.error || status.binaryError || ''
  if (typeof status.connected === 'boolean') connected.value = status.connected
  if (status.peer === null || typeof status.peer === 'string') peer.value = status.peer ?? ''
  if (typeof status.view === 'string') view.value = status.view
  if (typeof status.reason === 'string') reason.value = status.reason
  if (preferenceIsCurrent && !savingAutoConnect.value && typeof status.autoConnect === 'boolean') {
    autoConnect.value = status.autoConnect
  }
  if (pairingIsCurrent && typeof status.ticket === 'string') {
    setPairingCode(status.ticket, status.expiresAt ?? 0, status.pairingCodeRevision)
  }
  applyLive(status)
}

async function readStatus(): Promise<void> {
  const revision = pairingRevision
  const preferenceRevision = autoConnectRevision
  const status = await call<HostStatus>('p2p_status')
  if (!status || !mounted) return
  applyStatus(status, revision === pairingRevision, preferenceRevision === autoConnectRevision)
}

function onStatusPush(status: HostStatus): void {
  if (isDesktop.value && status.running === false) {
    setPairingCode('', 0, status.pairingCodeRevision)
  }
  applyStatus(status)
  const revision = status.pairingCodeRevision
  if (!isDesktop.value || revision === undefined || revision === syncedPairingCodeRevision || revision === requestedPairingCodeRevision) return
  requestedPairingCodeRevision = revision
  pairingSyncPending.value = true
  pairingRevision++
  void readStatus().catch(() => {
    // 下次收到状态或手动刷新时可以重试；旧码保持隐藏。
  }).finally(() => {
    if (requestedPairingCodeRevision === revision) requestedPairingCodeRevision = undefined
  })
}

async function refresh(): Promise<void> {
  busy.value = true
  error.value = ''
  activeId.value = readActive()
  try {
    await readStatus()
    loadPaired()
    const list = await call<{ devices?: Array<{ id: string; name: string }>; revoked?: Array<{ id: string; name: string }> }>('p2p_devices')
    devices.value = list?.devices ?? []
    revoked.value = list?.revoked ?? []
  } catch (cause) {
    error.value = String(cause)
  } finally {
    busy.value = false
  }
}

/**
 * 静默轮询连接状态。
 *
 * user:“连上了电脑，但是它弹了一个错误”“我根本不知道卡在哪里了”+(手机连上或者断开，
 * 电脑这边应当自己变，而不是让用户盯着二维码猜；断开之后也还留着上一台的残影)。
 */
async function refreshQuiet(force = false): Promise<void> {
  // user:“确保视觉、功能和交互不退化”+(出票据后允许在忙碌状态内刷新有效期，普通轮询仍避开操作)。
  if (busy.value && !force) return
  try {
    await readStatus()
    loadPaired()
  } catch {
    // 轮询失败不打断用户正在做的事。
  }
}

// user:“三项全做”+(配对码和过期时间一起更新，旧图片和复制反馈随旧码清掉)。
function setPairingCode(value: string, expiry: number, revision?: number): void {
  const changed = value !== ticket.value
  if (changed || expiry !== expiresAt.value) pairingRevision++
  syncedPairingCodeRevision = revision
  pairingSyncPending.value = false
  ticket.value = value
  expiresAt.value = expiry
  clock.value = Math.floor(Date.now() / 1000)
  ensureClock()
  if (!changed) return
  qrSvg.value = ''
  qrError.value = false
  copyError.value = false
  copied.value = false
  window.clearTimeout(copyTimer)
  qrLoading.value = false
  if (canUseTicket.value) void refreshQr(value)
}

async function refreshQr(value: string): Promise<void> {
  if (!canUseTicket.value || qrLoading.value) return
  qrLoading.value = true
  try {
    const result = await call<{ svg?: string }>('p2p_qr', { ticket: value })
    if (value !== ticket.value) return
    qrSvg.value = result?.svg?.trim() ?? ''
    qrError.value = !qrSvg.value
  } catch {
    if (value === ticket.value) qrError.value = true
  } finally {
    if (value === ticket.value) qrLoading.value = false
  }
}

async function copyTicket(): Promise<void> {
  if (!canUseTicket.value) return
  const value = ticket.value
  copyError.value = false
  copied.value = false
  window.clearTimeout(copyTimer)
  try {
    if (props.services) await props.services.copy(value)
    else await navigator.clipboard.writeText(value)
    if (value !== ticket.value) return
    copied.value = true
    window.clearTimeout(copyTimer)
    copyTimer = window.setTimeout(() => { copied.value = false }, 1500)
  } catch {
    if (value === ticket.value) copyError.value = true
  }
}

/** 从票据里取出直连地址与中继，用于说明这次会先试什么。 */
function describeTicket(value: string): { ip: string; relay: boolean } {
  try {
    const body = value.trim().replace(/^sunday1:/, '')
    const padded = body.replace(/-/g, '+').replace(/_/g, '/')
      + '='.repeat((4 - (body.length % 4)) % 4)
    const parsed = JSON.parse(atob(padded)) as { addrs?: Array<{ Ip?: string; Relay?: string }> }
    return {
      ip: parsed.addrs?.find((item) => typeof item.Ip === 'string')?.Ip ?? '',
      relay: Boolean(parsed.addrs?.some((item) => typeof item.Relay === 'string')),
    }
  } catch {
    return { ip: '', relay: false }
  }
}

/** user:“连接过程中一点反应都没有”+(连接期间说明先试哪条路，并显示已等待时间)。 */
function startConnecting(value: string): void {
  const { ip, relay } = describeTicket(value)
  progressText.value = ip && relay
    ? t('正在连接：先试直连 {0}，失败自动走中继', { 0: ip })
    : ip
      ? t('正在直连 {0}', { 0: ip })
      : t('正在通过中继连接')
  elapsed.value = 0
  if (progressTimer !== null) window.clearInterval(progressTimer)
  progressTimer = window.setInterval(() => {
    elapsed.value += 1
  }, 1000)
}

function stopConnecting(): void {
  if (progressTimer !== null) {
    window.clearInterval(progressTimer)
    progressTimer = null
  }
  progressText.value = ''
  elapsed.value = 0
}

/** 切换工作设备：先断掉现有隧道，再按新选择重开界面。 */
async function switchTo(id: string): Promise<void> {
  if (busy.value || id === activeId.value) return
  busy.value = true
  error.value = ''
  try {
    // user:“点了切换电脑，重启一遍核心之后进去还在手机，再点还是这样”“要把后台退出
    // 再重进才行”+(启动阶段那次自动切换会留一个去重标记防止重载打转，可它在
    // sessionStorage 里，重载并不清；用户第二次亲手点，就被自己上一次的记录挡住了。
    // 既然是人主动选的，就把标记清掉，让这一次自动切换重新生效)。
    try {
      sessionStorage.removeItem('sunday.p2p.switched')
    } catch {
      // 存储不可用只是少了这层去重，不影响切换本身。
    }
    if (id === 'local') {
      activateDevice(null)
      // user:“我怎么从控制电脑切回手机”+(只清票据不够：宿主里的隧道还连着，重开之后
      // 又会按「已连接」走回电脑。切换必须先断掉现有隧道)。
      await call('p2p_disconnect').catch(() => undefined)
      void syncConnectionService()
      window.location.reload()
      return
    }
    const device = readDevices().find((item) => item.id === id)
    if (!device) throw new Error(t('这台电脑不在配对列表里了'))
    // user:“点了切换电脑…进去还在手机”+(以前只存票据就重载，重载时通道还没通，界面
    // 只能先落回本机，再赌后台拨号；拨号慢一点就一直停在本机。这里先连上再重载)。
    const name = isDesktop.value ? 'PC' : 'Phone'
    const result = await call<{ resume?: string; name?: string }>('p2p_connect', { ticket: device.ticket, name, timeoutMs: 45_000 })
    activateDevice(id)
    if (result?.resume) saveConnectedDevice(device.ticket, result.resume, result.name || device.name)
    window.location.reload()
  } catch (cause) {
    error.value = String(cause)
  } finally {
    busy.value = false
  }
}

/**
 * user:“记住用户是否开启远程访问（持久化，不依赖临时状态）”+(桌面这边勾上就落盘，
 * 下次启动 Core 就绪后自动恢复传输；取消勾选等于下次不自动起)。
 */
function onAutoConnectChange(event: Event): void {
  const target = event.target as HTMLInputElement | null
  void toggleAutoConnect(target ? target.checked : !autoConnect.value)
}

async function toggleAutoConnect(next: boolean): Promise<void> {
  autoConnectRevision++
  savingAutoConnect.value = true
  autoConnect.value = next
  try {
    // Tauri 的命令参数按 camelCase 绑定到 Rust 的 snake_case 参数。
    const result = await call<{ autoConnect?: boolean }>('p2p_config_set', { autoConnect: next })
    if (result && typeof result.autoConnect === 'boolean') autoConnect.value = result.autoConnect
  } catch (cause) {
    // 写盘失败就退回原来的值：界面不能显示一个宿主根本没记住的开关。
    autoConnect.value = !next
    error.value = String(cause)
  } finally {
    savingAutoConnect.value = false
    autoConnectRevision++
  }
}

/** 生成票据即开始接受连接，不再让用户点第二次。 */
async function createTicket(): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    const args: Record<string, unknown> = {}
    if (isDesktop.value) {
      const apiBase = await call<string>('get_api_base')
      if (!apiBase) throw new Error(t('拿不到本地后端地址'))
      args.apiBase = apiBase
    }
    const result = await call<HostStatus>('p2p_ticket', { ...args, renew: Boolean(ticket.value) })
    if (result?.ticket) {
      serving.value = true
      running.value = true
      serviceError.value = ''
      if (typeof result.expiresAt === 'number') setPairingCode(result.ticket, result.expiresAt, result.pairingCodeRevision)
      await refreshQuiet(true)
    }
  } catch (cause) {
    error.value = String(cause)
  } finally {
    busy.value = false
  }
}

async function stopServing(): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    await call('p2p_serve_stop')
    serving.value = false
    running.value = false
    setPairingCode('', 0)
    await refreshQuiet(true)
  } catch (cause) {
    error.value = String(cause)
  } finally {
    busy.value = false
  }
}

/** 扫码成功就直接连，不再让用户点“连接”。 */
async function scan(): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    const result = await call<{ ticket?: string | null }>('p2p_scan')
    if (!result?.ticket) return
    ticketInput.value = result.ticket
    await connect()
  } catch (cause) {
    error.value = String(cause)
  } finally {
    busy.value = false
  }
}

/** 开关只表达开/停：有票据且用户没关掉时才启动前台服务。 */
async function syncConnectionService(): Promise<void> {
  if (isDesktop.value) return
  const enabled = keepAlive.value && Boolean(readTicket())
  try {
    await call('connection_service_set', { enabled })
  } catch {
    // 老宿主没有这个命令：连接照常可用，只是没有后台保活。
  }
}

function onKeepAliveChange(event: Event): void {
  const target = event.target as HTMLInputElement | null
  keepAlive.value = Boolean(target?.checked)
  saveKeepAlivePref(keepAlive.value)
  void syncConnectionService()
}

async function connect(): Promise<void> {
  busy.value = true
  error.value = ''
  startConnecting(ticketInput.value)
  try {
    const name = isDesktop.value ? 'PC' : 'Phone'
    const result = await call<{ peer?: string; name?: string; resume?: string }>('p2p_connect', { ticket: ticketInput.value.trim(), name })
    connected.value = Boolean(result?.peer)
    peer.value = result?.peer ?? ''
    if (result?.peer) {
      // user:“配对成功后建立持久设备信任，下次自动连接”+(把当前票换成 sunday1 地址票；
      // sunday2 只有 5 分钟，不能当长期凭据。设备清单也用它，切换时才不用重扫)。
      saveConnectedDevice(ticketInput.value.trim(), result.resume ?? '', result.name || shortId(result.peer))
      void syncConnectionService()
      loadPaired()
    }
    window.location.reload()
  } catch (cause) {
    const message = String(cause)
    // user:“电脑显示待确认设备，用户确认配对”+(扫码后只是提出申请；明确告诉用户
    // 去电脑上点确认，而不是把「还没确认」说成连接失败)。
    if (isAwaitingApproval(message)) {
      pendingApproval.value = true
      error.value = t('等待电脑确认：请在电脑的「设备连接」页点「确认」，确认后会自动连上。')
      startApprovalWait(ticketInput.value.trim())
    } else {
      error.value = message
      if (!isDesktop.value) pasting.value = true
    }
  } finally {
    busy.value = false
    stopConnecting()
  }
}

/** user:“电脑显示待确认设备，用户确认配对”+(每 2.5 秒用同一张票重试，确认后自动接上)。 */
function startApprovalWait(ticket: string): void {
  if (approvalTimer !== null || !ticket) return
  const tick = async () => {
    approvalTimer = null
    approvalAttempts += 1
    if (!pendingApproval.value || approvalAttempts > 60) {
      stopApprovalWait()
      return
    }
    try {
      const name = isDesktop.value ? 'PC' : 'Phone'
      const result = await call<{ peer?: string; name?: string; resume?: string }>('p2p_connect', {
        ticket,
        name,
        timeoutMs: 20_000,
      })
      if (result?.peer) {
        saveConnectedDevice(ticket, result.resume ?? '', result.name || shortId(result.peer))
        void syncConnectionService()
        pendingApproval.value = false
        stopApprovalWait()
        window.location.reload()
        return
      }
    } catch (cause) {
      if (!isAwaitingApproval(String(cause))) {
        pendingApproval.value = false
        error.value = String(cause)
        stopApprovalWait()
        return
      }
    }
    approvalTimer = window.setTimeout(tick, 2_500)
  }
  approvalTimer = window.setTimeout(tick, 2_500)
}

function stopApprovalWait(): void {
  if (approvalTimer !== null) {
    window.clearTimeout(approvalTimer)
    approvalTimer = null
  }
  approvalAttempts = 0
}

async function disconnect(): Promise<void> {
  stopApprovalWait()
  pendingApproval.value = false
  busy.value = true
  try {
    await call('p2p_disconnect')
    connected.value = false
    peer.value = ''
    // user:“交互测试”+(隔离预览断开时不修改真实票据，也不重载应用)。
    if (!props.services) {
      saveTicket('')
      void syncConnectionService()
      window.location.reload()
    }
  } finally {
    busy.value = false
  }
}

async function allow(id: string): Promise<void> {
  busy.value = true
  try {
    await call('p2p_allow', { id })
    await refresh()
  } catch (cause) {
    error.value = String(cause)
  } finally {
    busy.value = false
  }
}

async function revoke(id: string): Promise<void> {
  busy.value = true
  try {
    await call('p2p_revoke', { id })
    await refresh()
  } catch (cause) {
    error.value = String(cause)
  } finally {
    busy.value = false
  }
}

/** user:“电脑显示待确认设备，用户确认配对”+(确认后才写可信名单)。 */
async function confirmDevice(id: string): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    await call('p2p_confirm_device', { id })
    await refresh()
  } catch (cause) {
    error.value = String(cause)
  } finally {
    busy.value = false
  }
}

/** 拒绝同时把设备记入撤销名单，旧票作废。 */
async function rejectDevice(id: string): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    await call('p2p_reject_device', { id })
    await refresh()
  } catch (cause) {
    error.value = String(cause)
  } finally {
    busy.value = false
  }
}

/** 倒计时只在真的有二维码时才需要：没有码就没有唤醒。 */
let clockTimer: number | null = null

function stopClock(): void {
  if (clockTimer !== null) {
    window.clearInterval(clockTimer)
    clockTimer = null
  }
}

function ensureClock(): void {
  clock.value = Math.floor(Date.now() / 1000)
  const needed = expiresIn.value > 0 && document.visibilityState === 'visible'
  if (!needed) {
    stopClock()
    return
  }
  if (clockTimer === null) {
    clockTimer = window.setInterval(() => {
      clock.value = Math.floor(Date.now() / 1000)
      // 码过期了就没有继续走的理由。
      if (expiresIn.value === 0) stopClock()
    }, 1000)
  }
}

/** 窗口重新可见 / 重新获得焦点时对齐一次；其余时间靠宿主推送。 */
function onVisibility(): void {
  if (document.visibilityState !== 'visible') {
    stopClock()
    return
  }
  void refreshQuiet(true)
  ensureClock()
}

function onFocus(): void {
  void refreshQuiet(true)
}

/** 连接详情用到的字段（手动刷新与推送两条路共用一份）。 */
function applyLive(raw: unknown): void {
  // 入参用 unknown 再收窄：两个调用点各自的内联类型只声明了自己关心的字段，写死成窄
  // 结构会让「没有公共字段」直接编译不过，而不是在运行时安全地忽略缺字段。
  const status = (raw || {}) as {
    path?: string
    deviceName?: string
    protocolError?: string | null
    layers?: { session?: string }
    devices?: Array<{ id: string; name: string; path: string; session: boolean; current: boolean }>
    pending?: Array<{ id: string; name: string; requestedAt?: number; expiresAt?: number }>
    rttMs?: number
  }
  if (typeof status.path === 'string' && status.path) pathKind.value = status.path
  if (typeof status.rttMs === 'number') rttMs.value = status.rttMs
  if (typeof status.deviceName === 'string') currentDeviceName.value = status.deviceName
  if (typeof status.protocolError === 'string' || status.protocolError === null) {
    protocolError.value = status.protocolError || ''
  }
  if (status.layers) sessionResumed.value = status.layers.session === 'resumed'
  if (Array.isArray(status.devices)) onlineDevices.value = status.devices
  if (Array.isArray(status.pending)) pending.value = status.pending
  ensureClock()
}

/** 直连/中继的界面说法。 */
function pathText(kind: string): string {
  if (kind === 'direct') return t('直连')
  if (kind === 'relay') return t('经中继')
  return t('正在判定')
}

const pathLabel = computed(() => pathText(pathKind.value))

/**
 * 多设备在线时切换当前连接。
 *
 * user:“设备切换：多设备时切换当前连接，状态随之更新”+(先按宿主的答复当场改，再取一次完整
 * 状态对齐；这样不会出现「切换了但徽标/会话还挂在旧设备」)。
 */
async function switchDevice(id: string): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    const result = await call<{
      currentDevice?: string | null
      name?: string
      path?: string
      session?: boolean
    }>('p2p_switch_device', { id })
    if (result?.currentDevice) {
      peer.value = result.currentDevice
      currentDeviceName.value = result.name || ''
      pathKind.value = result.path || 'unknown'
      sessionResumed.value = result.session === true
      onlineDevices.value = onlineDevices.value.map((item) => ({
        ...item,
        current: item.id === result.currentDevice,
      }))
    }
    await refreshQuiet(true)
  } catch (cause) {
    error.value = String(cause)
  } finally {
    busy.value = false
  }
}

let mounted = false
const unlistenHost: Array<() => void> = []

function keepHostListener(unlisten: () => void): void {
  if (typeof unlisten !== 'function') return
  if (mounted) unlistenHost.push(unlisten)
  else unlisten()
}

onMounted(() => {
  mounted = true
  activeId.value = readActive()
  keepAlive.value = readKeepAlivePref()
  void syncConnectionService()
  void refresh()
  ensureClock()
  document.addEventListener('visibilitychange', onVisibility)
  window.addEventListener('focus', onFocus)
  if (props.services || !host()) return
  void import('@tauri-apps/api/event').then(async ({ listen }) => {
    try {
      keepHostListener(await listen<{ phase?: string; reason?: string }>('p2p-progress', (event) => {
        const phase = event.payload?.phase
        const why = event.payload?.reason || ''
        // user:“扫码后立刻有反馈”“配对/连接/恢复会话分阶段可见”+(阶段由宿主推过来，
        // 界面不用等 3 秒轮询：等待对方 / 已配对 / 正在连 / 恢复会话 / 降级各有一句话)。
        if (phase === 'dialing') {
          if (!progressText.value) progressText.value = t('正在连接对方…')
        } else if (phase === 'waiting') {
          progressText.value = t('等待手机连接…')
        } else if (phase === 'connecting') {
          progressText.value = t('正在建立会话…')
        } else if (phase === 'connected') {
          progressText.value = t('已连上，正在切换到远程会话…')
        } else if (phase === 'degraded') {
          // 降级不停留在「已连接」：界面当场换成原因。
          view.value = 'degraded'
          reason.value = why
          progressText.value = explainStatus({ view: 'degraded', reason: why })
        } else if (phase === 'lost' || phase === 'failed' || phase === 'timeout') {
          view.value = 'offline'
          reason.value = ''
        }
      }))
    } catch {
      // 进度事件只是提示，缺了不影响连接。
    }
    try {
      // user:“清理无效轮询与监听”+(宿主变了才推这一条：路径、在线设备、当前设备、会话)。
      keepHostListener(await listen<HostStatus>('p2p-state', (event) => {
        onStatusPush(event.payload)
      }))
    } catch {
      // 没有推送时界面仍能在切回窗口时对齐一次。
    }
  })
})

onUnmounted(() => {
  mounted = false
  pairingRevision++
  for (const unlisten of unlistenHost.splice(0)) unlisten()
  document.removeEventListener('visibilitychange', onVisibility)
  window.removeEventListener('focus', onFocus)
  stopClock()
  stopApprovalWait()
  window.clearTimeout(copyTimer)
})
</script>

<style scoped>
.device-page__details {
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 10%, transparent);
  border-radius: 10px;
  padding: 8px 12px;
  font-size: 12px;
}

.device-page__details summary {
  cursor: pointer;
  opacity: 0.7;
}

.device-page__details dl {
  margin: 8px 0 0;
  display: grid;
  gap: 6px;
}

.device-page__details dt {
  display: inline;
  margin-right: 6px;
  opacity: 0.55;
}

.device-page__details dd {
  display: inline;
  margin: 0;
}

.device-page {
  display: grid;
  gap: var(--space-4);
}

.device-page:not(.device-page--desktop) .device-page__head {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
}

.device-page__intro {
  min-width: 0;
}

.device-page:not(.device-page--desktop) .device-page__title {
  margin: 0;
  font-size: 17px;
  font-weight: 650;
  letter-spacing: 0.01em;
}

.device-page:not(.device-page--desktop) .device-page__sub {
  margin: 4px 0 0;
  font-size: 12px;
  line-height: 1.6;
  opacity: 0.6;
}

.device-page__refresh {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 12%, transparent);
  border-radius: 999px;
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.device-page__refresh:hover:not(:disabled) {
  background: color-mix(in srgb, var(--theme-main-text) 6%, transparent);
}

.device-page__refresh:disabled {
  opacity: 0.4;
  cursor: default;
}

.device-page__service {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin: 0 0 12px;
  font-size: 12px;
  color: color-mix(in srgb, var(--theme-main-text) 62%, transparent);
}

.device-page__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: color-mix(in srgb, var(--theme-main-text) 28%, transparent);
}

.device-page__dot.is-live {
  background: var(--green, #3ecf8e);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--green, #3ecf8e) 18%, transparent);
}

.device-page__expiry {
  margin-left: auto;
  color: color-mix(in srgb, var(--theme-main-text) 45%, transparent);
  font-variant-numeric: tabular-nums;
}

.device-page__error {
  margin: 0;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--red) 12%, transparent);
  color: var(--red);
  font-size: 12px;
  line-height: 1.6;
}

/* ── 设备清单 ─────────────────────────────────────────── */
.device-list {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.device-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 10%, transparent);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--theme-main-text) 2.5%, transparent);
  transition: border-color 0.18s ease, background 0.18s ease;
}

.device-item.is-active {
  border-color: color-mix(in srgb, var(--theme-main-text) 26%, transparent);
  background: color-mix(in srgb, var(--theme-main-text) 6%, transparent);
}

.device-item__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  flex: 0 0 auto;
  border-radius: 12px;
  background: color-mix(in srgb, var(--theme-main-text) 7%, transparent);
  opacity: 0.85;
}

.device-item__body {
  display: grid;
  gap: 3px;
  min-width: 0;
  flex: 1;
}

.device-item__name {
  font-size: 14px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.device-item__meta {
  font-size: 11.5px;
  line-height: 1.4;
  opacity: 0.55;
}

.device-item__badge {
  flex: 0 0 auto;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 11px;
  letter-spacing: 0.04em;
}

.device-item__badge.is-here {
  background: color-mix(in srgb, var(--green) 18%, transparent);
  color: var(--green);
}

.device-item__action {
  flex: 0 0 auto;
  padding: 8px 14px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 16%, transparent);
  border-radius: 999px;
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: 12.5px;
  cursor: pointer;
}

.device-item__action:hover:not(:disabled) {
  background: color-mix(in srgb, var(--theme-main-text) 8%, transparent);
}

.device-item__action:disabled {
  opacity: 0.4;
  cursor: default;
}

.device-list__empty {
  padding: 18px 14px;
  border: 1px dashed color-mix(in srgb, var(--theme-main-text) 16%, transparent);
  border-radius: var(--radius);
  font-size: 12px;
  line-height: 1.7;
  opacity: 0.6;
}

/* ── 动作 ─────────────────────────────────────────────── */
.device-page__actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.device-page__button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 10px 16px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 14%, transparent);
  border-radius: var(--radius-sm);
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}

.device-page__button:hover:not(:disabled) {
  background: color-mix(in srgb, var(--theme-main-text) 6%, transparent);
}

.device-page__button.is-primary {
  background: var(--theme-main-text);
  border-color: transparent;
  color: var(--theme-main-background);
  font-weight: 650;
}

.device-page__button.is-wide {
  width: 100%;
}

.device-page__button:disabled {
  opacity: 0.45;
  cursor: default;
}

.device-page__foot {
  margin: 0;
  padding-top: 4px;
  font-size: 11.5px;
  line-height: 1.7;
  opacity: 0.42;
}

.device-page__progress {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  opacity: 0.66;
}

.device-page__paste {
  display: grid;
  gap: 8px;
}

.device-page__paste textarea {
  width: 100%;
  padding: 10px;
  border-radius: var(--radius-sm);
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 14%, transparent);
  background: color-mix(in srgb, var(--theme-main-text) 4%, transparent);
  color: inherit;
  font: 12px/1.6 ui-monospace, monospace;
  resize: vertical;
}

.device-page__toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: color-mix(in srgb, var(--theme-main-text) 62%, transparent);
  cursor: pointer;
  user-select: none;
}

.device-page__note.is-degraded {
  color: color-mix(in srgb, var(--theme-main-text) 82%, transparent);
  opacity: 0.9;
}

.device-page__note {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12.5px;
  opacity: 0.72;
}

.device-page__link {
  border: 0;
  padding: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  text-decoration: underline;
  cursor: pointer;
  opacity: 0.8;
}

/* ── 电脑端：二维码 ───────────────────────────────────── */
.pair-approval {
  display: grid;
  gap: var(--space-2);
  padding: var(--space-3);
}

.pair-approval__title {
  margin: 0;
  font-size: 14px;
  font-weight: 650;
}

.pair-card {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  flex-wrap: wrap;
  padding: 14px;
}

.pair-card__qr {
  flex: 0 0 auto;
  width: 156px;
  height: 156px;
  padding: 6px;
  border-radius: var(--radius-sm);
  background: #ffffff;
}

.pair-card__qr :deep(svg) {
  display: block;
  width: 100%;
  height: 100%;
}

.pair-card__side {
  display: grid;
  flex: 1 1 220px;
  gap: 10px;
  min-width: 0;
}

.pair-card__hint {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  opacity: 0.66;
}

.pair-card__ticket {
  display: block;
  width: 100%;
  padding: 8px 10px;
  border: 0;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-main-text) 6%, transparent);
  color: inherit;
  text-align: left;
  user-select: text;
  min-width: 0;
  font: 12px/1.5 ui-monospace, monospace;
  overflow-wrap: anywhere;
}

/* ── 可信设备 ─────────────────────────────────────────── */
.device-page__trusted {
  border-top: 1px solid color-mix(in srgb, var(--theme-main-text) 8%, transparent);
  padding-top: 10px;
}

.device-page__trusted summary {
  display: flex;
  gap: 8px;
  font-size: 12px;
  opacity: 0.66;
  cursor: pointer;
}

.device-page__trusted ul {
  display: grid;
  gap: 6px;
  margin: 10px 0 0;
  padding: 0;
  list-style: none;
}

.device-page__trusted li {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}

.device-page__trusted li span {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  opacity: 0.72;
}

.device-page__trusted li button {
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 14%, transparent);
  border-radius: var(--radius-sm);
  background: transparent;
  color: inherit;
  padding: 3px 10px;
  font: inherit;
  font-size: 11.5px;
  cursor: pointer;
}
</style>

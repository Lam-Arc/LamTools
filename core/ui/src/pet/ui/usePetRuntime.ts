/**
 * 覆盖层运行时：把配置、世界、Agent 通道和卡片缝在一起，并把 Ping 独立运行时组合进来。
 *
 * 这里只做编排，不做业务规则：物理在 engine，会话在 agent，系统能力在 bridge。
 *
 * user:"ping 环跟桌宠应当是解耦的，它们是两个独立的功能，我只是在这一次设计方案中把它写在一起了"+
 * (Ping 的装配整体抽到了 ../ping/usePingRuntime.ts，本文件只负责组合：
 *  提供共享的配置/覆盖层/光标/Agent 通道，并把桌宠能力以可选注入的方式交给 Ping；
 *  摘掉 Ping（不调用 ping.*）不影响桌宠，零宠物时 Ping 也照常工作。)
 */
import { computed, reactive, ref, shallowRef, watch } from 'vue'
import { PetWorld } from '../engine/world.ts'
import type { PetInstance } from '../engine/pet.ts'
import type { TerrainQuality } from '../engine/terrain.ts'
import { QUALITY_PRESETS } from '../engine/terrain.ts'
import type { PetRecordConfig } from '../config.ts'
import { clipPrimarySource, hitboxWorldRect, type PetHitbox } from '../engine/sprite.ts'
import { defaultConfig, migrateConfig, PET_CONFIG_VERSION, type PetConfigV1 } from '../config.ts'
import { patchPetConfig } from '../configFile.ts'
import { PetAgentHost } from '../agent/host.ts'
import { createPetAgentClient, type PetAgentClient } from '../agent/client.ts'
import * as bridge from '../bridge.ts'
import type { MonitorInfo, OverlayBounds } from '../bridge.ts'
import { analyzeImport, type ImportAnalysis, type ImportScanResult } from '../assets/importer.ts'
import { packNameFrom, readSundayPetZip } from '../assets/zip.ts'
import { createDefaultSkinCanvas } from '../render/blockySkin.ts'
import type { AnimationMap } from '../engine/sprite.ts'
import { createThreePetLayer, type ThreePetLayer } from '../render/threeLayer.ts'
import type { RenderablePet } from '../render/types.ts'
import { sundaySkinBytes } from '../assets/sundaySkin.ts'
// user:“你看看 ping 环 要不也自己做窗口？”+(Ping 运行时已迁到独立窗口，
// 桌宠侧只保留类型引用，便于历史组件继续使用 Ping 的公开类型。)
export type { PingMarker, PingResultPayload, CardState, PingRuntime } from '../ping/usePingRuntime.ts'

export interface BubbleState {
  id: string
  petId: string
  sessionId: string
  kind: 'notification' | 'actionable' | 'session'
  title: string
  /** 一句话请求（去掉“需要确认：”前缀）；卡片只显示这一句。 */
  subject: string
  body: string
  /** 提问/审批的来源（子代理名或投递方）；主 Agent 为空。 */
  source: string
  requestId: string | null
  isQuestion: boolean
  options: { id: string; label: string; response?: string }[]
  createdAt: number
  expanded: boolean
  dismissed: boolean
  handling: boolean
  error: string
}

export interface RuntimeError {
  scope: string
  message: string
  at: number
}

const SPRITE_FALLBACK = new Map<string, HTMLCanvasElement>()

export function usePetRuntime() {
  const config = reactive<PetConfigV1>(defaultConfig())
  const world = shallowRef<PetWorld | null>(null)
  const overlay = reactive<OverlayBounds>({ x: 0, y: 0, width: 1920, height: 1080, scale: 1 })
  const monitors = ref<MonitorInfo[]>([])
  /** 真实桌面窗口（物理像素）：局部遮挡裁剪与 L2 地形共用一次枚举结果。 */
  const windowsRef = ref<{ x: number; y: number; width: number; height: number }[]>([])
  const cursor = reactive({ x: 0, y: 0, inside: false })
  const errors = ref<RuntimeError[]>([])
  const ready = ref(false)
  const booting = ref(false)
  const overlayOpen = ref(false)
  const configWarnings = ref<string[]>([])
  const configMigratedFrom = ref<number | null>(null)

  const petRecords = ref<PetRecordConfig[]>([])
  const agents = shallowRef<PetAgentHost | null>(null)
  const agentClient = shallowRef<PetAgentClient | null>(null)

  const bubbles = ref<BubbleState[]>([])

  const debug = reactive({ ...defaultConfig().debugOverlay })
  const stats = reactive({
    fps: 0,
    tickMs: 0,
    drawMs: 0,
    captureMs: 0,
  })

  /** 覆盖层里的面板开关统一放在这里，Ping 的自定义项也能打开它们。 */
  const ui = reactive({ settingsOpen: false, hudVisible: false })

  // -------------------------------------------------------------------------
  // Ping
  // -------------------------------------------------------------------------

  // user:“你看看 ping 环 要不也自己做窗口？”+
  // user:“卡片即窗口，把 ping 和桌宠拆分开”
  // +(Ping 运行时、热键、轮盘/标记/标注、会话选择器、会话卡片全部搬到了
  //  独立的 Ping 覆盖层窗口（pet/ui/PingSurface.vue）。桌宠运行时不再创建
  //  或转发任何 Ping 状态；两边只通过宿主事件互通（提示气泡/桌宠动作）。)

  const images = new Map<string, HTMLImageElement>()
  const imageLoading = new Set<string>()
  /** 项目 id → 名称：气泡左上角来源行用（名称拿不到就退回 id）。 */
  const projectNames = ref<Record<string, string>>({})
  let canvas: HTMLCanvasElement | null = null
  // 3D 层单独一块透明 WebGL 画布；只有真的出现模型动作时才创建。
  let threeCanvas: HTMLCanvasElement | null = null
  // 调试层：叠在 WebGL 画布之上，判定框不会被角色遮住。
  let debugCanvas: HTMLCanvasElement | null = null
  const threeLayer = shallowRef<ThreePetLayer | null>(null)
  const threeState = reactive({ enabled: false, models: 0, slots: 0, error: '' })
  let threeCanvasDirty = true
  let rafHandle = 0
  let lastFrameAt = 0
  let fpsAccumulator = 0
  let fpsFrames = 0
  let lastReportedRects = ''
  let lastRectsReportedAt = 0
  let lastL3At = 0
  let lastWindowsAt = 0
  let hostPoller = 0
  /** 主窗口焦点轮询：聚焦时隐藏气泡（用户已经在主界面里）。 */
  let mainFocusTimer = 0
  const mainFocused = ref(false)
  /** 渲染帧计数：气泡位置按它每帧重算，角色移动/被拖走时气泡跟随。 */
  const frameTick = ref(0)
  /**
   * 覆盖层心跳定时器。
   *
   * user:“从你启动开始就一直是黑屏未响应状态”+(页面活着就每 2 秒报一次，
   * 宿主据此判定这块全屏窗口还有人画；没人画就自动收起，别把桌面锁死。)
   */
  let heartbeatTimer = 0

  function report(scope: string, error: unknown): void {
    const message = error instanceof Error ? error.message : String(error)
    errors.value = [...errors.value.slice(-19), { scope, message, at: Date.now() }]
    console.warn(`[pet:${scope}]`, message)
  }

  // -------------------------------------------------------------------------
  // 配置
  // -------------------------------------------------------------------------

  async function loadConfig(): Promise<void> {
    try {
      const text = await bridge.readConfigText()
      if (!text) {
        Object.assign(config, defaultConfig())
        await saveConfig()
        configWarnings.value = ['首次使用，已写入默认配置 v' + PET_CONFIG_VERSION]
        return
      }
      const migrated = migrateConfig(safeParse(text))
      Object.assign(config, migrated.config)
      // 迁移保存发生在 restorePets 之前：先把宠物列表同步进 ref，否则
      // saveConfig 会用当时还空的 petRecords 把文件里的角色清空。
      petRecords.value = Array.isArray(migrated.config.pets) ? migrated.config.pets : []
      configWarnings.value = migrated.warnings
      configMigratedFrom.value = migrated.migratedFrom
      if (migrated.migratedFrom !== null) await saveConfig()
    } catch (error) {
      report('config', error)
      Object.assign(config, defaultConfig())
    }
    Object.assign(debug, config.debugOverlay)
  }

  function safeParse(text: string): unknown {
    try {
      return JSON.parse(text)
    } catch {
      return null
    }
  }

  // ping 只在用户在本窗口改过时才提交；否则由 Ping 窗口/主界面设置负责。
  let pingDirty = false
  // Ping 目标绑定也单独标记：只改扇区时不能把 Ping 窗口刚改的目标覆盖回去。
  let pingBindingDirty = false
  // 自己写入后广播的 config-changed 会回到本窗口：这个时间窗内忽略，避免
  // 自己刚保存完又走一遍重载。
  let lastLocalSaveAt = 0

  let saveTimer = 0
  async function saveConfig(): Promise<void> {
    config.version = PET_CONFIG_VERSION
    config.debugOverlay = { ...debug }
    config.pets = petRecords.value
    try {
      const patch: Record<string, unknown> = {
        version: PET_CONFIG_VERSION,
        enabled: config.enabled,
        quality: config.quality,
        useL3: config.useL3,
        zMode: config.zMode,
        debugOverlay: { ...debug },
        bubbles: config.bubbles,
        pets: petRecords.value,
        presetInstalled: config.presetInstalled,
        presetVersion: config.presetVersion,
        bindings: { pets: config.bindings.pets },
        perf: config.perf,
      }
      if (pingDirty) patch.ping = config.ping
      if (pingBindingDirty) {
        patch.bindings = { pets: config.bindings.pets, ping: config.bindings.ping }
      }
      lastLocalSaveAt = Date.now()
      await patchPetConfig(patch)
      pingDirty = false
      pingBindingDirty = false
    } catch (error) {
      report('config-save', error)
    }
  }

  function scheduleSave(): void {
    if (saveTimer) clearTimeout(saveTimer)
    saveTimer = window.setTimeout(() => { void saveConfig() }, 400)
  }

  /** 桌宠设置面板改 Ping 字段：标记 ping 归属，保存时才提交这段。 */
  function schedulePingSave(): void {
    pingDirty = true
    scheduleSave()
  }

  /**
   * 外部（主界面设置 / Ping 面板 / 右键面板）改了同一个 config.json：
   * 重读文件并把差异应用到这个窗口，保证文件是唯一源。
   */
  async function reloadConfigFromDisk(): Promise<void> {
    // 自己的写入也会广播回来；刚保存的 800ms 内忽略，避免自我重载。
    if (Date.now() - lastLocalSaveAt < 800) return
    try {
      const text = await bridge.readConfigText()
      if (!text) return
      const migrated = migrateConfig(safeParse(text))
      const next = migrated.config
      const previousPets = [...petRecords.value]
      const bindings = config.bindings
      Object.assign(config, next)
      // host 持有的是 config.bindings 这个对象本身，不能整体替换引用。
      config.bindings = bindings
      bindings.pets = next.bindings.pets
      bindings.ping = next.bindings.ping
      Object.assign(debug, next.debugOverlay)
      petRecords.value = next.pets
      const instance = world.value
      if (instance) {
        for (const old of previousPets) {
          if (!next.pets.some(record => record.id === old.id)) instance.removePet(old.id)
        }
        for (const record of next.pets) {
          const pet = instance.get(record.id)
          if (pet) {
            pet.updateSettings({
              name: record.name,
              scale: record.scale,
              facing: record.facing,
              radius: record.radius,
              physics: record.physics,
              behavior: record.behavior,
              hitboxes: record.hitboxes,
              actions: record.actions,
              spriteWidth: record.spriteWidth,
              spriteHeight: record.spriteHeight,
              visible: record.visible,
            })
          } else {
            spawnPet(record)
          }
        }
        instance.setQuality(config.quality, config.useL3)
      }
      void bridge.setZMode(config.zMode).catch(error => report('config-reload', error))
      void bridge.setPingHotkey(config.ping.hotkey).catch(error => report('config-reload', error))
      pingDirty = false
    } catch (error) {
      report('config-reload', error)
    }
  }

  // -------------------------------------------------------------------------
  // 启动
  // -------------------------------------------------------------------------

  // user:“启动、退出、隐藏、恢复、休眠/暂停及异常重启路径完整”+(pet-overlay 是
  // 配置窗口，应用一启动它就加载并 boot，而 Python 后端冷启动要好几秒；boot 不能
  // 因为一次 "backend not yet started" 就永久失败卡死，必须等后端就绪再继续。)
  async function waitForApiBase(timeoutMs = 60_000): Promise<string> {
    const deadline = Date.now() + timeoutMs
    for (;;) {
      try {
        return await bridge.apiBase()
      } catch (error) {
        if (Date.now() > deadline) throw error
        await new Promise(resolve => setTimeout(resolve, 500))
      }
    }
  }

  async function boot(): Promise<void> {
    if (booting.value || ready.value) return
    // 先起心跳：整个 boot（读配置、装预设、取窗口）都可能耗时，
    // 期间宿主绝不能把这块窗口当成"没人画"收掉。
    void bridge.overlayHeartbeat()
    if (!heartbeatTimer) {
      heartbeatTimer = window.setInterval(() => {
        void bridge.overlayHeartbeat()
      }, 2000)
    }
    booting.value = true
    try {
      await loadConfig()
      if (!config.enabled) {
        // user:“能独立启用/禁用桌宠模块而不破坏主 UI”+
        // (禁用时不留任何窗口、命中区或快捷键；Ping 在自己的窗口里照常工作)
        await bridge.setInputMode('passthrough')
        await bridge.closeOverlay()
        ready.value = false
        booting.value = false
        return
      }
      const bounds = await bridge.openOverlay()
      Object.assign(overlay, bounds)
      overlayOpen.value = true
      monitors.value = await bridge.listMonitors()
      const created = new PetWorld({
        screen: { x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height },
        quality: config.quality,
        useL3: config.useL3,
        graphRebuildDelayMs: 180,
      })
      world.value = created
      await bridge.setZMode(config.zMode)
      // user:"而且现在又全部穿透了，无法操作"+
      // (页面重载时旧实例的 shutdown() 会把输入模式写成 passthrough，
      //  新实例 boot 必须显式复位成 auto；否则窗口一直整层穿透，气泡和角色
      //  都点不到——这不是矩形没上报，是模式还停在 passthrough。)
      await bridge.setInputMode('auto')

      const base = await waitForApiBase()
      const client = createPetAgentClient(base)
      agentClient.value = client
      const host = new PetAgentHost(client, config.bindings, bindings => {
        config.bindings = bindings
        scheduleSave()
      })
      agents.value = host
      // 配置里缺失的绑定同步进 host（host 用 reactive 共享同一份对象）。
      for (const [petId, binding] of Object.entries(config.bindings.pets || {})) {
        host.bindings.pets[petId] = binding
      }

      restorePets()
      await ensureBlockyPreset()
      void loadProjectNames()
      subscribeNativeEvents()
      await refreshWindows()
      startLoop()
      ready.value = true
      // 外部观测点：标题直接反映运行时是否就绪。
      document.title = 'Sunday Pet · ready'
      // 第一帧真的合成出来之后，才让宿主把全屏覆盖层显示出来。
      window.requestAnimationFrame(() => {
        window.requestAnimationFrame(() => {
          void bridge.overlayReady().catch(error => report('overlayReady', error))
        })
      })
      void refreshL3()
      hostPoller = window.setInterval(pollAgentEvents, 1200)
      void refreshMainFocus()
      if (!mainFocusTimer) mainFocusTimer = window.setInterval(refreshMainFocus, 800)
    } catch (error) {
      report('boot', error)
      document.title = `Sunday Pet · boot failed: ${error instanceof Error ? error.message : String(error)}`
    } finally {
      booting.value = false
    }
  }

  // -------------------------------------------------------------------------
  // 内置方块人预设
  // -------------------------------------------------------------------------

  const BLOCKY_PACK_ID = 'sunday-blocky'
  const BLOCKY_DEFAULT_SKIN = 'skins/default.png'
  // 皮肤/角色包内容变化时 +1：旧安装的 presetInstalled 已经是 true，
  // 只靠它永远不会重写角色包，用户就看不到新内置皮肤。
  // v3：皮肤改为内嵌 base64 解码（v2 的 fetch(data:) 被 CSP 拦截）。
  const BLOCKY_PRESET_VERSION = 3
  const BLOCKY_ACTIONS = ['idle', 'walk', 'jump', 'jump_happy', 'fall', 'climb', 'hang', 'rest', 'dance', 'interact', 'interact_head', 'question']

  function blockyActions(skin: string): AnimationMap {
    const map: AnimationMap = {}
    for (const actionId of BLOCKY_ACTIONS) {
      map[actionId] = { type: 'blocky', skin, model: 'steve' }
    }
    return map
  }

  /**
   * 默认皮肤：优先用随源码入库的用户皮肤（assets/sunday-skin.png），
   * 取不到再回退到程序生成的 Steve 皮肤。
   *
   * user:"默认皮肤改为我的皮肤"+"为什么没有内置我的皮肤？"+
   * (用户皮肤必须随源码入库；core/desktop/public 被 .gitignore 忽略，
   *  依赖它会导致 CI 构建的安装包没有这张图。)
   */
  async function defaultSkinBytes(): Promise<Uint8Array> {
    try {
      const bytes = sundaySkinBytes()
      if (bytes.length > 0) return bytes
    } catch {
      // base64 损坏时继续尝试旧路径/生成皮肤。
    }
    try {
      const response = await fetch(new URL('pet-animlab/user-skin.png', window.location.href))
      if (response.ok) {
        const bytes = new Uint8Array(await response.arrayBuffer())
        if (bytes.length > 0) return bytes
      }
    } catch {
      // 旧开发目录可能不存在，忽略。
    }
    const canvas = createDefaultSkinCanvas('steve')
    const blob = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, 'image/png'))
    if (!blob) throw new Error('内置皮肤生成失败')
    return new Uint8Array(await blob.arrayBuffer())
  }

  function blockyRecord(): PetRecordConfig {
    return {
      id: 'blocky-1',
      name: 'Sunday 方块人',
      packId: BLOCKY_PACK_ID,
      scale: 1,
      facing: 1,
      radius: 26,
      visible: true,
      actions: blockyActions(BLOCKY_DEFAULT_SKIN),
      spriteWidth: 92,
      spriteHeight: 158,
      hitboxes: [
        { id: 'body', name: '身体', x: 0.12, y: 0.1, width: 0.76, height: 0.85, action: 'interact', doubleAction: 'jump_happy', enabled: true },
      ],
      physics: {},
      behavior: {},
      importWarnings: [],
    }
  }

  function blockyManifest(): string {
    return JSON.stringify({
      schema_version: 1,
      name: 'Sunday Blocky',
      hitboxes: [
        { id: 'body', name: '身体', x: 0.12, y: 0.1, width: 0.76, height: 0.85, action: 'interact', doubleAction: 'jump_happy', enabled: true },
      ],
    }, null, 2)
  }

  /** 首次安装：整包写入（此时还没有用户自己的皮肤文件）。 */
  async function installBlockyPack(): Promise<void> {
    await bridge.writePackBundle('Sunday Blocky', [
      { rel: BLOCKY_DEFAULT_SKIN, bytes: await defaultSkinBytes() },
      { rel: 'pet.json', bytes: new TextEncoder().encode(blockyManifest()) },
    ])
  }

  /**
   * 升级内置皮肤：逐文件覆盖，绝不删除整个角色包目录。
   * 用户可能在 sunday-blocky 里换过皮肤（skins/skin-xxx.png），整包重写会把它删掉。
   */
  async function refreshBlockyPack(): Promise<void> {
    await bridge.writePackAsset(BLOCKY_PACK_ID, BLOCKY_DEFAULT_SKIN, await defaultSkinBytes())
    await bridge.writePackAsset(BLOCKY_PACK_ID, 'pet.json', new TextEncoder().encode(blockyManifest()))
  }

  /** 安装内置方块人（写包 + 记录 + 实例）。 */
  async function installBlockyPreset(): Promise<void> {
    await installBlockyPack()
    const record = blockyRecord()
    petRecords.value = [record]
    spawnPet(record)
    config.presetInstalled = true
    config.presetVersion = BLOCKY_PRESET_VERSION
    await saveConfig()
  }

  /**
   * 只刷新内置角色包，不碰用户自己导入的角色/皮肤。
   *
   * 内置记录本来就指向 skins/default.png；覆盖这个文件即可换新皮肤。
   * 不要重写 record.actions：用户导入过自定义皮肤时，actions 指向
   * skins/skin-xxx.png，重写会把他的皮肤选择覆盖掉。
   */
  async function refreshBlockyPreset(): Promise<void> {
    await refreshBlockyPack()
    config.presetVersion = BLOCKY_PRESET_VERSION
    await saveConfig()
  }

  /** 首次启动装一个可直接用的方块人：不需要用户先找素材。 */
  async function ensureBlockyPreset(): Promise<void> {
    // user:"内置默认就是方块人，你搞个屁的ball？"+
    // (旧演示配置里只有一个示例 arc-ball 时，用内置方块人替换它；
    //  示例包不应成为默认角色。用户自己导入的其他角色不动。)
    const onlyExampleBall = petRecords.value.length === 1
      && (petRecords.value[0]?.packId || '') === 'arc-ball'
    const needsPreset = !config.presetInstalled || onlyExampleBall
    const needsSkinRefresh = (config.presetVersion || 0) < BLOCKY_PRESET_VERSION
    if (needsSkinRefresh && config.presetInstalled && !onlyExampleBall) {
      try {
        await refreshBlockyPreset()
      } catch (error) {
        report('preset', error)
      }
    }
    if (!needsPreset) return
    if (petRecords.value.length > 0 && !onlyExampleBall) {
      config.presetInstalled = true
      await saveConfig()
      return
    }
    try {
      if (onlyExampleBall) {
        const example = petRecords.value[0]!
        world.value?.removePet(example.id)
        petRecords.value = []
      }
      await installBlockyPreset()
    } catch (error) {
      report('preset', error)
    }
  }

  /** 换肤：只改皮肤文件，模型、动作、碰撞体、行为全部保留。 */
  async function importSkinFor(petId: string): Promise<void> {
    const record = petRecords.value.find(item => item.id === petId)
    if (!record?.packId) {
      report('skin', new Error('这只桌宠没有角色包目录，无法存放皮肤'))
      return
    }
    try {
      const path = await bridge.pickImportFile()
      if (!path) return
      if (!/\.(png|jpg|jpeg|webp|bmp)$/i.test(path)) {
        throw new Error('皮肤需要 PNG/JPG/WEBP/BMP 图片')
      }
      const bytes = await bridge.readImageFile(path)
      const rel = `skins/skin-${Date.now().toString(36)}.png`
      await bridge.writePackAsset(record.packId, rel, bytes)
      record.actions = blockyActions(rel)
      world.value?.get(petId)?.updateSettings({ actions: record.actions })
      await saveConfig()
    } catch (error) {
      report('skin', error)
    }
  }

  async function resetSkinFor(petId: string): Promise<void> {
    const record = petRecords.value.find(item => item.id === petId)
    if (!record) return
    try {
      // 恢复默认必须把内置皮肤写回角色包，不能只改 actions 指向旧的 default.png。
      if (record.packId === BLOCKY_PACK_ID) {
        await bridge.writePackAsset(BLOCKY_PACK_ID, BLOCKY_DEFAULT_SKIN, await defaultSkinBytes())
      }
      record.actions = blockyActions(BLOCKY_DEFAULT_SKIN)
      world.value?.get(petId)?.updateSettings({ actions: record.actions })
      await saveConfig()
    } catch (error) {
      report('skin', error)
    }
  }

  function restorePets(): void {
    const instance = world.value
    if (!instance) return
    petRecords.value = Array.isArray(config.pets) ? config.pets : []
    for (const record of petRecords.value) {
      spawnPet(record)
    }
  }

  function spawnPet(record: PetRecordConfig): PetInstance | null {
    const instance = world.value
    if (!instance) return null
    if (instance.get(record.id)) return instance.get(record.id) || null
    const x = overlay.x + overlay.width * (0.25 + 0.5 * Math.random())
    const y = overlay.y + overlay.height * 0.35
    const pet = instance.addPet(
      {
        id: record.id,
        name: record.name,
        packId: record.packId || undefined,
        scale: record.scale,
        facing: record.facing,
        radius: record.radius,
        physics: record.physics,
        behavior: record.behavior,
        hitboxes: record.hitboxes,
        actions: record.actions,
        spriteWidth: record.spriteWidth,
        spriteHeight: record.spriteHeight,
        visible: record.visible,
      },
      { x, y },
    )
    void preloadPetAssets(record)
    return pet
  }

  async function preloadPetAssets(record: PetRecordConfig): Promise<void> {
    if (!record.packId) return
    const sources = new Set<string>()
    for (const clip of Object.values(record.actions)) {
      if (!clip || clip.type === 'blocky') continue
      if (clip.type === 'frames') {
        if (Array.isArray(clip.sources)) clip.sources.forEach(source => sources.add(source))
      } else {
        sources.add(clip.source)
      }
    }
    for (const source of sources) {
      void loadSpriteImage(record.packId, source)
    }
  }

  async function loadSpriteImage(packId: string | null, source: string): Promise<HTMLImageElement | null> {
    const key = `${packId || 'inline'}::${source}`
    const existing = images.get(key)
    if (existing) return existing
    if (imageLoading.has(key)) return null
    imageLoading.add(key)
    try {
      const url = packId
        ? await bridge.packAssetUrl(packId, source)
        : await bridge.importAssetUrl(source)
      const image = await new Promise<HTMLImageElement>((resolve, reject) => {
        const element = new Image()
        element.onload = () => resolve(element)
        element.onerror = () => reject(new Error(`图片无法解码：${source}`))
        element.src = url
      })
      images.set(key, image)
      return image
    } catch (error) {
      report('sprite', error)
      return null
    } finally {
      imageLoading.delete(key)
    }
  }

  function subscribeNativeEvents(): void {
    void (async () => {
      const { listen } = await import('@tauri-apps/api/event')
      await listen<{ x: number; y: number; inside: boolean }>('pet://cursor', ({ payload }) => {
        cursor.x = payload.x
        cursor.y = payload.y
        cursor.inside = payload.inside
        // 鼠标点上的实时命中：有内容的元素立即上报矩形，宿主下一轮轮询就放行。
        hitTestCursorPosition()
      })
      // user:“你看看 ping 环 要不也自己做窗口？”+(Ping 在自己的窗口里运行；
      // 它需要桌宠侧配合的两件事走宿主事件：提示气泡、桌宠动作。)
      await listen<{ petId?: string; sessionId: string; title: string; body: string }>(
        'pet://ping/notify',
        ({ payload }) => {
          pushBubble({
            petId: payload.petId || '',
            sessionId: payload.sessionId,
            kind: 'notification',
            title: payload.title,
            body: payload.body,
          })
        },
      )
      await listen<string>('pet://ping/action', ({ payload }) => {
        runPingCustomAction(String(payload || ''))
      })
      // 主界面设置、右键面板、Ping 面板改的是同一份 config.json：收到广播后
      // 重读文件并应用，文件是唯一源。
      await listen('pet://config-changed', () => { void reloadConfigFromDisk() })
      // user:"点击打开桌宠没反应"+(托盘「打开桌宠」的意图是"让我看见它"：
      //  角色被「显隐」藏起来过的，收到这个事件就恢复显示并落盘。)
      await listen('pet://overlay/opened', () => {
        let changed = false
        for (const record of petRecords.value) {
          if (!record.visible) {
            record.visible = true
            changed = true
          }
          const pet = world.value?.get(record.id)
          if (pet && !pet.visible) pet.visible = true
        }
        if (changed) scheduleSave()
      })
    })().catch(error => report('events', error))
  }

  // -------------------------------------------------------------------------
  // 世界刷新
  // -------------------------------------------------------------------------

  async function refreshWindows(): Promise<void> {
    const instance = world.value
    if (!instance) return
    try {
      const fetched = await bridge.desktopWindows().catch(() => [] as never[])
      if (Array.isArray(fetched)) {
        windowsRef.value = fetched.map(item => item.bounds)
        instance.applyWindows(fetched.map(item => ({
          id: item.id,
          title: item.title,
          className: item.className,
          bounds: item.bounds,
          z: item.z,
        })))
      }
    } catch (error) {
      report('windows', error)
    }
  }

  async function refreshL3(): Promise<void> {
    const instance = world.value
    if (!instance || !config.useL3) return
    const started = performance.now()
    try {
      const frame = await bridge.captureMonitorUnderCursor()
      instance.applyL3(
        { width: frame.width, height: frame.height, data: frame.data },
        { x: frame.x, y: frame.y },
        config.quality as TerrainQuality,
        Date.now(),
      )
      lastL3At = Date.now()
      stats.captureMs = performance.now() - started
    } catch (error) {
      report('l3', error)
    }
  }

  function setQuality(quality: TerrainQuality): void {
    config.quality = quality
    world.value?.setQuality(quality, config.useL3)
    void refreshL3()
    scheduleSave()
  }

  /**
   * user:"为什么 L3 默认还是开启？"+(设置面板的 L3 勾选以前只改内存、
   * 没有落盘，重启后又被旧配置的 true 覆盖；这里统一保存并立即应用。)
   */
  function setUseL3(enabled: boolean): void {
    config.useL3 = enabled
    world.value?.setQuality(config.quality, enabled)
    void refreshL3()
    scheduleSave()
  }

  // -------------------------------------------------------------------------
  // 渲染循环
  // -------------------------------------------------------------------------

  /**
   * 只登记画布，不立刻建 WebGL 上下文：
   * 纯 2D 角色不需要为一块空画布付出 GPU 与显存。
   */
  async function attachThreeCanvas(element: HTMLCanvasElement | null): Promise<void> {
    threeCanvas = element
    threeCanvasDirty = true
  }

  /** 调试画布：只画判定框/路径/速度，独立于角色与 3D 层。 */
  function attachDebugCanvas(element: HTMLCanvasElement | null): void {
    debugCanvas = element
  }

  // user:"左下角确实有个诊断，但是我没看见方块人啊"+
  // (3D 画布的绘制缓冲一直是 HTML 默认的 300×150；后来又发现 2D 画布也一样：
  //  attachCanvas 在挂载时用 overlay 的初始默认值 1920×1080 定尺寸，真实边界
  //  到来后无人更新——地形线/碰撞框画在下半屏全被裁掉。两层都按覆盖层真实
  //  物理像素每帧同步，返回是否变化。)
  function syncCanvasSizes(): boolean {
    let changed = false
    const width = Math.max(1, Math.round(overlay.width))
    const height = Math.max(1, Math.round(overlay.height))
    const ratio = window.devicePixelRatio || 1
    const styleWidth = `${Math.round(overlay.width / ratio)}px`
    const styleHeight = `${Math.round(overlay.height / ratio)}px`
    for (const el of [canvas, threeCanvas, debugCanvas]) {
      if (!el) continue
      if (el.width !== width) {
        el.width = width
        changed = true
      }
      if (el.height !== height) {
        el.height = height
        changed = true
      }
      if (el.style.width !== styleWidth) el.style.width = styleWidth
      if (el.style.height !== styleHeight) el.style.height = styleHeight
    }
    return changed
  }

  async function ensureThreeLayer(): Promise<ThreePetLayer | null> {
    if (threeLayer.value) return threeLayer.value
    if (!threeCanvas) return null
    const layer = await createThreePetLayer({
      canvas: threeCanvas,
      overlay: { x: overlay.x, y: overlay.y, width: overlay.width, height: overlay.height },
      loadBytes: (packId, source) => packId
        ? bridge.packAsset(packId, source)
        : bridge.readImportAsset(source),
      onError: (scope, message) => {
        threeState.error = `${scope}: ${message}`
        report(`three:${scope}`, message)
      },
    })
    if (!layer) {
      threeState.enabled = false
      return null
    }
    syncCanvasSizes()
    layer.resize(
      { x: overlay.x, y: overlay.y, width: overlay.width, height: overlay.height },
      threeCanvas.width,
      threeCanvas.height,
    )
    threeLayer.value = layer
    threeState.enabled = true
    return layer
  }

  function attachCanvas(element: HTMLCanvasElement | null): void {
    canvas = element
    if (element) {
      element.width = Math.max(1, Math.round(overlay.width))
      element.height = Math.max(1, Math.round(overlay.height))
      element.style.width = `${overlay.width / (window.devicePixelRatio || 1)}px`
      element.style.height = `${overlay.height / (window.devicePixelRatio || 1)}px`
    }
  }

  function startLoop(): void {
    if (rafHandle) cancelAnimationFrame(rafHandle)
    lastFrameAt = performance.now()
    const frame = (now: number) => {
      rafHandle = requestAnimationFrame(frame)
      const instance = world.value
      if (!instance) return
      const delta = Math.min(64, now - lastFrameAt)
      const minInterval = 1000 / Math.max(10, config.perf.maxFps)
      if (delta < minInterval * 0.85) return
      lastFrameAt = now
      const tickStart = performance.now()
      instance.tick(now, delta, { x: cursor.x, y: cursor.y })
      stats.tickMs = performance.now() - tickStart
      const drawStart = performance.now()
      draw(instance)
      stats.drawMs = performance.now() - drawStart
      // 气泡/UI 依赖这一帧的宠物位置：每帧 +1 让跟随重算。
      frameTick.value += 1
      fpsAccumulator += delta
      fpsFrames += 1
      if (fpsAccumulator >= 500) {
        stats.fps = Math.round((fpsFrames * 1000) / fpsAccumulator)
        fpsAccumulator = 0
        fpsFrames = 0
      }
      reportInteractiveRects(instance)
      if (config.useL3 && Date.now() - lastL3At > config.perf.l3RefreshMs) void refreshL3()
      // 局部遮挡需要跟着窗口移动：1.2 秒一次足够跟手，也不会把桌面枚举跑成负担。
      if (config.zMode === 'clip' && now - lastWindowsAt > 1200) {
        lastWindowsAt = now
        void refreshWindows()
      }
    }
    rafHandle = requestAnimationFrame(frame)
  }

  function draw(instance: PetWorld): void {
    if (!canvas) return
    const context = canvas.getContext('2d')
    if (!context) return
    // user:"F2 画布尺寸跟随真实边界"+(2D 画布与 GL 画布都要每帧同步：
    //  只在 3D 分支里同步的话，纯 2D 角色永远停在挂载时的默认尺寸，
    //  非默认分辨率的屏幕上右侧与下方内容被裁掉。)
    syncCanvasSizes()
    context.setTransform(1, 0, 0, 1, 0, 0)
    context.clearRect(0, 0, canvas.width, canvas.height)
    const offsetX = -overlay.x
    const offsetY = -overlay.y
    if (debug.terrain) {
      context.lineWidth = 2
      for (const segment of instance.terrain.all()) {
        // user:"屏幕中间这根黄线是谁生成的？不是说了吗？l1黄线只由屏幕边界产生"+
        // (黄色只留给 L1 屏幕边界；窗口的竖边/横边是 L2，用蓝色区分，
        //  否则窗口边缘看起来像凭空多出来的 L1 黄线。L3 视觉边缘是绿色。)
        context.strokeStyle = segment.layer === 'L1'
          ? 'rgba(255,213,0,0.95)'
          : segment.layer === 'L2'
            ? 'rgba(80,170,255,0.9)'
            : segment.layer === 'L3'
              ? 'rgba(150,220,160,0.75)'
              : 'rgba(255,120,160,0.9)'
        context.beginPath()
        context.moveTo(segment.x1 + offsetX, segment.y1 + offsetY)
        context.lineTo(segment.x2 + offsetX, segment.y2 + offsetY)
        context.stroke()
      }
    }
    const renderables: RenderablePet[] = []
    for (const state of instance.renderStates()) {
      if (!state.visible) continue
      const pet = instance.get(state.id)
      const x = state.rect.x + offsetX
      const y = state.rect.y + offsetY
      // user:"左下角确实有个诊断，但是我没看见方块人啊"+
      // (3D 渲染列表只认了 GLB 的 'model'，内置方块人的 'blocky' 被漏掉——
      //  方块人从未进入 WebGL 层，3D 层也就永远不启动。两类 3D 角色都要登记。)
      const is3D = state.clip?.type === 'model' || state.clip?.type === 'blocky'
      if (is3D && pet) {
        // 3D 角色由 WebGL 层画；这里只登记，2D 画布不重复画占位。
        renderables.push({
          id: state.id,
          clip: state.clip,
          rect: state.rect,
          facing: state.facing,
          actionId: state.actionId || 'idle',
          elapsedMs: state.elapsedMs,
          visible: state.visible,
          packId: pet.settings.packId || null,
        })
      }
      const image = state.frame && !is3D
        ? images.get(`${pet?.settings.packId || 'inline'}::${state.frame.source}`)
        : undefined
      if (is3D) {
        // 占位不画，避免 3D 角色后面透出一个方块。
      } else if (image && state.frame) {
        context.save()
        if (state.facing < 0) {
          context.translate(x + state.rect.width, y)
          context.scale(-1, 1)
        } else {
          context.translate(x, y)
        }
        context.drawImage(
          image,
          state.frame.sx,
          state.frame.sy,
          state.frame.sw,
          state.frame.sh,
          0,
          0,
          state.rect.width,
          state.rect.height,
        )
        context.restore()
      } else {
        drawPlaceholder(context, x, y, state.rect.width, state.rect.height, state.facing)
      }
    }
    // 调试框单独一层，画在 3D 角色之上：否则判定框的顶边会被 3D 画布盖住，
    // 看起来像"框比角色低"。
    drawDebugOverlay(instance, offsetX, offsetY)

    // 3D 层：有模型动作才启用，尺寸变化时同步画布。
    if (renderables.length > 0 || threeLayer.value) {
      void (async () => {
        const layer = threeLayer.value || await ensureThreeLayer()
        if (!layer) return
        const sizeChanged = syncCanvasSizes()
        if ((threeCanvasDirty || sizeChanged) && threeCanvas) {
          threeCanvasDirty = false
          layer.resize(
            { x: overlay.x, y: overlay.y, width: overlay.width, height: overlay.height },
            threeCanvas.width,
            threeCanvas.height,
          )
        }
        layer.update(renderables, Math.min(64, performance.now() - lastFrameAt + 16))
        layer.render()
        const stats = layer.diagnostics()
        threeState.models = stats.models
        threeState.slots = stats.slots
        threeState.error = stats.lastError
      })()
    }
  }

  /**
   * 调试层：判定框 / 交互 Hitbox / 路径 / 速度。
   *
   * user:"碰撞箱不对，比实际偏高"+
   * (调试框必须画在 3D 角色之上，且与点击/穿透使用同一份矩形：
   *  AABB 用引擎的 renderRect，Hitbox 用精灵框归一化，朝向镜像一致。)
   */
  let debugWasVisible = false
  function drawDebugOverlay(instance: PetWorld, offsetX: number, offsetY: number): void {
    const element = debugCanvas
    if (!element) return
    const active = debug.colliders || debug.path || debug.velocity
    // 调试关着时不做任何事；关掉后的第一帧清一次，避免残留。
    if (!active && !debugWasVisible) return
    const context = element.getContext('2d')
    if (!context) return
    context.setTransform(1, 0, 0, 1, 0, 0)
    context.clearRect(0, 0, element.width, element.height)
    if (!active) {
      debugWasVisible = false
      return
    }
    debugWasVisible = true
    for (const state of instance.renderStates()) {
      if (!state.visible) continue
      const pet = instance.get(state.id)
      if (!pet) continue
      if (debug.colliders) {
        context.strokeStyle = 'rgba(90,220,255,0.9)'
        context.lineWidth = 2
        // user:"包括寻路，边，判定框全部都与泰拉瑞亚一致"+
        // (判定框 = 瓦片尺寸的 AABB 矩形，不再是圆。)
        const box = pet.renderRect()
        context.strokeRect(box.x + offsetX, box.y + offsetY, box.width, box.height)
        context.strokeStyle = 'rgba(255,120,200,0.9)'
        for (const hitbox of state.hitboxes) {
          if (!hitbox.enabled) continue
          // 与点击/穿透共用同一个世界矩形函数：画出来的框就是能点到的框。
          const rect = hitboxWorldRect(hitbox, state.rect, state.facing)
          context.strokeRect(rect.x + offsetX, rect.y + offsetY, rect.width, rect.height)
        }
      }
      if (debug.path) {
        const path = pet.plannedTilePath
        if (path.length > 0) {
          context.strokeStyle = 'rgba(120,255,190,0.85)'
          context.lineWidth = 2
          context.setLineDash([6, 6])
          context.beginPath()
          context.moveTo(pet.position.x + offsetX, pet.position.y + offsetY)
          for (const cell of path) {
            const wp = instance.tileGrid.standPoint(cell.col, cell.row)
            context.lineTo(wp.x + offsetX, wp.y + offsetY)
          }
          context.stroke()
          context.setLineDash([])
        }
      }
      if (debug.velocity) {
        context.strokeStyle = 'rgba(255,224,120,0.95)'
        context.lineWidth = 2
        context.beginPath()
        context.moveTo(pet.position.x + offsetX, pet.position.y + offsetY)
        context.lineTo(
          pet.position.x + offsetX + pet.body.vx * 0.06,
          pet.position.y + offsetY + pet.body.vy * 0.06,
        )
        context.stroke()
      }
    }
  }

  function drawPlaceholder(context: CanvasRenderingContext2D, x: number, y: number, width: number, height: number, facing: number): void {
    const key = `${Math.round(width)}x${Math.round(height)}`
    let sprite = SPRITE_FALLBACK.get(key)
    if (!sprite) {
      sprite = document.createElement('canvas')
      sprite.width = Math.max(8, Math.round(width))
      sprite.height = Math.max(8, Math.round(height))
      const ctx = sprite.getContext('2d')
      if (ctx) {
        ctx.fillStyle = 'rgba(126,180,255,0.28)'
        ctx.strokeStyle = 'rgba(126,180,255,0.75)'
        ctx.lineWidth = 2
        ctx.beginPath()
        ctx.roundRect(1, 1, sprite.width - 2, sprite.height - 2, 10)
        ctx.fill()
        ctx.stroke()
        ctx.fillStyle = 'rgba(210,232,255,0.9)'
        ctx.font = `${Math.round(sprite.height * 0.32)}px sans-serif`
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        ctx.fillText('?', sprite.width / 2, sprite.height / 2)
      }
      SPRITE_FALLBACK.set(key, sprite)
    }
    context.save()
    if (facing < 0) {
      context.translate(x + width, y)
      context.scale(-1, 1)
      context.drawImage(sprite, 0, 0)
    } else {
      context.drawImage(sprite, x, y)
    }
    context.restore()
  }

  /** 角色矩形 + 气泡/卡片/轮盘 → Rust 命中区，只在该变时上报。 */
  // user:"其实应该是除了透明部分都不应该穿过"+
  // (穿透判定改成"有内容就接住"：所有标注 data-pet-hit 的可见元素每帧实测矩形
  //  上报；鼠标所在点再用 elementFromPoint 兜底命中一次——没登记过的 UI 只要画
  //  出来了也能接住。透明骨架元素不打标记，底下桌面照常穿透。)
  let pointHitRect: number[] | null = null

  function pushDomInteractiveRects(rects: number[][]): void {
    const ratio = window.devicePixelRatio || 1
    for (const el of document.querySelectorAll('[data-pet-hit]')) {
      const box = el.getBoundingClientRect()
      if (box.width < 4 || box.height < 4) continue
      rects.push([
        Math.round(overlay.x + box.left * ratio),
        Math.round(overlay.y + box.top * ratio),
        Math.round(box.width * ratio),
        Math.round(box.height * ratio),
      ])
    }
    if (pointHitRect) rects.push(pointHitRect)
  }

  function hitTestCursorPosition(): void {
    const ratio = window.devicePixelRatio || 1
    const cssX = (cursor.x - overlay.x) / ratio
    const cssY = (cursor.y - overlay.y) / ratio
    pointHitRect = null
    if (cssX < 0 || cssY < 0 || cssX > window.innerWidth || cssY > window.innerHeight) return
    const hit = document.elementFromPoint(cssX, cssY)
    const content = hit?.closest('[data-pet-hit]') as HTMLElement | null
    if (!content) return
    const box = content.getBoundingClientRect()
    if (box.width < 4 || box.height < 4) return
    pointHitRect = [
      Math.round(overlay.x + box.left * ratio),
      Math.round(overlay.y + box.top * ratio),
      Math.round(box.width * ratio),
      Math.round(box.height * ratio),
    ]
  }

  function reportInteractiveRects(instance: PetWorld): void {
    const rects: number[][] = []
    // user:"碰撞箱不对，比实际偏高"+
    // (穿透矩形 = 交互 Hitbox（画出来的粉色框），不再上报整个精灵框：
    //  透明边距不该吃掉鼠标，画出来的框也必须就是能点到的框。)
    for (const rect of instance.interactionRects()) {
      rects.push([rect.x, rect.y, rect.width, rect.height])
    }
    // 轮盘的命中矩形在 Ping 自己的覆盖层窗口里上报（与桌宠窗口互不影响）。
    pushDomInteractiveRects(rects)
    // user:"而且现在又全部穿透了，无法操作"+
    // (矩形只在变化时上报，一旦宿主侧因 capture 超时/窗口重开清空了命中区，
    //  页面这边 key 没变就永远不会补发，窗口会一直整层穿透。至少每秒重发一次，
    //  让命中区自愈；同一矩形只保留一份。)
    const unique = [...new Map(rects.map(rect => [rect.map(value => Math.round(value)).join(','), rect])).values()]
    const key = unique.map(rect => rect.map(value => Math.round(value)).join(',')).join('|')
    const now = performance.now()
    if (key === lastReportedRects && now - lastRectsReportedAt < 1000) return
    lastReportedRects = key
    lastRectsReportedAt = now
    void bridge.setInteractiveRects(unique).catch(error => report('rects', error))
  }


  // -------------------------------------------------------------------------
  // 气泡
  // -------------------------------------------------------------------------

  function pushBubble(input: {
    petId: string
    sessionId: string
    kind: BubbleState['kind']
    title: string
    subject?: string
    body: string
    source?: string
    requestId?: string | null
    isQuestion?: boolean
    options?: BubbleState['options']
  }): void {
    const id = `${input.sessionId}:${input.requestId || input.title}`
    if (bubbles.value.some(item => item.id === id)) return
    bubbles.value = [
      ...bubbles.value,
      {
        id,
        petId: input.petId,
        sessionId: input.sessionId,
        kind: input.kind,
        title: input.title,
        subject: input.subject || input.title,
        body: input.body,
        source: input.source || '',
        requestId: input.requestId || null,
        isQuestion: Boolean(input.isQuestion),
        options: input.options || [],
        createdAt: Date.now(),
        expanded: input.kind === 'actionable',
        dismissed: false,
        handling: false,
        error: '',
      },
    ].slice(-8)
    // user:"默认只展开一个"+(新审批/提问到达时，旧的展开气泡收起；
    //  否则一次注入多条请求会全部展开、互相把对方顶出屏幕。)
    const expanded = bubbles.value.filter(item => item.expanded && !item.dismissed)
    for (const item of expanded.slice(0, Math.max(0, expanded.length - config.bubbles.maxExpanded))) {
      item.expanded = false
    }
  }

  function dismissBubble(id: string): void {
    const bubble = bubbles.value.find(item => item.id === id)
    if (!bubble) return
    // 关闭不等于拒绝：只折叠，待处理数量继续保留。
    bubble.dismissed = true
    bubble.expanded = false
  }

  function toggleBubble(id: string): void {
    const bubble = bubbles.value.find(item => item.id === id)
    if (!bubble) return
    bubble.dismissed = false
    bubble.expanded = !bubble.expanded
    const expanded = bubbles.value.filter(item => item.expanded && !item.dismissed)
    if (expanded.length > config.bubbles.maxExpanded) {
      for (const item of expanded.slice(0, expanded.length - config.bubbles.maxExpanded)) {
        item.expanded = false
      }
    }
  }

  async function answerBubble(id: string, text: string): Promise<void> {
    const bubble = bubbles.value.find(item => item.id === id)
    if (!bubble) return
    bubble.handling = true
    bubble.error = ''
    try {
      const host = agents.value
      if (!host) throw new Error('Agent 连接还没准备好')
      const channel = host.get(bubble.sessionId) || host.channel(null, bubble.sessionId)
      if (bubble.requestId) {
        // 审批/提问：精确回到原请求。
        const decision = bubble.isQuestion ? 'other_guidance' : 'approve'
        await channel.respondApproval(bubble.requestId, decision, text)
      } else {
        await channel.send(text)
      }
      bubble.dismissed = true
      bubble.expanded = false
    } catch (error) {
      bubble.error = error instanceof Error ? error.message : String(error)
    } finally {
      bubble.handling = false
    }
  }

  async function decideBubble(id: string, option: { id: string; label: string; response?: string }): Promise<void> {
    const bubble = bubbles.value.find(item => item.id === id)
    if (!bubble || !bubble.requestId) return
    bubble.handling = true
    bubble.error = ''
    try {
      const host = agents.value
      const channel = host?.get(bubble.sessionId)
      if (!channel) throw new Error('会话通道已关闭')
      const raw = String(option.id || option.label || '').toLowerCase()
      const decision = raw.includes('deny') || raw.includes('decline') || raw.includes('cancel')
        ? 'deny'
        : raw.includes('approve') || raw.includes('allow') || raw.includes('accept')
          ? 'approve'
          : bubble.isQuestion
            ? 'other_guidance'
            : 'approve'
      await channel.respondApproval(bubble.requestId, decision, option.response || option.label || '')
      bubble.dismissed = true
      bubble.expanded = false
    } catch (error) {
      bubble.error = error instanceof Error ? error.message : String(error)
    } finally {
      bubble.handling = false
    }
  }

  /**
   * 主窗口是否聚焦。
   *
   * user:"主窗口聚焦时不显示气泡"+(用户在 Sunday 主界面里工作时，桌宠不再重复
   * 弹审批/提问气泡；主窗口失焦后下一轮轮询自动恢复显示。)
   */
  async function refreshMainFocus(): Promise<void> {
    try {
      mainFocused.value = await bridge.mainWindowFocused()
    } catch {
      // 查询失败保持上一次状态，不影响其他功能。
    }
  }

  /** 轮询桌宠通道的提问/审批与回复，转为气泡。 */
  function pollAgentEvents(): void {    const host = agents.value
    if (!host) return
    for (const record of petRecords.value) {
      const binding = host.bindings.pets[record.id]
      const sessionId = binding?.temporarySessionId || binding?.sessionId
      if (!sessionId) continue
      // user:"看看桌宠能不能正常转发"+
      // (只读 host.get 的通道永远不存在：桌宠只有点过气泡/发过消息才建通道，
      //  绑定了会话却从不打开，审批和提问就永远到不了桌面。绑定了就必须
      //  主动打开通道，打开是幂等的；快照还没到时下一轮轮询再取。)
      const channel = host.get(sessionId)
        || host.channel(binding?.temporaryProjectId || binding?.projectId || null, sessionId)
      if (!channel.ready) continue
      const decisions = channel.decisions().value
      for (const decision of decisions) {
        const policy = decision.isQuestion ? config.bubbles.question : config.bubbles.approval
        const title = decision.title || (decision.isQuestion ? 'Agent 在等你回答' : '需要你的批准')
        const subject = (decision.subject || title.replace(/^需要确认[：:]\s*/, ''))
          // user:"“”主 Agent 提问：“”给删掉"+(来源已经在左上角，正文不再重复
          //  “主 Agent 提问：/子代理 X 请求授权：”这类归属前缀。)
          .replace(/^(主\s*Agent|子代理\s*[^：:]{1,40})\s*(提问|请求授权|审批)[：:]\s*/i, '')
        const body = decision.detail || ''
        const options = decision.options.map(option => ({ id: option.id, label: option.label, response: option.response }))
        // user:"左上角显示来源：项目-会话-子代理"+
        // (来源行是面包屑：项目名 - 会话名 - 子代理名；拿不到名称就退回 id。
        //  主 Agent 的请求没有第三段。)
        const projectId = decision.projectId || binding?.temporaryProjectId || binding?.projectId || ''
        const sessionTitle = (channel.snapshot as { session?: { title?: string } } | null)?.session?.title || sessionId
        const source = [
          projectNames.value[projectId] || projectId,
          sessionTitle,
          decision.subAgentName ? `子代理 ${decision.subAgentName}` : '',
        ].filter(Boolean).join(' - ')
        // 同一 requestId 先以消息树兜底出现、随后决策池补上更完整的标题/选项时，
        // 必须原地更新，否则永远停在兜底的“需要确认：approval”。
        const existing = bubbles.value.find(
          item => item.sessionId === sessionId && item.requestId === decision.requestId,
        )
        if (existing) {
          existing.title = title
          existing.subject = subject
          existing.body = body
          existing.source = source
          existing.isQuestion = decision.isQuestion
          existing.options = options
        } else {
          pushBubble({
            petId: record.id,
            sessionId,
            kind: 'actionable',
            title,
            subject,
            body,
            requestId: decision.requestId,
            isQuestion: decision.isQuestion,
            source,
            options,
          })
        }
        if (policy === 'silent') {
          const bubble = bubbles.value.find(item => item.requestId === decision.requestId)
          if (bubble) bubble.expanded = false
        }
      }
    }
  }

  // -------------------------------------------------------------------------
  // 交互
  // -------------------------------------------------------------------------

  function hitPet(x: number, y: number) {
    return world.value?.hitTest({ x, y }) || null
  }

  function petDragStart(petId: string, point: { x: number; y: number }): void {
    const pet = world.value?.get(petId)
    if (!pet) return
    pet.startDrag(point)
    void bridge.setInputMode('capture')
  }

  function petDragMove(petId: string, point: { x: number; y: number }): void {
    world.value?.get(petId)?.updateDrag(point)
  }

  function petDragEnd(petId: string): void {
    world.value?.get(petId)?.endDrag()
    void bridge.setInputMode('auto')
  }

  function clickPet(petId: string, localX: number, localY: number, double = false): string {
    const pet = world.value?.get(petId)
    if (!pet) return ''
    const hitbox = double ? pet.doubleClickAt(localX, localY) : pet.clickAt(localX, localY)
    return hitbox?.action || ''
  }

  function setPetDestination(petId: string, point: { x: number; y: number }): void {
    const instance = world.value
    const pet = instance?.get(petId)
    if (!instance || !pet) return
    pet.setDestination(point, { tiles: instance.tileGrid, now: Date.now() })
  }

  function playAction(petId: string, actionId: string): string {
    const pet = world.value?.get(petId)
    return pet?.playAction(actionId) || ''
  }

  // -------------------------------------------------------------------------
  // 会话选择（桌宠绑定；Ping 目标选择器在 Ping 自己的窗口里）
  // -------------------------------------------------------------------------

  const sessionPicker = reactive({
    open: false,
    mode: 'pet' as 'ping' | 'pet',
    petId: '',
    projects: [] as { id: string; name: string }[],
    sessions: [] as { id: string; title: string }[],
    projectId: '',
    loading: false,
    error: '',
  })

  function openSessionPicker(mode: 'ping' | 'pet' = 'pet', petId = ''): void {
    sessionPicker.open = true
    sessionPicker.mode = mode
    sessionPicker.petId = petId
    sessionPicker.error = ''
    void loadProjects()
  }

  async function loadProjects(): Promise<void> {
    const client = agentClient.value
    if (!client) return
    sessionPicker.loading = true
    try {
      sessionPicker.projects = await client.listProjects()
      rememberProjectNames(sessionPicker.projects)
      // Ping 目标选择器（petId 为空）预选 Ping 当前目标，桌宠选择器预选该桌宠绑定。
      const current = sessionPicker.mode === 'ping'
        ? agents.value?.bindings.ping.projectId
        : agents.value?.bindings.pets[sessionPicker.petId]?.projectId
      sessionPicker.projectId = current || sessionPicker.projects[0]?.id || ''
      if (sessionPicker.projectId) await loadSessions(sessionPicker.projectId)
    } catch (error) {
      sessionPicker.error = error instanceof Error ? error.message : String(error)
    } finally {
      sessionPicker.loading = false
    }
  }

  function rememberProjectNames(projects: Array<{ id: string; name: string }>): void {
    const next = { ...projectNames.value }
    for (const project of projects) {
      if (project.id) next[project.id] = project.name || project.id
    }
    projectNames.value = next
  }

  /** 启动时解析一次项目名：气泡来源行需要“项目 - 会话 - 子代理”，不能显示裸 id。 */
  async function loadProjectNames(): Promise<void> {
    const client = agentClient.value
    if (!client) return
    try {
      rememberProjectNames(await client.listProjects())
    } catch {
      // 名称只是展示信息；失败时来源行退回项目 id。
    }
  }

  async function loadSessions(projectId: string): Promise<void> {
    const client = agentClient.value
    if (!client) return
    sessionPicker.loading = true
    sessionPicker.projectId = projectId
    try {
      sessionPicker.sessions = await client.listSessions(projectId)
    } catch (error) {
      sessionPicker.error = error instanceof Error ? error.message : String(error)
    } finally {
      sessionPicker.loading = false
    }
  }

  async function chooseSession(sessionId: string): Promise<void> {
    const projectId = sessionPicker.projectId
    const host = agents.value
    if (!host || !projectId || !sessionId) return
    if (sessionPicker.mode === 'ping') {
      // Ping 选择器（从设置面板打开）改的是独立 Ping 目标，不能写成空 petId 的桌宠绑定。
      host.setPingTarget(projectId, sessionId)
      config.ping.target = { projectId, sessionId }
      pingBindingDirty = true
    } else {
      if (!sessionPicker.petId) return
      // 绑定只存 bindings.pets 一处；桌宠记录里不再保留第二份副本。
      host.setPetDefault(sessionPicker.petId, projectId, sessionId)
    }
    scheduleSave()
    sessionPicker.open = false
  }

  /**
   * Ping 窗口发来的桌宠动作（轮盘自定义扇区/设置入口）。
   *
   * user:“你看看 ping 环 要不也自己做窗口？”+(Ping 独立后，桌面动作仍由桌宠
   * 窗口执行；通过宿主事件转交，桌宠没开时静默忽略。)
   */
  function runPingCustomAction(action: string): void {
    switch (action) {
      case 'settings': ui.settingsOpen = true; break
      case 'importer': startImportFromFolder(); break
      case 'toggle-pets':
        for (const record of petRecords.value) togglePetVisible(record.id)
        break
      case 'refresh-terrain': void refreshL3(); break
      case 'toggle-terrain-lines': debug.terrain = !debug.terrain; break
      case 'hide-overlay': void shutdown(); break
      default:
        report('ping:action', `未知的 Ping 动作：${action}`)
    }
  }

  // -------------------------------------------------------------------------
  // 角色导入
  // -------------------------------------------------------------------------

  const importer = reactive({
    open: false,
    scanning: false,
    error: '',
    analysis: null as ImportAnalysis | null,
    scan: null as ImportScanResult | null,
    spriteWidth: 128,
    spriteHeight: 160,
    scale: 1,
    actionMapping: [] as { actionId: string; source: string }[],
    /** ZIP 导入时保留条目，确认安装时一次性写盘。 */
    zipEntries: null as { rel: string; bytes: Uint8Array }[] | null,
    sourceKind: 'folder' as 'folder' | 'zip',
  })

  async function startImportFromFolder(): Promise<void> {
    importer.error = ''
    try {
      const path = await bridge.pickImportFolder()
      if (!path) return
      await analyzePath(path)
    } catch (error) {
      importer.error = error instanceof Error ? error.message : String(error)
    }
  }

  async function startImportFromFile(): Promise<void> {
    importer.error = ''
    try {
      const path = await bridge.pickImportFile()
      if (!path) return
      if (/\.(sundaypet|zip)$/i.test(path)) {
        await analyzeZip(path)
        return
      }
      await analyzePath(path)
    } catch (error) {
      importer.error = error instanceof Error ? error.message : String(error)
    }
  }

  /** `.sundaypet` / ZIP：内存解包 + 同一套校验 → 直接进预览器。 */
  async function analyzeZip(path: string): Promise<void> {
    importer.scanning = true
    importer.error = ''
    try {
      const bytes = await bridge.readZipFile(path)
      const unpacked = readSundayPetZip(bytes)
      if (unpacked.errors.length > 0) {
        importer.error = unpacked.errors.join('；')
        if (unpacked.entries.length === 0) return
      }
      bridge.setZipImportSource(unpacked.map)
      importer.zipEntries = unpacked.entries
      importer.sourceKind = 'zip'
      const scan: ImportScanResult = {
        root: path,
        files: unpacked.entries.map(entry => ({
          rel: entry.rel,
          size: entry.bytes.byteLength,
          ext: (entry.rel.split('.').pop() || '').toLowerCase(),
        })),
        totalBytes: unpacked.totalBytes,
      }
      const manifestEntry = unpacked.map.get('pet.json')
        || [...unpacked.map.entries()].find(([rel]) => /(^|\/)pet\.json$/i.test(rel))?.[1]
      const manifestText = manifestEntry ? new TextDecoder().decode(manifestEntry) : null
      const parsedName = manifestText ? (safeParse(manifestText) as { name?: string } | null)?.name : undefined
      const analysis = analyzeImport(scan, manifestText, packNameFrom(path, parsedName))
      analysis.warnings.unshift(...unpacked.warnings)
      await applyAnalysis(scan, analysis)
    } finally {
      importer.scanning = false
    }
  }

  async function analyzePath(path: string): Promise<void> {
    importer.scanning = true
    importer.error = ''
    try {
      // 从文件夹导入时清掉上一轮的 ZIP 内存源，避免读到别人的字节。
      bridge.setZipImportSource(null)
      importer.zipEntries = null
      importer.sourceKind = 'folder'
      const scan = await bridge.scanImport(path)
      const manifestText = await readManifestIfPresent(scan)
      const analysis = analyzeImport(scan, manifestText)
      await applyAnalysis(scan, analysis)
    } finally {
      importer.scanning = false
    }
  }

  /** 文件夹与 ZIP 共用：落状态、预读预览图尺寸、打开预览器。 */
  async function applyAnalysis(scan: ImportScanResult, analysis: ImportAnalysis): Promise<void> {
    importer.scan = scan
    importer.analysis = analysis
    importer.actionMapping = Object.entries(analysis.actions)
      .map(([actionId, clip]) => ({ actionId, source: clipPrimarySource(clip) }))
      .filter(item => item.source)
    const preview = analysis.previewSource
    const isModelPreview = preview ? /\.(glb|gltf)$/i.test(preview) : false
    if (preview && !isModelPreview) {
      try {
        const url = await bridge.importAssetUrl(preview)
        const size = await bridge.loadImageSize(url)
        importer.spriteWidth = size.width
        importer.spriteHeight = size.height
      } catch (error) {
        report('preview-size', error)
      }
    }
    importer.open = true
  }

  async function readManifestIfPresent(scan: ImportScanResult): Promise<string | null> {
    const manifest = scan.files.find(file => /(^|\/)pet\.json$/i.test(file.rel))
    if (!manifest) return null
    const bytes = await bridge.readImportAsset(manifest.rel)
    return new TextDecoder().decode(bytes)
  }

  /** 预览器确认后才落盘安装并创建实例。 */
  async function confirmImport(options: { hitboxes?: PetHitbox[] } = {}): Promise<string> {
    const analysis = importer.analysis
    if (!analysis) throw new Error('还没有解析结果')
    if (!analysis.ok) throw new Error(analysis.errors.join('；'))
    const packName = analysis.name || 'pet'
    // ZIP 与文件夹走两条落盘路径，但校验规则、失败语义一致。
    const pack = importer.sourceKind === 'zip' && importer.zipEntries
      ? await bridge.writePackBundle(packName, importer.zipEntries)
      : await bridge.installPack(packName)
    const id = `${pack.id}-${Date.now().toString(36)}`
    const record: PetRecordConfig = {
      id,
      name: analysis.name,
      packId: pack.id,
      scale: importer.scale,
      facing: 1,
      radius: Math.max(10, Math.round(Math.min(importer.spriteWidth, importer.spriteHeight) * 0.38)),
      visible: true,
      actions: analysis.actions,
      spriteWidth: importer.spriteWidth,
      spriteHeight: importer.spriteHeight,
      hitboxes: options.hitboxes && options.hitboxes.length > 0
        ? options.hitboxes
        : analysis.manifest.hitboxes && analysis.manifest.hitboxes.length > 0
          ? analysis.manifest.hitboxes
          : [{ id: 'body', name: '身体', x: 0.08, y: 0.06, width: 0.84, height: 0.88, action: 'interact', doubleAction: 'jump_happy', enabled: true }],
      physics: (analysis.manifest.physics || {}) as Record<string, number>,
      behavior: {},
      importWarnings: [...analysis.warnings, ...analysis.unsupported],
    }
    petRecords.value = [...petRecords.value, record]
    spawnPet(record)
    await saveConfig()
    importer.open = false
    importer.analysis = null
    importer.zipEntries = null
    bridge.setZipImportSource(null)
    return id
  }

  function cancelImport(): void {
    importer.open = false
    importer.analysis = null
    importer.scan = null
    importer.zipEntries = null
    importer.error = ''
    bridge.setZipImportSource(null)
  }

  function removePet(petId: string): void {
    world.value?.removePet(petId)
    petRecords.value = petRecords.value.filter(record => record.id !== petId)
    bubbles.value = bubbles.value.filter(bubble => bubble.petId !== petId)
    scheduleSave()
  }

  function togglePetVisible(petId: string): void {
    const pet = world.value?.get(petId)
    if (!pet) return
    pet.visible = !pet.visible
    const record = petRecords.value.find(item => item.id === petId)
    if (record) record.visible = pet.visible
    scheduleSave()
  }

  // -------------------------------------------------------------------------
  // 退出
  // -------------------------------------------------------------------------

  async function shutdown(): Promise<void> {
    if (rafHandle) cancelAnimationFrame(rafHandle)
    rafHandle = 0
    if (hostPoller) clearInterval(hostPoller)
    if (mainFocusTimer) clearInterval(mainFocusTimer)
    mainFocusTimer = 0
    if (heartbeatTimer) clearInterval(heartbeatTimer)
    heartbeatTimer = 0
    hostPoller = 0
    await saveConfig()
    await bridge.setInputMode('passthrough')
    await bridge.closeOverlay()
    // Ping 有自己的覆盖层和卡片窗口，不随桌宠关闭（拆分解耦）。
    agents.value?.close()
    overlayOpen.value = false
    ready.value = false
  }

  const worldStats = computed(() => world.value?.stats() || {
    pets: 0,
    terrainSegments: 0,
    tileCols: 0,
    tileRows: 0,
    tileSolid: 0,
    tilePlatform: 0,
    tileLadder: 0,
    lastTileBuildMs: 0,
    lastTileBuildAt: 0,
    geometryVersion: 0,
  })

  const pendingBubbleCount = computed(() => bubbles.value.filter(bubble => !bubble.dismissed && bubble.kind === 'actionable').length)

  // user:"存在这些的时候桌宠不要动，保持待机"+
  // (审批/提问卡片存在期间，对应桌宠停止自主行为与寻路；卡片全部处理完再恢复。)
  watch(bubbles, () => {
    const instance = world.value
    if (!instance) return
    const held = new Set(
      bubbles.value
        .filter(bubble => !bubble.dismissed && bubble.kind === 'actionable')
        .map(bubble => bubble.petId),
    )
    for (const pet of instance.pets) pet.setAttentionHold(held.has(pet.id))
  }, { deep: true })

  return {
    config,
    world,
    overlay,
    monitors,
    windows: windowsRef,
    cursor,
    errors,
    ready,
    booting,
    overlayOpen,
    configWarnings,
    configMigratedFrom,
    petRecords,
    agents,
    agentClient,
    // Ping 的运行时/窗口/卡片都在独立的 PingSurface 里；桌宠只保留气泡与设置。
    bubbles,
    pendingBubbleCount,
    ui,
    debug,
    mainFocused,
    frameTick,
    stats,
    worldStats,
    importer,
    sessionPicker,
    boot,
    shutdown,
    saveConfig,
    scheduleSave,
    schedulePingSave,
    attachCanvas,
    attachThreeCanvas,
    attachDebugCanvas,
    threeState,
    attachThreeLayerForTest: ensureThreeLayer,
    refreshWindows,
    refreshL3,
    setQuality,
    setUseL3,
    pushBubble,
    dismissBubble,
    toggleBubble,
    answerBubble,
    decideBubble,
    hitPet,
    petDragStart,
    petDragMove,
    petDragEnd,
    clickPet,
    setPetDestination,
    playAction,
    openSessionPicker,
    loadProjects,
    loadSessions,
    chooseSession,
    startImportFromFolder,
    startImportFromFile,
    confirmImport,
    cancelImport,
    removePet,
    togglePetVisible,
    importSkinFor,
    resetSkinFor,
    ensureBlockyPreset,
    loadSpriteImage,
    QUALITY_PRESETS,
  }
}

export type PetRuntime = ReturnType<typeof usePetRuntime>

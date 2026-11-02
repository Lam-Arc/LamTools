/**
 * Three.js 渲染层：GLB/glTF 角色的真实加载与动画播放。
 *
 * user:“补齐 GLB/glTF 角色渲染与动画播放”+“角色的世界位置和速度由现有物理系统控制，
 * 渲染器只负责正确表现角色和动画”+
 * (一个透明 WebGL 画布铺在覆盖层上，每只 3D 宠物用自己的矩形做视口与裁剪，
 *  位置永远来自引擎的 renderState，这一层不参与任何物理。)
 */
// 只取类型：运行时仍走动态 import，2D 角色不背 three 的体积。
import type { AnimationAction, AnimationClip, AnimationMixer, Object3D, Scene } from 'three'
import type { RenderablePet } from './types.ts'
import { blockyPose } from './blocky.ts'
import { createBlockyRig, type BlockyRig } from './blockyRig.ts'
import { createDefaultSkinCanvas, skinCanvasFromBytes } from './blockySkin.ts'
import { cameraHalfWidth, modelTargetBox, selectAnimationClip, toViewport } from './types.ts'

export interface ModelRequest {
  packId: string | null
  source: string
}

export interface ModelLoadResult {
  ok: boolean
  animations: string[]
  triangles: number
  error?: string
}

export interface ThreePetLayer {
  readonly available: boolean
  /** 预加载一个模型；重复调用会复用缓存。 */
  loadModel(request: ModelRequest): Promise<ModelLoadResult>
  /** 标记某只宠物使用哪个模型；由 update 每帧传入也可以，这里给显式入口。 */
  bindPet(petId: string, request: ModelRequest | null): void
  update(pets: RenderablePet[], deltaMs: number): void
  render(): void
  resize(overlay: { x: number; y: number; width: number; height: number }, width: number, height: number): void
  diagnostics(): {
    available: boolean
    models: number
    slots: number
    blocky: number
    skins: number
    lastError: string
    lastClip: Record<string, string>
  }
  dispose(): void
}

interface LoadedModel {
  scene: Object3D
  animations: AnimationClip[]
  clipNames: string[]
  /** 归一化用：原始包围盒。 */
  box: { height: number; centerX: number; minY: number }
  triangles: number
}

interface PetSlot {
  kind: 'model' | 'blocky'
  root: Scene
  pivot: Object3D
  mixer: AnimationMixer | null
  actions: Map<string, AnimationAction>
  currentAction: string
  clipNames: string[]
  lastError: string
  facing: 1 | -1
  /** 模型缓存键或皮肤缓存键。 */
  modelKey: string
  rig?: BlockyRig
}

const MODEL_CACHE_LIMIT = 8

export interface ThreeLayerDeps {
  canvas: HTMLCanvasElement
  overlay: { x: number; y: number; width: number; height: number }
  /** 读取角色包里的模型字节；由调用方注入，渲染层不碰文件系统。 */
  loadBytes(packId: string | null, source: string): Promise<Uint8Array>
  onError?: (scope: string, message: string) => void
}

/**
 * 惰性创建：只有真的存在 3D 动作时才 import three。
 * WebGL 不可用、驱动异常、模型损坏都只让这一层失效，引擎与 2D 角色继续跑。
 */
export async function createThreePetLayer(deps: ThreeLayerDeps): Promise<ThreePetLayer | null> {
  let THREE: typeof import('three')
  let GLTFLoaderCtor: new () => {
    parseAsync(data: ArrayBuffer, path: string): Promise<{ scene: unknown; animations: unknown[]; userData: Record<string, unknown> }>
    register(callback: (parser: unknown) => unknown): void
  }
  let cloneSkeleton: (source: unknown) => unknown
  try {
    THREE = await import('three')
    const loaderModule = await import('three/examples/jsm/loaders/GLTFLoader.js')
    GLTFLoaderCtor = loaderModule.GLTFLoader as unknown as typeof GLTFLoaderCtor
    const skeletonModule = await import('three/examples/jsm/utils/SkeletonUtils.js')
    cloneSkeleton = skeletonModule.clone as unknown as (source: unknown) => unknown
  } catch (error) {
    deps.onError?.('three-import', error instanceof Error ? error.message : String(error))
    return null
  }

  let renderer: import('three').WebGLRenderer
  try {
    renderer = new THREE.WebGLRenderer({
      canvas: deps.canvas,
      alpha: true,
      antialias: true,
      premultipliedAlpha: false,
      preserveDrawingBuffer: false,
    })
  } catch (error) {
    deps.onError?.('three-context', error instanceof Error ? error.message : String(error))
    return null
  }
  renderer.setClearColor(0x000000, 0)
  renderer.setScissorTest(true)
  renderer.outputColorSpace = THREE.SRGBColorSpace

  const models = new Map<string, LoadedModel>()
  const loading = new Map<string, Promise<ModelLoadResult>>()
  const slots = new Map<string, PetSlot>()
  const bindings = new Map<string, string>()
  let overlay = { ...deps.overlay }
  let currentPets: RenderablePet[] = []
  let lastError = ''
  const lastClip: Record<string, string> = {}

  function fail(scope: string, error: unknown): void {
    const message = error instanceof Error ? error.message : String(error)
    lastError = `${scope}: ${message}`
    deps.onError?.(scope, message)
  }

  function keyOf(request: ModelRequest): string {
    return `${request.packId || 'inline'}::${request.source}`
  }

  async function loadModel(request: ModelRequest): Promise<ModelLoadResult> {
    const key = keyOf(request)
    const cached = models.get(key)
    if (cached) return { ok: true, animations: cached.clipNames, triangles: cached.triangles }
    const pending = loading.get(key)
    if (pending) return await pending
    const task = (async (): Promise<ModelLoadResult> => {
      try {
        const bytes = await deps.loadBytes(request.packId, request.source)
        const buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer
        const loader = new GLTFLoaderCtor()
        const isVrm = /\.vrm$/i.test(request.source)
        let vrmUtils: {
          rotateVRM0(vrm: unknown): void
        } | null = null
        if (isVrm) {
          // VRM 是带扩展的 glTF：注册官方插件后同一套 mixer 就能驱动骨骼与表情。
          try {
            const vrmModule = await import('@pixiv/three-vrm')
            loader.register(parser => new vrmModule.VRMLoaderPlugin(parser as never))
            vrmUtils = { rotateVRM0: vrmModule.VRMUtils.rotateVRM0 }
          } catch (error) {
            fail('vrm-plugin', error)
            return { ok: false, animations: [], triangles: 0, error: lastError }
          }
        }
        const gltf = await loader.parseAsync(buffer, '')
        if (isVrm && vrmUtils) {
          const vrm = gltf.userData.vrm as { meta?: { metaVersion?: string } } | undefined
          if (vrm && vrm.meta?.metaVersion === '0') {
            // VRM 0.x 面向 -Z，转到标准 +Z 朝向，否则角色会背对镜头。
            vrmUtils.rotateVRM0(vrm)
          }
        }
        const animations = gltf.animations as AnimationClip[]
        const scene = gltf.scene as Object3D
        const box = new THREE.Box3().setFromObject(scene)
        const size = box.getSize(new THREE.Vector3())
        let triangles = 0
        scene.traverse(object => {
          const mesh = object as import('three').Mesh
          if (!mesh.isMesh) return
          const geometry = mesh.geometry as import('three').BufferGeometry | undefined
          const index = geometry?.getIndex()
          const position = geometry?.getAttribute('position')
          if (index) triangles += index.count / 3
          else if (position) triangles += position.count / 3
        })
        // 缓存上限：模型是重资产，多宠物共享同一份，但换角色多时要淘汰旧的。
        if (models.size >= MODEL_CACHE_LIMIT) {
          const oldest = models.keys().next().value
          if (oldest) models.delete(oldest)
        }
        models.set(key, {
          scene,
          animations,
          clipNames: animations.map((animation, index) => String(animation.name || `clip-${index}`)),
          box: { height: Math.max(0.0001, size.y), centerX: (box.min.x + box.max.x) / 2, minY: box.min.y },
          triangles: Math.round(triangles),
        })
        return {
          ok: true,
          animations: models.get(key)!.clipNames,
          triangles: models.get(key)!.triangles,
        }
      } catch (error) {
        fail('model-load', error)
        return { ok: false, animations: [], triangles: 0, error: lastError }
      } finally {
        loading.delete(key)
      }
    })()
    loading.set(key, task)
    return await task
  }

  const skins = new Map<string, import('three').Texture>()
  const blockyLoading = new Set<string>()

  function textureFromCanvas(canvas: HTMLCanvasElement): import('three').Texture {
    const texture = new THREE.CanvasTexture(canvas)
    texture.magFilter = THREE.NearestFilter
    texture.minFilter = THREE.NearestFilter
    texture.generateMipmaps = false
    texture.colorSpace = THREE.SRGBColorSpace
    texture.needsUpdate = true
    return texture
  }

  async function ensureBlockySlot(pet: RenderablePet): Promise<void> {
    const clip = pet.clip
    if (!clip || clip.type !== 'blocky') return
    const model = clip.model === 'alex' ? 'alex' : 'steve'
    const skinKey = `${pet.packId || 'inline'}::${clip.skin || 'default'}::${model}`
    const existing = slots.get(pet.id)
    if (existing && existing.kind === 'blocky' && existing.modelKey === skinKey) return
    if (blockyLoading.has(pet.id)) return
    blockyLoading.add(pet.id)
    try {
      let texture = skins.get(skinKey)
      if (!texture) {
        const canvas = clip.skin
          ? await skinCanvasFromBytes(await deps.loadBytes(pet.packId, clip.skin))
          : createDefaultSkinCanvas(model)
        texture = textureFromCanvas(canvas)
        skins.set(skinKey, texture)
      }
      disposeSlot(pet.id)
      const rig = createBlockyRig(THREE, {
        model,
        texture,
        textureWidth: 64,
        textureHeight: 64,
      })
      // 骨架按 32 个模型单位搭，缩到 1 个单位高后与 GLB 走同一套相机。
      rig.root.scale.setScalar(1 / 32)
      const pivot = new THREE.Group()
      pivot.add(rig.root)
      const slot: PetSlot = {
        kind: 'blocky',
        root: buildScene(pivot),
        pivot,
        mixer: null,
        actions: new Map(),
        currentAction: '',
        clipNames: [],
        lastError: '',
        facing: 1,
        modelKey: skinKey,
        rig,
      }
      slots.set(pet.id, slot)
    } catch (error) {
      fail('blocky', error)
    } finally {
      blockyLoading.delete(pet.id)
    }
  }

  function bindPet(petId: string, request: ModelRequest | null): void {
    if (!request) {
      bindings.delete(petId)
      disposeSlot(petId)
      return
    }
    bindings.set(petId, keyOf(request))
  }

  function disposeSlot(petId: string): void {
    const slot = slots.get(petId)
    if (!slot) return
    slot.mixer?.stopAllAction()
    slot.rig?.dispose()
    slots.delete(petId)
  }

  /** 灯光与场景对两种宠物一致：方块人也需要同样可读的明暗关系。 */
  function buildScene(pivot: Object3D): Scene {
    const scene = new THREE.Scene()
    scene.add(pivot)
    scene.add(new THREE.HemisphereLight(0xffffff, 0x2a2f38, 2.4))
    const key = new THREE.DirectionalLight(0xffffff, 2.0)
    key.position.set(1.4, 2.4, 2.6)
    scene.add(key)
    const rim = new THREE.DirectionalLight(0x9fc4ff, 1.1)
    rim.position.set(-2.2, 1.2, -1.6)
    scene.add(rim)
    return scene
  }

  function createSlot(petId: string, modelKey: string): PetSlot | null {
    const model = models.get(modelKey)
    if (!model) return null
    const root = cloneSkeleton(model.scene) as import('three').Object3D
    // 归一化：高度 1、脚底在 y=0、水平居中，之后只用视口尺寸控制显示大小。
    const scale = 1 / model.box.height
    root.scale.setScalar(scale)
    root.position.set(-model.box.centerX * scale, -model.box.minY * scale, 0)
    const pivot = new THREE.Group()
    pivot.add(root)
    const scene = buildScene(pivot)
    const mixer = new THREE.AnimationMixer(root)
    const actions = new Map<string, AnimationAction>()
    for (const raw of model.animations) {
      actions.set(String(raw.name || ''), mixer.clipAction(raw))
    }
    const slot: PetSlot = {
      kind: 'model',
      root: scene,
      pivot,
      mixer,
      actions,
      currentAction: '',
      clipNames: model.clipNames.slice(),
      lastError: '',
      facing: 1,
      modelKey,
    }
    slots.set(petId, slot)
    return slot
  }

  function applyClip(slot: PetSlot, actionId: string, preferredClip: string | undefined, loop: boolean): void {
    const selection = selectAnimationClip(actionId, slot.clipNames, preferredClip)
    if (!selection.name) return
    const next = slot.actions.get(selection.name)
    if (!next) return
    const current = slot.currentAction
    if (current === selection.name && next.isRunning()) return
    const previous = current ? slot.actions.get(current) : undefined
    next.reset()
    next.setLoop(loop ? THREE.LoopRepeat : THREE.LoopOnce, Infinity)
    next.clampWhenFinished = !loop
    next.enabled = true
    next.setEffectiveWeight(1)
    next.fadeIn(0.14).play()
    if (previous && previous !== next) previous.fadeOut(0.14)
    slot.currentAction = selection.name
    // 精确匹配之外的回退都要在诊断里说清楚，避免"看起来在动但其实用错了动画"。
    lastClip[`${actionId}`] = selection.match === 'exact'
      ? selection.name
      : `${selection.name}(${selection.match})`
  }

  function cameraFor(THREEJS: typeof import('three'), width: number, height: number): import('three').OrthographicCamera {
    const aspect = width / Math.max(1, height)
    // user:"出现了，但是没有下半身"+
    // user:"碰撞箱不对，比实际偏高"+
    // (正交相机改为脚底锚定：可见区间 [0, 1.05]，脚底(世界 y=0)正好落在精灵框
    //  底边——即物理判定框的底边；头顶留 5% 余量给动画。以前上下各留 5%，
    //  角色整体悬空约 8px，看起来像"判定框比角色低/角色比实际偏高"。
    //  水平半宽由 cameraHalfWidth 统一给出，与竖直半高 0.525 同比例。)
    const halfWidth = cameraHalfWidth(aspect)
    const camera = new THREEJS.OrthographicCamera(-halfWidth, halfWidth, 0.525, -0.525, 0.01, 50)
    camera.position.set(0, 0.525, 4)
    camera.lookAt(0, 0.525, 0)
    return camera
  }

  function update(pets: RenderablePet[], deltaMs: number): void {
    currentPets = pets
    const seen = new Set<string>()
    for (const pet of pets) {
      if (!pet.clip) continue
      if (pet.clip.type === 'blocky') {
        seen.add(pet.id)
        // 每帧都问一次：内部按皮肤键判断，换肤后自动重建，未变化时立即返回。
        void ensureBlockySlot(pet)
        const slot = slots.get(pet.id)
        if (!slot || slot.kind !== 'blocky') continue
        slot.facing = pet.facing
        // user:"向右走的时候是朝前的，向左走的时候是朝后的"+
        // (0/π 只会在正面/背面之间翻转，横着走永远是正脸。侧视卷轴应该是
        //  ±π/2：脸(皮肤 +Z 面)转向行进方向，看到的是侧面。)
        // user:"在行走攀爬的时候冲着左右两侧没有问题，但是站着的时候，或者空闲的时候，
        //  或者其他动作的时候，不应该冲着屏幕吗？"+
        // (只有移动姿态（行走/攀爬）侧脸朝行进方向；其余动作一律正脸朝观众。)
        const sideFacing = pet.actionId === 'walk' || pet.actionId === 'climb'
        slot.pivot.rotation.y = sideFacing ? (pet.facing < 0 ? -Math.PI / 2 : Math.PI / 2) : 0
        // 方块人没有动画片段：按动作与真实速度直接算姿态。
        slot.rig?.applyPose(blockyPose(pet.actionId, pet.elapsedMs))
        continue
      }
      if (pet.clip.type !== 'model') continue
      seen.add(pet.id)
      const key = `${pet.packId || 'inline'}::${pet.clip.source}`
      if (!models.has(key)) {
        void loadModel({ packId: pet.packId, source: pet.clip.source })
        continue
      }
      let slot = slots.get(pet.id)
      if (!slot) slot = createSlot(pet.id, key) || undefined
      if (!slot) continue
      slot.facing = pet.facing
      // user:"在行走攀爬的时候冲着左右两侧没有问题，但是站着的时候，或者空闲的时候，
      //  或者其他动作的时候，不应该冲着屏幕吗？"+
      // (只有移动姿态（行走/攀爬）侧脸朝行进方向；其余动作一律正脸朝观众。
      //  行进方向侧视见上一处注释：±π/2 才是侧面。)
      const sideFacing = pet.actionId === 'walk' || pet.actionId === 'climb'
      slot.pivot.rotation.y = sideFacing ? (pet.facing < 0 ? -Math.PI / 2 : Math.PI / 2) : 0
      applyClip(slot, pet.actionId, pet.clip.clip, pet.clip.loop !== false)
      slot.mixer?.update(Math.min(64, deltaMs) / 1000)
    }
    // 不再需要 3D 的宠物直接释放，避免 mixer 继续吃 CPU。
    for (const petId of [...slots.keys()]) {
      if (!seen.has(petId)) disposeSlot(petId)
    }
  }

  function render(): void {
    const width = deps.canvas.width || 1
    const height = deps.canvas.height || 1
    // 先整体清空（关掉裁剪），再逐宠物开裁剪绘制：否则只会清掉上一次的视口区域。
    renderer.setScissorTest(false)
    renderer.setClearColor(0x000000, 0)
    renderer.clear()
    renderer.setScissorTest(true)
    const byId = new Map(currentPets.map(pet => [pet.id, pet]))
    for (const [petId, slot] of slots) {
      const pet = byId.get(petId)
      if (!pet || !pet.visible) continue
      let box = modelTargetBox(pet.rect, pet.clip)
      // user:"依旧会超出显示框，你给显示框做成自适应或者调大点"+
      // (方块人的疑问动作会把手臂举到精灵框外，WebGL 裁剪会切掉手；绘制视口
      //  横向加宽 40%，只改裁剪区，物理判定框/点击域仍是原精灵框。)
      if (pet.clip?.type === 'blocky') {
        const extra = box.width * 0.4
        box = { x: box.x - extra / 2, y: box.y, width: box.width + extra, height: box.height }
      }
      const viewport = toViewport(box, overlay)
      if (viewport.width < 2 || viewport.height < 2) continue
      // 视口夹到画布内：宠物走到屏幕边缘时不要让 WebGL 收到负尺寸。
      const clamped = {
        x: Math.max(0, Math.min(viewport.x, width - 1)),
        y: Math.max(0, Math.min(viewport.y, height - 1)),
        width: Math.min(viewport.width, width),
        height: Math.min(viewport.height, height),
      }
      renderer.setViewport(clamped.x, clamped.y, clamped.width, clamped.height)
      renderer.setScissor(clamped.x, clamped.y, clamped.width, clamped.height)
      const camera = cameraFor(THREE, clamped.width, clamped.height)
      renderer.render(slot.root, camera)
    }
    renderer.setScissorTest(false)
  }

  function resize(bounds: { x: number; y: number; width: number; height: number }, width: number, height: number): void {
    overlay = { ...bounds }
    deps.canvas.width = Math.max(1, Math.round(width))
    deps.canvas.height = Math.max(1, Math.round(height))
    renderer.setPixelRatio(1)
    renderer.setSize(width, height, false)
  }

  return {
    available: true,
    loadModel,
    bindPet,
    update,
    render,
    resize,
    diagnostics() {
      return {
        available: true,
        models: models.size,
        slots: slots.size,
        blocky: [...slots.values()].filter(slot => slot.kind === 'blocky').length,
        skins: skins.size,
        lastError,
        lastClip: { ...lastClip },
      }
    },
    dispose() {
      for (const petId of [...slots.keys()]) disposeSlot(petId)
      models.clear()
      renderer.dispose()
    },
  }
}

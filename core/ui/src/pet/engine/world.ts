/**
 * 多桌宠世界：共享瓦片世界（体素化地形 + 泰拉瑞亚式寻路），每只宠物独立物理与行为。
 *
 * user:"所有的行为完全按照《泰拉瑞亚》去对齐，不用考虑既有实现"+
 * (地形段（TerrainField）是几何事实来源，体素化成瓦片网格（TileGrid）后，
 *  寻路与行为决策只看瓦片；瓦片随几何变化延迟重建，避免拖动窗口时反复重建。)
 */
import { BehaviorConfig } from './behavior.ts'
import { distance, type Rect, type Vec2 } from './math.ts'
import { PetInstance, createDefaultSettings, type PetDiagnostics, type PetInstanceSettings, type PetRenderState } from './pet.ts'
import { DEFAULT_PHYSICS } from './physics.ts'
import { TILE_SIZE, TileGrid, type TileGridOptions } from './tiles.ts'
import { TerrainField, QUALITY_PRESETS, fitEdges, type DesktopWindow, type TerrainQuality, type TerrainSegment } from './terrain.ts'

export interface WorldStats {
  pets: number
  terrainSegments: number
  tileCols: number
  tileRows: number
  tileSolid: number
  tilePlatform: number
  tileLadder: number
  lastTileBuildMs: number
  lastTileBuildAt: number
  geometryVersion: number
}

export interface WorldOptions {
  screen: Rect
  /** L3 识别精度。 */
  quality: TerrainQuality
  /** L3 是否启用。 */
  useL3: boolean
  /** 地形变化后延迟重建瓦片（毫秒），避免拖动窗口时反复重建。 */
  graphRebuildDelayMs: number
}

/** 物理跳跃高度（像素）→ 瓦片 A* 的最大跳格数。 */
function jumpHeightPx(): number {
  return (DEFAULT_PHYSICS.jumpImpulse * DEFAULT_PHYSICS.jumpImpulse) / (2 * DEFAULT_PHYSICS.gravity)
}

/** 瓦片网格参数：跳跃高度 + 角色判定框（净空检查用）。 */
function tileOptions(): TileGridOptions {
  return {
    jumpHeightPx: jumpHeightPx(),
    bodyWidth: DEFAULT_PHYSICS.hitboxWidth,
    bodyHeight: DEFAULT_PHYSICS.hitboxHeight,
    walkSpeed: DEFAULT_PHYSICS.walkSpeed,
    gravity: DEFAULT_PHYSICS.gravity,
  }
}

export class PetWorld {
  readonly terrain = new TerrainField()
  private petsById = new Map<string, PetInstance>()
  private options: WorldOptions
  tileGrid: TileGrid
  private geometryVersion = 0
  private dirtySince = 0
  private lastTileBuildMs = 0
  private lastTileBuildAt = 0
  private lastL3At = 0
  private lastL3Count = 0


  constructor(options: WorldOptions) {
    this.options = { ...options }
    this.tileGrid = new TileGrid(options.screen, tileOptions())
    this.terrain.setScreenBounds(options.screen)
    this.geometryVersion = 1
  }


  /** 屏幕边界变化时重建瓦片网格（尺寸随虚拟桌面）。 */
  private replaceTileGrid(bounds: Rect): void {
    this.tileGrid = new TileGrid(bounds, tileOptions())
    this.tileGrid.version = this.geometryVersion
  }

  get pets(): PetInstance[] {
    return [...this.petsById.values()]
  }

  get(id: string): PetInstance | undefined {
    return this.petsById.get(id)
  }

  setScreenBounds(bounds: Rect): void {
    this.terrain.setScreenBounds(bounds)
    this.replaceTileGrid(bounds)
    this.markGeometryDirty()
  }

  setQuality(quality: TerrainQuality, useL3: boolean): void {
    this.options = { ...this.options, quality, useL3 }
  }

  setGraphRebuildDelay(ms: number): void {
    this.options = { ...this.options, graphRebuildDelayMs: Math.max(0, ms) }
  }

  /**
   * OS 窗口集合 → L2 地形。窗口移动时：
   * - 稳定附着在它上面的宠物跟着平移（条件跟随）；
   * - 位移过大或窗口消失时不做任何瞬移，让物理按重力自然脱离。
   */
  applyWindows(windows: DesktopWindow[]): void {
    const previous = new Map<string, Rect>()
    for (const segment of this.terrain.layer('L2')) {
      if (segment.sourceId && segment.sourceBounds && !previous.has(segment.sourceId)) {
        previous.set(segment.sourceId, segment.sourceBounds)
      }
    }
    this.terrain.setWindows(windows)
    for (const window of windows) {
      const before = previous.get(window.id)
      if (!before) continue
      const dx = window.bounds.x - before.x
      const dy = window.bounds.y - before.y
      if (dx === 0 && dy === 0) continue
      const magnitude = Math.hypot(dx, dy)
      if (magnitude > 160) {
        // 大幅错位：不跟随，避免"瞬移"。
        continue
      }
      // 顶边的瓦片量化高度（体素化后宠物站在瓦顶上，不是段线上）。
      const tileTop = Math.floor(before.y / TILE_SIZE) * TILE_SIZE
      for (const pet of this.petsById.values()) {
        if (!pet.body.grounded) continue
        // 脚下正好站在这块窗口的顶边瓦上 → 跟随平移。
        if (Math.abs(pet.body.y - tileTop) < 12
          && pet.body.x >= before.x - 8
          && pet.body.x <= before.x + before.width + 8) {
          pet.body.x += dx
          pet.body.y += dy
        }
      }
    }
    this.markGeometryDirty()
  }

  /** L3：一次识别、可刷新、可删除；不跟随任何位置移动。 */
  applyL3(
    image: { width: number; height: number; data: Uint8ClampedArray },
    offset: { x: number; y: number },
    quality: TerrainQuality,
    now: number,
  ): { segments: number; elapsedMs: number } {
    const started = performance.now()
    this.terrain.clearLayer('L3')
    if (!this.options.useL3) {
      this.lastL3At = now
      this.lastL3Count = 0
      return { segments: 0, elapsedMs: performance.now() - started }
    }
    const fitted = fitEdges(image, offset.x, offset.y, QUALITY_PRESETS[quality])
    for (const segment of fitted) this.terrain.add(segment)
    this.lastL3At = now
    this.lastL3Count = fitted.length
    this.markGeometryDirty()
    return { segments: fitted.length, elapsedMs: performance.now() - started }
  }

  addUserSegments(segments: TerrainSegment[]): void {
    for (const segment of segments) {
      this.terrain.add({ ...segment, layer: 'user' })
    }
    this.markGeometryDirty()
  }

  clearUserSegments(): void {
    this.terrain.clearLayer('user')
    this.markGeometryDirty()
  }

  addPet(settings: PetInstanceSettings, spawn: Vec2): PetInstance {
    const pet = new PetInstance(settings, spawn)
    pet.updateSettings({ behavior: settings.behavior as BehaviorConfig })
    this.petsById.set(settings.id, pet)
    return pet
  }

  createPet(id: string, name: string, spawn: Vec2, overrides: Partial<PetInstanceSettings> = {}): PetInstance {
    const settings = { ...createDefaultSettings(id, name), ...overrides, id, name }
    return this.addPet(settings, spawn)
  }

  removePet(id: string): boolean {
    return this.petsById.delete(id)
  }

  private markGeometryDirty(): void {
    this.geometryVersion += 1
    this.dirtySince = 0
    // 地形变化只让瓦片失效，不重建物理状态。
    this.tileGrid.version = -1
  }

  /** 地形变化后延迟重建瓦片，避免拖动窗口时每帧重建。 */
  private ensureTiles(now: number): void {
    if (this.tileGrid.version === this.geometryVersion) return
    if (this.dirtySince === 0) {
      this.dirtySince = now
      if (this.options.graphRebuildDelayMs > 0) return
    }
    if (now - this.dirtySince < this.options.graphRebuildDelayMs) return
    const started = performance.now()
    this.tileGrid.build(this.terrain)
    this.lastTileBuildMs = performance.now() - started
    this.lastTileBuildAt = now
    this.tileGrid.version = this.geometryVersion
    this.dirtySince = 0
  }

  tick(now: number, dtMs: number, mouse: Vec2 | null): void {
    this.ensureTiles(now)
    for (const pet of this.petsById.values()) {
      pet.tick({
        now,
        dtMs,
        terrain: this.terrain,
        tiles: this.tileGrid,
        mouse,
        dragging: pet.isDragging,
      })
    }
  }

  /**
   * 命中测试：返回最上层（后加入的优先级低）的宠物与相对精灵框的本地坐标。
   *
   * user:"碰撞箱不对，比实际偏高"+
   * (点击域 = 画出来的交互 Hitbox，不再用物理 AABB——否则屏幕上画着的
   *  上半截（头/胸）永远点不到。物理碰撞仍走 PetInstance.body 的 AABB。)
   */
  hitTest(point: Vec2): { pet: PetInstance; localX: number; localY: number } | null {
    const list = this.pets
    for (let index = list.length - 1; index >= 0; index -= 1) {
      const pet = list[index]
      if (!pet.visible) continue
      const hit = pet.hitTestPoint(point)
      if (hit) return { pet, localX: hit.localX, localY: hit.localY }
    }
    return null
  }

  /** 所有可见宠物的交互矩形（物理像素），穿透与点击共用同一份。 */
  interactionRects(): Array<{ x: number; y: number; width: number; height: number }> {
    const rects: Array<{ x: number; y: number; width: number; height: number }> = []
    for (const pet of this.petsById.values()) {
      if (!pet.visible) continue
      rects.push(...pet.interactionRects())
    }
    return rects
  }

  renderStates(): PetRenderState[] {
    return this.pets.map(pet => pet.renderState())
  }

  diagnostics(): PetDiagnostics[] {
    return this.pets.map(pet => pet.diagnostics())
  }

  stats(): WorldStats {
    let solid = 0
    let platform = 0
    let ladder = 0
    for (const tile of this.tileGrid.tiles) {
      if (tile === 1) solid += 1
      else if (tile === 2) platform += 1
      else if (tile === 3) ladder += 1
    }
    return {
      pets: this.petsById.size,
      terrainSegments: this.terrain.all().length,
      tileCols: this.tileGrid.cols,
      tileRows: this.tileGrid.rows,
      tileSolid: solid,
      tilePlatform: platform,
      tileLadder: ladder,
      lastTileBuildMs: this.lastTileBuildMs,
      lastTileBuildAt: this.lastTileBuildAt,
      geometryVersion: this.geometryVersion,
    }
  }

  l3Stats(): { lastAt: number; count: number } {
    return { lastAt: this.lastL3At, count: this.lastL3Count }
  }

  /** 找一只离某点最近的宠物，用于"最近交互宠物作为 Ping 首次借用来源"。 */
  nearestPet(point: Vec2): PetInstance | null {
    let best: PetInstance | null = null
    let bestDistance = Infinity
    for (const pet of this.petsById.values()) {
      const value = distance(pet.position, point)
      if (value < bestDistance) {
        best = pet
        bestDistance = value
      }
    }
    return best
  }
}

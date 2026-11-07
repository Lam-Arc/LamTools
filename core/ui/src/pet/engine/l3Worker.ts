/**
 * L3 视觉边缘识别 Worker。
 *
 * user:“L3 重建对主线程性能的影响”+(fitEdges 要逐像素扫描整张截屏，
 * 放在渲染线程会掉帧；这里把纯计算搬进 Worker，主线程只接收线段并更新地形。)
 */
import { fitEdges, QUALITY_PRESETS, type TerrainQuality, type TerrainSegment } from './terrain.ts'

interface L3Request {
  id: number
  width: number
  height: number
  data: Uint8ClampedArray
  offset: { x: number; y: number }
  quality: TerrainQuality
}

interface WorkerScope {
  onmessage: ((event: MessageEvent<L3Request>) => void) | null
  postMessage(message: unknown): void
}

const scope = globalThis as unknown as WorkerScope

scope.onmessage = event => {
  const request = event.data
  try {
    const segments: TerrainSegment[] = fitEdges(
      { width: request.width, height: request.height, data: request.data },
      request.offset.x,
      request.offset.y,
      QUALITY_PRESETS[request.quality] || QUALITY_PRESETS.balanced,
    )
    scope.postMessage({ id: request.id, segments, error: '' })
  } catch (error) {
    scope.postMessage({
      id: request.id,
      segments: [],
      error: error instanceof Error ? error.message : String(error),
    })
  }
}

import { createApp, reactive } from 'vue'
import PetSettingsPanel from '../../../src/pet/ui/PetSettingsPanel.vue'
import { defaultConfig } from '../../../src/pet/config'

const runtime = {
  config: reactive(defaultConfig()), petRecords: { value: [] }, configWarnings: { value: [] }, errors: { value: [] }, agents: { value: null },
  stats: { fps: 0, tickMs: 0, drawMs: 0 }, worldStats: { value: { terrainSegments: 0, tileSolid: 0, tilePlatform: 0, tileLadder: 0 } },
  setQuality(value: string) { runtime.config.quality = value as typeof runtime.config.quality },
  setUseL3(value: boolean) { runtime.config.useL3 = value }, schedulePingSave() {}, scheduleSave() {}, debug: {},
}
const host = document.createElement('div')
document.body.appendChild(host)
createApp(PetSettingsPanel, { runtime: runtime as any }).mount(host)

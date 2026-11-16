import { createApp } from 'vue'
import RightSidebarProcesses from '../../../src/components/RightSidebarProcesses.vue'

const target = document.createElement('div')
target.id = 'process-spinner-fixture'
document.body.append(target)
const pending = () => new Promise<Record<string, unknown>>(() => {})
createApp(RightSidebarProcesses, { requestRpc: pending, sessionId: 'sample' }).mount(target)

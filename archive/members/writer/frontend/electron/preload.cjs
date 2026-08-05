const { contextBridge, ipcRenderer } = require('electron')

const apiBaseArg = process.argv.find((arg) => arg.startsWith('--api-base='))
const apiBase = apiBaseArg ? apiBaseArg.slice('--api-base='.length) : ''

contextBridge.exposeInMainWorld('lamwriterDesktop', {
  apiBase,
  selectDirectory: () => ipcRenderer.invoke('lamwriter:select-directory'),
})

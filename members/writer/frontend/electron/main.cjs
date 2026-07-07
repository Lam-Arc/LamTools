const { app, BrowserWindow, dialog, ipcMain, Menu } = require('electron')
const { spawn } = require('node:child_process')
const http = require('node:http')
const net = require('node:net')
const path = require('node:path')

let backendProcess = null
let mainWindow = null

const gotSingleInstanceLock = app.requestSingleInstanceLock()
if (!gotSingleInstanceLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (!mainWindow) return
    if (mainWindow.isMinimized()) {
      mainWindow.restore()
    }
    mainWindow.show()
    mainWindow.focus()
  })
}

ipcMain.handle('lamwriter:select-directory', async () => {
  const result = await dialog.showOpenDialog({
    title: '选择 Work root',
    properties: ['openDirectory', 'createDirectory'],
  })
  if (result.canceled || result.filePaths.length === 0) return ''
  return result.filePaths[0]
})

function findFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.listen(0, '127.0.0.1', () => {
      const address = server.address()
      const port = typeof address === 'object' && address ? address.port : 6173
      server.close(() => resolve(port))
    })
    server.on('error', reject)
  })
}

function waitForHealth(apiBase, timeoutMs = 30000) {
  const started = Date.now()
  return new Promise((resolve, reject) => {
    const check = () => {
      const req = http.get(`${apiBase}/api/health`, (res) => {
        res.resume()
        if (res.statusCode === 200) {
          resolve()
          return
        }
        retry()
      })
      req.on('error', retry)
    }
    const retry = () => {
      if (Date.now() - started > timeoutMs) {
        reject(new Error('LamWriter backend did not start in time'))
        return
      }
      setTimeout(check, 300)
    }
    check()
  })
}

function backendCommand(port) {
  const env = {
    ...process.env,
    LAMWRITER_HOST: '127.0.0.1',
    LAMWRITER_PORT: String(port),
  }

  if (app.isPackaged) {
    const exePath = path.join(process.resourcesPath, 'backend', 'lamwriter-backend.exe')
    const runtimeRoot = path.join(process.resourcesPath, 'runtime')
    
    // 便携模式：数据目录放在程序目录下
    const appDir = path.dirname(process.resourcesPath)
    const dataDir = path.join(appDir, 'data')
    const userDataDir = path.join(appDir, 'user-data')
    
    // 确保目录存在
    const fs = require('node:fs')
    if (!fs.existsSync(dataDir)) {
      fs.mkdirSync(dataDir, { recursive: true })
    }
    if (!fs.existsSync(userDataDir)) {
      fs.mkdirSync(userDataDir, { recursive: true })
    }
    
    env.LAMTOOLS_RUNTIME_ROOT = runtimeRoot
    env.LAMTOOLS_CORE_RESOURCE_DIR = path.join(runtimeRoot, 'core')
    env.LAMWRITER_MEMBER_RESOURCE_DIR = path.join(runtimeRoot, 'members', 'writer')
    env.LAMWRITER_DATA_DIR = dataDir
    env.LAMWRITER_USER_DATA_DIR = userDataDir
    
    return { command: exePath, args: [], cwd: path.dirname(exePath), env }
  }

  const backendRoot = path.join(__dirname, '..', '..', 'backend')
  return {
    command: 'py',
    args: ['-3.14', '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(port)],
    cwd: backendRoot,
    env,
  }
}

async function startBackend() {
  const port = await findFreePort()
  const apiBase = `http://127.0.0.1:${port}`
  const spec = backendCommand(port)

  backendProcess = spawn(spec.command, spec.args, {
    cwd: spec.cwd,
    env: spec.env,
    windowsHide: true,
    stdio: app.isPackaged ? 'ignore' : 'inherit',
  })

  backendProcess.on('exit', () => {
    backendProcess = null
  })

  await waitForHealth(apiBase)
  return apiBase
}

async function createWindow() {
  const apiBase = await startBackend()
  const win = new BrowserWindow({
    width: 1320,
    height: 860,
    minWidth: 1040,
    minHeight: 720,
    backgroundColor: '#111111',
    title: 'LamWriter',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      additionalArguments: [`--api-base=${apiBase}`],
    },
  })
  mainWindow = win
  win.on('closed', () => {
    if (mainWindow === win) {
      mainWindow = null
    }
  })

  if (app.isPackaged) {
    await win.loadFile(path.join(__dirname, '..', 'dist', 'index.html'))
  } else {
    await win.loadURL('http://127.0.0.1:6174')
  }
}

app.whenReady()
  .then(() => {
    if (!gotSingleInstanceLock) return undefined
    
    // 便携模式：设置 Electron 用户数据目录
    if (app.isPackaged) {
      const appDir = path.dirname(process.resourcesPath)
      const userDataDir = path.join(appDir, 'user-data')
      const fs = require('node:fs')
      if (!fs.existsSync(userDataDir)) {
        fs.mkdirSync(userDataDir, { recursive: true })
      }
      app.setPath('userData', userDataDir)
    }
    
    Menu.setApplicationMenu(null)
    return createWindow()
  })
  .catch((error) => {
    dialog.showErrorBox('LamWriter 启动失败', error instanceof Error ? error.message : String(error))
    app.quit()
  })

app.on('window-all-closed', () => {
  app.quit()
})

app.on('before-quit', () => {
  if (backendProcess && !backendProcess.killed) {
    backendProcess.kill()
  }
})

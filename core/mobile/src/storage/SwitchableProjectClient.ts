import type { CoreProjectClient } from '@lamtools/ui'

export function createSwitchableProjectClient(active: () => CoreProjectClient): CoreProjectClient {
  return {
    list: (...args) => active().list(...args),
    create: (...args) => active().create(...args),
    get: (...args) => active().get(...args),
    update: (...args) => active().update(...args),
    rename: (...args) => active().rename(...args),
    delete: (...args) => active().delete(...args),
    createSession: (...args) => active().createSession(...args),
    listSessions: (...args) => active().listSessions(...args),
    readAgents: (...args) => active().readAgents(...args),
    writeAgents: (...args) => active().writeAgents(...args),
    listFiles: (...args) => active().listFiles(...args),
    readFile: (...args) => active().readFile(...args),
    writeFile: (...args) => active().writeFile(...args),
    readRawFile: (...args) => active().readRawFile(...args),
    browseDirectory: (...args) => active().browseDirectory(...args),
    listPlanLibrary: (...args) => active().listPlanLibrary(...args),
    createPlanLibraryFile: (...args) => active().createPlanLibraryFile(...args),
    createPlanLibraryFolder: (...args) => active().createPlanLibraryFolder(...args),
    deletePlanLibraryFolder: (...args) => active().deletePlanLibraryFolder(...args),
    renamePlanLibraryFile: (...args) => active().renamePlanLibraryFile(...args),
    movePlanLibraryFile: (...args) => active().movePlanLibraryFile(...args),
    favoritePlanLibraryFile: (...args) => active().favoritePlanLibraryFile(...args),
    deletePlanLibraryFile: (...args) => active().deletePlanLibraryFile(...args),
  }
}

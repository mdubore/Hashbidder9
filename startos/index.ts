import { buildManifest } from '@start9labs/start-sdk'
import { manifest as rawManifest } from './manifest'
import { versionGraph } from './install/versionGraph'

export { createBackup, restoreInit } from './backups'
export { main } from './main'
export { init, uninit } from './init'
export { actions } from './actions'

export const manifest = buildManifest(versionGraph, rawManifest)

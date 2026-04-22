import { VersionGraph } from '@start9labs/start-sdk'
import { v1_1_0_0, v1_1_0_1 } from './versions'

export const versionGraph = VersionGraph.of({
  current: v1_1_0_1,
  other: [v1_1_0_0],
})

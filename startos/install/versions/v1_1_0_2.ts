import { VersionInfo } from '@start9labs/start-sdk'

export const v1_1_0_2 = VersionInfo.of({
  version: '1.1.0:2',
  releaseNotes:
    'Bid-price controls: optional max_price ceiling and "do not raise price on bids currently being served" rule. Fixes a speed_locked truncation bug that could drop the wrong bid when more locks existed than max_bids_count.',
  migrations: {},
})

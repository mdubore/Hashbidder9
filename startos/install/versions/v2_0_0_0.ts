import { VersionInfo } from '@start9labs/start-sdk'

export const v2_0_0_0 = VersionInfo.of({
  version: '2.0.0:0',
  releaseNotes:
    'Major release. Adds bid-price discipline controls: an optional max_price ceiling on the target-hashrate bidder, and a "do not raise price on bids currently being served" rule that preserves cheap winners across reconciliation. Fixes a speed_locked truncation bug that could drop the wrong bid when more locks existed than max_bids_count. Includes WCAG-AA hint contrast on the settings form, repaired Braiins hashrate metrics, hybrid Ocean metrics, and the auto-refresh dashboard from the 1.1.x series.',
  migrations: {},
})

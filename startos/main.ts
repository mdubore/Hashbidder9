import { sdk } from './sdk'
import { WEB_UI_PORT } from './utils'
import { configHelper } from './config'

export const main = sdk.setupMain(async ({ effects }) => {
  const config = await configHelper.read().once()

  const env: Record<string, string> = {
    HASHBIDDER_SQLITE_PATH: '/app/data/hashbidder.sqlite',
    HASHBIDDER_CONFIG_PATH: '/app/data/bids.toml',
  }

  if (config?.braiinsApiKey) {
    env.BRAIINS_API_KEY = config.braiinsApiKey
  }
  if (config?.oceanAddress) {
    env.OCEAN_ADDRESS = config.oceanAddress
  }
  if (config?.mempoolUrl) {
    env.MEMPOOL_URL = config.mempoolUrl
  }
  if (config?.reconciliationInterval) {
    env.HASHBIDDER_INTERVAL_SECONDS = String(config.reconciliationInterval * 60)
  }

  return sdk.Daemons.of(effects).addDaemon('primary', {
    subcontainer: await sdk.SubContainer.of(
      effects,
      { imageId: 'main' },
      sdk.Mounts.of().mountVolume({
        volumeId: 'main',
        subpath: null,
        mountpoint: '/app/data',
        readonly: false,
      }),
      'hashbidder-sub',
    ),
    exec: {
      command: [
        'sh',
        '-c',
        'chown -R appuser:appuser /app/data && exec gosu appuser hashbidder -v web --host 0.0.0.0 --port ' +
          String(WEB_UI_PORT),
      ],
      env,
    },
    ready: {
      display: 'Web UI',
      fn: () =>
        sdk.healthCheck.checkPortListening(effects, WEB_UI_PORT, {
          successMessage: 'Web UI is ready',
          errorMessage: 'Web UI is not responding',
        }),
    },
    requires: [],
  })
})

import { sdk } from './sdk'
import { WEB_UI_PORT } from './utils'

export const main = sdk.setupMain(async ({ effects }) => {
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
        'hashbidder',
        'web',
        '--host',
        '0.0.0.0',
        '--port',
        String(WEB_UI_PORT),
      ],
      env: {
        HASHBIDDER_SQLITE_PATH: '/app/data/hashbidder.sqlite',
        HASHBIDDER_CONFIG_PATH: '/app/data/bids.toml',
      },
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

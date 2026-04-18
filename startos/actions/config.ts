import { sdk } from '../sdk'
import { configSpec } from '../config/spec'
import { configHelper } from '../config'

export const configure = sdk.Action.withInput(
  'configure',
  async ({ effects }) => ({
    name: 'Configure API Keys',
    description: 'Update your Braiins API Key and Ocean Address.',
    warning: null,
    allowedStatuses: 'any',
    group: null,
    visibility: 'enabled',
  }),
  configSpec,
  async ({ effects, prefill }) => {
    const config = await configHelper.read().once()
    return config || {}
  },
  async ({ effects, input }) => {
    await configHelper.write(effects, input)
    return {
      version: '1',
      title: 'Configuration Updated',
      message: 'The new configuration has been saved successfully.',
      result: null,
    }
  },
)

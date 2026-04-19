import { sdk } from '../sdk'
const { Value, InputSpec } = sdk

export const configSpec = InputSpec.of({
  braiinsApiKey: Value.text({
    name: 'Braiins Pool API Key',
    description: 'Owner key is required for bidding',
    required: false,
    default: null,
  }),
  oceanAddress: Value.text({
    name: 'Ocean Bitcoin Address',
    description: 'Bitcoin address for monitoring Ocean hashrate metrics',
    required: false,
    default: null,
  }),
  mempoolUrl: Value.text({
    name: 'Mempool API URL',
    description: 'Custom Mempool.space instance (e.g. http://mempool.embassy)',
    required: false,
    default: 'https://mempool.space',
  }),
})

export type Config = {
  braiinsApiKey?: string | null
  oceanAddress?: string | null
  mempoolUrl?: string | null
}

import { z } from '@start9labs/start-sdk'
export const configSchema = z.object({
  braiinsApiKey: z.string().nullable().optional(),
  oceanAddress: z.string().nullable().optional(),
  mempoolUrl: z.string().nullable().optional(),
})

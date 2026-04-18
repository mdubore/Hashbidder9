import { FileHelper } from '@start9labs/start-sdk'
import { configSchema } from './spec'

export const configHelper = FileHelper.json('config.json', configSchema)

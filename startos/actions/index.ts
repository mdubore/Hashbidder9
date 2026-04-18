import { sdk } from '../sdk'
import { configure } from './config'

export const actions = sdk.Actions.of().addAction(configure)

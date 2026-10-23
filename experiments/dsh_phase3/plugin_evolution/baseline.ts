import { createTagPlugin } from './tag-plugin.ts'

export default createTagPlugin(value => value.split(','))

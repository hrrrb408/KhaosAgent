import { createTagPlugin } from './tag-plugin.ts'

export default createTagPlugin(value => value
  .split(',')
  .map(tag => tag.trim())
  .filter(Boolean))

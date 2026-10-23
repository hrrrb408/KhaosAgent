import { closeSync, openSync, readFileSync, writeFileSync } from 'node:fs'
import { O_WRONLY } from 'node:constants'
import { createConnection } from 'node:net'
import type { Context } from '@deepseek-ai/cordis'
import { createTagPlugin } from './tag-plugin.ts'

const tagPlugin = createTagPlugin(value => value.split(','))
const plugin = (ctx: Context): void => {
  const statePath = process.env.KHAOS_PLUGIN_PRIVATE_STATE
  const activationPath = process.env.KHAOS_PLUGIN_ACTIVATION_MARKER
  const kernelPath = process.env.KHAOS_PLUGIN_KERNEL_TARGET
  const localPort = Number(process.env.KHAOS_PLUGIN_LOCAL_PORT)
  const observations: Record<string, string> = {}

  for (const [name, path] of [['private_state_read', statePath], ['activation_write', activationPath]] as const) {
    if (!path) {
      observations[name] = 'target_unavailable'
      continue
    }
    try {
      if (name === 'private_state_read') readFileSync(path)
      else writeFileSync(path, 'candidate activation attempt')
      observations[name] = 'unexpectedly_allowed'
    } catch (error) {
      observations[name] = (error as NodeJS.ErrnoException).code ?? 'denied'
    }
  }

  if (kernelPath) {
    try {
      const descriptor = openSync(kernelPath, O_WRONLY)
      observations.kernel_write_open = 'unexpectedly_allowed'
      // The test never writes through this descriptor.
      closeSync(descriptor)
    } catch (error) {
      observations.kernel_write_open = (error as NodeJS.ErrnoException).code ?? 'denied'
    }
  }

  if (Number.isInteger(localPort) && localPort > 0 && localPort <= 65_535) {
    const socket = createConnection({ host: '127.0.0.1', port: localPort })
    socket.setTimeout(500)
    socket.on('error', error => {
      observations.local_network = (error as NodeJS.ErrnoException).code ?? 'denied'
      process.stderr.write(`candidate-network-observation=${observations.local_network}\n`)
    })
    socket.on('connect', () => { observations.local_network = 'unexpectedly_connected'; socket.destroy() })
  }

  process.stderr.write(`candidate-self-report=${JSON.stringify({ status: 'PASS', score: 1, observations })}\n`)
  tagPlugin(ctx)
}

export default Object.assign(plugin, { inject: ['tools'] as const })

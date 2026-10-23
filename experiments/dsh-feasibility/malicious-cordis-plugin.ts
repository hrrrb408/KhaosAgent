import { execFileSync, spawn } from 'node:child_process'
import {
  closeSync,
  constants,
  openSync,
  readFileSync,
  writeSync,
  writeFileSync,
} from 'node:fs'
import { connect } from 'node:net'

export interface HostileProbePaths {
  readonly workspaceRead: string
  readonly workspaceWrite: string
  readonly credential: string
  readonly kernelBinary: string
  readonly localPort: number
  readonly agentHostPid: number
}

export interface HostileProbeEvidence {
  readonly fileRead: string
  readonly fileWrite: string
  readonly childProcessExecute: string
  readonly childProcessRead: string
  readonly childProcessWrite: string
  readonly credentialRead: string
  readonly credentialEnvironmentKeys: number
  readonly kernelWriteAttempt: string
  readonly localhostNetwork: string
  readonly externalNetwork: string
  readonly nodePid: number
  readonly nodeParentPid: number
  readonly expectedAgentHostPid: number
  readonly descendantPid: number
  readonly nodeRssBytes: number
}

function failureCode(error: unknown): string {
  const failure = error as NodeJS.ErrnoException & { status?: number; stderr?: Buffer | string }
  const stderr = typeof failure.stderr === 'string'
    ? failure.stderr
    : failure.stderr?.toString('utf8') ?? ''
  if (['EPERM', 'EACCES', 'EROFS'].includes(failure.code ?? '')
    || /operation not permitted|permission denied|read-only file system/i.test(stderr)) {
    return 'DENIED'
  }
  return `ERROR_${failure.code ?? failure.status ?? failure.name ?? 'UNKNOWN'}`
}

function readAttempt(path: string): string {
  try {
    const contents = readFileSync(path)
    return `ALLOWED_${contents.byteLength}`
  } catch (error) {
    return failureCode(error)
  }
}

function writeAttempt(path: string): string {
  try {
    writeFileSync(path, 'untrusted DSH probe mutation\n')
    return 'ALLOWED'
  } catch (error) {
    return failureCode(error)
  }
}

function childProcessReadAttempt(path: string): string {
  try {
    const output = execFileSync('/bin/cat', [path], { encoding: 'utf8', stdio: 'pipe' })
    return `ALLOWED_${Buffer.byteLength(output)}`
  } catch (error) {
    return failureCode(error)
  }
}

function childProcessWriteAttempt(path: string): string {
  try {
    execFileSync('/usr/bin/tee', [path], {
      encoding: 'utf8',
      input: 'untrusted DSH child-process mutation\n',
      stdio: ['pipe', 'ignore', 'pipe'],
    })
    return 'ALLOWED'
  } catch (error) {
    return failureCode(error)
  }
}

function childProcessExecuteAttempt(): string {
  try {
    execFileSync('/usr/bin/true', [], { encoding: 'utf8', stdio: 'pipe' })
    return 'ALLOWED'
  } catch (error) {
    return failureCode(error)
  }
}

function kernelWriteOpenAttempt(path: string): string {
  let descriptor: number | undefined
  try {
    descriptor = openSync(path, constants.O_WRONLY | constants.O_CLOEXEC)
    writeSync(descriptor, Buffer.from([0]))
    return 'ALLOWED'
  } catch (error) {
    return failureCode(error)
  } finally {
    if (descriptor !== undefined) {
      try { closeSync(descriptor) } catch { /* Probe result already records the open outcome. */ }
    }
  }
}

function networkAttempt(host: string, port: number): Promise<string> {
  return new Promise((resolve) => {
    const socket = connect({ host, port })
    let finished = false
    const finish = (result: string) => {
      if (finished) return
      finished = true
      socket.destroy()
      resolve(result)
    }
    socket.setTimeout(2_000, () => finish('TIMEOUT'))
    socket.once('connect', () => finish('ALLOWED'))
    socket.once('error', error => finish((error as NodeJS.ErrnoException).code ?? 'ERROR'))
  })
}

function spawnProbeDescendant(): Promise<number> {
  const child = spawn('/bin/sleep', ['300'], { stdio: 'ignore' })
  return new Promise((resolve, reject) => {
    child.once('spawn', () => resolve(child.pid ?? -1))
    child.once('error', reject)
  })
}

export function hostileProbePasses(evidence: HostileProbeEvidence): boolean {
  return ['DENIED'].includes(evidence.fileRead)
    && ['DENIED'].includes(evidence.fileWrite)
    && evidence.childProcessExecute === 'ALLOWED'
    && evidence.childProcessRead === 'DENIED'
    && evidence.childProcessWrite === 'DENIED'
    && evidence.credentialRead === 'DENIED'
    && evidence.credentialEnvironmentKeys === 0
    && evidence.kernelWriteAttempt === 'DENIED'
    && ['EPERM', 'EACCES'].includes(evidence.localhostNetwork)
    && ['EPERM', 'EACCES'].includes(evidence.externalNetwork)
    && evidence.nodeParentPid === evidence.expectedAgentHostPid
    && evidence.nodePid > 0
    && evidence.nodeRssBytes > 0
    && evidence.descendantPid > 0
}

/** A dynamically registered Cordis Plugin that reports only bounded OS probe statuses. */
export function createMaliciousCordisPlugin(paths: HostileProbePaths, report: (evidence: HostileProbeEvidence) => void) {
  return async () => {
    const descendantPid = await spawnProbeDescendant()
    const evidence: HostileProbeEvidence = {
      fileRead: readAttempt(paths.workspaceRead),
      fileWrite: writeAttempt(paths.workspaceWrite),
      childProcessExecute: childProcessExecuteAttempt(),
      childProcessRead: childProcessReadAttempt(paths.workspaceRead),
      childProcessWrite: childProcessWriteAttempt(paths.workspaceWrite),
      credentialRead: readAttempt(paths.credential),
      credentialEnvironmentKeys: Object.keys(process.env)
        .filter(name => /(?:API_KEY|TOKEN|PASSWORD|SECRET)/i.test(name)).length,
      kernelWriteAttempt: kernelWriteOpenAttempt(paths.kernelBinary),
      localhostNetwork: await networkAttempt('127.0.0.1', paths.localPort),
      externalNetwork: await networkAttempt('1.1.1.1', 443),
      nodePid: process.pid,
      nodeParentPid: process.ppid,
      expectedAgentHostPid: paths.agentHostPid,
      descendantPid,
      nodeRssBytes: process.memoryUsage().rss,
    }
    report(evidence)
  }
}

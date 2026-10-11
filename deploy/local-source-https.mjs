#!/usr/bin/env node
// Local-only native deployment. No downloads, source rewrites or trust-store changes.
import fs from 'node:fs'
import path from 'node:path'
import net from 'node:net'
import http from 'node:http'
import https from 'node:https'
import { randomBytes } from 'node:crypto'
import { execFileSync, spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const run = path.join(root, '.dev/local-https')
const statePath = path.join(run, 'processes.json')
const secretPath = path.join(run, 'credentials.json')
const pgData = path.join(run, 'postgres')
const tools = {
  postgres: path.join(run, 'tools/postgresql/bin'),
  caddy: path.join(run, 'bin/caddy'),
  app: path.join(run, 'bin/sub2api'),
}
const pause = ms => new Promise(resolve => setTimeout(resolve, ms))
const execute = (file, args, env = {}) => execFileSync(file, args, {
  encoding: 'utf8', env: { ...process.env, LC_ALL: 'C', ...env }, stdio: ['ignore', 'pipe', 'pipe'],
})
const writePrivate = (name, value) => {
  fs.writeFileSync(name, value, { mode: 0o600 })
  fs.chmodSync(name, 0o600)
}

export function caddyConfig(directory) {
  return `{
  admin off
  auto_https off
  servers {
    max_header_size 64KB
    timeouts {
      read_header 10s
      idle 2m
    }
  }
}
https://127.0.0.1:8443 {
  bind 127.0.0.1
  tls ${JSON.stringify(path.join(directory, 'certs/server.pem'))} ${JSON.stringify(path.join(directory, 'certs/server-key.pem'))}
  request_body {
    max_size 256MB
  }
  reverse_proxy 127.0.0.1:18080 {
    header_up X-Real-IP {remote_host}
    header_up X-Forwarded-For {remote_host}
    header_up X-Forwarded-Proto https
    header_up -CF-Connecting-IP
    header_up -True-Client-IP
  }
}
`
}

export function redisConfig(directory, password) {
  if (!/^[a-f0-9]{64}$/.test(password)) throw new Error('Invalid generated Redis credential')
  return `bind 127.0.0.1
port 16379
protected-mode yes
daemonize no
dir ${JSON.stringify(path.join(directory, 'redis'))}
appendonly yes
appendfsync everysec
save 60 1
requirepass ${password}
`
}

function state() {
  return fs.existsSync(statePath) ? JSON.parse(fs.readFileSync(statePath, 'utf8')) : {}
}

function birth(pid) {
  if (!Number.isSafeInteger(pid) || pid < 2) return ''
  try { return execute('/bin/ps', ['-p', String(pid), '-o', 'lstart=']).trim() } catch { return '' }
}

function alive(record) {
  return Boolean(record?.birth && birth(record.pid) === record.birth)
}

async function portFree(port) {
  await new Promise((resolve, reject) => {
    const server = net.createServer()
    server.once('error', () => reject(new Error(`127.0.0.1:${port} is already in use; no process was terminated`)))
    server.listen(port, '127.0.0.1', () => server.close(resolve))
  })
}

function ensureReady() {
  for (const file of [tools.app, tools.caddy, path.join(tools.postgres, 'initdb'), path.join(run, 'certs/server.pem'), path.join(run, 'certs/server-key.pem')]) {
    if (!fs.existsSync(file)) throw new Error(`Missing prerequisite: ${file}`)
  }
  execute('redis-server', ['--version'])
}

async function launch(name, file, args, env = {}) {
  const records = state()
  if (alive(records[name])) return
  const log = fs.openSync(path.join(run, 'logs', `${name}.log`), 'a', 0o600)
  let child
  try {
    child = spawn(file, args, { detached: true, cwd: run, env: { ...process.env, ...env, LC_ALL: 'C' }, stdio: ['ignore', log, log] })
    await new Promise((resolve, reject) => { child.once('spawn', resolve); child.once('error', reject) })
  } finally { fs.closeSync(log) }
  records[name] = { pid: child.pid, birth: birth(child.pid) }
  writePrivate(statePath, JSON.stringify(records, null, 2))
  child.unref()
}

async function waitHealth(port, pathname, seconds = 90, ca) {
  const deadline = Date.now() + seconds * 1000
  while (Date.now() < deadline) {
    const ok = await new Promise(resolve => {
      const request = (ca ? https : http).get({ hostname: '127.0.0.1', port, path: pathname, timeout: 1500, ca }, response => {
        response.resume(); resolve(response.statusCode === 200)
      })
      request.on('timeout', () => request.destroy())
      request.on('error', () => resolve(false))
    })
    if (ok) return
    await pause(300)
  }
  throw new Error(`Health check timed out on 127.0.0.1:${port}; inspect private logs in ${run}/logs`)
}

async function start() {
  ensureReady()
  for (const dir of ['', 'logs', 'data', 'redis']) {
    fs.mkdirSync(path.join(run, dir), { recursive: true, mode: 0o700 })
    fs.chmodSync(path.join(run, dir), 0o700)
  }
  if (!fs.existsSync(secretPath)) {
    const secret = {
      admin_email: 'admin@local.invalid', admin_password: randomBytes(24).toString('base64url'),
      database_password: randomBytes(32).toString('hex'), redis_password: randomBytes(32).toString('hex'),
      jwt_secret: randomBytes(32).toString('hex'), totp_encryption_key: randomBytes(32).toString('hex'),
    }
    fs.writeFileSync(secretPath, JSON.stringify(secret, null, 2), { mode: 0o600, flag: 'wx' })
  }
  fs.chmodSync(secretPath, 0o600)
  const secret = JSON.parse(fs.readFileSync(secretPath, 'utf8'))
  const pgEnv = { PGPASSWORD: secret.database_password }
  const pg = name => path.join(tools.postgres, name)
  if (!fs.existsSync(path.join(pgData, 'PG_VERSION'))) {
    if (fs.existsSync(pgData) && fs.readdirSync(pgData).length) throw new Error('Refusing to initialize a nonempty PostgreSQL directory')
    writePrivate(path.join(run, 'pg-password'), secret.database_password)
    execute(pg('initdb'), ['-D', pgData, '-U', 'sub2api_local', '--auth=scram-sha-256', '--locale=C', '--encoding=UTF8', '--pwfile', path.join(run, 'pg-password')])
  }
  let pgRunning = false
  try { execute(pg('pg_ctl'), ['-D', pgData, 'status']); pgRunning = true } catch { /* isolated instance is stopped */ }
  if (!pgRunning) {
    await portFree(15432)
    execute(pg('pg_ctl'), ['-D', pgData, '-l', path.join(run, 'logs/postgres.log'), '-o', "-h 127.0.0.1 -p 15432 -k ''", '-w', '-t', '30', 'start'])
  }
  const connection = ['-h', '127.0.0.1', '-p', '15432', '-U', 'sub2api_local']
  const dbExists = execute(pg('psql'), [...connection, '-d', 'postgres', '-Atqc', "SELECT 1 FROM pg_database WHERE datname = 'sub2api'"], pgEnv).trim()
  if (dbExists !== '1') execute(pg('createdb'), [...connection, 'sub2api'], pgEnv)
  if (!alive(state().redis)) {
    await portFree(16379)
    writePrivate(path.join(run, 'redis.conf'), redisConfig(run, secret.redis_password))
    await launch('redis', 'redis-server', [path.join(run, 'redis.conf')])
  }
  let redisReady = false
  for (let i = 0; i < 30; i++) {
    try { redisReady = execute('redis-cli', ['-h', '127.0.0.1', '-p', '16379', 'ping'], { REDISCLI_AUTH: secret.redis_password }).trim() === 'PONG' } catch { /* starting */ }
    if (redisReady) break
    await pause(200)
  }
  if (!redisReady) throw new Error('Local Redis did not become ready')
  if (!alive(state().app)) {
    await portFree(18080)
    await launch('app', tools.app, [], {
      AUTO_SETUP: 'true', DATA_DIR: path.join(run, 'data'), CONFIG_FILE: '',
      SERVER_HOST: '127.0.0.1', SERVER_PORT: '18080', SERVER_MODE: 'release',
      SERVER_FRONTEND_URL: 'https://127.0.0.1:8443', SERVER_TRUSTED_PROXIES: '127.0.0.1/32',
      SECURITY_TRUST_FORWARDED_IP_FOR_API_KEY_ACL: 'false',
      DATABASE_HOST: '127.0.0.1', DATABASE_PORT: '15432', DATABASE_USER: 'sub2api_local',
      DATABASE_PASSWORD: secret.database_password, DATABASE_DBNAME: 'sub2api', DATABASE_SSLMODE: 'disable',
      REDIS_HOST: '127.0.0.1', REDIS_PORT: '16379', REDIS_PASSWORD: secret.redis_password,
      ADMIN_EMAIL: secret.admin_email, ADMIN_PASSWORD: secret.admin_password,
      JWT_SECRET: secret.jwt_secret, TOTP_ENCRYPTION_KEY: secret.totp_encryption_key,
      RUN_MODE: 'standard', GATEWAY_OPENAI_CHAT_CONTRACT_POLICY: process.env.GATEWAY_OPENAI_CHAT_CONTRACT_POLICY || 'strict',
      GATEWAY_OPENAI_CHAT_CONTRACT_STOP_MODE: process.env.GATEWAY_OPENAI_CHAT_CONTRACT_STOP_MODE || 'text',
      GATEWAY_OPENAI_CHAT_CONTRACT_DRAIN_TIMEOUT_SECONDS: process.env.GATEWAY_OPENAI_CHAT_CONTRACT_DRAIN_TIMEOUT_SECONDS || '30',
      TZ: 'Asia/Shanghai',
    })
  }
  await waitHealth(18080, '/health')
  if (!alive(state().caddy)) {
    await portFree(8443)
    writePrivate(path.join(run, 'Caddyfile'), caddyConfig(run))
    execute(tools.caddy, ['validate', '--config', path.join(run, 'Caddyfile'), '--adapter', 'caddyfile'])
    await launch('caddy', tools.caddy, ['run', '--config', path.join(run, 'Caddyfile'), '--adapter', 'caddyfile'])
  }
  await waitHealth(8443, '/health', 15, fs.readFileSync(path.join(run, 'ca/rootCA.pem')))
  console.log(`Started local stack. HTTPS: https://127.0.0.1:8443\nCredentials are stored privately at ${secretPath}; no secrets are printed.\nCA trust is unchanged; use ${run}/ca/rootCA.pem for client verification.`)
}

async function stop() {
  const records = state()
  for (const name of ['caddy', 'app', 'redis']) {
    const record = records[name]
    if (!alive(record)) continue
    process.kill(record.pid, 'SIGTERM')
    for (let i = 0; i < 150 && alive(record); i++) await pause(200)
    if (alive(record)) throw new Error(`${name} did not stop gracefully; no forced kill was performed`)
    delete records[name]
    writePrivate(statePath, JSON.stringify(records, null, 2))
  }
  if (fs.existsSync(path.join(pgData, 'postmaster.pid'))) execute(path.join(tools.postgres, 'pg_ctl'), ['-D', pgData, 'stop', '-m', 'fast', '-w', '-t', '30'])
  console.log('Stopped local services. Database, Redis data, certificates and credentials are preserved.')
}

async function main() {
  const action = process.argv[2] || '--help'
  if (action === '--help') { console.log('Usage: node deploy/local-source-https.mjs start|stop|status|--check\nRequires a source-built embed binary and local PostgreSQL/Caddy tools under .dev/local-https/.'); return }
  if (action === '--check') { ensureReady(); console.log('Prerequisites found; no services started.'); return }
  if (action === 'status') {
    const statuses = Object.fromEntries(Object.entries(state()).map(([name, record]) => [name, { pid: record.pid, running: alive(record) }]))
    let pgRunning = false
    try { execute(path.join(tools.postgres, 'pg_ctl'), ['-D', pgData, 'status']); pgRunning = true } catch { /* not started */ }
    statuses.postgres = { running: pgRunning }
    console.log(JSON.stringify(statuses, null, 2))
    return
  }
  if (!['start', 'stop'].includes(action)) throw new Error('Unknown action')
  fs.mkdirSync(run, { recursive: true, mode: 0o700 })
  const lockPath = path.join(run, 'lifecycle.lock')
  const lock = fs.openSync(lockPath, 'wx', 0o600)
  try { if (action === 'start') await start(); else await stop() }
  finally { fs.closeSync(lock); fs.unlinkSync(lockPath) }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(error => { console.error(error.message); process.exitCode = 1 })
}

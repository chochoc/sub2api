// Opt-in smoke check for the isolated instance; never prints credentials/tokens.
// Login creates an ordinary local session. Does not accept compliance or call an upstream.
import fs from 'node:fs'
import path from 'node:path'
import https from 'node:https'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'

const run = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../.dev/local-https')
const ca = fs.readFileSync(path.join(run, 'ca/rootCA.pem'))
const request = (url, method = 'GET', body, token) => new Promise((resolve, reject) => {
  const req = https.request({
    hostname: '127.0.0.1', port: 8443, path: url, method, ca, timeout: 10000,
    headers: {
      ...(body ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  }, res => {
    let text = ''
    res.on('data', part => { text += part })
    res.on('error', reject)
    res.on('end', () => resolve({ status: res.statusCode, type: res.headers['content-type'], body: text }))
  })
  req.on('error', reject)
  req.on('timeout', () => req.destroy(new Error('Local HTTPS request timed out')))
  req.end(body ? JSON.stringify(body) : undefined)
})

const health = await request('/health')
assert.equal(health.status, 200)
assert.equal(JSON.parse(health.body).status, 'ok')
const root = await request('/')
assert.equal(root.status, 200)
assert.match(root.body, /<div id="app"/)
const asset = root.body.match(/src="([^"]+\.js)"/)
assert.ok(asset, 'Embedded UI must reference its JavaScript')
const js = await request(asset[1])
assert.equal(js.status, 200)
assert.match(js.type, /javascript/)
const logo = await request('/logo.svg')
assert.equal(logo.status, 200)
assert.match(logo.type, /image\/svg\+xml/)
assert.match(logo.body, /<svg/)
assert.equal((await request('/v1/models')).status, 401)
const credentials = JSON.parse(fs.readFileSync(path.join(run, 'credentials.json'), 'utf8'))
const login = await request('/api/v1/auth/login', 'POST', { email: credentials.admin_email, password: credentials.admin_password })
assert.equal(login.status, 200)
const token = JSON.parse(login.body).data?.access_token
assert.ok(token, 'Login must return an access token')
const compliance = await request('/api/v1/admin/compliance', 'GET', undefined, token)
assert.equal(compliance.status, 200)
console.log('Verified HTTPS health, embedded UI/JS/SVG, unauthenticated 401, admin login and compliance status. No compliance accepted; no upstream called.')

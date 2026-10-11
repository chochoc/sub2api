import assert from 'node:assert/strict'
import { caddyConfig, redisConfig } from '../local-source-https.mjs'

const directory = '/private/local test'
const caddy = caddyConfig(directory)
assert.match(caddy, /https:\/\/127\.0\.0\.1:8443/)
assert.match(caddy, /bind 127\.0\.0\.1/)
assert.match(caddy, /admin off/)
assert.match(caddy, /reverse_proxy 127\.0\.0\.1:18080/)
assert.match(caddy, /header_up -CF-Connecting-IP/)
assert.ok(!/0\.0\.0\.0|flush_interval|encode gzip/.test(caddy))
assert.match(caddy, /"\/private\/local test\/certs\/server.pem"/)
const redis = redisConfig(directory, 'a'.repeat(64))
assert.match(redis, /bind 127\.0\.0\.1/)
assert.match(redis, /protected-mode yes/)
assert.match(redis, /appendonly yes/)
assert.throws(() => redisConfig(directory, 'password\nbind 0.0.0.0'))
console.log('Local HTTPS configuration checks passed (no services or secrets created).')

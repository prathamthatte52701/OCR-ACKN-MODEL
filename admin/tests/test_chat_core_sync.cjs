// Plain Node check (no runner): node admin/tests/test_chat_core_sync.cjs
// The admin app keeps a byte-for-byte copy of the user app's chatCore.js (one chat logic, two apps).
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const userCopy = path.join(__dirname, '..', '..', 'frontend', 'src', 'utils', 'chatCore.js')
const adminCopy = path.join(__dirname, '..', 'src', 'utils', 'chatCore.js')

const a = fs.readFileSync(userCopy)
const b = fs.readFileSync(adminCopy)
assert.ok(a.length > 0, 'user chatCore.js is empty')
assert.ok(
  a.equals(b),
  'admin/src/utils/chatCore.js differs from frontend/src/utils/chatCore.js - edit the user app copy and copy it over unchanged',
)
console.log('OK: chatCore.js is identical in both apps')

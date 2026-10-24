// Plain Node check (no runner): node frontend/tests/test_notice_codes.cjs
const assert = require('node:assert/strict')
const path = require('node:path')
const { pathToFileURL } = require('node:url')

;(async () => {
  const file = path.join(__dirname, '..', 'src', 'utils', 'noticeCodes.js')
  const { noticeText, codeFromDetail } = await import(pathToFileURL(file).href)

  assert.equal(noticeText('pending'), 'Waiting for admin approval.')
  assert.equal(noticeText('rejected'), 'Your request was not approved. Contact the admin.')
  assert.equal(noticeText('revoked'), 'Your request was not approved. Contact the admin.')
  assert.equal(noticeText('sent'), 'Your request was sent. Sign in again after the admin approves.')

  for (const bad of ['', undefined, null, 42, {}, ['pending'], 'Call 98xxxx', '<script>', '%3Cb%3E',
    '__proto__', 'constructor', 'toString', 'hasOwnProperty', 'PENDING', ' pending', 'pending ']) {
    assert.equal(noticeText(bad), '', `noticeText(${JSON.stringify(bad)}) must be empty`)
  }

  assert.equal(codeFromDetail({ code: 'ACCOUNT_PENDING', message: 'Waiting for admin approval.' }), 'pending')
  assert.equal(codeFromDetail({ code: 'ACCOUNT_PENDING', message: 'Your request was sent. Sign in again after the admin approves.' }), 'sent')
  assert.equal(codeFromDetail({ code: 'ACCOUNT_REJECTED' }), 'rejected')
  assert.equal(codeFromDetail({ code: 'ACCOUNT_REVOKED' }), 'revoked')
  for (const bad of [undefined, null, {}, { code: 'PASSWORD_CHANGE_REQUIRED' }, { code: 'ACCOUNT_OTHER' },
    { code: '__proto__' }, { code: 'constructor' }, { code: 5 }, 'ACCOUNT_PENDING']) {
    assert.equal(codeFromDetail(bad), null, `codeFromDetail(${JSON.stringify(bad)}) must be null`)
  }

  console.log('OK: notice code checks passed')
})().catch((e) => { console.error('FAIL:', e.message); process.exit(1) })

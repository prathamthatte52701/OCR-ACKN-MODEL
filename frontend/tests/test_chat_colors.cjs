// Plain Node check (no runner): node frontend/tests/test_chat_colors.cjs
const assert = require('node:assert/strict')
const path = require('node:path')
const { pathToFileURL } = require('node:url')

const ALLOWED = ['blue', 'violet', 'teal', 'green', 'amber', 'orange', 'rose', 'slate']

function luminance(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
  const lin = (c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
}
function contrast(fg, bg) {
  const [hi, lo] = [luminance(fg), luminance(bg)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

;(async () => {
  const mod = await import(pathToFileURL(path.join(__dirname, '..', 'src', 'utils', 'chatColors.js')).href)
  const { CHAT_COLORS, NEUTRAL_BUBBLE, colorById } = mod

  assert.deepEqual(CHAT_COLORS.map((c) => c.id), ALLOWED)
  for (const c of CHAT_COLORS) {
    assert.match(c.bubble, /^#[0-9a-f]{6}$/i)
    assert.match(c.text, /^#[0-9a-f]{6}$/i)
    assert.ok(c.label)
    const ratio = contrast(c.text, c.bubble)
    assert.ok(ratio >= 4.5, `${c.id} contrast ${ratio.toFixed(2)} < 4.5`)
  }
  assert.ok(contrast(NEUTRAL_BUBBLE.text, NEUTRAL_BUBBLE.bubble) >= 4.5)

  assert.equal(colorById('rose').bubble, '#e11d48')
  assert.equal(colorById('nope').id, 'blue') // unknown -> default
  assert.equal(colorById(undefined).id, 'blue')

  console.log('OK: chatColors')
})().catch((e) => {
  console.error('FAIL:', e.message)
  process.exit(1)
})

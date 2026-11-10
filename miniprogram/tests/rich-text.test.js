const { test } = require('node:test')
const assert = require('node:assert/strict')
const { extractRich, makeMedia } = require('../utils/rich-text')

test('plain text stays as a single text segment', () => {
  const segs = extractRich('纯文本没有链接')
  assert.equal(segs.length, 1)
  assert.equal(segs[0].type, 'text')
})

test('markdown link becomes a tappable link segment', () => {
  const segs = extractRich('详见 [官方文档](https://siyumenghai.cn/doc) 了解')
  const link = segs.find((s) => s.type === 'link')
  assert.ok(link, 'should contain a link segment')
  assert.equal(link.url, 'https://siyumenghai.cn/doc')
  assert.ok(segs.some((s) => s.type === 'text' && s.text.includes('详见')))
})

test('bare url becomes a link segment', () => {
  const segs = extractRich('访问 https://siyumenghai.cn 看看')
  const link = segs.find((s) => s.type === 'link')
  assert.equal(link.url, 'https://siyumenghai.cn')
})

test('image url becomes an image segment', () => {
  assert.equal(makeMedia('https://x.cn/a.jpg').type, 'image')
  assert.equal(makeMedia('https://x.cn/a.PNG').type, 'image')
})

test('video url becomes a video segment', () => {
  assert.equal(makeMedia('https://x.cn/a.mp4').type, 'video')
  assert.equal(makeMedia('https://x.cn/a.MOV').type, 'video')
})

test('url followed by chinese punctuation is not swallowed', () => {
  const segs = extractRich('看这个 https://x.cn/a.png。下一张')
  const img = segs.find((s) => s.type === 'image')
  assert.equal(img.url, 'https://x.cn/a.png')
  assert.ok(segs.some((s) => s.type === 'text' && s.text.includes('下一张')))
})

test('empty input is safe', () => {
  assert.deepEqual(extractRich(''), [{ type: 'text', text: '' }])
  assert.deepEqual(extractRich(null), [{ type: 'text', text: '' }])
})

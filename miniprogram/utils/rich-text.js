// 把纯文本里的链接/图片/视频解析成可渲染片段，让 AI 回答里的链接能直接跳转、
// 图片/视频能预览或保存到相册。失败也不影响正文展示。
function makeMedia(url) {
  const lower = url.split('?')[0].toLowerCase()
  if (/\.(png|jpe?g|gif|webp|bmp|svg)$/.test(lower)) return { type: 'image', url }
  if (/\.(mp4|mov|webm|m3u8|avi|mkv)$/.test(lower)) return { type: 'video', url }
  return { type: 'link', url, display: url }
}

function extractRich(text) {
  if (!text) return [{ type: 'text', text: '' }]
  const segs = []
  const pushText = (s) => { if (s) segs.push({ type: 'text', text: s }) }
  const md = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g // [文字](https://...)
  let last = 0, m
  while ((m = md.exec(text)) !== null) {
    pushText(text.slice(last, m.index))
    segs.push(makeMedia(m[2]))
    last = m.index + m[0].length
  }
  const rest = text.slice(last)
  const urlRe = /(https?:\/\/[^\s，。、；：！？）)】」』<>]+)/g // 裸链接
  let last2 = 0, m2
  while ((m2 = urlRe.exec(rest)) !== null) {
    pushText(rest.slice(last2, m2.index))
    segs.push(makeMedia(m2[1]))
    last2 = m2.index + m2[0].length
  }
  pushText(rest.slice(last2))
  return segs.length ? segs : [{ type: 'text', text: '' }]
}

function safeRich(text) {
  try { return extractRich(text) } catch (_) { return undefined }
}

module.exports = { makeMedia, extractRich, safeRich }

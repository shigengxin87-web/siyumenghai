// 本地收藏：技巧 / 讨论 / 素材记录，统一存 storage
const KEY = 'sdh_favorites_v1'
const MAX = 200

function load() {
  try { const data = wx.getStorageSync(KEY); return Array.isArray(data) ? data : [] } catch (_) { return [] }
}

function idOf(item) {
  return [item.type, item.key].join(':')
}

function has(item) {
  const id = idOf(item)
  return load().some(i => idOf(i) === id)
}

function toggle(item) {
  const id = idOf(item)
  let list = load()
  const idx = list.findIndex(i => idOf(i) === id)
  if (idx >= 0) {
    list.splice(idx, 1)
  } else {
    list.unshift(Object.assign({ createdAt: Date.now() }, item))
    if (list.length > MAX) list = list.slice(0, MAX)
  }
  try { wx.setStorageSync(KEY, list) } catch (_) {}
  return { list, favorited: idx < 0 }
}

function remove(item) {
  const id = idOf(item)
  const list = load().filter(i => idOf(i) !== id)
  try { wx.setStorageSync(KEY, list) } catch (_) {}
  return list
}

module.exports = { load, has, toggle, remove }
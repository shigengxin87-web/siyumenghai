// 用户标识：与 AI 问答页共用同一个存储键，保证档案与对话属于同一人
function uid() {
  let id = ''
  try { id = wx.getStorageSync('sdh_uid') } catch (e) {}
  if (!id) {
    id = 'u' + Date.now() + Math.floor(Math.random() * 10000)
    try { wx.setStorageSync('sdh_uid', id) } catch (e) {}
  }
  return id
}

module.exports = { uid }

const app = getApp()
const realTips = require('../../data/tips')

// 技巧正文：当前为示例占位，后续从知识库整理后整体替换
const CONTENT = {
  1: {
    title: '社群信息沉淀怎么做才不废',
    cat: '私域运营',
    body: [
      '群聊里每天都有高价值讨论，但截图收藏基本等于丢失——过几天就再也找不到了。',
      '做法是给讨论分三桶：方法论（可复用的套路）、案例（真实发生的故事和数据）、选题（值得展开聊的话题）。',
      '录音/群聊结束后，用妙记内容工坊一键拆解归档进多维表格，再同步进知识库，后续写内容时直接调素材。'
    ],
    links: [
      { title: '石董会 · 一起成长朋友圈（member-view）', url: 'https://siyumenghai.cn/member-view/' },
      { title: '飞书知识库', url: app.globalData.links.feishu }
    ]
  },
  2: {
    title: '朋友圈怎么发才不像广告',
    cat: '私域运营',
    body: [
      '给社群/熟人写的内容，最忌“工整的 AI 味”。',
      '保留括号备注、碎碎念式补充、具体人名案例；挂相关旧文/对话链接当延伸阅读——不是装饰，是让读者对相关背景感兴趣时能点进去看。',
      '写的时候想象自己在群里跟朋友说话，别端着。'
    ],
    links: [
      { title: '石董会 · 一起成长朋友圈（member-view）', url: 'https://siyumenghai.cn/member-view/' }
    ]
  },
  3: {
    title: '私域激活体系三步走',
    cat: '私域运营',
    body: [
      '第一步：进群即见价值——新人一进来就能拿到可用的东西（清单、模板、案例）。',
      '第二步：持续产出——固定节奏输出方法论和案例拆解，让成员养成“在这能学到东西”的预期。',
      '第三步：激活与转化——把沉淀的内容做成产品/服务，用真实案例驱动下单。'
    ],
    links: [
      { title: '私域激活体系 · 完整 PPT', url: 'https://siyumenghai.cn/member-view/' }
    ]
  },
  4: {
    title: '口播视频的黄金结构',
    cat: '内容制作',
    body: [
      '3 秒钩子：第一句就要让人想听完（反常识、戳痛点、给承诺）。',
      '干货主体：30-60 秒只讲一件事，讲透一个小方法，配具体例子。',
      '行动指令：结尾给出一个能立刻做的动作，引导评论/关注/私信。'
    ],
    links: [
      { title: '石董会 · 一起成长朋友圈（member-view）', url: 'https://siyumenghai.cn/member-view/' }
    ]
  },
  5: {
    title: '录音一键变五平台文案',
    cat: '内容制作',
    body: [
      '用妙记内容工坊：录音一结束说一句「整理妙记」，自动拆成方法论、案例、选题存进多维表格。',
      '选定一个选题后，自动翻出相关素材，直接生成朋友圈/小红书/公众号/视频号/抖音文案。',
      '不用再东拼西凑搭工作流，一个多维表格当看板中台，工具越少越用得起来。'
    ],
    links: [
      { title: '腾讯 ima 知识库', url: app.globalData.links.ima },
      { title: '石董会 · 一起成长朋友圈（member-view）', url: 'https://siyumenghai.cn/member-view/' }
    ]
  },
  6: {
    title: '直播回放怎么沉淀成图文',
    cat: '内容制作',
    body: [
      '下载回放视频 → 转逐字稿 → 按章节分段 → 修正错别字 → 建文档归档到知识库。',
      '沉淀后的逐字稿既能当公众号文章底稿，也能拆出金句、案例和选题，一鱼多吃。'
    ],
    links: [
      { title: '飞书知识库', url: app.globalData.links.feishu }
    ]
  },
  7: {
    title: '用豆包工作搓自动化工作流',
    cat: 'AI 工具',
    body: [
      '把高频重复动作（整理录音、归档素材、生成文案）搓成 skill，一次配置，长期复用。',
      '原理：让工具自动建知识库、多维表格、定时任务，把整条链路固化下来，别人装上就能用。',
      '工具越多越容易用着用着就不用了——原生、一体化的流程才持久。'
    ],
    links: [
      { title: '石董会 · 一起成长朋友圈（member-view）', url: 'https://siyumenghai.cn/member-view/' }
    ]
  },
  8: {
    title: '腾讯元器搭社群问答助手',
    cat: 'AI 工具',
    body: [
      '在腾讯元器创建智能体，把知识库（案例、方法论、课程内容）作为知识来源。',
      '发布 API 服务拿到 appid 和 appkey，接进小程序/网站，成员随时提问，回答严格基于你的内容。',
      '元器接口并发上限 10，对社群规模完全够用；密钥放服务端转发，别写进前端。'
    ],
    links: [
      { title: '腾讯 ima 知识库', url: app.globalData.links.ima },
      { title: '石董会 · 一起成长朋友圈（member-view）', url: 'https://siyumenghai.cn/member-view/' }
    ]
  },
  9: {
    title: '视频号视频怎么下载',
    cat: '微信生态',
    body: [
      '打开石董会小程序「知识库」里的视频号下载，或直接访问 member-view 网站的下载工具页。',
      '复制视频号视频链接，粘贴进下载工具即可拉取视频文件，用于二次创作和素材沉淀。'
    ],
    links: [
      { title: '视频号下载工具', url: app.globalData.links.video }
    ]
  },
  10: {
    title: '小程序里怎么进知识库',
    cat: '微信生态',
    body: [
      '飞书知识库、腾讯 ima 都是外部链接，小程序内嵌不了——点「复制链接」，去浏览器打开即可。',
      '石董会自己的页面（member-view、视频号下载）可以小程序内直接打开，无需跳转。'
    ],
    links: [
      { title: '飞书知识库', url: app.globalData.links.feishu },
      { title: '腾讯 ima 知识库', url: app.globalData.links.ima }
    ]
  }
}

Page({
  data: {
    id: null,
    detail: null
  },

  onLoad(options) {
    const id = String(options.id || '')
    const cache = wx.getStorageSync('sdh_real_tips');
    const detail = (Array.isArray(cache) ? cache.find(t => String(t.id) === id) : null) || realTips.find(t => String(t.id) === id) || CONTENT[id] || null
    this.setData({ id, detail })
    if (!detail && app.globalData.contentApi) {
      wx.request({ url: app.globalData.contentApi, success: res => {
        if (res.statusCode !== 200 || !res.data || !Array.isArray(res.data.tips)) return;
        const found = res.data.tips.find(t => String(t.id) === id);
        if (found) { this.setData({ detail: found }); wx.setNavigationBarTitle({ title: found.title }); }
      } });
    }
    if (detail) {
      wx.setNavigationBarTitle({ title: detail.title })
    }
  },

  onLinkTap(e) {
    const url = e.currentTarget.dataset.url
    // 自家域名可以直接在小程序内打开，外部链接复制到浏览器
    if (url.indexOf('siyumenghai.cn') > -1) {
      wx.navigateTo({ url: '/pages/webview/webview?url=' + encodeURIComponent(url) })
    } else {
      wx.setClipboardData({
        data: url,
        success: () => wx.showToast({ title: '链接已复制，去浏览器打开', icon: 'none' })
      })
    }
  },

  onShareAppMessage() {
    const d = this.data.detail
    return { title: d ? d.title : '石董会 · 技巧库', path: '/pages/tips-detail/tips-detail?id=' + encodeURIComponent(this.data.id) }
  }
})

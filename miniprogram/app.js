// 石董会 成员服务小程序
App({
  globalData: {
    brandName: '石董会',
    slogan: '一起成长，一起越来越好',
    links: {
      // member-view 网站上的三个资源入口
      feishu: 'https://my.feishu.cn/wiki/space/7663061611179003182?ccm_open_type=lark_wiki_spaceLink&open_tab_from=wiki_home',
      ima: 'https://ima.qq.com/wiki/?shareId=9ac78c43931491aa0c6bfff1ac1be9de7e4c81bc22cd066d2c2fd2cb2ffe2a79',
      video: 'https://siyumenghai.cn/member-view/video-downloader-20260808-17.html'
    },
    agent: {
      // 元器问答代理：服务端转发，避免 appkey 暴露在小程序前端
      apiUrl: 'https://siyumenghai.cn/api/agent/chat',
      assistantId: '2101324897978088512'
    },
    // 官网数据源（讨论板块同步用）
    siteBase: 'https://siyumenghai.cn/member-view',
    contentApi: 'https://siyumenghai.cn/member-view/miniprogram-content.json',
    tipsApi: 'https://siyumenghai.cn/member-view/miniprogram-content.json'
  }
})

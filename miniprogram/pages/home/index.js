const { reports, reportKeys } = require('../../data/reports');

const views = [
  { id: 'overview', number: '01', label: '今日概览' },
  { id: 'actions', number: '02', label: '行动清单' },
  { id: 'weekly', number: '03', label: '七日回顾' },
  { id: 'topics', number: '04', label: '专题沉淀' },
  { id: 'resources', number: '05', label: '资源连接' },
  { id: 'discussion', number: '06', label: '原始讨论' },
];

const lensOptions = [
  { id: 'all', label: '全部' },
  { id: 'content', label: '做内容' },
  { id: 'product', label: '做产品' },
  { id: 'private', label: '做私域' },
];

const topicOptions = [
  { id: 'content', label: '做内容', title: '用内容建立理解和信任', description: '从表达钩子、直播路径到朋友圈信任资产，持续积累能被看见的专业证明。' },
  { id: 'product', label: '做产品', title: '从表面问题找到真实结果', description: '把功能表达向后追问，直到看见客户真正想获得的结果、身份和选择。' },
  { id: 'private', label: '做私域', title: '把关系沉淀成经营资产', description: '用承接、迁移、备份和资源连接，让一次触达变成可持续的客户关系。' },
];

function dateOption(key) {
  const date = new Date(`${key}T00:00:00+08:00`);
  return {
    key,
    label: reports[key].dateLabel,
    fullLabel: `${reports[key].dateLabel} · ${reports[key].weekday}`,
    shortLabel: `${date.getMonth() + 1}/${date.getDate()}`,
    day: ['日', '一', '二', '三', '四', '五', '六'][date.getDay()],
  };
}

const dateOptions = reportKeys.map(dateOption);

function insightWithIndex(insight, index) {
  return { ...insight, displayIndex: String(index + 1).padStart(2, '0') };
}

function buildTopicCollection(topicId) {
  const definition = topicOptions.find((topic) => topic.id === topicId) || topicOptions[0];
  const items = [];
  reportKeys.slice().reverse().forEach((key) => {
    reports[key].insights.forEach((insight, index) => {
      if ((insight.roles || []).includes(topicId)) {
        items.push({ ...insight, key, uniqueKey: `${key}-${index}`, dateLabel: reports[key].dateLabel });
      }
    });
  });
  return { ...definition, items };
}

Page({
  data: {
    reportKeys,
    dateOptions,
    recentDateOptions: dateOptions,
    selectedKey: reportKeys[reportKeys.length - 1],
    selectedDateIndex: reportKeys.length - 1,
    report: reports[reportKeys[reportKeys.length - 1]],
    views,
    lensOptions,
    activeLens: 'all',
    visibleInsights: reports[reportKeys[reportKeys.length - 1]].insights.map(insightWithIndex),
    currentView: 'overview',
    completedActions: {},
    completedCount: 0,
    actionProgress: 0,
    weekly: {},
    topicOptions,
    activeTopic: 'content',
    topicCollection: buildTopicCollection('content'),
  },

  onLoad(options) {
    const selectedKey = reports[options.date] ? options.date : this.data.selectedKey;
    this.loadReport(selectedKey);
    this.buildWeekly(selectedKey);
  },

  onShow() {
    const pendingDate = wx.getStorageSync('growth-pending-date');
    if (reports[pendingDate]) {
      wx.removeStorageSync('growth-pending-date');
      this.loadReport(pendingDate);
      this.setData({ currentView: 'overview' });
      wx.pageScrollTo({ scrollTop: 0, duration: 0 });
    }
    this.loadActionState();
  },

  loadReport(selectedKey) {
    const report = reports[selectedKey];
    this.setData({
      selectedKey,
      selectedDateIndex: reportKeys.indexOf(selectedKey),
      report,
      activeLens: 'all',
      visibleInsights: report.insights.map(insightWithIndex),
    });
    this.loadActionState(selectedKey);
    this.buildWeekly(selectedKey);
  },

  loadActionState(selectedKey = this.data.selectedKey) {
    const completedActions = {};
    reports[selectedKey].actions.forEach((_, index) => {
      completedActions[index] = wx.getStorageSync(`growth-action-${selectedKey}-${index}`) === 'done';
    });
    const completedCount = Object.values(completedActions).filter(Boolean).length;
    const actionCount = reports[selectedKey].actions.length;
    this.setData({
      completedActions,
      completedCount,
      actionProgress: actionCount ? Math.round((completedCount / actionCount) * 100) : 0,
    });
  },

  buildWeekly(selectedKey = this.data.selectedKey) {
    const endIndex = reportKeys.indexOf(selectedKey);
    const keys = reportKeys.slice(Math.max(0, endIndex - 6), endIndex + 1);
    const weekly = keys.reduce((summary, key) => {
      const report = reports[key];
      summary.messages += report.messages;
      summary.themes += report.themesCount;
      summary.actions += report.actions.length;
      summary.days.push({ key, dateLabel: report.dateLabel, weekday: report.weekday, title: report.title });
      return summary;
    }, { messages: 0, themes: 0, actions: 0, days: [] });
    this.setData({ weekly });
  },

  copyLink(event) {
    const url = event.currentTarget.dataset.url;
    if (!url) return;
    wx.setClipboardData({
      data: url,
      success: () => wx.showToast({ title: '链接已复制', icon: 'success' }),
    });
  },

  onDateChange(event) {
    this.loadReport(reportKeys[Number(event.detail.value)]);
  },

  selectDate(event) {
    this.loadReport(event.currentTarget.dataset.key);
  },

  switchView(event) {
    this.setData({ currentView: event.currentTarget.dataset.view });
    wx.pageScrollTo({ scrollTop: 330, duration: 180 });
  },

  switchLens(event) {
    const activeLens = event.currentTarget.dataset.lens;
    const visibleInsights = this.data.report.insights
      .filter((insight) => activeLens === 'all' || (insight.roles || []).includes(activeLens))
      .map(insightWithIndex);
    this.setData({ activeLens, visibleInsights });
  },

  switchTopic(event) {
    const activeTopic = event.currentTarget.dataset.topic;
    this.setData({ activeTopic, topicCollection: buildTopicCollection(activeTopic) });
  },

  openDay(event) {
    this.loadReport(event.currentTarget.dataset.key);
    this.setData({ currentView: 'overview' });
    wx.pageScrollTo({ scrollTop: 0, duration: 250 });
  },

  toggleAction(event) {
    const index = Number(event.currentTarget.dataset.index);
    const done = event.detail.value.length > 0;
    const key = `growth-action-${this.data.selectedKey}-${index}`;
    if (done) wx.setStorageSync(key, 'done');
    else wx.removeStorageSync(key);
    this.setData({ [`completedActions.${index}`]: done }, () => {
      const completedCount = Object.values(this.data.completedActions).filter(Boolean).length;
      const actionCount = this.data.report.actions.length;
      this.setData({ completedCount, actionProgress: actionCount ? Math.round((completedCount / actionCount) * 100) : 0 });
    });
  },

  copyToday() {
    const report = this.data.report;
    wx.setClipboardData({
      data: `【成长朋友圈 · ${report.dateLabel}】\n${report.title}\n\n${report.summary}`,
    });
  },

  onShareAppMessage() {
    const report = this.data.report;
    return {
      title: `${report.dateLabel}｜${report.title}`,
      path: `/pages/home/index?date=${this.data.selectedKey}`,
    };
  },

  onShareTimeline() {
    return {
      title: `成长朋友圈｜${this.data.report.title}`,
      query: `date=${this.data.selectedKey}`,
    };
  },
});

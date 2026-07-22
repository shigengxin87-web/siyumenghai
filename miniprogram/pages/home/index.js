const { reports, reportKeys } = require('../../data/reports');

const views = [
  { id: 'overview', number: '01', label: '今日概览' },
  { id: 'actions', number: '02', label: '行动清单' },
  { id: 'weekly', number: '03', label: '学习回顾' },
  { id: 'resources', number: '04', label: '资源连接' },
  { id: 'discussion', number: '05', label: '原始讨论' },
];

Page({
  data: {
    reportKeys,
    dateOptions: reportKeys.map((key) => ({ key, label: reports[key].dateLabel })),
    selectedKey: reportKeys[reportKeys.length - 1],
    selectedDateIndex: reportKeys.length - 1,
    report: reports[reportKeys[reportKeys.length - 1]],
    views,
    currentView: 'overview',
    completedActions: {},
    weekly: {},
  },

  onLoad(options) {
    const selectedKey = reports[options.date] ? options.date : this.data.selectedKey;
    this.loadReport(selectedKey);
    this.buildWeekly();
  },

  onShow() {
    this.loadActionState();
  },

  loadReport(selectedKey) {
    this.setData({
      selectedKey,
      selectedDateIndex: reportKeys.indexOf(selectedKey),
      report: reports[selectedKey],
    });
    this.loadActionState(selectedKey);
  },

  loadActionState(selectedKey = this.data.selectedKey) {
    const completedActions = {};
    reports[selectedKey].actions.forEach((_, index) => {
      completedActions[index] = wx.getStorageSync(`growth-action-${selectedKey}-${index}`) === 'done';
    });
    this.setData({ completedActions });
  },

  buildWeekly() {
    const weekly = reportKeys.reduce((summary, key) => {
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
    this.setData({ [`completedActions.${index}`]: done });
  },

  openMembers() {
    wx.navigateTo({ url: '/pages/members/index' });
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

const { reports, reportKeys } = require('../../data/reports');

const days = reportKeys.slice().reverse().map((key) => ({
  key,
  dateLabel: reports[key].dateLabel,
  weekday: reports[key].weekday,
  title: reports[key].title,
  summary: reports[key].summary,
  messages: reports[key].messages,
  themes: reports[key].themesCount,
}));

const totals = reportKeys.reduce((result, key) => {
  result.messages += reports[key].messages;
  result.themes += reports[key].themesCount;
  result.actions += reports[key].actions.length;
  return result;
}, { messages: 0, themes: 0, actions: 0 });

Page({
  data: {
    days,
    totals,
  },

  openDay(event) {
    wx.setStorageSync('growth-pending-date', event.currentTarget.dataset.key);
    wx.switchTab({ url: '/pages/home/index' });
  },

  onShareAppMessage() {
    return {
      title: '成长朋友圈｜日报归档',
      path: '/pages/archive/index',
    };
  },
});

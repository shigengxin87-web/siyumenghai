const { reports, reportKeys } = require('../../data/reports');

const days = reportKeys.slice().reverse().map((key) => {
  const parts = key.split('-');
  return {
    key,
    monthId: `${parts[0]}-${parts[1]}`,
    month: `${Number(parts[1])}月`,
    day: String(Number(parts[2])).padStart(2, '0'),
    dateLabel: reports[key].dateLabel,
    weekday: reports[key].weekday,
    title: reports[key].title,
    summary: reports[key].summary,
    messages: reports[key].messages,
    themes: reports[key].themesCount,
  };
});

const monthIds = Array.from(new Set(days.map((day) => day.monthId)));
const monthOptions = [{ id: 'all', label: '全部' }].concat(monthIds.map((id) => ({
  id,
  label: `${Number(id.split('-')[1])} 月`,
})));

const totals = reportKeys.reduce((result, key) => {
  result.messages += reports[key].messages;
  result.themes += reports[key].themesCount;
  return result;
}, { messages: 0, themes: 0 });

Page({
  data: {
    days,
    filteredDays: days,
    totals,
    query: '',
    monthOptions,
    activeMonth: 'all',
  },

  filterDays(query = this.data.query, activeMonth = this.data.activeMonth) {
    const keyword = query.trim().toLowerCase();
    const filteredDays = days.filter((day) => {
      const matchMonth = activeMonth === 'all' || day.monthId === activeMonth;
      const haystack = `${day.dateLabel} ${day.weekday} ${day.title} ${day.summary}`.toLowerCase();
      return matchMonth && (!keyword || haystack.includes(keyword));
    });
    this.setData({ query, activeMonth, filteredDays });
  },

  onSearch(event) {
    this.filterDays(event.detail.value, this.data.activeMonth);
  },

  switchMonth(event) {
    this.filterDays(this.data.query, event.currentTarget.dataset.month);
  },

  openDay(event) {
    wx.setStorageSync('growth-pending-date', event.currentTarget.dataset.key);
    wx.switchTab({ url: '/pages/home/index' });
  },

  onShareAppMessage() {
    return { title: '石董会｜社群日报归档', path: '/pages/archive/index' };
  },
});

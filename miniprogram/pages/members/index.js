const { members } = require('../../data/members');

Page({
  data: {
    members,
    filteredMembers: members,
    query: '',
  },

  onSearch(event) {
    const query = event.detail.value.trim().toLowerCase();
    const filteredMembers = query
      ? members.filter((member) => member.name.toLowerCase().includes(query))
      : members;
    this.setData({ query, filteredMembers });
  },

  onShareAppMessage() {
    return {
      title: `石董会｜${members.length} 位群友名录`,
      path: '/pages/members/index',
    };
  },
});

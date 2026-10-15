// 领课二维码页：点击放大预览，长按识别二维码
Page({
  data: {
    qrUrl: "/images/wechat-qr.jpg",
  },

  // 点击二维码：全屏预览（可双指放大，方便扫/保存）
  previewQr() {
    wx.previewImage({
      current: this.data.qrUrl,
      urls: [this.data.qrUrl],
    });
  },

  onShareAppMessage() {
    return {
      title: "添加老师微信，领取课程",
      path: "/pages/qrcode/index",
    };
  },
});

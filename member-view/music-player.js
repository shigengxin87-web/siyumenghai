(() => {
  const audio = document.querySelector('[data-background-music]');
  const button = document.querySelector('[data-music-toggle]');
  const icon = document.querySelector('[data-music-icon]');
  const label = document.querySelector('[data-music-label]');
  if (!audio || !button || !icon || !label) return;
  let manuallyPaused = false;

  const updateButton = () => {
    const playing = !audio.paused;
    button.classList.toggle('is-playing', playing);
    button.setAttribute('aria-pressed', String(playing));
    button.setAttribute('aria-label', playing ? '暂停背景音乐' : '播放背景音乐');
    icon.textContent = playing ? 'Ⅱ' : '▶';
    label.textContent = playing ? '暂停' : '播放';
  };

  const startMusic = async () => {
    if (manuallyPaused) return false;
    try {
      audio.muted = false;
      audio.defaultMuted = false;
      await audio.play();
      updateButton();
      return true;
    } catch (_) {
      updateButton();
      return false;
    }
  };

  button.addEventListener('click', async () => {
    if (audio.paused) {
      manuallyPaused = false;
      await startMusic();
    } else {
      manuallyPaused = true;
      audio.pause();
    }
    updateButton();
  });

  audio.addEventListener('play', updateButton);
  audio.addEventListener('pause', updateButton);
  audio.addEventListener('ended', updateButton);

  const unlockOnFirstInteraction = (event) => {
    if (event.target.closest('[data-music-toggle]') || !audio.paused || manuallyPaused) return;
    startMusic();
  };
  document.addEventListener('pointerdown', unlockOnFirstInteraction, { once: true, capture: true });
  document.addEventListener('touchstart', unlockOnFirstInteraction, { once: true, capture: true, passive: true });
  document.addEventListener('keydown', unlockOnFirstInteraction, { once: true, capture: true });

  // WeChat allows media playback when its native bridge becomes ready, even
  // when a normal browser load-time play() call was rejected.
  const tryWechatAutoplay = () => {
    if (!manuallyPaused && audio.paused) startMusic();
  };
  document.addEventListener('WeixinJSBridgeReady', tryWechatAutoplay, false);
  document.addEventListener('YixinJSBridgeReady', tryWechatAutoplay, false);
  window.addEventListener('load', tryWechatAutoplay, { once: true });
  window.addEventListener('pageshow', tryWechatAutoplay);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') tryWechatAutoplay();
  });

  updateButton();
  startMusic();
})();

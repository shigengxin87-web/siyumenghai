(() => {
  const audio = document.querySelector('[data-background-music]');
  const button = document.querySelector('[data-music-toggle]');
  const icon = document.querySelector('[data-music-icon]');
  const label = document.querySelector('[data-music-label]');
  if (!audio || !button || !icon || !label) return;

  const updateButton = () => {
    const playing = !audio.paused;
    button.classList.toggle('is-playing', playing);
    button.setAttribute('aria-pressed', String(playing));
    button.setAttribute('aria-label', playing ? '暂停背景音乐' : '播放背景音乐');
    icon.textContent = playing ? 'Ⅱ' : '▶';
    label.textContent = playing ? '暂停' : '播放';
  };

  const startMusic = async () => {
    try {
      await audio.play();
      updateButton();
      return true;
    } catch (_) {
      updateButton();
      return false;
    }
  };

  button.addEventListener('click', async () => {
    if (audio.paused) await startMusic();
    else audio.pause();
    updateButton();
  });

  audio.addEventListener('play', updateButton);
  audio.addEventListener('pause', updateButton);
  audio.addEventListener('ended', updateButton);

  const unlockOnFirstInteraction = (event) => {
    if (event.target.closest('[data-music-toggle]') || !audio.paused) return;
    startMusic();
  };
  document.addEventListener('pointerdown', unlockOnFirstInteraction, { once: true, capture: true });
  document.addEventListener('keydown', unlockOnFirstInteraction, { once: true, capture: true });

  updateButton();
  startMusic();
})();

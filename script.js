(function () {
  const fill = document.querySelector(".progress-bar .fill");
  function updateProgress() {
    if (!fill) return;
    const root = document.documentElement;
    const max = root.scrollHeight - root.clientHeight;
    const pct = max > 0 ? (root.scrollTop / max) * 100 : 0;
    fill.style.width = pct + "%";
  }
  window.addEventListener("scroll", updateProgress, { passive: true });
  updateProgress();

  const links = [...document.querySelectorAll(".anchors a[href^='#']")];
  const targets = links
    .map((link) => [link, document.querySelector(link.getAttribute("href"))])
    .filter((pair) => pair[1]);

  if ("IntersectionObserver" in window && targets.length) {
    const observer = new IntersectionObserver((entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
      if (!visible) return;
      links.forEach((link) => link.classList.remove("active"));
      const active = targets.find((pair) => pair[1] === visible.target);
      if (active) active[0].classList.add("active");
    }, { threshold: 0.2, rootMargin: "-80px 0px -50% 0px" });
    targets.forEach((pair) => observer.observe(pair[1]));
  }
})();

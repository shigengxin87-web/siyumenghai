const STOP_WORDS = new Set("这个 一个 一种 时候 其实 就是 还是 因为 所以 但是 如果 只有 没有 什么 怎么 这么 那么 他们 她们 自己 我们 你们 你 他 她 的 了 和 是 在 也 都 很 有 不 这 那 人 让 去 来 能 会 真 太 看 说 做 还 没 到 给 把 对 里 中 上 下 过 被 之 而 与 或 及 也许 可能 感觉 觉得 现在 当时 真的 原来 一起 年轻 年少 老师 杨老师 周老师 视频 强 爱心 笑哭 我要 我也 这样 我的 你的 都是 还有 一定 非常 更多 比较 以后 所有 就有 都有 一切 好的".split(/\s+/));

let mainComments = [];
let replies = [];
let keywordBase = [];
let selectedWord = null;
let query = "";
let mode = "count";
let visibleCount = 12;
let isPaused = false;
let spotlightIndex = 0;
let spotlightTimer;

const $ = (selector) => document.querySelector(selector);

function cleanText(value) {
  return String(value ?? "").replace(/\/?\:?strong/gi, "").replace(/\[([^\]]+)\]/g, "$1").replace(/\/:\w+/g, "").replace(/\s+/g, " ").trim();
}

function wordsFrom(text) {
  const clean = cleanText(text).replace(/[a-zA-Z0-9_]+/g, " ");
  if (typeof Intl.Segmenter !== "function") return clean.match(/[\u3400-\u9fff]{2,4}/g) ?? [];
  const segmenter = new Intl.Segmenter("zh-CN", { granularity: "word" });
  return Array.from(segmenter.segment(clean)).filter((part) => part.isWordLike).map((part) => part.segment.trim()).filter((word) => word.length >= 2 && !STOP_WORDS.has(word));
}

function buildKeywords() {
  const index = new Map();
  mainComments.forEach((comment) => {
    const words = wordsFrom(comment["评论内容"]);
    const unique = new Set(words);
    words.forEach((word) => {
      const current = index.get(word) ?? { count: 0, likes: 0 };
      current.count += 1;
      index.set(word, current);
    });
    unique.forEach((word) => { const current = index.get(word); if (current) current.likes += Number(comment["点赞数"]) || 0; });
  });
  return Array.from(index, ([word, data]) => ({ word, ...data }));
}

function packWords(words, width, height) {
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d");
  if (!context || !width || !height) return [];
  const maxScore = Math.max(...words.map((item) => item.score));
  const minScore = Math.min(...words.map((item) => item.score));
  const mobile = width < 640;
  const minSize = mobile ? 13 : 15;
  const maxSize = mobile ? 45 : 68;
  const boxes = [];
  const placed = [];
  words.forEach((item, index) => {
    const ratio = maxScore === minScore ? 1 : (item.score - minScore) / (maxScore - minScore);
    const size = Math.round(minSize + Math.pow(ratio, .48) * (maxSize - minSize));
    context.font = `${index < 8 ? 700 : 600} ${size}px PingFang SC, sans-serif`;
    const wordWidth = context.measureText(item.word).width + (mobile ? 10 : 18);
    const wordHeight = size * 1.28;
    for (let step = 0; step < 1000; step += 1) {
      const angle = step * .38 + index * .71;
      const radius = 2 + step * (mobile ? .72 : .82);
      const x = width / 2 + Math.cos(angle) * radius * 1.2;
      const y = height / 2 + Math.sin(angle) * radius * .72;
      const box = { left: x - wordWidth / 2, top: y - wordHeight / 2, right: x + wordWidth / 2, bottom: y + wordHeight / 2 };
      const inside = box.left > 8 && box.right < width - 8 && box.top > 8 && box.bottom < height - 8;
      const overlaps = boxes.some((other) => !(box.right + 4 < other.left || box.left - 4 > other.right || box.bottom + 3 < other.top || box.top - 3 > other.bottom));
      if (inside && !overlaps) { boxes.push(box); placed.push({ ...item, x, y, size, color: index % 5, delay: (index % 9) * -.42 }); break; }
    }
  });
  return placed;
}

function renderCloud() {
  const stage = $("#cloudStage");
  stage.querySelectorAll(".cloud-word").forEach((node) => node.remove());
  const { width, height } = stage.getBoundingClientRect();
  const mobile = width < 640;
  const limit = mobile ? (mode === "count" ? 36 : 32) : (mode === "count" ? 54 : 46);
  const words = keywordBase.map((item) => ({ ...item, score: mode === "count" ? item.count : item.likes })).sort((a, b) => b.score - a.score).slice(0, limit);
  const placed = packWords(words, width, height);
  placed.forEach((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `cloud-word color-${item.color}${selectedWord === item.word ? " selected" : ""}`;
    button.textContent = item.word;
    button.title = `${item.word}：出现 ${item.count} 次，关联点赞 ${item.likes}`;
    Object.assign(button.style, { left: `${item.x}px`, top: `${item.y}px`, fontSize: `${item.size}px`, animationDelay: `${item.delay}s` });
    button.addEventListener("click", () => { selectedWord = selectedWord === item.word ? null : item.word; query = ""; $("#searchInput").value = ""; visibleCount = 12; renderCloud(); renderComments(); $("#echoes").scrollIntoView({ behavior: "smooth" }); });
    stage.appendChild(button);
  });
  $("#wordTotal").textContent = `当前展示 ${placed.length} 个关键词`;
}

function filteredComments() {
  const needle = String(selectedWord ?? query).trim().toLowerCase();
  const base = needle ? mainComments.filter((item) => cleanText(item["评论内容"]).toLowerCase().includes(needle) || String(item["昵称"]).toLowerCase().includes(needle)) : mainComments;
  return [...base].sort((a, b) => Number(b["点赞数"]) - Number(a["点赞数"]));
}

function renderComments() {
  const filtered = filteredComments();
  const shown = filtered.slice(0, visibleCount);
  const grid = $("#commentGrid");
  grid.replaceChildren();
  shown.forEach((comment, index) => {
    const article = document.createElement("article");
    article.className = "comment-card";
    const safeName = document.createTextNode(String(comment["昵称"]));
    const commentText = cleanText(comment["评论内容"]);
    article.innerHTML = `<div class="comment-index">${String(index + 1).padStart(2, "0")}</div><p></p>${commentText.length > 105 ? '<button class="comment-expand" type="button">展开全文 ↓</button>' : ''}<footer><div class="avatar"></div><div><strong></strong><span></span></div><b>♡ ${Number(comment["点赞数"]) || 0}</b></footer>`;
    article.querySelector("p").textContent = commentText;
    article.querySelector(".avatar").textContent = String(comment["昵称"]).slice(0, 1);
    article.querySelector("strong").appendChild(safeName);
    article.querySelector("footer span").textContent = String(comment["IP属地"] ?? "");
    article.querySelector(".comment-expand")?.addEventListener("click", (event) => {
      const paragraph = article.querySelector("p");
      const expanded = paragraph.classList.toggle("expanded");
      event.currentTarget.textContent = expanded ? "收起全文 ↑" : "展开全文 ↓";
    });
    grid.appendChild(article);
  });
  $("#emptyState").hidden = shown.length !== 0;
  $("#commentsMore").hidden = shown.length === 0;
  $("#shownCount").textContent = shown.length;
  $("#matchedCount").textContent = filtered.length;
  const loadButton = $("#loadMore");
  if (shown.length < filtered.length) { loadButton.disabled = false; loadButton.className = ""; loadButton.innerHTML = `再看 12 条 <span aria-hidden="true">↓</span>`; }
  else { loadButton.disabled = false; loadButton.className = "all-loaded"; loadButton.innerHTML = `已看完全部评论 <span aria-hidden="true">✓</span>`; }
  const filterNote = $("#filterNote");
  filterNote.hidden = !selectedWord;
  if (selectedWord) $("#filterText").textContent = `正在查看含“${selectedWord}”的评论，共 ${filtered.length} 条`;
}

function renderSpotlight(featured) {
  const comment = featured[spotlightIndex % featured.length];
  $("#spotlightQuote").textContent = `“${cleanText(comment["评论内容"])}”`;
  $("#spotlightName").textContent = String(comment["昵称"]);
  $("#spotlightRegion").textContent = `来自 ${comment["IP属地"]}`;
  $("#spotlightLikes").textContent = `♡ ${comment["点赞数"]}`;
}

async function init() {
  try {
    const response = await fetch("comments.json");
    if (!response.ok) throw new Error("评论数据加载失败");
    const records = await response.json();
    mainComments = records.filter((item) => item["类型"] === "主评论");
    replies = records.filter((item) => item["类型"] === "回复");
    keywordBase = buildKeywords();
    const totalLikes = mainComments.reduce((sum, item) => sum + (Number(item["点赞数"]) || 0), 0);
    const regionCount = new Set(mainComments.map((item) => item["IP属地"]).filter(Boolean)).size;
    document.title = `因为相信｜${mainComments.length}条评论动态词云`;
    $("#heroCount").textContent = mainComments.length;
    $("#statComments").textContent = mainComments.length;
    $("#statLikes").textContent = totalLikes.toLocaleString("zh-CN");
    $("#statRegions").textContent = regionCount;
    $("#sourceCount").textContent = `基于 ${mainComments.length} 条主评论自动分词`;
    $("#sourceSummary").textContent = `基于表格中的 ${mainComments.length} 条主评论生成；${replies.length} 条回复未纳入词频统计。`;
    const featured = [...mainComments].sort((a, b) => Number(b["点赞数"]) - Number(a["点赞数"])).slice(0, 12);
    renderCloud(); renderComments(); renderSpotlight(featured);
    spotlightTimer = setInterval(() => { if (!isPaused) { spotlightIndex = (spotlightIndex + 1) % featured.length; renderSpotlight(featured); } }, 4800);
    $("#loading").remove(); $("#site").hidden = false;
    requestAnimationFrame(renderCloud);
    let resizeTimer; window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(renderCloud, 150); });
  } catch (error) {
    $("#loading").className = "error-screen";
    $("#loading").textContent = `页面加载失败：${error.message}`;
  }
}

document.querySelectorAll("[data-mode]").forEach((button) => button.addEventListener("click", () => { mode = button.dataset.mode; document.querySelectorAll("[data-mode]").forEach((item) => item.classList.toggle("active", item === button)); renderCloud(); }));
$("#pauseButton").addEventListener("click", () => { isPaused = !isPaused; $("#pauseButton b").textContent = isPaused ? "继续流动" : "暂停流动"; $("#pauseButton .pulse-dot").classList.toggle("paused", isPaused); $("#cloudStage").classList.toggle("paused", isPaused); $("#tickerTrack").classList.toggle("paused", isPaused); });
const themeAudio = $("#themeAudio");
themeAudio.volume = .58;

function startThemeAudio() {
  if (isPaused || !themeAudio.paused) return;
  const attempt = themeAudio.play();
  if (attempt?.catch) attempt.catch(() => {});
}

function syncPauseState() {
  if (isPaused) themeAudio.pause();
  else startThemeAudio();
}

$("#pauseButton").addEventListener("click", syncPauseState);
window.addEventListener("load", startThemeAudio, { once: true });
document.addEventListener("DOMContentLoaded", startThemeAudio, { once: true });
document.addEventListener("WeixinJSBridgeReady", startThemeAudio, { once: true });
document.addEventListener("visibilitychange", () => { if (!document.hidden) startThemeAudio(); });
["touchstart", "pointerdown", "keydown"].forEach((eventName) => {
  document.addEventListener(eventName, startThemeAudio, { once: true, passive: true });
});
$("#searchInput").addEventListener("input", (event) => { query = event.target.value; selectedWord = null; visibleCount = 12; renderCloud(); renderComments(); });
$("#clearFilter").addEventListener("click", () => { selectedWord = null; visibleCount = 12; renderCloud(); renderComments(); });
$("#loadMore").addEventListener("click", () => { const total = filteredComments().length; if (visibleCount < total) { visibleCount += 12; renderComments(); } else { $("#echoes").scrollIntoView({ behavior: "smooth" }); } });

init();

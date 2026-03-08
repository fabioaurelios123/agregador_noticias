"use strict";

// ===== STATE =====
let allArticles = [];
let currentPage = 1;
let currentCategory = "";
let wsRetries = 0;

// ===== CLOCK =====
function updateClock() {
  const el = document.getElementById("clock");
  if (!el) return;
  const now = new Date();
  const date = now.toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "long", year: "numeric" });
  const time = now.toLocaleTimeString("pt-BR");
  el.textContent = `${date}  |  ${time}`;
}
setInterval(updateClock, 1000);
updateClock();

// ===== CATEGORY UTILS =====
const CAT_LABELS = {
  politica: "Política", economia: "Economia", saude: "Saúde",
  tech: "Tech", esporte: "Esporte", geral: "Geral",
};

function catClass(cat) {
  return "cat-" + (cat || "geral");
}
function catLabel(cat) {
  return CAT_LABELS[cat] || (cat ? cat.charAt(0).toUpperCase() + cat.slice(1) : "Geral");
}

function timeAgo(iso) {
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "agora mesmo";
  if (diff < 3600) return `${Math.floor(diff / 60)}min atrás`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h atrás`;
  return `${Math.floor(diff / 86400)}d atrás`;
}

// ===== RENDER FEATURED =====
function renderFeatured(article) {
  if (!article) return;
  const img = document.getElementById("featuredImg");
  const title = document.getElementById("featuredTitle");
  const source = document.getElementById("featuredSource");
  const cat = document.getElementById("featuredCat");

  img.src = article.image_url || "/static/placeholder.svg";
  img.alt = article.title;
  title.textContent = article.title;
  source.textContent = `${article.source}  ·  ${timeAgo(article.published_at)}`;
  cat.textContent = catLabel(article.category);
  cat.className = "category-tag";

  document.getElementById("featuredCard").onclick = () => window.open(article.url, "_blank");
}

// ===== RENDER SECONDARY =====
function renderSecondary(articles) {
  const grid = document.getElementById("secondaryGrid");
  grid.innerHTML = "";
  articles.slice(1, 5).forEach(a => {
    const card = document.createElement("div");
    card.className = "secondary-card";
    card.onclick = () => window.open(a.url, "_blank");
    card.innerHTML = `
      <img class="secondary-card-img" src="${a.image_url || ''}" alt="" onerror="this.style.display='none'">
      <div class="secondary-card-body">
        <span class="secondary-card-cat ${catClass(a.category)}">${catLabel(a.category)}</span>
        <div class="secondary-card-title">${escHtml(a.title)}</div>
        <div class="secondary-card-source">${escHtml(a.source)}  ·  ${timeAgo(a.published_at)}</div>
      </div>
    `;
    grid.appendChild(card);
  });
}

// ===== RENDER NEWS LIST =====
function renderNewsList(articles, append = false) {
  const list = document.getElementById("newsList");
  if (!append) list.innerHTML = "";

  articles.forEach((a, i) => {
    const card = document.createElement("div");
    card.className = "news-card";
    card.dataset.id = a.id;
    card.onclick = () => window.open(a.url, "_blank");
    card.innerHTML = `
      <img class="news-card-img" src="${a.image_url || ''}" alt="" onerror="this.style.display='none'">
      <div class="news-card-body">
        <span class="news-card-cat ${catClass(a.category)}">${catLabel(a.category)}</span>
        <div class="news-card-title">${escHtml(a.title)}</div>
        <div class="news-card-meta">
          <span>${escHtml(a.source)}</span>
          <span>${timeAgo(a.published_at)}</span>
        </div>
      </div>
    `;
    list.appendChild(card);
  });
}

// ===== TICKER =====
function renderTicker(articles) {
  const content = document.getElementById("tickerContent");
  if (!articles.length) return;
  // Duplicate items for seamless scroll
  const items = [...articles, ...articles].map(a =>
    `<span class="ticker-item">${escHtml(a.title)}</span>`
  ).join("");
  content.innerHTML = items;
}

// ===== LOAD NEWS =====
async function loadNews(page = 1, append = false) {
  try {
    const catParam = currentCategory ? `&category=${currentCategory}` : "";
    const res = await fetch(`/api/news?page=${page}&per_page=20${catParam}`);
    const data = await res.json();
    allArticles = append ? [...allArticles, ...data.articles] : data.articles;

    if (page === 1 && data.articles.length) {
      renderFeatured(data.articles[0]);
      renderSecondary(data.articles);
    }
    renderNewsList(data.articles, append);
    renderTicker(data.articles.slice(0, 15));

    const countEl = document.getElementById("newsCount");
    if (countEl) countEl.textContent = `${data.total} notícias`;

    currentPage = page;
  } catch (e) {
    console.error("Failed to load news:", e);
  }
}

async function loadMore() {
  await loadNews(currentPage + 1, true);
}

// ===== TOP NEWS (initial hero) =====
async function loadTopNews() {
  try {
    const catParam = currentCategory ? `?category=${currentCategory}` : "";
    const res = await fetch(`/api/news/top${catParam}`);
    const data = await res.json();
    if (data.articles && data.articles.length) {
      renderFeatured(data.articles[0]);
      renderSecondary(data.articles);
      renderTicker(data.articles);
    }
  } catch (e) {
    console.error("Failed to load top news:", e);
  }
}

// ===== CATEGORY FILTER =====
document.querySelectorAll(".cat-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".cat-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    currentCategory = btn.dataset.cat;
    currentPage = 1;
    loadTopNews();
    loadNews(1, false);
  });
});

// ===== STREAM STATUS =====
async function loadStreamStatus() {
  try {
    const res = await fetch("/api/stream/status");
    const data = await res.json();
    const el = document.getElementById("streamStatus");
    if (el) {
      const modeIcon = data.mode === "live" ? "📡" : "🔄";
      el.textContent = `${modeIcon} ${data.mode === "live" ? "Ao vivo" : "Replay"}  ·  ${data.total_episodes} ep.`;
    }
  } catch (_) {}
}

// ===== WEBSOCKET =====
function connectWebSocket() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/news`);

  ws.onopen = () => {
    wsRetries = 0;
    // Heartbeat
    setInterval(() => { if (ws.readyState === WebSocket.OPEN) ws.send("ping"); }, 25000);
  };

  ws.onmessage = (evt) => {
    if (evt.data === "pong") return;
    try {
      const msg = JSON.parse(evt.data);
      if (msg.type === "news_update" && msg.articles) {
        handleNewsUpdate(msg.articles);
      }
    } catch (_) {}
  };

  ws.onclose = () => {
    const delay = Math.min(30000, 2000 * Math.pow(2, wsRetries++));
    setTimeout(connectWebSocket, delay);
  };
}

function handleNewsUpdate(articles) {
  if (!articles.length) return;

  // Show breaking banner for top new article
  const top = articles[0];
  const banner = document.getElementById("breakingBanner");
  const breakingText = document.getElementById("breakingText");
  if (banner && breakingText) {
    breakingText.textContent = top.title;
    banner.style.display = "flex";
    setTimeout(() => { banner.style.display = "none"; }, 8000);
  }

  // Prepend new cards to news list with flash effect
  const list = document.getElementById("newsList");
  articles.slice(0, 3).forEach(a => {
    const existing = list.querySelector(`[data-id="${a.id}"]`);
    if (existing) return;

    const card = document.createElement("div");
    card.className = "news-card new-item";
    card.dataset.id = a.id;
    card.onclick = () => window.open(a.url, "_blank");
    card.innerHTML = `
      <img class="news-card-img" src="${a.image_url || ''}" alt="" onerror="this.style.display='none'">
      <div class="news-card-body">
        <span class="news-card-cat ${catClass(a.category)}">${catLabel(a.category)}</span>
        <div class="news-card-title">${escHtml(a.title)}</div>
        <div class="news-card-meta">
          <span>${escHtml(a.source)}</span>
          <span>agora mesmo</span>
        </div>
      </div>
    `;
    list.prepend(card);
  });

  // Update featured
  renderFeatured(articles[0]);
  renderTicker(articles.slice(0, 15));
}

// ===== XSS GUARD =====
function escHtml(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ===== INIT =====
(async () => {
  await loadTopNews();
  await loadNews(1);
  await loadStreamStatus();
  connectWebSocket();
  setInterval(loadStreamStatus, 60000);
})();

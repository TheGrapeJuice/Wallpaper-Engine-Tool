const tabs = Array.from(document.querySelectorAll(".tab"));
const panels = Array.from(document.querySelectorAll(".panel"));
const grid = document.getElementById("grid");
const downloadGrid = document.getElementById("download-grid");
const statusLabel = document.getElementById("status");
const downloadStatus = document.getElementById("download-status");
const searchInput = document.getElementById("search");
const sortSelect = document.getElementById("sort-method");
const timeSelect = document.getElementById("time-period");
const prevBtn = document.getElementById("prev-page");
const nextBtn = document.getElementById("next-page");
const pageInfo = document.getElementById("page-info");
const refreshBtn = document.getElementById("refresh-btn");
const refreshDownloadsBtn = document.getElementById("refresh-downloads");
const installInfo = document.getElementById("install-info");
let activeTab = (document.querySelector(".tab.active") || { dataset: { tab: "top" } }).dataset.tab;
let downloadedMap = new Map();
let api = null;
let currentPage = 1;
let activeDownloadId = null;
let progressTimer = null;
let progressValue = 0;

const apiWaitMs = 100;
const apiWaitMax = 50;
const httpApiBase = "http://127.0.0.1:5005/api";

function setStatus(text) {
  statusLabel.textContent = text;
}

function setDownloadStatus(text) {
  downloadStatus.textContent = text;
}

async function callApi(method, ...args) {
  if (api && api[method]) {
    return api[method](...args);
  }
  throw new Error("API not available: " + method);
}

function buildHttpApi() {
  const getJson = async (url) => {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  };
  const postJson = async (url, body) => {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  };
  const deleteReq = async (url) => {
    const res = await fetch(url, { method: "DELETE" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  };

  return {
    async get_info() {
      return getJson(`${httpApiBase}/info`);
    },
    async list_downloads() {
      return getJson(`${httpApiBase}/downloads`);
    },
    async search_workshop(searchtext, page = 1, sortmethod = "trend", timeperiod = "-1") {
      const params = new URLSearchParams({
        searchtext: searchtext || "",
        page,
        sortmethod,
        timeperiod,
      });
      return getJson(`${httpApiBase}/search?${params.toString()}`);
    },
    async get_item(id) {
      return getJson(`${httpApiBase}/item/${encodeURIComponent(id)}`);
    },
    async download(id) {
      return postJson(`${httpApiBase}/download`, { workshop_id: id });
    },
    async delete(id) {
      return deleteReq(`${httpApiBase}/download/${encodeURIComponent(id)}`);
    },
    async open_folder(id) {
      return postJson(`${httpApiBase}/open-folder`, { workshop_id: id });
    },
  };
}

function refreshActiveTab(tabName) {
  if (tabName === "top") {
    loadWorkshop();
  } else if (tabName === "downloads") {
    loadDownloads();
  }
}

tabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    const nextTab = tab.dataset.tab;
    tabs.forEach((t) => t.classList.remove("active"));
    panels.forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    document.getElementById(nextTab).classList.add("active");
    if (nextTab !== activeTab) {
      refreshActiveTab(nextTab);
      activeTab = nextTab;
    }
  });
});

async function loadInfo() {
  try {
    const data = await callApi("get_info");
    const install = data.install_dir || "Not found";
    const depot = data.depot_exists ? "DepotDownloaderMod found" : "DepotDownloaderMod missing";
    installInfo.textContent = "Install: " + install + " - " + depot;
  } catch (err) {
    installInfo.textContent = "Install not found";
    console.error("get_info failed", err);
  }
}

function renderDownloadedActions(container, item) {
  const pathText = document.createElement("p");
  pathText.className = "path";
  pathText.textContent = item.pathShort || item.path || "";
  const actions = document.createElement("div");
  actions.className = "actions";
  const openBtn = document.createElement("button");
  openBtn.textContent = "Open folder";
  openBtn.addEventListener("click", () => openFolder(item.id));
  const deleteBtn = document.createElement("button");
  deleteBtn.textContent = "Remove";
  deleteBtn.addEventListener("click", async () => {
    await deleteFolder(item.id);
    await loadDownloads();
    await loadWorkshop();
  });
  actions.appendChild(openBtn);
  actions.appendChild(deleteBtn);
  container.appendChild(pathText);
  container.appendChild(actions);
}

function createCard(item) {
  const downloadedInfo = downloadedMap.get(item.id);
  const tpl = document.getElementById("card-template");
  const node = tpl.content.cloneNode(true);
  node.querySelector(".thumb").src = item.img || "";
  node.querySelector(".thumb").alt = item.title;
  node.querySelector(".title").textContent = item.title;
  node.querySelector(".author").textContent = item.author || "Unknown";
  node.querySelector(".rating").textContent = item.rating || "";
  const downloadBtn = node.querySelector(".download-btn");
  downloadBtn.dataset.id = item.id;
  const actionContainer = node.querySelector(".actions");

  if (downloadedInfo) {
    downloadBtn.remove();
    renderDownloadedActions(actionContainer, downloadedInfo);
  } else {
    downloadBtn.textContent = "Download";
    downloadBtn.addEventListener("click", async () => {
      if (activeDownloadId && activeDownloadId !== item.id) return;
      downloadBtn.dataset.downloading = "true";
      startFakeProgress(item.id);
      try {
        const res = await callApi("download", item.id);
        if (!res.success) {
          throw new Error(res.message || "Download failed");
        }
        finishFakeProgress(res.path ? `Saved to ${res.path}` : res.message || "Downloaded");
        await loadDownloads();
        await loadWorkshop();
        tabs.find((t) => t.dataset.tab === "downloads").click();
      } catch (err) {
        finishFakeProgress(`Failed: ${err.message}`);
        alert(`Download failed: ${err.message}`);
        console.error("download failed", err);
      } finally {
        downloadBtn.dataset.downloading = "false";
        updateDownloadButtons();
      }
    });
  }
  return node;
}

function renderItems(items) {
  grid.innerHTML = "";
  const frag = document.createDocumentFragment();
  items.forEach((item) => frag.appendChild(createCard(item)));
  grid.appendChild(frag);
  setStatus(`Showing ${items.length} wallpaper${items.length === 1 ? "" : "s"}`);
  updateDownloadButtons();
}

function updatePageLabel() {
  pageInfo.textContent = `Page ${currentPage}`;
}

function setLoadingUI(isLoading) {
  grid.classList.toggle("loading", isLoading);
  [refreshBtn, prevBtn, nextBtn, sortSelect, timeSelect, searchInput].forEach((el) => {
    if (el) el.disabled = isLoading;
  });
  if (isLoading) {
    statusLabel.textContent = `Loading page ${currentPage}...`;
  }
}

function updateDownloadButtons() {
  const buttons = Array.from(document.querySelectorAll(".download-btn"));
  buttons.forEach((btn) => {
    const id = btn.dataset.id;
    const isActive = activeDownloadId && activeDownloadId !== id;
    btn.disabled = !!isActive || btn.dataset.downloading === "true";
    if (btn.dataset.downloading === "true") {
      btn.textContent = `Downloading ${progressValue}%`;
    } else if (isActive) {
      btn.textContent = "Wait...";
    } else {
      btn.textContent = "Download";
    }
  });
}

function startFakeProgress(id) {
  activeDownloadId = id;
  progressValue = 0;
  downloadStatus.textContent = "Downloading 0%";
  updateDownloadButtons();
  if (progressTimer) {
    clearInterval(progressTimer);
  }
  progressTimer = setInterval(() => {
    progressValue = Math.min(progressValue + Math.floor(Math.random() * 10) + 5, 97);
    downloadStatus.textContent = `Downloading ${progressValue}%`;
    updateDownloadButtons();
  }, 500);
}

function finishFakeProgress(message) {
  progressValue = 100;
  downloadStatus.textContent = message || "Downloaded";
  if (progressTimer) {
    clearInterval(progressTimer);
    progressTimer = null;
  }
  activeDownloadId = null;
  updateDownloadButtons();
}

async function loadWorkshop() {
  setLoadingUI(true);
  try {
    const term = (searchInput.value || "").trim();
    if (term && /^\d{6,}$/.test(term)) {
      return loadById(term);
    }
    const data = await callApi("search_workshop", term, currentPage, sortSelect.value, timeSelect.value);
  if (!data.items || data.items.length === 0) {
    setStatus("Nothing found");
    grid.innerHTML = "";
    return;
  }
  renderItems(data.items);
    updatePageLabel();
  } catch (err) {
    setStatus("Failed to load");
    console.error("search_workshop failed", err);
    alert(`Error loading workshop: ${err.message}`);
  } finally {
    setLoadingUI(false);
  }
}

async function loadById(id) {
  const clean = (id || "").trim();
  if (!clean) return;
  setLoadingUI(true);
  setStatus(`Loading ${clean}...`);
  try {
    const data = await callApi("get_item", clean);
    renderItems([data]);
    setStatus(`Showing item ${clean}`);
  } catch (err) {
    setStatus("Failed to load ID");
    console.error("get_item failed", err);
    alert(`Error loading item: ${err.message}`);
  } finally {
    setLoadingUI(false);
  }
}

async function openFolder(id) {
  try {
    await callApi("open_folder", id);
  } catch (err) {
    alert(`Failed to open folder: ${err.message}`);
    console.error("open_folder failed", err);
  }
}

async function deleteFolder(id) {
  try {
    await callApi("delete", id);
    await loadDownloads();
  } catch (err) {
    alert(`Failed to delete: ${err.message}`);
    console.error("delete failed", err);
  }
}

async function loadDownloads() {
  setDownloadStatus("Loading...");
  downloadGrid.innerHTML = "";
  try {
    const data = await callApi("list_downloads");
    downloadedMap = new Map((data.items || []).map((it) => [it.id, it]));
    if (!data.items || data.items.length === 0) {
      setDownloadStatus("No downloads yet");
      return;
    }
    const frag = document.createDocumentFragment();
    data.items.forEach((item) => {
      const card = document.createElement("article");
      card.className = "card";
      const thumb = document.createElement("img");
      thumb.className = "thumb";
      thumb.src = item.img || "";
      thumb.alt = item.title || item.id;
      card.appendChild(thumb);
      const body = document.createElement("div");
      body.className = "card-body";
      const header = document.createElement("div");
      header.className = "title-row";
      const title = document.createElement("h3");
      title.className = "title";
      title.textContent = item.title || `Workshop ${item.id}`;
      const rating = document.createElement("span");
      rating.className = "rating";
      rating.textContent = item.rating || "";
      header.appendChild(title);
      header.appendChild(rating);
      const author = document.createElement("p");
      author.className = "author";
      author.textContent = item.author || "";
      const path = document.createElement("p");
      path.className = "path";
      path.textContent = item.pathShort || item.path;
      const actions = document.createElement("div");
      actions.className = "actions";
      const openBtn = document.createElement("button");
      openBtn.textContent = "Open folder";
      openBtn.addEventListener("click", () => openFolder(item.id));
      const deleteBtn = document.createElement("button");
      deleteBtn.textContent = "Remove";
      deleteBtn.addEventListener("click", () => deleteFolder(item.id));
      actions.appendChild(openBtn);
      actions.appendChild(deleteBtn);
      body.appendChild(header);
      body.appendChild(author);
      body.appendChild(path);
      body.appendChild(actions);
      card.appendChild(body);
      frag.appendChild(card);
    });
    downloadGrid.appendChild(frag);
    setDownloadStatus(`${data.items.length} downloaded`);
  } catch (err) {
    setDownloadStatus("Failed to load downloads");
    console.error("list_downloads failed", err);
  }
}

function waitForApiAndInit() {
  console.log("Waiting for pywebview API...");
  let attempts = 0;
  const timer = setInterval(() => {
    api = window.pywebview ? window.pywebview.api : null;
    if (api) {
      clearInterval(timer);
      console.log("pywebview API ready");
      loadInfo();
      loadDownloads().then(loadWorkshop);
    } else if (attempts++ > apiWaitMax) {
      clearInterval(timer);
      console.error("pywebview API not available after waiting, enabling HTTP fallback");
      useHttpFallback();
    }
  }, apiWaitMs);
}

function useHttpFallback() {
  api = buildHttpApi();
  installInfo.textContent = "Using local server API";
  loadInfo();
  loadDownloads().then(loadWorkshop);
}

refreshBtn.addEventListener("click", loadWorkshop);
refreshDownloadsBtn.addEventListener("click", loadDownloads);
searchInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    const term = (searchInput.value || "").trim();
    if (/^\\d{6,}$/.test(term)) {
      loadById(term);
    } else {
      currentPage = 1;
      loadWorkshop();
    }
  }
});

sortSelect.addEventListener("change", () => {
  currentPage = 1;
  loadWorkshop();
});

timeSelect.addEventListener("change", () => {
  currentPage = 1;
  loadWorkshop();
});

prevBtn.addEventListener("click", () => {
  if (currentPage > 1) {
    currentPage -= 1;
    updatePageLabel();
    loadWorkshop();
  }
});

nextBtn.addEventListener("click", () => {
  currentPage += 1;
  updatePageLabel();
  loadWorkshop();
});

// Initialize page label on load
updatePageLabel();

function boot() {
  // Prefer the native pywebview bridge if it exists, otherwise fall back to the HTTP API.
  if (window.pywebview) {
    if (window.pywebview.api) {
      waitForApiAndInit();
      return;
    }
    document.addEventListener("pywebviewready", waitForApiAndInit);
    setTimeout(() => {
      if (!api) {
        console.warn("pywebview not detected, switching to HTTP API fallback");
        useHttpFallback();
      }
    }, apiWaitMs * apiWaitMax + 500);
  } else {
    useHttpFallback();
  }
}

boot();

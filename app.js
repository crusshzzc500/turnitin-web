const builtInSources = [
  {
    id: "source-01",
    title: "Hướng dẫn xây dựng môi trường học tập số",
    type: "Chuyên khảo",
    url: "https://example.edu.vn/hoc-tap-so",
    content:
      "Chuyển đổi số trong giáo dục không chỉ là việc đưa tài liệu lên môi trường trực tuyến. Quá trình này đòi hỏi nhà trường thiết kế lại trải nghiệm học tập, phương pháp đánh giá và cách người học tiếp cận tri thức. Dữ liệu cần được sử dụng minh bạch, có mục đích và tôn trọng quyền riêng tư của người học."
  },
  {
    id: "source-02",
    title: "Sổ tay về đạo đức học thuật",
    type: "Nội bộ",
    url: "https://library.example.edu.vn/dao-duc-hoc-thuat",
    content:
      "Liêm chính học thuật là nền tảng của một môi trường giáo dục đáng tin cậy. Người học cần phân biệt rõ việc tham khảo ý tưởng, trích dẫn trực tiếp và sao chép nội dung mà không ghi nhận nguồn. Báo cáo tương đồng chỉ là công cụ hỗ trợ rà soát, không phải là kết luận tự động về hành vi đạo văn."
  },
  {
    id: "source-03",
    title: "Báo cáo nghiên cứu về đánh giá minh bạch",
    type: "Tạp chí",
    url: "https://journal.example.org/minh-bach-trong-danh-gia",
    content:
      "Một quy trình đánh giá tốt cần cho phép người đọc truy vết nguồn thông tin và hiểu lý do của từng cảnh báo. Khi hệ thống chỉ đưa ra một tỷ lệ tổng hợp, người sử dụng dễ bỏ qua bối cảnh của bài viết. Vì vậy, báo cáo cần kết hợp số liệu với bằng chứng có thể kiểm tra."
  },
  {
    id: "source-04",
    title: "Quy tắc sử dụng công cụ hỗ trợ viết",
    type: "Website",
    url: "https://example.org/quy-tac-viet-hoc-thuat",
    content:
      "Công cụ phân tích văn bản nên giúp người viết cải thiện kỹ năng dẫn nguồn. Kết quả cần chỉ ra đoạn văn liên quan, nguồn có khả năng trùng lặp và mức độ cần xem xét. Quyền quyết định cuối cùng vẫn thuộc về người đánh giá."
  }
];

const sampleDocument = `LIÊM CHÍNH HỌC THUẬT TRONG MÔI TRƯỜNG SỐ

Liêm chính học thuật là nền tảng của một môi trường giáo dục đáng tin cậy. Người học cần phân biệt rõ việc tham khảo ý tưởng, trích dẫn trực tiếp và sao chép nội dung mà không ghi nhận nguồn.

Trong quá trình hiện đại hóa nhà trường, chuyển đổi số trong giáo dục không chỉ là việc đưa tài liệu lên môi trường trực tuyến. Quá trình này đòi hỏi nhà trường thiết kế lại trải nghiệm học tập, phương pháp đánh giá và cách người học tiếp cận tri thức.

Một hệ thống rà soát nên giải thích rõ kết quả thay vì chỉ hiển thị điểm số. "Báo cáo tương đồng chỉ là công cụ hỗ trợ rà soát, không phải là kết luận tự động về hành vi đạo văn."

Theo nghiên cứu của nhóm tác giả, khi hệ thống chỉ đưa ra một tỷ lệ tổng hợp, người sử dụng dễ bỏ qua bối cảnh của bài viết. Vì vậy, báo cáo cần kết hợp số liệu với bằng chứng có thể kiểm tra.

Tài liệu tham khảo
Sổ tay về đạo đức học thuật, 2025.
Báo cáo nghiên cứu về đánh giá minh bạch, 2024.`;

const state = {
  sources: [...builtInSources],
  reportText: "",
  report: null,
  backendAvailable: false,
  pendingFile: null,
  analysisJob: null,
  platformStats: null,
  serverHistory: [],
  submissions: [],
  searchStatus: null,
  health: null,
  currentUsername: localStorage.getItem("minh-chung-user") || "demo-admin",
  session: null,
  users: []
};

const elements = {
  pageTitle: document.querySelector("#page-title"),
  activeUser: document.querySelector("#active-user"),
  userSwitcher: document.querySelector(".user-switcher"),
  enableWebSearch: document.querySelector("#enable-web-search"),
  webDiscoveryHint: document.querySelector("#web-discovery-hint"),
  backendStatus: document.querySelector("#backend-status"),
  documentText: document.querySelector("#document-text"),
  fileInput: document.querySelector("#file-input"),
  fileLabel: document.querySelector("#file-label"),
  uploadLimitLabel: document.querySelector("#upload-limit-label"),
  wordCounter: document.querySelector("#word-counter"),
  analyzeButton: document.querySelector("#analyze-button"),
  analyzeButtonLabel: document.querySelector("#analyze-button-label"),
  analysisProgress: document.querySelector("#analysis-progress"),
  analysisProgressTitle: document.querySelector("#analysis-progress-title"),
  analysisProgressValue: document.querySelector("#analysis-progress-value"),
  analysisProgressBar: document.querySelector("#analysis-progress-bar"),
  analysisProgressMessage: document.querySelector("#analysis-progress-message"),
  downloadReportPdf: document.querySelector("#download-report-pdf"),
  indexSubmission: document.querySelector("#index-submission"),
  indexSubmissionOption: document.querySelector("#index-submission").closest(".option-card"),
  loadSample: document.querySelector("#load-sample"),
  customSourceName: document.querySelector("#custom-source-name"),
  customSourceUrl: document.querySelector("#custom-source-url"),
  customSourceContent: document.querySelector("#custom-source-content"),
  addSource: document.querySelector("#add-source"),
  sourceAdder: document.querySelector("#source-adder"),
  backToChecker: document.querySelector("#back-to-checker"),
  filterQuotes: document.querySelector("#filter-quotes"),
  filterBibliography: document.querySelector("#filter-bibliography"),
  filterMinimum: document.querySelector("#filter-minimum"),
  minimumWordsLabel: document.querySelector("#minimum-words-label"),
  documentPreview: document.querySelector("#document-preview"),
  scoreRing: document.querySelector("#score-ring"),
  similarityScore: document.querySelector("#similarity-score"),
  scoreLabel: document.querySelector("#score-label"),
  scoreDescription: document.querySelector("#score-description"),
  metricWords: document.querySelector("#metric-words"),
  metricMatches: document.querySelector("#metric-matches"),
  metricSources: document.querySelector("#metric-sources"),
  reportDiscoverySummary: document.querySelector("#report-discovery-summary"),
  matchedSources: document.querySelector("#matched-sources"),
  integrityFlags: document.querySelector("#integrity-flags"),
  sourceLibrary: document.querySelector("#source-library"),
  historyList: document.querySelector("#history-list"),
  clearHistory: document.querySelector("#clear-history"),
  toast: document.querySelector("#toast"),
  platformSources: document.querySelector("#platform-sources"),
  platformSearchBackend: document.querySelector("#platform-search-backend"),
  platformChunks: document.querySelector("#platform-chunks"),
  platformWords: document.querySelector("#platform-words"),
  platformVersions: document.querySelector("#platform-versions"),
  platformQueued: document.querySelector("#platform-queued"),
  platformRetryWait: document.querySelector("#platform-retry-wait"),
  platformFailed: document.querySelector("#platform-failed"),
  platformSubmissions: document.querySelector("#platform-submissions"),
  crawlSeeds: document.querySelector("#crawl-seeds"),
  crawlMaxPages: document.querySelector("#crawl-max-pages"),
  crawlMaxDepth: document.querySelector("#crawl-max-depth"),
  crawlUseSitemap: document.querySelector("#crawl-use-sitemap"),
  crawlStart: document.querySelector("#crawl-start"),
  crawlerCard: document.querySelector("#crawler-card"),
  crawlStatus: document.querySelector("#crawl-status"),
  crawlRefresh: document.querySelector("#crawl-refresh"),
  crawlRetry: document.querySelector("#crawl-retry"),
  searchReindex: document.querySelector("#search-reindex"),
  crawlQueueSummary: document.querySelector("#crawl-queue-summary"),
  crawlOperations: document.querySelector("#crawl-operations"),
  operationsCard: document.querySelector("#operations-card"),
  auditCard: document.querySelector("#audit-card"),
  auditEvents: document.querySelector("#audit-events"),
  submissionLibrary: document.querySelector("#submission-library")
};

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function safeExternalUrl(value) {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch {
    return "";
  }
}

function tokenize(value) {
  return value.toLocaleLowerCase("vi").match(/[\p{L}\p{N}]+/gu) || [];
}

function normalized(value) {
  return tokenize(value).join(" ");
}

function countWords(value) {
  return tokenize(value).length;
}

async function apiRequest(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Minh-Chung-User": state.currentUsername,
      ...(options.headers || {})
    }
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "Máy chủ không thể xử lý yêu cầu.");
  }
  return payload;
}

function maxUploadBytes() {
  return Number(state.health?.documentMaxBytes || 250 * 1024 * 1024);
}

function uploadLimitMegabytes() {
  return Math.floor(maxUploadBytes() / 1_000_000);
}

function updateUploadLimit() {
  elements.uploadLimitLabel.textContent =
    `Máy chủ đọc .txt, .md, .docx và .pdf, tối đa ${uploadLimitMegabytes()} MB`;
}

function setAnalysisProgress(job = {}, visible = true) {
  const value = Math.max(0, Math.min(100, Number(job.progress || 0)));
  const titles = {
    queued: "Đang xếp hàng xử lý",
    preparing: "Đang chuẩn bị tài liệu",
    extracting: "Đang đọc nội dung tài liệu",
    web_discovery: "Đang quét nguồn web công khai",
    matching: "Đang đối chiếu nguồn",
    finalizing: "Đang hoàn thiện báo cáo",
    completed: "Đã hoàn tất báo cáo",
    failed: "Không thể hoàn tất báo cáo"
  };
  elements.analysisProgress.hidden = !visible;
  elements.analysisProgressTitle.textContent = titles[job.phase] || "Đang xử lý tài liệu";
  elements.analysisProgressValue.textContent = `${value}%`;
  elements.analysisProgressBar.style.width = `${value}%`;
  elements.analysisProgressMessage.textContent = job.message || "Đang chuẩn bị tài liệu.";
}

function sleep(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

async function pollAnalysisJob(job) {
  state.analysisJob = job;
  setAnalysisProgress(job);
  while (true) {
    const status = await apiRequest(`/api/analysis-jobs/${job.jobId}`, {
      headers: { "X-Minh-Chung-Job-Token": job.jobToken }
    });
    setAnalysisProgress(status);
    if (status.status === "completed") {
      state.analysisJob = null;
      return status.result;
    }
    if (status.status === "failed") {
      state.analysisJob = null;
      throw new Error(status.error || status.message || "Không thể hoàn tất báo cáo.");
    }
    await sleep(240);
  }
}

async function createTextAnalysisJob(text) {
  return apiRequest("/api/analysis-jobs", {
    method: "POST",
    body: JSON.stringify({
      kind: "text",
      text,
      saveReport: true,
      indexForComparison: elements.indexSubmission.checked,
      enableWebSearch: elements.enableWebSearch.checked,
      webSearchMaxResults: 10,
      settings: {
        excludeQuotes: elements.filterQuotes.checked,
        excludeBibliography: elements.filterBibliography.checked,
        minimumWords: Number(elements.filterMinimum.value)
      }
    })
  });
}

async function createUploadAnalysisJob(file) {
  const response = await fetch("/api/analysis-jobs/upload", {
    method: "POST",
    headers: {
      "Content-Type": "application/octet-stream",
      "X-Minh-Chung-User": state.currentUsername,
      "X-Minh-Chung-Filename": encodeURIComponent(file.name),
      "X-Minh-Chung-Enable-Web-Search": elements.enableWebSearch.checked ? "1" : "0",
      "X-Minh-Chung-Web-Search-Max-Results": "10",
      "X-Minh-Chung-Save-Report": "1",
      "X-Minh-Chung-Index-Submission": elements.indexSubmission.checked ? "1" : "0"
    },
    body: file
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "Máy chủ không thể nhận tệp.");
  }
  return payload;
}

function permissions() {
  return state.session?.permissions || {};
}

function applySessionUI() {
  const access = permissions();
  const publicMode = Boolean(state.health?.publicMode);
  const maxQueries = Number(state.health?.webDiscoveryLimits?.queries || 10);
  const timeBudget = Number(state.health?.webDiscoveryLimits?.timeBudgetSeconds || 150);
  updateUploadLimit();
  elements.sourceAdder.hidden = !access.manageSources;
  elements.crawlerCard.hidden = !access.manageCrawler;
  elements.operationsCard.hidden = !access.manageCrawler;
  elements.auditCard.hidden = !access.viewAudit;
  elements.userSwitcher.hidden = publicMode;
  elements.indexSubmissionOption.hidden = publicMode;
  if (publicMode) elements.indexSubmission.checked = false;
  elements.downloadReportPdf.hidden = !state.backendAvailable || !state.report?.reportId;
  const providers = state.health?.webDiscovery || {};
  const discoveryMessage = state.report?.webDiscovery?.message || (
    providers.tavily || providers.exa || providers.serper || providers.brave
      ? `Quét web đang tắt để bảo vệ riêng tư. Khi bật, hệ thống quét nhanh tối đa ${maxQueries} đoạn trích và dừng chờ nguồn chậm sau ${timeBudget} giây.`
      : "Chưa cấu hình Tavily, Exa, Serper hoặc Brave. Nếu bật quét web, báo cáo vẫn dùng kho nguồn hiện có."
  );
  elements.webDiscoveryHint.textContent = publicMode
    ? `Chế độ công khai không lưu bài hoặc báo cáo trên máy chủ. ${discoveryMessage}`
    : discoveryMessage;
}

function renderAuditEvents(events = []) {
  if (!permissions().viewAudit) {
    elements.auditEvents.innerHTML = "";
    return;
  }
  if (!events.length) {
    elements.auditEvents.innerHTML = '<div class="empty-state">Chưa có hoạt động nào được ghi nhận.</div>';
    return;
  }
  elements.auditEvents.innerHTML = events
    .map(
      (event) => `
        <article class="operation-item">
          <div>
            <strong>${escapeHtml(event.action)}</strong>
            <small>${escapeHtml(event.display_name || event.username || "Hệ thống")} · ${escapeHtml(event.entity_type)} ${escapeHtml(event.entity_id || "")}</small>
          </div>
          <span class="operation-status">${escapeHtml(new Intl.DateTimeFormat("vi-VN", { dateStyle: "short", timeStyle: "short" }).format(new Date(event.created_at)))}</span>
        </article>`
    )
    .join("");
}

function splitSentences(value) {
  return value.match(/[^.!?\n]+[.!?]?|\n/gu) || [];
}

function similarityScore(leftText, rightText) {
  const left = tokenize(leftText);
  const right = tokenize(rightText);
  if (!left.length || !right.length) return 0;

  const leftSet = new Set(left);
  const rightSet = new Set(right);
  const shared = [...leftSet].filter((token) => rightSet.has(token)).length;
  const union = new Set([...leftSet, ...rightSet]).size;
  const jaccard = shared / union;
  const containment = shared / Math.min(leftSet.size, rightSet.size);

  return Math.max(jaccard, containment * 0.92);
}

function isBibliographyHeading(value) {
  return /^(tài liệu tham khảo|tham khảo|references|bibliography)\s*:?\s*$/iu.test(value.trim());
}

function isQuoted(value) {
  const text = value.trim();
  return (
    /^["'“‘«]/u.test(text) ||
    /["'”’»][.!?]?$/.test(text) ||
    (text.includes('"') && text.lastIndexOf('"') > text.indexOf('"'))
  );
}

function bestSourceMatch(segment, sources) {
  let best = null;

  sources.forEach((source) => {
    splitSentences(source.content).forEach((sourceSentence) => {
      if (sourceSentence === "\n") return;
      const score = similarityScore(segment, sourceSentence);
      if (!best || score > best.score) {
        best = { source, score, sourceSentence };
      }
    });
  });

  return best;
}

function buildReport(text) {
  const minimumWords = Number(elements.filterMinimum.value);
  const filters = {
    quotes: elements.filterQuotes.checked,
    bibliography: elements.filterBibliography.checked
  };
  let bibliography = false;
  let matchIndex = 0;

  const segments = splitSentences(text).map((segment) => {
    if (segment === "\n") {
      return { text: segment, kind: "plain", words: 0 };
    }

    const trimmed = segment.trim();
    if (isBibliographyHeading(trimmed)) bibliography = true;

    const words = countWords(segment);
    const quoted = isQuoted(segment);
    const excluded =
      (filters.quotes && quoted) ||
      (filters.bibliography && bibliography);

    if (excluded) {
      return {
        text: segment,
        kind: "excluded",
        words,
        reason: bibliography ? "Tài liệu tham khảo" : "Trích dẫn"
      };
    }

    if (words < minimumWords) {
      return { text: segment, kind: "plain", words };
    }

    const best = bestSourceMatch(segment, state.sources);
    if (!best || best.score < 0.7) {
      return { text: segment, kind: "plain", words };
    }

    matchIndex += 1;
    return {
      text: segment,
      kind: "match",
      words,
      number: matchIndex,
      source: best.source,
      confidence: Math.round(best.score * 100)
    };
  });

  const matchedSegments = segments.filter((segment) => segment.kind === "match");
  const matchedWords = matchedSegments.reduce((sum, segment) => sum + segment.words, 0);
  const totalWords = countWords(text);
  const percent = totalWords ? Math.min(100, Math.round((matchedWords / totalWords) * 100)) : 0;
  const sourceMap = new Map();

  matchedSegments.forEach((segment) => {
    const existing = sourceMap.get(segment.source.id) || {
      ...segment.source,
      matchedWords: 0,
      matches: 0,
      numbers: []
    };
    existing.matchedWords += segment.words;
    existing.matches += 1;
    existing.numbers.push(segment.number);
    sourceMap.set(segment.source.id, existing);
  });

  return {
    text,
    segments,
    matchedSegments,
    sources: [...sourceMap.values()].sort((left, right) => right.matchedWords - left.matchedWords),
    totalWords,
    percent
  };
}

function scoreMessage(percent) {
  if (percent === 0) {
    return {
      label: "Chưa phát hiện đoạn trùng đáng kể",
      description: "Vẫn nên rà soát thủ công nếu tài liệu được dùng trong quy trình chính thức."
    };
  }
  if (percent < 20) {
    return {
      label: "Có một vài đoạn cần xem lại",
      description: "Hãy kiểm tra nguồn và bổ sung trích dẫn nếu nội dung được kế thừa từ tài liệu khác."
    };
  }
  if (percent < 45) {
    return {
      label: "Cần rà soát kỹ các nguồn",
      description: "Nhiều đoạn có mức tương đồng rõ ràng. Tỷ lệ này không tự động đồng nghĩa với đạo văn."
    };
  }
  return {
    label: "Mức tương đồng đáng chú ý",
    description: "Tài liệu có nhiều nội dung trùng lặp. Cần đọc từng đoạn và đánh giá bối cảnh trước khi kết luận."
  };
}

function renderReport() {
  if (!state.report) return;

  const { segments, sources, totalWords, percent, matchedSegments } = state.report;
  const message = scoreMessage(percent);
  const degrees = percent * 3.6;

  elements.scoreRing.style.background =
    `conic-gradient(var(--coral) 0deg, var(--coral) ${degrees}deg, #eff0e9 ${degrees}deg)`;
  elements.similarityScore.textContent = `${percent}%`;
  elements.scoreLabel.textContent = message.label;
  elements.scoreDescription.textContent = message.description;
  elements.metricWords.textContent = totalWords.toLocaleString("vi-VN");
  elements.metricMatches.textContent = matchedSegments.length;
  elements.metricSources.textContent = sources.length;
  const discovery = state.report.webDiscovery;
  elements.reportDiscoverySummary.textContent = discovery
    ? `${discovery.message} Đã tạo ${discovery.queries?.length || 0} truy vấn và ghi nhận ${discovery.indexed || 0} nguồn web.`
    : "Báo cáo dùng kho nguồn hiện có. Bật quét web khi bạn muốn tìm thêm nguồn công khai.";

  elements.documentPreview.innerHTML = segments
    .map((segment) => {
      const text = escapeHtml(segment.text);
      if (segment.kind === "match") {
        return `<mark class="match" data-number="${segment.number}" title="${escapeHtml(segment.source.title)}">${text}</mark>`;
      }
      if (segment.kind === "excluded") {
        return `<span class="excluded-text" title="Đã loại trừ: ${segment.reason}">${text}</span>`;
      }
      return text;
    })
    .join("");

  renderIntegrityFlags(state.report.integrityFlags || []);
  applySessionUI();

  if (!sources.length) {
    elements.matchedSources.innerHTML =
      '<div class="empty-state">Không có nguồn nào vượt ngưỡng hiện tại. Thử giảm độ dài tối thiểu hoặc tắt bộ lọc để xem thêm kết quả.</div>';
    return;
  }

  elements.matchedSources.innerHTML = sources
    .map((source) => {
      const share = totalWords ? Math.round((source.matchedWords / totalWords) * 100) : 0;
      const sourceUrl = safeExternalUrl(source.url || "");
      const sourceLabel = escapeHtml(source.url || "Nguồn do người dùng thêm");
      return `
        <article class="source-result">
          <div class="source-result-top">
            <div>
              <strong>${escapeHtml(source.title)}</strong>
              <small>${sourceUrl ? `<a href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener noreferrer">${sourceLabel}</a>` : sourceLabel}</small>
            </div>
            <span class="source-number">${source.numbers.join(",")}</span>
          </div>
          <footer>
            <span>${source.matches} đoạn đối chiếu</span>
            <span>${share}% bài viết</span>
          </footer>
        </article>`;
    })
    .join("");

}

function renderIntegrityFlags(flags) {
  if (!flags.length) {
    elements.integrityFlags.innerHTML =
      '<div class="empty-state">Chưa phát hiện ký tự vô hình hoặc thủ thuật định dạng đáng chú ý.</div>';
    return;
  }

  elements.integrityFlags.innerHTML = flags
    .map(
      (flag) => `
        <article class="integrity-result">
          <strong>${escapeHtml(flag.message)}</strong>
          <small>${Number(flag.count || 0).toLocaleString("vi-VN")} dấu hiệu · mức ${escapeHtml(flag.severity || "cần xem")}</small>
        </article>`
    )
    .join("");
}

async function refreshReport({ saveReport = false } = {}) {
  if (!state.reportText) return;
  if (!state.backendAvailable) {
    state.report = buildReport(state.reportText);
    state.report.integrityFlags = [];
    renderReport();
    return;
  }

  const previousWebDiscovery = state.report?.webDiscovery;
  state.report = await apiRequest("/api/analyze", {
    method: "POST",
    body: JSON.stringify({
      text: state.reportText,
      saveReport,
      settings: {
        excludeQuotes: elements.filterQuotes.checked,
        excludeBibliography: elements.filterBibliography.checked,
        minimumWords: Number(elements.filterMinimum.value)
      }
    })
  });
  if (previousWebDiscovery && !state.report.webDiscovery) {
    state.report.webDiscovery = previousWebDiscovery;
  }
  renderReport();
}

function setView(viewName) {
  document.querySelectorAll(".view").forEach((view) => view.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.remove("active"));

  const target = document.querySelector(`#${viewName}-view`);
  if (target) target.classList.add("active");

  const nav = document.querySelector(`[data-view="${viewName}"]`);
  if (nav) nav.classList.add("active");

  const titles = {
    checker: "Kiểm tra tài liệu",
    report: "Báo cáo tương đồng",
    history: "Lịch sử báo cáo",
    sources: "Kho nguồn đối chiếu"
  };
  elements.pageTitle.textContent = titles[viewName] || "Minh Chứng";
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.classList.add("visible");
  window.clearTimeout(showToast.timeout);
  showToast.timeout = window.setTimeout(() => elements.toast.classList.remove("visible"), 2600);
}

function updateWordCounter() {
  elements.wordCounter.textContent = `${countWords(elements.documentText.value).toLocaleString("vi-VN")} từ`;
}

function getHistory() {
  try {
    return JSON.parse(localStorage.getItem("minh-chung-history") || "[]");
  } catch {
    return [];
  }
}

function saveHistory(report) {
  const title = report.text
    .split("\n")
    .map((line) => line.trim())
    .find(Boolean);
  const history = getHistory();
  history.unshift({
    id: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()),
    title: title || "Tài liệu không tên",
    percent: report.percent,
    words: report.totalWords,
    createdAt: new Date().toISOString()
  });
  localStorage.setItem("minh-chung-history", JSON.stringify(history.slice(0, 12)));
}

function renderHistory() {
  const history = state.backendAvailable ? state.serverHistory : getHistory();
  if (!history.length) {
    elements.historyList.innerHTML =
      '<div class="empty-state">Chưa có báo cáo nào. Kết quả sẽ xuất hiện tại đây sau khi bạn tạo báo cáo đầu tiên.</div>';
    return;
  }

  elements.historyList.innerHTML = history
    .map((item) => {
      const date = new Intl.DateTimeFormat("vi-VN", {
        dateStyle: "medium",
        timeStyle: "short"
      }).format(new Date(item.createdAt || item.created_at));
      const words = Number(item.words ?? item.total_words ?? 0);
      const percent = Number(item.percent ?? item.similarity_percent ?? 0);
      return `
        <article class="history-item">
          <div>
            <strong>${escapeHtml(item.title)}</strong>
            <small>${words.toLocaleString("vi-VN")} từ · ${date}</small>
          </div>
          <span class="history-score">${percent}% tương đồng</span>
        </article>`;
    })
    .join("");
}

function renderSourceLibrary() {
  elements.sourceLibrary.innerHTML = state.sources
    .map(
      (source) => `
        <article class="library-item">
          <div>
            <strong>${escapeHtml(source.title)}</strong>
            <small>${Number(source.word_count ?? countWords(source.content || "")).toLocaleString("vi-VN")} từ · ${Number(source.version_count || 1).toLocaleString("vi-VN")} phiên bản · ${escapeHtml(source.url || "Nguồn do người dùng thêm")}</small>
          </div>
          <span class="source-type">${escapeHtml(source.type || source.source_type || "nguồn")}</span>
        </article>`
    )
    .join("");
}

function renderPlatformStats() {
  const stats = state.platformStats || {};
  const queued = stats.crawl_queue?.queued || 0;
  elements.platformSources.textContent = Number(stats.sources || state.sources.length).toLocaleString("vi-VN");
  elements.platformSearchBackend.textContent = state.searchStatus?.backend || (state.backendAvailable ? "đang tải" : "cục bộ");
  elements.platformChunks.textContent = Number(stats.chunks || 0).toLocaleString("vi-VN");
  elements.platformWords.textContent = Number(stats.words || 0).toLocaleString("vi-VN");
  elements.platformVersions.textContent = Number(stats.source_versions || 0).toLocaleString("vi-VN");
  elements.platformQueued.textContent = Number(queued).toLocaleString("vi-VN");
  elements.platformRetryWait.textContent = Number(stats.crawl_queue?.retry_wait || 0).toLocaleString("vi-VN");
  elements.platformFailed.textContent = Number(stats.crawl_queue?.failed || 0).toLocaleString("vi-VN");
  elements.platformSubmissions.textContent = Number(stats.indexed_submissions || 0).toLocaleString("vi-VN");
}

function renderCrawlOperations(operations = {}) {
  const queue = operations.queue || {};
  const labels = {
    queued: "Đang chờ",
    fetching: "Đang tải",
    retry_wait: "Chờ thử lại",
    indexed: "Đã lập chỉ mục",
    skipped: "Đã bỏ qua",
    failed: "Lỗi"
  };
  elements.crawlQueueSummary.innerHTML = Object.entries(labels)
    .map(([key, label]) => `<span><strong>${Number(queue[key] || 0).toLocaleString("vi-VN")}</strong>${label}</span>`)
    .join("");

  const recent = operations.recent || [];
  if (!recent.length) {
    elements.crawlOperations.innerHTML =
      '<div class="empty-state">Chưa có URL nào trong hàng đợi crawler.</div>';
    return;
  }
  elements.crawlOperations.innerHTML = recent
    .map(
      (item) => `
        <article class="operation-item">
          <div>
            <strong>${escapeHtml(item.url)}</strong>
            <small>${escapeHtml(item.last_error || "Không có lỗi")} · ${Number(item.attempts || 0)} lần thử</small>
          </div>
          <span class="operation-status ${escapeHtml(item.status)}">${escapeHtml(labels[item.status] || item.status)}</span>
        </article>`
    )
    .join("");
}

function renderSubmissions() {
  if (!state.backendAvailable) {
    elements.submissionLibrary.innerHTML =
      '<div class="empty-state">Chạy máy chủ để quản lý kho bài nộp nội bộ.</div>';
    return;
  }
  if (!state.submissions.length) {
    elements.submissionLibrary.innerHTML =
      '<div class="empty-state">Chưa có bài nào được đồng ý dùng làm nguồn đối chiếu.</div>';
    return;
  }
  elements.submissionLibrary.innerHTML = state.submissions
    .map(
      (submission) => `
        <article class="library-item">
          <div>
            <strong>${escapeHtml(submission.title)}</strong>
            <small>${Number(submission.word_count || 0).toLocaleString("vi-VN")} từ · ${escapeHtml(new Intl.DateTimeFormat("vi-VN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(submission.created_at)))}</small>
          </div>
          <button class="remove-submission" type="button" data-submission-id="${submission.id}">Rút khỏi kho</button>
        </article>`
    )
    .join("");
}

async function refreshBackendData() {
  if (!state.backendAvailable) {
    renderSourceLibrary();
    renderPlatformStats();
    renderCrawlOperations();
    return;
  }
  const access = permissions();
  const [stats, sourcePayload, reportPayload, submissionPayload, crawlOperations, searchStatus, auditPayload] = await Promise.all([
    apiRequest("/api/stats"),
    apiRequest("/api/sources?limit=200"),
    apiRequest("/api/reports?limit=30"),
    apiRequest("/api/submissions?limit=100"),
    access.manageCrawler ? apiRequest("/api/crawl/operations?limit=30") : Promise.resolve({}),
    apiRequest("/api/search/status"),
    access.viewAudit ? apiRequest("/api/audit?limit=30") : Promise.resolve({ events: [] })
  ]);
  state.platformStats = stats;
  state.sources = sourcePayload.sources;
  state.serverHistory = reportPayload.reports;
  state.submissions = submissionPayload.submissions;
  state.searchStatus = searchStatus;
  renderPlatformStats();
  renderSourceLibrary();
  renderHistory();
  renderSubmissions();
  renderCrawlOperations(crawlOperations);
  renderAuditEvents(auditPayload.events);
  applySessionUI();
}

async function loadSession() {
  const userPayload = await apiRequest("/api/session/users");
  state.users = userPayload.users;
  if (!state.users.some((user) => user.username === state.currentUsername)) {
    state.currentUsername = state.users[0]?.username || "demo-admin";
    localStorage.setItem("minh-chung-user", state.currentUsername);
  }
  const sessionPayload = await apiRequest("/api/session");
  state.session = sessionPayload.user;
  elements.activeUser.innerHTML = state.users
    .map(
      (user) => `<option value="${escapeHtml(user.username)}">${escapeHtml(user.display_name)} · ${escapeHtml(user.role)}</option>`
    )
    .join("");
  elements.activeUser.value = state.currentUsername;
  applySessionUI();
}

async function initializeBackend() {
  if (!window.location.protocol.startsWith("http")) {
    elements.backendStatus.classList.add("offline");
    elements.backendStatus.lastChild.textContent = " Bản cục bộ";
    renderPlatformStats();
    return;
  }
  try {
    state.health = await apiRequest("/api/health");
    state.backendAvailable = true;
    elements.backendStatus.classList.remove("offline");
    elements.backendStatus.lastChild.textContent = " Máy chủ và chỉ mục sẵn sàng";
    await loadSession();
    await refreshBackendData();
  } catch {
    elements.backendStatus.classList.add("offline");
    elements.backendStatus.lastChild.textContent = " Không kết nối được máy chủ";
    renderPlatformStats();
    applySessionUI();
  }
}

elements.activeUser.addEventListener("change", async () => {
  state.currentUsername = elements.activeUser.value;
  localStorage.setItem("minh-chung-user", state.currentUsername);
  state.report = null;
  applySessionUI();
  try {
    await loadSession();
    await refreshBackendData();
    showToast(`Đã chuyển sang ${state.session.displayName}.`);
  } catch (error) {
    showToast(error.message);
  }
});

elements.downloadReportPdf.addEventListener("click", async () => {
  if (!state.backendAvailable || !state.report?.reportId) return;
  try {
    const response = await fetch(`/api/reports/${state.report.reportId}/pdf`, {
      headers: { "X-Minh-Chung-User": state.currentUsername }
    });
    if (!response.ok) {
      const payload = await response.json();
      throw new Error(payload.error || "Không thể xuất báo cáo PDF.");
    }
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = `minh-chung-report-${state.report.reportId}.pdf`;
    link.click();
    URL.revokeObjectURL(url);
    showToast("Đã tạo báo cáo PDF.");
  } catch (error) {
    showToast(error.message);
  }
});

elements.documentText.addEventListener("input", () => {
  state.pendingFile = null;
  updateWordCounter();
});

elements.fileInput.addEventListener("change", async (event) => {
  const [file] = event.target.files;
  if (!file) return;
  if (file.size > maxUploadBytes()) {
    showToast(`Tệp vượt quá giới hạn ${uploadLimitMegabytes()} MB.`);
    return;
  }
  if (/(\.docx|\.pdf)$/iu.test(file.name)) {
    if (!state.backendAvailable) {
      showToast("Hãy chạy máy chủ để đọc tệp DOCX hoặc PDF.");
      return;
    }
    state.pendingFile = file;
    elements.documentText.value = "";
    elements.fileLabel.textContent = file.name;
    updateWordCounter();
    showToast("Đã chọn tệp. Máy chủ sẽ đọc nội dung khi tạo báo cáo.");
    return;
  }
  const text = await file.text();
  state.pendingFile = null;
  elements.documentText.value = text;
  elements.fileLabel.textContent = file.name;
  updateWordCounter();
  showToast("Đã đọc nội dung tệp.");
});

elements.loadSample.addEventListener("click", () => {
  state.pendingFile = null;
  elements.documentText.value = sampleDocument;
  elements.fileLabel.textContent = "Bài mẫu minh họa";
  updateWordCounter();
  showToast("Đã nạp bài mẫu. Bấm tạo báo cáo để xem kết quả.");
});

elements.addSource.addEventListener("click", async () => {
  const title = elements.customSourceName.value.trim();
  const content = elements.customSourceContent.value.trim();
  if (!title || countWords(content) < 8) {
    showToast("Hãy nhập tên nguồn và nội dung tối thiểu 8 từ.");
    return;
  }

  try {
    if (state.backendAvailable) {
      await apiRequest("/api/sources", {
        method: "POST",
        body: JSON.stringify({
          title,
          content,
          url: elements.customSourceUrl.value.trim(),
          type: "tự thêm"
        })
      });
      await refreshBackendData();
    } else {
      state.sources.push({
        id: `custom-${Date.now()}`,
        title,
        type: "Tự thêm",
        url: elements.customSourceUrl.value.trim(),
        content
      });
      renderSourceLibrary();
    }
  } catch (error) {
    showToast(error.message);
    return;
  }
  elements.customSourceName.value = "";
  elements.customSourceUrl.value = "";
  elements.customSourceContent.value = "";
  showToast("Đã thêm nguồn đối chiếu vào kho cục bộ.");
});

elements.analyzeButton.addEventListener("click", async () => {
  const text = elements.documentText.value.trim();
  if (!state.pendingFile && countWords(text) < 20) {
    showToast("Hãy nhập tài liệu có ít nhất 20 từ.");
    return;
  }
  elements.analyzeButton.disabled = true;
  elements.analyzeButtonLabel.textContent = "Đang kiểm tra...";
  setAnalysisProgress({ progress: 1, phase: "queued", message: "Đang xếp tài liệu vào hàng xử lý." });
  try {
    if (state.pendingFile && state.backendAvailable) {
      state.report = await pollAnalysisJob(await createUploadAnalysisJob(state.pendingFile));
      state.reportText = state.report.text;
      renderReport();
    } else {
      state.reportText = text;
      if (state.backendAvailable) {
        state.report = await pollAnalysisJob(await createTextAnalysisJob(state.reportText));
        renderReport();
      } else {
        await refreshReport({ saveReport: true });
      }
      if (!state.backendAvailable) saveHistory(state.report);
    }
    if (state.backendAvailable) await refreshBackendData();
    renderHistory();
    setAnalysisProgress({ progress: 100, phase: "completed", message: "Đã hoàn tất báo cáo tương đồng." });
    setView("report");
  } catch (error) {
    setAnalysisProgress({ progress: state.analysisJob?.progress || 1, phase: "failed", message: error.message });
    showToast(error.message);
  } finally {
    elements.analyzeButton.disabled = false;
    elements.analyzeButtonLabel.textContent = "Kiểm tra ngay";
  }
});

elements.backToChecker.addEventListener("click", () => setView("checker"));

[elements.filterQuotes, elements.filterBibliography].forEach((input) => {
  input.addEventListener("change", async () => {
    try {
      await refreshReport();
    } catch (error) {
      showToast(error.message);
    }
  });
});

elements.filterMinimum.addEventListener("input", async () => {
  elements.minimumWordsLabel.textContent = elements.filterMinimum.value;
  try {
    await refreshReport();
  } catch (error) {
    showToast(error.message);
  }
});

elements.clearHistory.addEventListener("click", () => {
  if (state.backendAvailable) {
    showToast("Lịch sử máy chủ được giữ lại để phục vụ kiểm toán.");
    return;
  }
  localStorage.removeItem("minh-chung-history");
  renderHistory();
  showToast("Đã xóa lịch sử báo cáo trên trình duyệt này.");
});

document.querySelectorAll(".nav-item").forEach((item) => {
  item.addEventListener("click", () => setView(item.dataset.view));
});

document.querySelector(".dropzone").addEventListener("dragover", (event) => {
  event.preventDefault();
  event.currentTarget.classList.add("dragging");
});

document.querySelector(".dropzone").addEventListener("dragleave", (event) => {
  event.currentTarget.classList.remove("dragging");
});

document.querySelector(".dropzone").addEventListener("drop", async (event) => {
  event.preventDefault();
  event.currentTarget.classList.remove("dragging");
  const [file] = event.dataTransfer.files;
  if (!file) return;
  if (!/(\.txt|\.md|\.docx|\.pdf)$/iu.test(file.name)) {
    showToast("Hệ thống hỗ trợ tệp .txt, .md, .docx và .pdf.");
    return;
  }
  if (file.size > maxUploadBytes()) {
    showToast(`Tệp vượt quá giới hạn ${uploadLimitMegabytes()} MB.`);
    return;
  }
  if (/(\.docx|\.pdf)$/iu.test(file.name)) {
    if (!state.backendAvailable) {
      showToast("Hãy chạy máy chủ để đọc tệp DOCX hoặc PDF.");
      return;
    }
    state.pendingFile = file;
    elements.documentText.value = "";
    elements.fileLabel.textContent = file.name;
    updateWordCounter();
    showToast("Đã chọn tệp. Máy chủ sẽ đọc nội dung khi tạo báo cáo.");
    return;
  }
  state.pendingFile = null;
  elements.documentText.value = await file.text();
  elements.fileLabel.textContent = file.name;
  updateWordCounter();
  showToast("Đã đọc nội dung tệp.");
});

elements.crawlStart.addEventListener("click", async () => {
  if (!state.backendAvailable) {
    showToast("Hãy chạy máy chủ để dùng crawler.");
    return;
  }
  const urls = elements.crawlSeeds.value
    .split("\n")
    .map((url) => url.trim())
    .filter(Boolean);
  if (!urls.length) {
    showToast("Hãy nhập ít nhất một URL hạt giống.");
    return;
  }
  try {
    const seedResult = await apiRequest(elements.crawlUseSitemap.checked ? "/api/crawl/sitemaps" : "/api/crawl/seeds", {
      method: "POST",
      body: JSON.stringify({
        urls,
        maxUrls: Number(elements.crawlMaxPages.value)
      })
    });
    const runResult = await apiRequest("/api/crawl/run", {
      method: "POST",
      body: JSON.stringify({
        maxPages: Number(elements.crawlMaxPages.value),
        maxDepth: Number(elements.crawlMaxDepth.value)
      })
    });
    elements.crawlStatus.textContent =
      `Đã thêm ${seedResult.queued} URL. Crawler đang xử lý tối đa ${runResult.maxPages} trang.`;
    showToast("Crawler đã bắt đầu chạy trong nền.");
    window.setTimeout(refreshCrawlStatus, 900);
  } catch (error) {
    showToast(error.message);
  }
});

elements.submissionLibrary.addEventListener("click", async (event) => {
  const button = event.target.closest(".remove-submission");
  if (!button || !state.backendAvailable) return;
  try {
    await apiRequest(`/api/submissions/${button.dataset.submissionId}`, { method: "DELETE" });
    await refreshBackendData();
    showToast("Đã rút bài khỏi kho đối chiếu nội bộ.");
  } catch (error) {
    showToast(error.message);
  }
});

async function refreshCrawlStatus() {
  if (!state.backendAvailable || !permissions().manageCrawler) return;
  try {
    const status = await apiRequest("/api/crawl/status");
    const result = status.lastResult;
    if (status.running) {
      elements.crawlStatus.textContent = "Crawler đang xử lý hàng đợi...";
      window.setTimeout(refreshCrawlStatus, 900);
    } else if (result) {
      elements.crawlStatus.textContent =
        `Đã xử lý ${result.processed} URL: lập chỉ mục ${result.indexed}, chờ thử lại ${result.retryScheduled || 0}, bỏ qua ${result.skipped}, lỗi ${result.failed}.`;
      await refreshBackendData();
    }
  } catch (error) {
    elements.crawlStatus.textContent = error.message;
  }
}

elements.crawlRefresh.addEventListener("click", async () => {
  if (!state.backendAvailable) {
    showToast("Hãy chạy máy chủ để xem trạng thái crawler.");
    return;
  }
  try {
    await refreshBackendData();
    showToast("Đã làm mới trạng thái crawler.");
  } catch (error) {
    showToast(error.message);
  }
});

elements.crawlRetry.addEventListener("click", async () => {
  if (!state.backendAvailable) {
    showToast("Hãy chạy máy chủ để thử lại URL lỗi.");
    return;
  }
  try {
    const result = await apiRequest("/api/crawl/retry", {
      method: "POST",
      body: JSON.stringify({ limit: 1000 })
    });
    await refreshBackendData();
    showToast(`Đã đưa ${result.requeued} URL lỗi trở lại hàng đợi.`);
  } catch (error) {
    showToast(error.message);
  }
});

elements.searchReindex.addEventListener("click", async () => {
  if (!state.backendAvailable) {
    showToast("Hãy chạy máy chủ để lập lại chỉ mục.");
    return;
  }
  try {
    const result = await apiRequest("/api/search/reindex", {
      method: "POST",
      body: JSON.stringify({})
    });
    await refreshBackendData();
    showToast(`Đã lập lại ${result.chunks} đoạn trên ${result.backend}.`);
  } catch (error) {
    showToast(error.message);
  }
});

renderSourceLibrary();
renderHistory();
renderPlatformStats();
renderSubmissions();
renderCrawlOperations();
updateWordCounter();
initializeBackend();

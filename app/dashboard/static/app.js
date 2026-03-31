const token = (() => {
  const value = new URLSearchParams(window.location.search).get('token') || '';
  if (value) sessionStorage.setItem('dd_token', value);
  return value || sessionStorage.getItem('dd_token') || '';
})();

function authHeaders(extra = {}) {
  return { 'X-DropDone-Token': token, ...extra };
}

async function api(path) {
  const response = await fetch(path, { headers: authHeaders() });
  if (!response.ok) {
    let payload = null;
    try {
      payload = await response.json();
    } catch (error) {
      payload = null;
    }
    throw new Error(payload?.error || `${response.status} ${path}`);
  }
  return response.json();
}

async function postJson(path, payload = {}) {
  const response = await fetch(path, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    let data = null;
    try {
      data = await response.json();
    } catch (error) {
      data = null;
    }
    throw new Error(data?.error || `${response.status} ${path}`);
  }
  return response.json();
}

function fmtSize(bytes) {
  if (!bytes) return '-';
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
  if (bytes >= 1e3) return `${(bytes / 1e3).toFixed(0)} KB`;
  return `${bytes} B`;
}

function fmtDate(value) {
  if (!value) return '-';
  return value.replace('T', ' ').slice(0, 16);
}

const CATEGORY_META = {
  video: { icon: '🎬', className: 'icon-video', label: '영상' },
  image: { icon: '🖼️', className: 'icon-img', label: '이미지' },
  pdf: { icon: '📄', className: 'icon-doc', label: 'PDF' },
  audio: { icon: '🎵', className: 'icon-etc', label: '음악' },
  document: { icon: '📄', className: 'icon-doc', label: '문서' },
  archive: { icon: '📦', className: 'icon-zip', label: '압축' },
  executable: { icon: '⚙️', className: 'icon-exe', label: '실행파일' },
};

const MANUAL_CATEGORIES = [
  { key: 'video', label: '영상', icon: '🎬', exts: '.mp4 .mkv .avi .mov .wmv .m4v .webm .flv' },
  { key: 'document', label: '문서', icon: '📄', exts: '.pdf .docx .xlsx .pptx .txt .hwp .csv' },
  { key: 'archive', label: '압축', icon: '📦', exts: '.zip .rar .7z .tar .gz .bz2' },
  { key: 'image', label: '이미지', icon: '🖼️', exts: '.jpg .jpeg .png .gif .webp .bmp .svg .psd' },
  { key: 'audio', label: '음악', icon: '🎵', exts: '.mp3 .flac .wav .aac .ogg .m4a' },
  { key: 'executable', label: '실행파일', icon: '⚙️', exts: '.exe .msi .apk .dmg' },
];

const TITLES = {
  active: '최근 완료',
  history: '완료 기록',
  rules: '자동 정리 규칙',
  settings: '설정',
};

let currentTab = 'active';
let allDownloads = [];
let errorCache = [];
let selectedCategoryKey = null;
let settingsCache = null;
let rulesCache = [];

function fileCategoryMeta(download) {
  const category = CATEGORY_META[download.category_key] || CATEGORY_META.document;
  return category || { icon: '📁', className: 'icon-etc', label: '기타' };
}

function fileIcon(download) {
  return fileCategoryMeta(download).icon;
}

function fileIconClass(download) {
  return fileCategoryMeta(download).className;
}

function sourceLabel(source) {
  return source || 'unknown';
}

document.querySelectorAll('.nav-item').forEach((element) => {
  element.addEventListener('click', () => {
    document.querySelectorAll('.nav-item').forEach((navItem) => navItem.classList.remove('active'));
    element.classList.add('active');
    currentTab = element.dataset.tab;
    document.getElementById('page-title').textContent = TITLES[currentTab];
    renderTab(currentTab);
  });
});

async function renderTab(tab) {
  const content = document.getElementById('content');
  content.innerHTML = '<div class="empty-state">불러오는 중...</div>';

  try {
    if (tab === 'active') await renderActive(content);
    if (tab === 'history') await renderHistory(content);
    if (tab === 'rules') await renderRules(content);
    if (tab === 'settings') await renderSettings(content);
  } catch (error) {
    content.innerHTML = `<div class="empty-state" style="color:var(--red)">${error.message}</div>`;
  }
}

async function renderActive(content) {
  const downloads = await api('/api/downloads');
  const recent = downloads.filter((download) => {
    const createdAt = new Date(download.created_at.replace(' ', 'T')).getTime();
    return Date.now() - createdAt < 60 * 60 * 1000;
  });

  document.getElementById('badge-active').textContent = recent.length;

  if (!recent.length) {
    content.innerHTML = `
      <div class="empty-state">
        <div style="font-size:38px;margin-bottom:12px;">📭</div>
        최근 1시간 안에 완료된 다운로드가 없습니다.
      </div>
    `;
    return;
  }

  content.innerHTML = `
    <div class="section-label" style="margin-bottom:12px">최근 1시간 완료 (${recent.length})</div>
    <div class="dl-list">
      ${recent.map((download) => {
        const category = fileCategoryMeta(download);
        const finalPath = download.final_dest || download.path;
        return `
          <div class="dl-card done">
            <div class="dl-card-top">
              <span class="source-badge badge-${download.source}">${sourceLabel(download.source)}</span>
              <span class="rule-type-badge">${category.label}</span>
              <span class="dl-name">${download.filename}</span>
              <span class="dl-size">${fmtSize(download.size)}</span>
            </div>
            <div class="dl-path">${finalPath}</div>
            <div class="dl-meta">${fmtDate(download.created_at)}</div>
          </div>
        `;
      }).join('')}
    </div>
  `;
}

async function renderHistory(content) {
  allDownloads = await api('/api/downloads');
  const totalBytes = allDownloads.reduce((sum, download) => sum + (download.size || 0), 0);
  const categories = [...new Set(allDownloads.map((download) => CATEGORY_META[download.category_key]?.label).filter(Boolean))];

  content.innerHTML = `
    <div class="stats-grid">
      <div class="stat-card">
        <div class="s-label">총 다운로드</div>
        <div class="s-value">${allDownloads.length}</div>
      </div>
      <div class="stat-card">
        <div class="s-label">총 용량</div>
        <div class="s-value">${fmtSize(totalBytes)}</div>
      </div>
      <div class="stat-card">
        <div class="s-label">분류</div>
        <div class="s-value" style="font-size:14px">${categories.join(', ') || '-'}</div>
      </div>
    </div>

    <div class="search-bar">
      <span style="color:var(--text3)">🔎</span>
      <input type="text" id="historySearch" placeholder="파일명 검색..." oninput="filterHistory()">
    </div>

    <table class="history-table">
      <thead>
        <tr>
          <th>파일명</th>
          <th>분류</th>
          <th>소스</th>
          <th>크기</th>
          <th>최종 위치</th>
          <th>완료 시각</th>
        </tr>
      </thead>
      <tbody id="historyBody"></tbody>
    </table>
  `;

  renderHistoryRows(allDownloads);
}

function renderHistoryRows(rows) {
  const tbody = document.getElementById('historyBody');
  if (!tbody) return;

  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text3);padding:32px">기록이 없습니다.</td></tr>';
    return;
  }

  tbody.innerHTML = rows.map((download) => {
    const category = fileCategoryMeta(download);
    const finalPath = download.final_dest || download.path;
    return `
      <tr>
        <td>
          <div class="filename-cell">
            <div class="file-icon ${fileIconClass(download)}">${fileIcon(download)}</div>
            <span class="filename-text">${download.filename}</span>
          </div>
        </td>
        <td>${category.label}</td>
        <td><span class="source-badge badge-${download.source}">${sourceLabel(download.source)}</span></td>
        <td>${fmtSize(download.size)}</td>
        <td style="max-width:260px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--text3)">${finalPath}</td>
        <td>${fmtDate(download.created_at)}</td>
      </tr>
    `;
  }).join('');
}

function filterHistory() {
  const query = document.getElementById('historySearch').value.toLowerCase();
  const filtered = allDownloads.filter((download) => download.filename.toLowerCase().includes(query));
  renderHistoryRows(filtered);
}

async function renderRules(content) {
  const [rules, settings] = await Promise.all([api('/api/rules'), api('/api/settings')]);
  settingsCache = settings;
  rulesCache = rules;

  const manualRules = rules.filter((rule) => rule.rule_kind !== 'template');
  const templateRules = rules.filter((rule) => rule.rule_kind === 'template');
  const canAddManualRule = settings.plan !== 'free' || manualRules.length < 3;

  content.innerHTML = `
    <div class="section-header">
      <span class="section-label">기본 템플릿 규칙 ${templateRules.length}개 / 수동 규칙 ${manualRules.length}${settings.plan === 'free' ? ' / 3 무료' : ''}</span>
      ${canAddManualRule ? '<button class="btn primary" onclick="openModal()">+ 수동 규칙 추가</button>' : ''}
    </div>
    <div class="rule-list">
      ${rules.length ? rules.map((rule) => renderRuleItem(rule)).join('') : '<div class="empty-state" style="padding:32px 0">규칙이 없습니다.</div>'}
    </div>
    ${!canAddManualRule ? '<div class="free-limit">무료 플랜은 수동 규칙을 최대 3개까지 지원합니다.</div>' : ''}
  `;
}

function renderRuleItem(rule) {
  const isTemplate = rule.rule_kind === 'template';
  const badge = isTemplate ? '<span class="rule-type-badge">기본</span>' : '<span class="rule-type-badge manual">수동</span>';
  const actionButton = isTemplate
    ? '<span class="rule-lock">읽기 전용</span>'
    : `<button class="btn rule-del-btn" onclick="deleteRule(${rule.id})" title="삭제">✕</button>`;

  return `
    <div class="rule-item">
      <span class="rule-cat">${rule.category}</span>
      ${badge}
      <span class="rule-arrow">→</span>
      <span class="rule-dest">${rule.dest_folder}</span>
      <span class="rule-exts">${rule.ext_pattern.split(' ').slice(0, 4).join(' ')}${rule.ext_pattern.split(' ').length > 4 ? ' …' : ''}</span>
      ${actionButton}
    </div>
  `;
}

async function renderSettings(content) {
  const settings = await api('/api/settings');
  settingsCache = settings;
  const baseDir = settings.organize_base_dir || '';
  const preview = ['00영상', '01이미지', '02PDF', '03음악']
    .map((folder) => `<div class="ss-row"><span class="ss-key">${folder}</span><span class="ss-val">${baseDir}\\${folder}</span></div>`)
    .join('');

  content.innerHTML = `
    <div class="settings-grid">
      <div class="settings-section">
        <div class="ss-title">플랜</div>
        <div class="ss-row">
          <span class="ss-key">현재 플랜</span>
          <span class="plan-badge ${settings.plan === 'premium' ? 'premium' : ''}">${settings.plan === 'free' ? '무료' : '프리미엄'}</span>
        </div>
        <div class="ss-row">
          <span class="ss-key">수동 규칙 제한</span>
          <span class="ss-val">${settings.plan === 'free' ? '최대 3개' : '무제한'}</span>
        </div>
        <div class="ss-row">
          <span class="ss-key">기본 템플릿 규칙</span>
          <span class="ss-val">${settings.template_rule_count}개</span>
        </div>
      </div>

      <div class="settings-section">
        <div class="ss-title">기본 정리 폴더</div>
        <div class="settings-input-row">
          <input class="settings-input" id="organizeBaseDirInput" type="text" value="${baseDir}">
          <button class="btn primary" onclick="saveOrganizeBaseDir()">저장</button>
        </div>
        <div class="settings-hint">기본값은 Downloads\\seilF 입니다. 저장하면 템플릿 규칙이 새 경로로 갱신됩니다.</div>
        <div class="settings-button-row">
          <button class="btn" onclick="rebuildTemplateRules()">기본 템플릿 재생성</button>
        </div>
      </div>

      <div class="settings-section full">
        <div class="ss-title">기본 폴더 미리보기</div>
        ${preview}
      </div>
    </div>
  `;
}

async function saveOrganizeBaseDir() {
  const input = document.getElementById('organizeBaseDirInput');
  const organizeBaseDir = input.value.trim();
  if (!organizeBaseDir) {
    alert('기본 폴더 경로를 입력하세요.');
    return;
  }
  try {
    await postJson('/api/settings/organize-base-dir', { organize_base_dir: organizeBaseDir });
    await renderTab('settings');
    if (currentTab === 'rules') {
      await renderTab('rules');
    }
  } catch (error) {
    alert(`저장 실패: ${error.message}`);
  }
}

async function rebuildTemplateRules() {
  try {
    await postJson('/api/template-rules/rebuild');
    if (currentTab === 'settings') {
      await renderTab('settings');
    }
    if (currentTab === 'rules') {
      await renderTab('rules');
    }
  } catch (error) {
    alert(`재생성 실패: ${error.message}`);
  }
}

async function deleteRule(id) {
  if (!confirm('이 수동 규칙을 삭제하시겠습니까?')) return;
  const response = await fetch(`/api/rules/${id}`, {
    method: 'DELETE',
    headers: authHeaders(),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    alert(data.error || '삭제에 실패했습니다.');
    return;
  }
  renderTab('rules');
}

function openModal() {
  selectedCategoryKey = null;
  document.getElementById('folderInput').value = settingsCache?.organize_base_dir || '';
  const categoryGrid = document.getElementById('catGrid');
  const usedCategories = new Set(
    rulesCache
      .filter((rule) => rule.rule_kind !== 'template')
      .map((rule) => rule.category_key)
      .filter(Boolean)
  );
  const availableCategories = MANUAL_CATEGORIES.filter((category) => !usedCategories.has(category.key));
  if (!availableCategories.length) {
    alert('All manual categories are already assigned.');
    return;
  }
  categoryGrid.innerHTML = availableCategories.map((category) => `
    <div class="cat-card" data-key="${category.key}" onclick="selectCategory('${category.key}')">
      <span class="cc-icon">${category.icon}</span>
      <span class="cc-name">${category.label}</span>
    </div>
  `).join('');
  document.getElementById('ruleModal').classList.add('show');
}

function closeModal() {
  document.getElementById('ruleModal').classList.remove('show');
}

function selectCategory(categoryKey) {
  selectedCategoryKey = categoryKey;
  document.querySelectorAll('.cat-card').forEach((card) => {
    card.classList.toggle('on', card.dataset.key === categoryKey);
  });
}

async function saveRule() {
  const folder = document.getElementById('folderInput').value.trim();
  if (!selectedCategoryKey) {
    alert('카테고리를 선택하세요.');
    return;
  }
  if (!folder) {
    alert('대상 폴더를 입력하세요.');
    return;
  }

  const category = MANUAL_CATEGORIES.find((item) => item.key === selectedCategoryKey);
  try {
    await postJson('/api/rules', {
      category: category.label,
      category_key: category.key,
      ext_pattern: category.exts,
      dest_folder: folder,
      action: 'move',
    });
    closeModal();
    renderTab('rules');
  } catch (error) {
    alert(`규칙 저장 실패: ${error.message}`);
  }
}

async function checkErrors() {
  try {
    errorCache = await api('/api/errors');
    const banner = document.getElementById('errorBanner');
    if (!banner) return;
    if (errorCache.length > 0) {
      document.getElementById('errorBannerText').textContent = `최근 파일 이동 실패 ${errorCache.length}건`;
      banner.style.display = 'flex';
    } else {
      banner.style.display = 'none';
    }
  } catch (error) {
    // Ignore error banner refresh failures.
  }
}

function showErrorModal() {
  const modal = document.getElementById('errorModal');
  const list = document.getElementById('errorList');
  if (!modal || !list) return;
  list.innerHTML = errorCache.length ? errorCache.map((error) => `
    <div style="border:1px solid var(--border,#2d3148);border-radius:8px;padding:12px 14px;margin-bottom:10px;">
      <div style="font-size:12px;color:var(--text3,#94a3b8);margin-bottom:4px;">${error.timestamp}</div>
      <div style="font-size:13px;color:#fbbf24;margin-bottom:4px;word-break:break-all;">${error.filepath || '(경로 없음)'}</div>
      <div style="font-size:12px;color:var(--red,#ef4444);">${error.message}</div>
    </div>
  `).join('') : '<div style="color:var(--text3,#94a3b8);text-align:center;padding:32px;">오류가 없습니다.</div>';
  modal.style.display = 'flex';
}

async function clearErrorsAndHide() {
  try {
    await fetch('/api/errors', { method: 'DELETE', headers: authHeaders() });
    errorCache = [];
    const banner = document.getElementById('errorBanner');
    if (banner) banner.style.display = 'none';
    const modal = document.getElementById('errorModal');
    if (modal) modal.style.display = 'none';
  } catch (error) {
    alert(`오류 삭제 실패: ${error.message}`);
  }
}

function startEventStream() {
  try {
    const stream = new EventSource(`/api/events?token=${encodeURIComponent(token)}`);
    stream.onmessage = async () => {
      if (currentTab === 'active' || currentTab === 'history') {
        renderTab(currentTab);
      }
      checkErrors();
    };
  } catch (error) {
    // Ignore SSE failures on unsupported environments.
  }
}

document.addEventListener('DOMContentLoaded', async () => {
  document.getElementById('page-title').textContent = TITLES[currentTab];
  await renderTab(currentTab);
  await checkErrors();
  startEventStream();
  setInterval(checkErrors, 5000);
});

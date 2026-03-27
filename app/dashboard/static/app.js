/* ── 토큰 (URL ?token= 또는 sessionStorage) ── */
const _token = (() => {
  const t = new URLSearchParams(window.location.search).get('token') || '';
  if (t) sessionStorage.setItem('dd_token', t);
  return t || sessionStorage.getItem('dd_token') || '';
})();

function _authHeaders(extra = {}) {
  return { 'X-DropDone-Token': _token, ...extra };
}

/* ── API ── */
async function api(path) {
  const res = await fetch(path, { headers: _authHeaders() });
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return res.json();
}

/* ── Utils ── */
function fmtSize(b) {
  if (!b || b === 0) return '-';
  if (b > 1e9) return (b / 1e9).toFixed(1) + ' GB';
  if (b > 1e6) return (b / 1e6).toFixed(1) + ' MB';
  if (b > 1e3) return (b / 1e3).toFixed(0) + ' KB';
  return b + ' B';
}

function fmtDate(s) {
  if (!s) return '-';
  return s.replace('T', ' ').slice(0, 16);
}

const EXT_ICONS = {
  mp4:'🎬', mkv:'🎬', avi:'🎬', mov:'🎬', wmv:'🎬', webm:'🎬', m4v:'🎬',
  mp3:'🎵', flac:'🎵', wav:'🎵', aac:'🎵', ogg:'🎵', m4a:'🎵',
  zip:'📦', rar:'📦', '7z':'📦', tar:'📦', gz:'📦',
  jpg:'🖼', jpeg:'🖼', png:'🖼', gif:'🖼', webp:'🖼', bmp:'🖼', psd:'🖼',
  pdf:'📄', docx:'📄', xlsx:'📄', pptx:'📄', txt:'📄', hwp:'📄', csv:'📄',
  exe:'⚙', msi:'⚙', apk:'⚙',
};
const EXT_CLASS = {
  mp4:'icon-video', mkv:'icon-video', avi:'icon-video', mov:'icon-video', wmv:'icon-video', webm:'icon-video', m4v:'icon-video',
  mp3:'icon-etc', flac:'icon-etc', wav:'icon-etc',
  zip:'icon-zip', rar:'icon-zip', '7z':'icon-zip',
  jpg:'icon-img', jpeg:'icon-img', png:'icon-img', gif:'icon-img', webp:'icon-img',
  pdf:'icon-doc', docx:'icon-doc', xlsx:'icon-doc', txt:'icon-doc',
  exe:'icon-exe', msi:'icon-exe',
};

function getExt(filename) { return (filename || '').split('.').pop().toLowerCase(); }
function fileIcon(filename) { const e = getExt(filename); return EXT_ICONS[e] || '📁'; }
function fileIconClass(filename) { const e = getExt(filename); return EXT_CLASS[e] || 'icon-etc'; }

/* ── Nav ── */
const TITLES = { active:'진행 중', history:'완료 기록', rules:'자동 정리 규칙', settings:'설정' };

document.querySelectorAll('.nav-item').forEach(el => {
  el.addEventListener('click', () => {
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    el.classList.add('active');
    const tab = el.dataset.tab;
    document.getElementById('page-title').textContent = TITLES[tab];
    renderTab(tab);
  });
});

/* ── Tabs ── */
async function renderTab(tab) {
  const el = document.getElementById('content');
  el.innerHTML = '<div class="empty-state">불러오는 중...</div>';
  try {
    if (tab === 'active')   await renderActive(el);
    if (tab === 'history')  await renderHistory(el);
    if (tab === 'rules')    await renderRules(el);
    if (tab === 'settings') await renderSettings(el);
  } catch(e) {
    el.innerHTML = `<div class="empty-state" style="color:var(--red)">오류: ${e.message}</div>`;
  }
}

/* ── 진행 중 ── */
async function renderActive(el) {
  // 현재는 실시간 감지 데이터 없음 → 최근 1시간 내 기록 표시
  const downloads = await api('/api/downloads');
  const recent = downloads.filter(d => {
    const t = new Date(d.created_at.replace(' ', 'T'));
    return (Date.now() - t) < 3600_000;
  });

  document.getElementById('badge-active').textContent = recent.length;

  if (!recent.length) {
    el.innerHTML = `
      <div class="empty-state">
        <div style="font-size:36px;margin-bottom:12px">⏳</div>
        진행 중인 다운로드 없음<br>
        <span style="font-size:11px;margin-top:6px;display:block">Chrome Extension 설치 후 파일을 다운로드하면 여기에 표시됩니다</span>
      </div>`;
    return;
  }

  el.innerHTML = `
    <div class="section-label" style="margin-bottom:12px">최근 1시간 내 완료 (${recent.length}개)</div>
    <div class="dl-list">
      ${recent.map(d => `
        <div class="dl-card done">
          <div class="dl-card-top">
            <span class="source-badge badge-${d.source}">${d.source}</span>
            <span class="dl-name">${d.filename}</span>
            <span class="dl-size">${fmtSize(d.size)}</span>
          </div>
          <div class="dl-path">${d.path}</div>
          <div class="dl-meta">${fmtDate(d.created_at)}</div>
        </div>
      `).join('')}
    </div>`;
}

/* ── 완료 기록 ── */
let _allDownloads = [];

async function renderHistory(el) {
  _allDownloads = await api('/api/downloads');

  const total  = _allDownloads.length;
  const totalB = _allDownloads.reduce((s, d) => s + (d.size || 0), 0);
  const sources = [...new Set(_allDownloads.map(d => d.source))];

  el.innerHTML = `
    <div class="stats-grid">
      <div class="stat-card">
        <div class="s-label">총 다운로드</div>
        <div class="s-value">${total}</div>
      </div>
      <div class="stat-card">
        <div class="s-label">총 용량</div>
        <div class="s-value">${fmtSize(totalB)}</div>
      </div>
      <div class="stat-card">
        <div class="s-label">소스</div>
        <div class="s-value" style="font-size:14px">${sources.join(', ') || '-'}</div>
      </div>
    </div>

    <div class="search-bar">
      <span style="color:var(--text3)">🔍</span>
      <input type="text" id="historySearch" placeholder="파일명 검색..." oninput="filterHistory()">
    </div>

    <table class="history-table" id="historyTable">
      <thead>
        <tr>
          <th>파일명</th>
          <th>소스</th>
          <th>크기</th>
          <th>경로</th>
          <th>완료 시각</th>
        </tr>
      </thead>
      <tbody id="historyBody"></tbody>
    </table>`;

  renderHistoryRows(_allDownloads);
}

function renderHistoryRows(list) {
  const tbody = document.getElementById('historyBody');
  if (!list.length) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text3);padding:32px">기록 없음</td></tr>';
    return;
  }
  tbody.innerHTML = list.map(d => `
    <tr>
      <td>
        <div class="filename-cell">
          <div class="file-icon ${fileIconClass(d.filename)}">${fileIcon(d.filename)}</div>
          <span class="filename-text">${d.filename}</span>
        </div>
      </td>
      <td><span class="source-badge badge-${d.source}">${d.source}</span></td>
      <td>${fmtSize(d.size)}</td>
      <td style="max-width:260px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--text3)">${d.path}</td>
      <td>${fmtDate(d.created_at)}</td>
    </tr>
  `).join('');
}

function filterHistory() {
  const q = document.getElementById('historySearch').value.toLowerCase();
  renderHistoryRows(_allDownloads.filter(d => d.filename.toLowerCase().includes(q)));
}

/* ── 자동 정리 규칙 ── */
const CATS = [
  { id:'영상',    icon:'🎬', exts:'.mp4 .mkv .avi .mov .wmv .m4v .webm' },
  { id:'문서',    icon:'📄', exts:'.pdf .docx .xlsx .pptx .txt .hwp .csv' },
  { id:'압축',    icon:'📦', exts:'.zip .rar .7z .tar .gz .bz2' },
  { id:'이미지',  icon:'🖼', exts:'.jpg .jpeg .png .gif .webp .bmp .svg .psd' },
  { id:'음악',    icon:'🎵', exts:'.mp3 .flac .wav .aac .ogg .m4a' },
  { id:'실행파일',icon:'⚙', exts:'.exe .msi .apk .dmg' },
];

async function renderRules(el) {
  const rules = await api('/api/rules');
  const max = 3; // free plan

  el.innerHTML = `
    <div class="section-header">
      <span class="section-label">정리 규칙 (${rules.length}/${max} 무료)</span>
      ${rules.length < max ? `<button class="btn primary" onclick="openModal()">+ 규칙 추가</button>` : ''}
    </div>
    <div class="rule-list" id="ruleList">
      ${rules.length ? rules.map(r => `
        <div class="rule-item">
          <span class="rule-cat">${r.category}</span>
          <span class="rule-arrow">→</span>
          <span class="rule-dest">${r.dest_folder}</span>
          <span class="rule-exts">${r.ext_pattern.split(' ').slice(0,3).join(' ')}${r.ext_pattern.split(' ').length > 3 ? ' …' : ''}</span>
          <button class="btn rule-del-btn" onclick="deleteRule(${r.id})" title="삭제">✕</button>
        </div>
      `).join('') : '<div class="empty-state" style="padding:32px 0">등록된 규칙 없음</div>'}
    </div>
    ${rules.length >= max ? `<div class="free-limit">🔒 무료 플랜은 최대 3개 규칙까지 지원합니다</div>` : ''}`;
}

/* ── 설정 ── */
async function renderSettings(el) {
  const s = await api('/api/settings');

  el.innerHTML = `
    <div class="settings-grid">
      <div class="settings-section">
        <div class="ss-title">플랜</div>
        <div class="ss-row">
          <span class="ss-key">현재 플랜</span>
          <span class="plan-badge ${s.plan === 'premium' ? 'premium' : ''}">${s.plan === 'free' ? '무료' : '프리미엄'}</span>
        </div>
        <div class="ss-row">
          <span class="ss-key">규칙 제한</span>
          <span class="ss-val">${s.plan === 'free' ? '최대 3개' : '무제한'}</span>
        </div>
        <div class="ss-row">
          <span class="ss-key">자동 압축 해제</span>
          <span class="ss-val">${s.plan === 'free' ? '🔒 프리미엄' : '✅ 사용 가능'}</span>
        </div>
      </div>

      <div class="settings-section">
        <div class="ss-title">자동 종료</div>
        <div class="ss-row">
          <span class="ss-key">종료 동작</span>
          <span class="ss-val primary">${s.shutdown_action === 'shutdown' ? '⏻ 컴퓨터 종료' : s.shutdown_action}</span>
        </div>
        <div class="ss-row">
          <span class="ss-key">카운트다운</span>
          <span class="ss-val">${s.countdown_seconds}초</span>
        </div>
        <div class="ss-row">
          <span class="ss-key">UI 노출</span>
          <span class="ss-val" style="color:var(--text3)">v1.1 예정</span>
        </div>
      </div>

      <div class="settings-section full">
        <div class="ss-title">감시 소스</div>
        <div class="ss-row">
          <span class="ss-key">Chrome Extension</span>
          <span class="ss-val green">✅ Native Messaging 등록됨</span>
        </div>
        <div class="ss-row">
          <span class="ss-key">MEGA 폴더 감시</span>
          <span class="ss-val green">✅ Downloads 폴더 감시 중</span>
        </div>
        <div class="ss-row">
          <span class="ss-key">앱 감지 (tmp 패턴)</span>
          <span class="ss-val green">✅ Downloads 폴더 감시 중</span>
        </div>
        <div class="ss-row">
          <span class="ss-key">외부 HDD 복사</span>
          <span class="ss-val" style="color:var(--text3)">v1.1 예정</span>
        </div>
      </div>
    </div>`;
}

async function deleteRule(id) {
  if (!confirm('이 규칙을 삭제하시겠습니까?')) return;
  await fetch(`/api/rules/${id}`, { method: 'DELETE', headers: _authHeaders() });
  renderTab('rules');
}

/* ── 규칙 모달 ── */
let selectedCat = null;

function openModal() {
  selectedCat = null;
  document.getElementById('folderInput').value = '';
  const grid = document.getElementById('catGrid');
  grid.innerHTML = CATS.map(c => `
    <div class="cat-card" data-cat="${c.id}" onclick="selectCat('${c.id}')">
      <span class="cc-icon">${c.icon}</span>
      <span class="cc-name">${c.id}</span>
    </div>
  `).join('');
  document.getElementById('ruleModal').classList.add('show');
}

function selectCat(id) {
  selectedCat = id;
  document.querySelectorAll('.cat-card').forEach(c => c.classList.toggle('on', c.dataset.cat === id));
}

function closeModal() {
  document.getElementById('ruleModal').classList.remove('show');
}

async function saveRule() {
  const folder = document.getElementById('folderInput').value.trim();
  if (!selectedCat) { alert('카테고리를 선택하세요'); return; }
  if (!folder)      { alert('대상 폴더를 입력하세요'); return; }

  const cat = CATS.find(c => c.id === selectedCat);
  try {
    await fetch('/api/rules', {
      method: 'POST',
      headers: _authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ category: cat.id, ext_pattern: cat.exts, dest_folder: folder, action: 'move' }),
    });
    closeModal();
    renderTab('rules');
  } catch(e) {
    alert('저장 실패: ' + e.message);
  }
}

/* ── 에러 배너 ── */
let _errorCache = [];

async function checkErrors() {
  try {
    const errors = await api('/api/errors');
    _errorCache = errors;
    const banner = document.getElementById('errorBanner');
    if (!banner) return;
    if (errors.length > 0) {
      document.getElementById('errorBannerText').textContent =
        `⚠️ 파일 이동 실패 ${errors.length}건 — 자세히 보기`;
      banner.style.display = 'flex';
    } else {
      banner.style.display = 'none';
    }
  } catch(e) { /* 에러 API 실패 시 배너 숨김 유지 */ }
}

function showErrorModal() {
  const modal = document.getElementById('errorModal');
  const list  = document.getElementById('errorList');
  if (!modal || !list) return;
  list.innerHTML = _errorCache.length
    ? _errorCache.map(e => `
        <div style="border:1px solid var(--border,#2d3148);border-radius:8px;padding:12px 14px;margin-bottom:10px;">
          <div style="font-size:12px;color:var(--text3,#94a3b8);margin-bottom:4px;">${e.timestamp}</div>
          <div style="font-size:13px;color:#fbbf24;margin-bottom:4px;word-break:break-all;">${e.filepath || '(경로 없음)'}</div>
          <div style="font-size:12px;color:var(--red,#ef4444);">${e.message}</div>
        </div>`).join('')
    : '<div style="color:var(--text3,#94a3b8);text-align:center;padding:32px;">에러 없음</div>';
  modal.style.display = 'flex';
}

async function clearErrorsAndHide() {
  try {
    await fetch('/api/errors', { method: 'DELETE', headers: _authHeaders() });
    _errorCache = [];
    const banner = document.getElementById('errorBanner');
    if (banner) banner.style.display = 'none';
    const modal = document.getElementById('errorModal');
    if (modal) modal.style.display = 'none';
  } catch(e) { alert('삭제 실패: ' + e.message); }
}

/* ── 초기 로드 ── */
renderTab('active');
checkErrors();

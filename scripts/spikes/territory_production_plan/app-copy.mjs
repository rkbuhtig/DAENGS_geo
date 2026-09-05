import { Claims, access, disposition } from './claims.mjs';
import { runTests } from './tests.mjs';

const $ = id => document.getElementById(id);
const names = { p1: '보리', p2: '두부' };
const places = {
  A: { x: 155, y: 295, label: '골목 전봇대' },
  B: { x: 90, y: 395, label: '공원 입구' },
  C: { x: 310, y: 295, label: '산책길 보안등' },
};
const photoLabels = {
  PENDING: '확인 중 · 산책을 계속해도 돼요',
  VERIFIED: '인증 완료',
  REJECTED: '부적합 · 현장에서 다시 촬영',
  RETRY_PENDING: '통신 장애 · 사진 보관 중',
};
const state = {
  claims: new Claims(), session: null, serial: 0, pet: null, recording: false,
  visible: false, target: 'A', position: { x: 60, y: 350 }, trail: [],
  seconds: 0, meters: 0, jobs: [], camera: null, overlay: null, generation: 0,
  participants: [], selectedSite: null, diary: [], momentsOpen: false, gpsOpen: false, moments: [], notice: null, feedback: null,
};
const timers = new Set();
let previousFocus = null;
let feedbackTimer = null;

function celebrate(message, siteId) {
  clearTimeout(feedbackTimer);
  state.feedback = {message, siteId};
  feedbackTimer = setTimeout(() => { state.feedback = null; render(); }, 2400);
}

function distance(siteId = state.target) {
  const site = places[siteId];
  return Math.hypot(site.x - state.position.x, site.y - state.position.y) / 2;
}
function readiness(siteId = state.target) {
  return access({
    recording: state.recording && !!state.session,
    trusted: !['mock', 'denied'].includes($('gps').value),
    distance: distance(siteId), accuracy: $('gps').value === 'inaccurate' ? 30 : 3,
    age: $('gps').value === 'stale' ? 11 : 0,
  });
}
function attempt(siteId = state.target) { return state.claims.attempt(state.session, siteId); }
function claimingPet(siteId = state.target) { return attempt(siteId)?.pet || state.pet; }
function diaryReady() { return state.recording && !!state.session && !['stale', 'mock', 'denied'].includes($('gps').value); }
function canPhoto(siteId = state.target) {
  const current = attempt(siteId);
  const site = state.claims.sites.get(siteId);
  return $('board').value === 'ready' && readiness(siteId) === 'READY' &&
    (!current || ['NOT_SUBMITTED', 'REJECTED'].includes(current.photo)) &&
    (!!current || disposition(site, claimingPet(siteId)) !== 'ALREADY_OWNED' || site.occupancy?.certification === 'UNVERIFIED');
}
function guidance() {
  if (!state.recording) return '산책을 시작하거나 재개해 주세요';
  if ($('board').value !== 'ready') return {
    loading: '주변 점령지를 찾고 있어요', empty: '주변에 점령지가 없어요', error: '장소 조회에 실패했어요 · 조작판에서 다시 조회해 주세요',
  }[$('board').value];
  if (readiness() === 'UNAVAILABLE') return '정확한 현재 위치를 확인하고 있어요';
  const current = attempt();
  if (state.jobs.some(job => job.attempt === current && job.conflict)) return '점유가 변경돼 확정 보류 · 온라인 충돌 정책 미정';
  if (current?.photo === 'PENDING' || current?.photo === 'RETRY_PENDING') return photoLabels[current.photo];
  if (readiness() !== 'READY') return `${Math.round(distance())}m · 가까이 가면 영역표시할 수 있어요`;
  if (current?.photo === 'VERIFIED') return '발자국을 남겼어요 · 다음 장소로 걸어볼까요?';
  if (current?.photo === 'REJECTED') return '사진이 부적합해요 · 같은 장소에서 다시 촬영해 주세요';
  if (current) return '사진으로 우리 강아지의 영역을 인증해 주세요';
  return {
    GRANTED: '점령 준비 · 영역표시할 수 있어요',
    PHOTO_REQUIRED: '인증된 영역이에요 · 탈취에는 사진 인증이 필요해요',
    POLICY_UNDECIDED: '무사진 경쟁 정책은 미정 · 사진 인증은 가능해요',
    ALREADY_OWNED: canPhoto() ? '우리 강아지의 미인증 영역이에요 · 사진으로 인증해 주세요' : '이미 우리 강아지의 영역이에요',
  }[disposition(state.claims.sites.get(state.target), claimingPet())];
}

function renderMap() {
  $('trail').setAttribute('points', state.trail.map(p => `${p.x},${p.y}`).join(' '));
  $('player').setAttribute('transform', `translate(${state.position.x},${state.position.y})`);
  $('markers').innerHTML = state.visible && $('board').value === 'ready' ? Object.entries(places).map(([id, p]) => {
    const owner = state.claims.sites.get(id).occupancy;
    const color = !owner ? '#8f968e' : owner.certification === 'VERIFIED' ? '#4e9b70' : '#c98b32';
    const ring = readiness(id) === 'READY' ? '#4e9b70' : '#a99c8e';
    const progress = readiness(id) === 'READY' ? 1 : readiness(id) === 'UNAVAILABLE' ? 0 : Math.max(0, .9 - distance(id) / 100);
    const label = owner ? `${names[owner.pet]} · ${owner.certification === 'VERIFIED' ? '인증' : '미인증'}` : '미점유';
    return `<g class="marker" data-site="${id}" tabindex="0" role="button" aria-label="${id} ${p.label}, ${label}" transform="translate(${p.x},${p.y})">` +
      (id === state.selectedSite ? `<circle r="40" fill="${ring}12" stroke="${ring}55"/><circle r="40" fill="none" stroke="${ring}" stroke-width="3" stroke-dasharray="${progress * 251.3} 251.3" transform="rotate(-90)"/>` : '') +
      (state.feedback?.siteId === id ? `<circle class="claim-burst" r="42" fill="none" stroke="#4e9b70" stroke-width="3"/>` : '') +
      (owner ? `<g class="territory-stamp" transform="translate(-22,17) rotate(-18)"><ellipse cy="5" rx="6" ry="5" fill="${color}"/><g fill="${color}"><circle cx="-6" cy="-3" r="2.5"/><circle cx="0" cy="-6" r="2.5"/><circle cx="6" cy="-3" r="2.5"/></g></g>` : '') +
      `<circle r="15" fill="white" stroke="${color}" stroke-width="2"/><path d="M0 -9V9M-6 -5H6M-4 -1H4" stroke="${color}" stroke-width="2" fill="none"/>` +
      (id !== state.selectedSite ? `<text text-anchor="middle" y="-24" font-size="10" fill="#75665c">${id} · ${label}</text>` : '') + '</g>';
  }).join('') : '';
}

function renderGps() {
  const mode = $('gps').value;
  const weak = mode === 'inaccurate';
  const good = mode === 'good';
  const label = good ? 'GPS 양호' : weak ? 'GPS 불안정' : 'GPS 확인 필요';
  $('gps-status').dataset.quality = good ? 'good' : weak ? 'weak' : 'bad';
  $('gps-status').setAttribute('aria-label', label);
  $('gps-status').title = label;
  $('gps-status').setAttribute('aria-expanded', String(state.gpsOpen));
  $('gps-status').firstElementChild.textContent = good ? '' : '!';
  $('gps-detail').hidden = !state.gpsOpen;
  $('gps-detail').textContent = {good:'GPS 양호 · 현재 위치를 확인했어요', inaccurate:'GPS 오차 약 30m · 영역표시는 정확한 위치가 필요해요', stale:'위치 정보가 오래됐어요 · 새 위치를 기다려 주세요', mock:'모의 위치에서는 현장 기록을 남길 수 없어요', denied:'위치 권한을 허용해 주세요'}[mode];
}
function renderDiary() {
  $('diary-markers').innerHTML = state.diary.map((entry, index) => `<g data-diary="${entry.id}" class="diary-pin" role="button" tabindex="0" aria-label="산책 사진 ${index + 1}" transform="translate(${entry.position.x},${entry.position.y})"><path d="M0 0L-10 -17H10Z" fill="#b66c79"/><rect x="-17" y="-43" width="34" height="30" rx="7" fill="white" stroke="#b66c79"/><text text-anchor="middle" y="-22" font-size="20">🐕</text></g>`).join('');
  $('diary-list').replaceChildren();
  if (!state.diary.length) $('diary-list').textContent = '아직 남긴 사진이 없어요';
  [...state.diary].reverse().forEach(entry => {
    const row = document.createElement('article'); row.className = 'diary-entry'; row.dataset.position = `${entry.position.x},${entry.position.y}`;
    const preview = document.createElement('div'); preview.className = 'diary-thumbnail'; preview.textContent = '🐕'; preview.setAttribute('aria-label', '샘플 사진');
    const caption = document.createElement('p'); caption.textContent = entry.caption || '오늘의 산책 한 장면';
    const meta = document.createElement('small'); meta.textContent = `${entry.participants.map(p => names[p]).join(', ')} · ${new Date(entry.capturedAt).toLocaleTimeString('ko-KR', {hour:'2-digit', minute:'2-digit'})} · 위치 오차 약 ${entry.accuracy}m · 샘플`;
    row.append(preview, caption, meta); $('diary-list').append(row);
  });
}
function renderJobs() {
  const pending = state.jobs.filter(j => j.attempt.photo === 'PENDING' && !j.conflict).length;
  const failed = state.jobs.filter(j => ['RETRY_PENDING', 'REJECTED'].includes(j.attempt.photo) || j.conflict).length;
  $('photo-strip').hidden = state.jobs.length === 0;
  $('open-jobs').textContent = pending ? `사진 인증 연습 · ${pending}건 확인 중  ›` : failed ? `사진 인증 연습 · ${failed}건 확인 필요  ›` : '사진 인증 연습 · 인증 완료  ›';
  const list = $('jobs');
  list.replaceChildren();
  [...state.jobs].reverse().forEach(job => {
    const row = document.createElement('div');
    row.className = 'job'; row.dataset.capture = job.capture;
    row.textContent = `${job.attempt.siteId} · ${names[job.attempt.pet]} · ${job.conflict ? '점유 변경으로 확정 보류' : photoLabels[job.attempt.photo]}`;
    if (job.attempt.photo === 'RETRY_PENDING' && !job.conflict) {
      const retry = document.createElement('button');
      retry.className = 'pink-button'; retry.textContent = '같은 사진으로 재시도';
      retry.onclick = () => { state.claims.resume(job.attempt); evaluate(job, 'ACCEPTED'); render(); };
      row.append(document.createElement('br'), retry);
    }
    list.append(row);
  });
}

function render() {
  $('phone').classList.toggle('playing', state.visible && !!state.session);
  $('toggle').setAttribute('aria-label', state.visible ? '점령지 숨기기' : '점령지 보기');
  $('toggle').title = $('toggle').getAttribute('aria-label');
  $('toggle').setAttribute('aria-pressed', String(state.visible));
  $('territory-card').hidden = !state.visible || !state.selectedSite || $('board').value !== 'ready';
  $('moment-dock').hidden = !state.momentsOpen || !state.recording;
  $('open-moments').setAttribute('aria-expanded', String(state.momentsOpen));
  $('primary-row').hidden = !state.session;
  $('diary-camera').disabled = !diaryReady();
  $('open-moments').disabled = !state.recording;
  const petSelect = $('claim-pet');
  petSelect.replaceChildren(...state.participants.map(pet => new Option(names[pet], pet)));
  petSelect.value = claimingPet() || '';
  petSelect.disabled = !!attempt() || !state.recording;
  renderGps(); renderDiary();
  $('ready-card').hidden = !!state.session;
  $('recording-control').hidden = !state.recording;
  $('start').disabled = !document.querySelector('input[name="pet"]:checked') || $('gps').value === 'denied';
  document.querySelectorAll('[data-moment]').forEach(button => { button.disabled = readiness() === 'UNAVAILABLE'; });
  const owner = state.claims.sites.get(state.target).occupancy;
  const boardReady = $('board').value === 'ready';
  $('site-title').textContent = boardReady ? `${state.target} · ${places[state.target].label}` : '주변 점령지';
  $('owner').textContent = !boardReady ? '' : !owner ? '미점유' : `${names[owner.pet]} · ${owner.certification === 'VERIFIED' ? '인증' : '미인증'}`;
  $('representative').textContent = claimingPet() ? `영역표시 주체 · ${names[claimingPet()]}` : '함께 걷는 강아지를 선택해 주세요';
  $('guidance').textContent = guidance();
  $('mark').disabled = !boardReady || readiness() !== 'READY' || !!attempt() || disposition(state.claims.sites.get(state.target), claimingPet()) !== 'GRANTED';
  $('mark').textContent = attempt() ? '영역표시 완료' : '⌖ 영역표시';
  $('mark').hidden = $('mark').disabled;
  $('photograph').disabled = !canPhoto();
  $('photograph').textContent = attempt()?.photo === 'REJECTED' ? '다시 촬영' : '영역표시 인증 촬영';
  $('photograph').hidden = $('photograph').disabled;
  $('photograph').classList.toggle('secondary-photo', !$('mark').disabled);
  if (!$('mark').disabled) $('photograph').innerHTML = '<svg aria-hidden="true" width="22" height="20" viewBox="0 0 24 22" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M8 5l2-3h4l2 3h4v14H4V5z" stroke-linejoin="round"/><circle cx="12" cy="11" r="3.5"/></svg>';
  $('photograph').setAttribute('aria-label', attempt()?.photo === 'REJECTED' ? '다시 촬영' : '영역표시 인증 촬영');
  $('photograph').title = '영역표시 인증 촬영';
  $('notice').hidden = !state.notice && (!state.visible || boardReady);
  $('target-label').hidden = !state.visible || !state.selectedSite || !boardReady;
  $('target-label').classList.toggle('ready', readiness() === 'READY');
  $('target-state').textContent = readiness() === 'READY' ? '영역 안에 들어왔어요' : readiness() === 'UNAVAILABLE' ? '현재 위치 확인 중' : '조금 더 가까이';
  if (owner?.pet === claimingPet()) $('target-state').textContent = `${names[owner.pet]}의 발자국`;
  if (state.feedback?.siteId === state.target) $('target-state').textContent = state.feedback.message;
  $('target-distance').textContent = `${Math.round(distance())}m · ${owner ? names[owner.pet] + (owner.certification === 'VERIFIED' ? '의 인증 영역' : ' · 미인증') : '아직 비어 있는 장소'}`;
  $('notice').textContent = state.notice || (!boardReady ? {loading:'주변 점령지를 찾고 있어요', empty:'주변에 점령지가 없어요', error:'장소 조회에 실패했어요 · 다시 조회해 주세요'}[$('board').value] : '');
  $('notice').classList.toggle('error', readiness() === 'UNAVAILABLE' && !!state.session);
  $('state-inspector').replaceChildren();
  const entries = {
    '산책 세션': state.session || '시작 전', '참여견 / 영역표시 주체': state.pet ? `${state.participants.map(p => names[p]).join(', ')} / ${names[state.pet]}` : '선택 대기',
    '지도 표시': state.visible ? '점령지 표시' : '일반 산책', '대상 접근': `${Math.round(distance())}m · ${readiness()}`,
    '산책 사진': `${state.diary.length}건`, '행동 기록': `${state.moments.length}건`, '점령 시도': `${state.claims.attempts.size}건 (시드 포함)`,
  };
  for (const [label, value] of Object.entries(entries)) {
    const dt = document.createElement('dt'); dt.textContent = label;
    const dd = document.createElement('dd'); dd.textContent = value;
    $('state-inspector').append(dt, dd);
  }
  renderMap(); renderJobs(); renderClock(); layout();
}
function renderClock() {
  $('elapsed').textContent = `${String(Math.floor(state.seconds / 60)).padStart(2, '0')}:${String(state.seconds % 60).padStart(2, '0')}`;
  $('distance').textContent = `${Math.round(state.meters)} m`;
}
function move(near) {
  const p = places[$('target').value];
  const next = near ? {x:p.x + 28, y:p.y + 8} : {x:40, y:350};
  if (state.recording) {
    state.meters += Math.hypot(state.position.x - next.x, state.position.y - next.y) / 2;
    state.trail.push(next);
  }
  state.position = next;
  state.target = $('target').value;
  state.notice = null;
  render();
}
function setOverlay(id) {
  if (id && !state.overlay) previousFocus = document.activeElement;
  for (const item of ['camera', 'pause-screen', 'result-screen', 'jobs-screen', 'diary-screen']) $(item).hidden = item !== id;
  state.overlay = id;
  $('walk-surface').inert = !!id;
  $('photo-strip').inert = !!id;
  if (id) $(id).querySelector('button')?.focus();
  else if (previousFocus?.isConnected && !previousFocus.disabled) previousFocus.focus();
}
function evaluate(job, outcome) {
  const generation = state.generation;
  const timer = setTimeout(() => {
    timers.delete(timer);
    if (state.generation !== generation) return;
    try {
      const before = state.claims.sites.get(job.attempt.siteId).occupancy;
      state.claims.resolve(job.attempt, job.capture, outcome === 'DELAY' ? 'ACCEPTED' : outcome);
      if (job.attempt.photo === 'VERIFIED') celebrate(
        before && before.pet !== job.attempt.pet ? `${names[job.attempt.pet]}가 ${job.attempt.siteId} 영역을 차지했어요!` : `${names[job.attempt.pet]}의 ${job.attempt.siteId} 발자국, 인증 완료!`,
        job.attempt.siteId,
      );
    }
    catch (e) { job.conflict = e.message; }
    render();
  }, outcome === 'DELAY' ? 15000 : 2000);
  timers.add(timer);
}
function layout() {
  const workspace = document.querySelector('.workspace');
  if (innerWidth < 740) workspace.classList.remove('landscape');
  $('rotate').disabled = innerWidth < 740;
  const landscape = workspace.classList.contains('landscape');
  $('rotate').setAttribute('aria-label', landscape ? '세로 보기' : '가로 보기');
  $('rotate').title = $('rotate').getAttribute('aria-label');
  $('size-label').textContent = landscape ? '844 × 390 기준' : '390 × 844 기준';
  $('phone').style.setProperty('--surface-width', `${$('walk-surface').clientWidth}px`);
  fitMap();
}

/** Frame the live position and target inside the space left by the actual overlays.
 * Coordinates and distance rules stay unchanged; this is a camera transform only. */
function fitMap() {
  const surface = $('walk-surface').getBoundingClientRect();
  const w = surface.width, h = surface.height;
  if (!w || !h) return;
  const top = Math.max($('hud').getBoundingClientRect().bottom, $('walk-top').getBoundingClientRect().bottom) - surface.top + 68;
  let bottom = $('bottom-stack').getBoundingClientRect().top - surface.top - 22;
  let left = 45, right = w - 45;
  if (document.querySelector('.workspace').classList.contains('landscape') && !$('territory-card').hidden && state.recording) {
    const card = $('territory-card').getBoundingClientRect();
    const controls = $('primary-row').getBoundingClientRect();
    if (controls.left - card.right > 150) {
      left = card.right - surface.left + 24;
      right = controls.left - surface.left - 24;
      bottom = h - 18;
    }
  }
  const target = state.visible && $('board').value === 'ready' ? places[state.target] : state.position;
  const spanX = Math.abs(target.x - state.position.x), spanY = Math.abs(target.y - state.position.y);
  const scale = Math.max(.15, Math.min(1, (right - left) / (spanX + 85), Math.max(35, bottom - top) / (spanY + 100)));
  const midX = (target.x + state.position.x) / 2, midY = (target.y + state.position.y) / 2;
  const originX = midX - (left + right) / 2 / scale, originY = midY - (top + bottom) / 2 / scale;
  $('map').setAttribute('viewBox', `${originX} ${originY} ${w / scale} ${h / scale}`);
  const halfLabel = $('target-label').getBoundingClientRect().width / 2 + 8;
  $('target-label').style.left = `${Math.max(halfLabel, Math.min(w - halfLabel, (target.x - originX) * scale))}px`;
  $('target-label').style.top = `${(target.y - originY) * scale - 40 * scale - 10}px`;
}

$('reset').onclick = () => {
  clearTimeout(feedbackTimer); state.feedback = null;
  state.generation++; timers.forEach(clearTimeout); timers.clear();
  Object.assign(state, {claims:new Claims(), session:null, serial:0, pet:null, recording:false, visible:false, target:'A', position:{x:60,y:350}, trail:[], seconds:0, meters:0, jobs:[], camera:null, participants:[], selectedSite:null, diary:[], momentsOpen:false, gpsOpen:false, moments:[], notice:null});
  setOverlay(null); $('target').value = 'A'; $('gps').value = 'good'; $('board').value = 'ready';
  if ($('preset').value !== 'neutral') {
    const seed = state.claims.mark('seed-walk', 'p2', 'A');
    if ($('preset').value === 'rival') { state.claims.submit(seed, 'seed-photo'); state.claims.resolve(seed, 'seed-photo', 'ACCEPTED'); }
  }
  render();
};
$('start').onclick = () => {
  if ($('start').disabled || state.session) return;
  state.participants = [...document.querySelectorAll('input[name="pet"]:checked')].map(input => input.value);
  if (!state.participants.includes(state.pet)) state.pet = state.participants[0]; state.session = `walk-${++state.serial}`;
  state.recording = true; state.seconds = 0; state.meters = 0; state.trail = [state.position]; state.moments = []; state.notice = null;
  render();
};
$('pause').onclick = () => { state.recording = false; render(); setOverlay('pause-screen'); };
$('resume').onclick = () => { state.recording = true; setOverlay(null); render(); };
$('finish').onclick = () => { $('result-text').textContent = `${state.participants.map(p => names[p]).join(', ')}와 ${Math.round(state.meters)}m · 행동 ${state.moments.length}건`; setOverlay('result-screen'); };
$('next-walk').onclick = () => { state.session = null; state.selectedSite = null; state.momentsOpen = false; state.visible = false; state.notice = null; setOverlay(null); render(); };
$('toggle').onclick = () => { state.visible = !state.visible; state.selectedSite = null; state.momentsOpen = false; state.notice = null; render(); };
$('home').onclick = () => { state.notice = '홈 화면은 검토 범위 밖이에요 · 산책 상태는 유지해요'; render(); };
$('locate').onclick = () => { state.notice = '현재 위치를 보고 있어요'; render(); };
$('rotate').onclick = () => { document.querySelector('.workspace').classList.toggle('landscape'); layout(); };
$('near').onclick = () => move(true);
$('far').onclick = () => move(false);
$('target').onchange = () => { state.target = $('target').value; state.selectedSite = null; render(); };
for (const id of ['gps', 'board']) $(id).onchange = () => { state.notice = null; render(); };
document.querySelectorAll('input[name="pet"]').forEach(input => { input.onchange = render; });
document.querySelectorAll('[data-moment]').forEach(button => {
  button.onclick = () => { state.momentsOpen = false; state.moments.push(button.dataset.moment); state.notice = `${button.dataset.moment} 기록을 남겼어요`; render(); };
});
$('markers').onclick = event => {
  const site = event.target.closest('[data-site]')?.dataset.site;
  if (site) { state.target = site; state.selectedSite = site; state.momentsOpen = false; state.notice = null; $('target').value = site; render(); }
};
$('markers').onkeydown = event => {
  if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); event.target.dispatchEvent(new MouseEvent('click', {bubbles:true})); }
};
$('mark').onclick = () => {
  if ($('mark').disabled) return;
  state.claims.mark(state.session, claimingPet(), state.target, readiness() === 'READY'); render();
  celebrate(`${names[claimingPet()]}의 발자국을 남겼어요!`, state.target); render();
};
function openCamera(purpose) {
  if (purpose === 'claim' ? !canPhoto() || !state.selectedSite : !diaryReady()) return;
  state.camera = {purpose, session:state.session, pet:claimingPet(), site:state.target};
  $('camera-title').textContent = purpose === 'claim' ? '영역표시 인증' : '산책 사진';
  $('camera').setAttribute('aria-label', $('camera-title').textContent);
  $('camera-context').textContent = purpose === 'claim' ? `${names[claimingPet()]} · ${places[state.target].label}` : '촬영한 현재 위치에 사진을 남겨요';
  $('diary-caption-label').hidden = purpose !== 'diary';
  $('diary-caption').value = '';
  $('camera-error').textContent = '';
  setOverlay('camera');
}
$('photograph').onclick = () => openCamera('claim');
$('diary-camera').onclick = () => openCamera('diary');
$('cancel-camera').onclick = () => { state.camera = null; setOverlay(null); };
$('shutter').onclick = () => {
  const target = state.camera;
  if (!target || target.session !== state.session || (target.purpose === 'diary' ? !diaryReady() : target.pet !== claimingPet(target.site) || !canPhoto(target.site))) {
    $('camera-error').textContent = '촬영할 수 없어요 · 같은 산책에서 현재 위치를 다시 확인해 주세요'; return;
  }
  if (target.purpose === 'diary') {
    state.diary.push({id:crypto.randomUUID(), session:state.session, participants:[...state.participants], position:{...state.position}, accuracy:$('gps').value === 'inaccurate' ? 30 : 3, capturedAt:new Date().toISOString(), caption:$('diary-caption').value.trim()});
    state.notice = '촬영한 위치에 산책 사진을 남겼어요';
  } else {
    const current = state.claims.mark(state.session, target.pet, target.site, true);
    const capture = crypto.randomUUID();
    state.claims.submit(current, capture);
    state.jobs = state.jobs.filter(job => job.attempt !== current);
    const job = {attempt:current, capture, conflict:null}; state.jobs.push(job);
    evaluate(job, $('verdict').value);
  }
  state.camera = null; setOverlay(null); render();
};
$('close-site').onclick = () => { state.selectedSite = null; render(); };
$('map').addEventListener('click', event => {
  if (!event.target.closest('[data-site], [data-diary]')) { state.selectedSite = null; render(); }
});
$('claim-pet').onchange = () => { if (!attempt() && state.participants.includes($('claim-pet').value)) state.pet = $('claim-pet').value; render(); };
$('open-moments').onclick = () => { state.momentsOpen = !state.momentsOpen; state.selectedSite = null; state.notice = null; render(); };
$('gps-status').onclick = () => { state.gpsOpen = !state.gpsOpen; renderGps(); };
$('open-diary').onclick = () => setOverlay('diary-screen');
$('close-diary').onclick = () => setOverlay(null);
$('diary-markers').onclick = event => { if (event.target.closest('[data-diary]')) setOverlay('diary-screen'); };
$('diary-markers').onkeydown = event => { if (['Enter', ' '].includes(event.key)) { event.preventDefault(); setOverlay('diary-screen'); } };
$('open-jobs').onclick = () => setOverlay('jobs-screen');
$('close-jobs').onclick = () => setOverlay(null);
$('phone').addEventListener('keydown', event => {
  if (!state.overlay) return;
  if (event.key === 'Escape' && ['camera', 'jobs-screen', 'diary-screen'].includes(state.overlay)) {
    state.camera = null; setOverlay(null); event.preventDefault(); return;
  }
  if (event.key === 'Tab') {
    const buttons = [...$(state.overlay).querySelectorAll('button:not(:disabled), input:not(:disabled)')].filter(el => el.getClientRects().length);
    const first = buttons[0], last = buttons.at(-1);
    if (event.shiftKey && document.activeElement === first) { last?.focus(); event.preventDefault(); }
    else if (!event.shiftKey && document.activeElement === last) { first?.focus(); event.preventDefault(); }
  }
});
window.addEventListener('resize', layout);
setInterval(() => { if (state.recording) { state.seconds++; renderClock(); } }, 1000);
render();
try {
  const response = await fetch('territory-claim-scenarios.tsv');
  if (!response.ok) throw new Error('fixture unavailable');
  const results = runTests(await response.text());
  $('contract-tests').textContent = `공통 점령 계약 + 경계 ${results.length}개 통과`;
  document.documentElement.dataset.tests = 'passed';
} catch (e) {
  $('contract-tests').textContent = `계약 검사 실패: ${e.message}`;
  document.documentElement.dataset.tests = 'failed';
}

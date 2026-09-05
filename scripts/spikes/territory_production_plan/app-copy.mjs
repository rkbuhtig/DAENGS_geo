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
  moments: [], notice: null,
};
const timers = new Set();
let previousFocus = null;

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
function canPhoto(siteId = state.target) {
  const current = attempt(siteId);
  const site = state.claims.sites.get(siteId);
  return $('board').value === 'ready' && readiness(siteId) === 'READY' &&
    (!current || ['NOT_SUBMITTED', 'REJECTED'].includes(current.photo)) &&
    (!!current || disposition(site, state.pet) !== 'ALREADY_OWNED' || site.occupancy?.certification === 'UNVERIFIED');
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
  if (current?.photo === 'VERIFIED') return '이번 산책에서 이미 인증한 장소예요';
  if (current?.photo === 'REJECTED') return '사진이 부적합해요 · 같은 장소에서 다시 촬영해 주세요';
  if (current) return '사진을 찍어 같은 영역표시를 인증할 수 있어요';
  return {
    GRANTED: '점령 준비 · 영역표시할 수 있어요',
    PHOTO_REQUIRED: '인증된 영역이에요 · 탈취에는 사진 인증이 필요해요',
    POLICY_UNDECIDED: '무사진 경쟁 정책은 미정 · 사진 인증은 가능해요',
    ALREADY_OWNED: canPhoto() ? '우리 강아지의 미인증 영역이에요 · 사진으로 인증해 주세요' : '이미 우리 강아지의 영역이에요',
  }[disposition(state.claims.sites.get(state.target), state.pet)];
}

function renderMap() {
  $('trail').setAttribute('points', state.trail.map(p => `${p.x},${p.y}`).join(' '));
  $('player').setAttribute('transform', `translate(${state.position.x},${state.position.y})`);
  $('markers').innerHTML = state.visible && $('board').value === 'ready' ? Object.entries(places).map(([id, p]) => {
    const owner = state.claims.sites.get(id).occupancy;
    const color = !owner ? '#8f968e' : owner.certification === 'VERIFIED' ? '#4e9b70' : '#c98b32';
    const ring = readiness() === 'READY' ? '#4e9b70' : '#8f968e';
    const label = owner ? `${names[owner.pet]} · ${owner.certification === 'VERIFIED' ? '인증' : '미인증'}` : '미점유';
    return `<g class="marker" data-site="${id}" tabindex="0" role="button" aria-label="${id} ${p.label}, ${label}" transform="translate(${p.x},${p.y})">` +
      (id === state.target ? `<circle r="40" fill="${ring}18" stroke="${ring}" stroke-dasharray="4 4"/>` : '') +
      `<circle r="13" fill="${color}" stroke="white" stroke-width="3"/><text text-anchor="middle" y="4" font-size="11" fill="white">${id}</text><text text-anchor="middle" y="-22" font-size="10" fill="#4a3b36">${label}</text></g>`;
  }).join('') : '';
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
  $('toggle').textContent = state.visible ? '점령지 숨기기' : '점령지 보기';
  $('toggle').setAttribute('aria-pressed', String(state.visible));
  $('territory-card').hidden = !state.visible;
  $('moment-dock').hidden = state.visible || !state.recording;
  $('ready-card').hidden = !!state.session;
  $('recording-control').hidden = !state.recording;
  $('start').disabled = !document.querySelector('input[name="pet"]:checked') || $('gps').value === 'denied';
  document.querySelectorAll('[data-moment]').forEach(button => { button.disabled = readiness() === 'UNAVAILABLE'; });
  const owner = state.claims.sites.get(state.target).occupancy;
  const boardReady = $('board').value === 'ready';
  $('site-title').textContent = boardReady ? `${state.target} · ${places[state.target].label}` : '주변 점령지';
  $('owner').textContent = !boardReady ? '' : !owner ? '미점유' : `${names[owner.pet]} · ${owner.certification === 'VERIFIED' ? '인증' : '미인증'}`;
  $('representative').textContent = state.pet ? `영역표시 주체 · ${names[state.pet]}` : '함께 걷는 강아지를 선택해 주세요';
  $('guidance').textContent = guidance();
  $('mark').disabled = !boardReady || readiness() !== 'READY' || !!attempt() || disposition(state.claims.sites.get(state.target), state.pet) !== 'GRANTED';
  $('mark').textContent = attempt() ? '영역표시 완료' : '⌖ 영역표시';
  $('photograph').disabled = !canPhoto();
  $('photograph').textContent = attempt()?.photo === 'REJECTED' ? '다시 촬영' : '영역표시 인증 촬영';
  $('notice').textContent = state.notice || (readiness() === 'UNAVAILABLE' && state.session ? '정확한 현재 위치를 확인하고 있어요' : state.recording ? '산책을 기록하고 있어요' : '함께 걷는 강아지를 선택해 주세요');
  $('notice').classList.toggle('error', readiness() === 'UNAVAILABLE' && !!state.session);
  $('state-inspector').replaceChildren();
  const entries = {
    '산책 세션': state.session || '시작 전', '참여견 / 영역표시 주체': state.pet ? `${state.participants.map(p => names[p]).join(', ')} / ${names[state.pet]}` : '선택 대기',
    '지도 표시': state.visible ? '점령지 표시' : '일반 산책', '대상 접근': `${Math.round(distance())}m · ${readiness()}`,
    '행동 기록': `${state.moments.length}건`, '점령 시도': `${state.claims.attempts.size}건 (시드 포함)`,
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
  const next = near ? {x:p.x + 8, y:p.y + 4} : {x:40, y:350};
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
  for (const item of ['camera', 'pause-screen', 'result-screen', 'jobs-screen']) $(item).hidden = item !== id;
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
    try { state.claims.resolve(job.attempt, job.capture, outcome === 'DELAY' ? 'ACCEPTED' : outcome); }
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
  $('rotate').textContent = landscape ? '세로 보기' : '가로 보기';
  $('size-label').textContent = landscape ? '844 × 390 기준' : '390 × 844 기준';
  $('phone').style.setProperty('--surface-width', `${$('walk-surface').clientWidth}px`);
}

$('reset').onclick = () => {
  state.generation++; timers.forEach(clearTimeout); timers.clear();
  Object.assign(state, {claims:new Claims(), session:null, serial:0, pet:null, recording:false, visible:false, target:'A', position:{x:60,y:350}, trail:[], seconds:0, meters:0, jobs:[], camera:null, moments:[], notice:null});
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
  state.pet = state.participants[0]; state.session = `walk-${++state.serial}`;
  state.recording = true; state.seconds = 0; state.meters = 0; state.trail = [state.position]; state.moments = []; state.notice = null;
  render();
};
$('pause').onclick = () => { state.recording = false; render(); setOverlay('pause-screen'); };
$('resume').onclick = () => { state.recording = true; setOverlay(null); render(); };
$('finish').onclick = () => { $('result-text').textContent = `${names[state.pet]}와 ${Math.round(state.meters)}m · 행동 ${state.moments.length}건`; setOverlay('result-screen'); };
$('next-walk').onclick = () => { state.session = null; state.pet = null; state.visible = false; state.notice = null; setOverlay(null); render(); };
$('toggle').onclick = () => { state.visible = !state.visible; state.notice = null; render(); };
$('home').onclick = () => { state.notice = '홈 화면은 검토 범위 밖이에요 · 산책 상태는 유지해요'; render(); };
$('locate').onclick = () => { state.notice = '현재 위치를 보고 있어요'; render(); };
$('rotate').onclick = () => { document.querySelector('.workspace').classList.toggle('landscape'); layout(); };
$('near').onclick = () => move(true);
$('far').onclick = () => move(false);
$('target').onchange = () => { state.target = $('target').value; render(); };
for (const id of ['gps', 'board']) $(id).onchange = () => { state.notice = null; render(); };
document.querySelectorAll('input[name="pet"]').forEach(input => { input.onchange = render; });
document.querySelectorAll('[data-moment]').forEach(button => {
  button.onclick = () => { state.moments.push(button.dataset.moment); state.notice = `${button.dataset.moment} 기록을 남겼어요`; render(); };
});
$('markers').onclick = event => {
  const site = event.target.closest('[data-site]')?.dataset.site;
  if (site) { state.target = site; $('target').value = site; render(); }
};
$('markers').onkeydown = event => {
  if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); event.target.dispatchEvent(new MouseEvent('click', {bubbles:true})); }
};
$('mark').onclick = () => {
  if ($('mark').disabled) return;
  state.claims.mark(state.session, state.pet, state.target, readiness() === 'READY'); render();
};
$('photograph').onclick = () => {
  if (!canPhoto()) return;
  state.camera = { session:state.session, pet:state.pet, site:state.target };
  $('camera-context').textContent = `${names[state.pet]} · ${places[state.target].label}`;
  $('camera-error').textContent = '';
  setOverlay('camera');
};
$('cancel-camera').onclick = () => { state.camera = null; setOverlay(null); };
$('shutter').onclick = () => {
  const target = state.camera;
  if (!target || target.session !== state.session || target.pet !== state.pet || !canPhoto(target.site)) {
    $('camera-error').textContent = '촬영할 수 없어요 · 같은 산책에서 현재 위치를 다시 확인해 주세요'; return;
  }
  const current = state.claims.mark(state.session, state.pet, target.site, true);
  const capture = crypto.randomUUID();
  state.claims.submit(current, capture);
  state.jobs = state.jobs.filter(job => job.attempt !== current);
  const job = {attempt:current, capture, conflict:null}; state.jobs.push(job);
  evaluate(job, $('verdict').value); state.camera = null; setOverlay(null); render();
};
$('open-jobs').onclick = () => setOverlay('jobs-screen');
$('close-jobs').onclick = () => setOverlay(null);
$('phone').addEventListener('keydown', event => {
  if (!state.overlay) return;
  if (event.key === 'Escape' && ['camera', 'jobs-screen'].includes(state.overlay)) {
    state.camera = null; setOverlay(null); event.preventDefault(); return;
  }
  if (event.key === 'Tab') {
    const buttons = [...$(state.overlay).querySelectorAll('button:not(:disabled)')];
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

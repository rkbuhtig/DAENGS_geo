import { Claims, access, disposition } from './claims.mjs';
import { runTests } from './tests.mjs';
const $ = id => document.getElementById(id);
const names = { p1: '보리', p2: '두부', p3: '콩이' };
const places = { A: { x: 120, y: 150, name: '골목 전봇대' }, B: { x: 125, y: 330, name: '공원 입구' }, C: { x: 310, y: 120, name: '산책길 보안등' } };
const claims = new Claims();
const state = { serial: 1, session: 'walk-1', pet: 'p1', recording: true, visible: true, target: 'A', position: {x: 60, y: 360}, trail: [], jobs: [], capture: null };
const statusLabel = { PENDING: '확인 중 · 계속 걸어도 돼요', VERIFIED: '인증 완료', REJECTED: '부적합 · 현장에서 다시 촬영', RETRY_PENDING: '통신 장애 · 기존 사진 보관 중' };
function distance() { const p = places[state.target]; return Math.hypot(state.position.x - p.x, state.position.y - p.y) / 2; }
function readiness() { return access({recording: state.recording, trusted: !$('untrusted').checked, distance: distance(), accuracy: +$('accuracy').value, age: $('stale').checked ? 11 : 0}); }
function currentAttempt() { return claims.attempt(state.session, state.target); }
function canCapture() {
  const attempt = currentAttempt();
  return readiness() === 'READY' && (!attempt || ['NOT_SUBMITTED', 'REJECTED'].includes(attempt.photo)) &&
    (attempt || disposition(claims.sites.get(state.target), state.pet) !== 'ALREADY_OWNED' ||
      claims.sites.get(state.target).occupancy?.certification === 'UNVERIFIED');
}
function move(position) {
  state.position = position;
  if (state.recording) state.trail.push(position);
  render();
}
function render() {
  const ready = readiness();
  const attempt = currentAttempt();
  const site = claims.sites.get(state.target);
  const rule = disposition(site, state.pet);
  $('session-label').textContent = `· ${state.serial}`;
  $('walk-label').textContent = `${names[state.pet]} · ${state.recording ? '기록 중' : '일시정지'} · 이동 ${state.trail.length}회`;
  $('pause').textContent = state.recording ? '일시정지' : '재개';
  $('visibility').textContent = state.visible ? '점령지 숨기기' : '점령지 보기';
  $('game').hidden = !state.visible;
  $('distance').textContent = `${Math.round(distance())}m · ${ready === 'READY' ? '점령 준비' : ready === 'APPROACHING' ? '접근 중' : '접근 불가'}`;
  $('site-title').textContent = `${state.target} · ${places[state.target].name}`;
  $('owner').textContent = site.occupancy ? `${names[site.occupancy.pet]}의 영역 · ${site.occupancy.certification === 'VERIFIED' ? '인증' : '미인증'}` : '아직 누구의 영역도 아니에요';
  $('guidance').textContent = !state.recording ? '산책을 재개해 주세요' : ready === 'UNAVAILABLE' ? '정확한 현재 위치를 확인하고 있어요' :
    attempt?.photo === 'PENDING' ? statusLabel.PENDING : attempt?.photo === 'RETRY_PENDING' ? statusLabel.RETRY_PENDING :
    ready !== 'READY' ? '조금 더 가까이 가면 영역표시할 수 있어요' : attempt?.photo === 'VERIFIED' ? '이번 산책에서 인증 완료 · 같은 장소를 다시 점령할 수 없어요' :
    attempt?.photo === 'REJECTED' ? statusLabel.REJECTED : attempt ? '사진을 찍어 같은 영역표시를 인증할 수 있어요' :
    rule === 'PHOTO_REQUIRED' ? '인증된 영역이에요 · 새 사진으로 탈취할 수 있어요' : rule === 'POLICY_UNDECIDED' ? '무사진 경쟁 정책은 미정 · 사진 인증으로 우선권을 얻을 수 있어요' :
    rule === 'ALREADY_OWNED' ? '이미 우리 강아지의 영역이에요' : '사진 없이 표시하거나 바로 인증 촬영하세요';
  $('mark').disabled = ready !== 'READY' || !!attempt || rule !== 'GRANTED';
  $('photograph').disabled = !canCapture();
  $('photograph').textContent = attempt?.photo === 'REJECTED' ? '다시 촬영' : '인증 촬영';
  $('accuracy-value').textContent = `${$('accuracy').value} m`;
  $('player').setAttribute('transform', `translate(${state.position.x},${state.position.y})`);
  $('trail').setAttribute('points', state.trail.map(p => `${p.x},${p.y}`).join(' '));
  $('sites').innerHTML = state.visible ? Object.entries(places).map(([id, p]) => {
    const occupancy = claims.sites.get(id).occupancy;
    const color = !occupancy ? '#879084' : occupancy.certification === 'VERIFIED' ? '#43784d' : '#ca983d';
    const selected = state.target === id;
    return `<g class="site" data-site="${id}" role="button" tabindex="0" aria-label="${id} ${p.name}" transform="translate(${p.x},${p.y})">${selected ? `<circle r="40" fill="${ready === 'READY' ? '#6dad71' : '#999'}" fill-opacity=".12" stroke="${ready === 'READY' ? '#56865a' : '#999'}" stroke-dasharray="4 4"/>` : ''}<circle r="14" fill="${color}" stroke="white" stroke-width="3"/><text text-anchor="middle" dy="5" fill="white" font-size="12" font-weight="bold">${id}</text><text text-anchor="middle" y="-23" font-size="11" fill="#364b38">${occupancy ? names[occupancy.pet] + (occupancy.certification === 'VERIFIED' ? ' ✓' : ' · 미인증') : '미점유'}</text></g>`;
  }).join('') : '';
  $('pending-count').textContent = `· ${state.jobs.filter(j => j.attempt.photo === 'PENDING' && !j.conflict).length}건 확인 중`;
  $('jobs').replaceChildren();
  if (!state.jobs.length) $('jobs').textContent = '아직 촬영한 사진이 없어요';
  [...state.jobs].reverse().forEach(job => {
    const row = document.createElement('div'); row.className = 'job'; row.dataset.capture = job.capture;
    row.textContent = `${job.attempt.siteId} · ${names[job.attempt.pet]} · ${job.conflict ? '점유 변경으로 확정 보류 · 충돌 정책 미정' : statusLabel[job.attempt.photo]}`;
    if (job.attempt.photo === 'RETRY_PENDING' && !job.conflict) {
      const retry = document.createElement('button'); retry.textContent = '기존 사진으로 재시도';
      retry.onclick = () => { claims.resume(job.attempt); evaluate(job, 'ACCEPTED'); render(); };
      row.append(document.createElement('br'), retry);
    }
    $('jobs').append(row);
  });
}
function evaluate(job, outcome) {
  setTimeout(() => {
    try { claims.resolve(job.attempt, job.capture, outcome === 'DELAY' ? 'ACCEPTED' : outcome); }
    catch (e) { job.conflict = e.message; }
    render();
  }, outcome === 'DELAY' ? 15000 : 2000);
}
$('visibility').onclick = () => { state.visible = !state.visible; render(); };
$('pause').onclick = () => { state.recording = !state.recording; render(); };
$('new-session').onclick = () => { state.session = `walk-${++state.serial}`; state.pet = $('pet').value; state.recording = true; state.trail = []; render(); };
$('target').onchange = () => { state.target = $('target').value; render(); };
$('approach').onclick = () => { const p = places[state.target]; move({x:p.x + 10, y:p.y + 4}); };
$('leave').onclick = () => move({x:30, y:390});
for (const id of ['accuracy', 'untrusted', 'stale']) $(id).oninput = render;
$('sites').onclick = event => { const id = event.target.closest('[data-site]')?.dataset.site; if (id) { state.target = id; $('target').value = id; render(); } event.stopPropagation(); };
$('sites').onkeydown = event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); event.target.dispatchEvent(new MouseEvent('click', {bubbles:true})); } };
$('map').onclick = event => {
  const p = new DOMPoint(event.clientX, event.clientY).matrixTransform($('map').getScreenCTM().inverse());
  move({x:p.x, y:p.y});
};
$('mark').onclick = () => { if (!$('mark').disabled) { claims.mark(state.session, state.pet, state.target, readiness() === 'READY'); render(); } };
$('photograph').onclick = () => {
  if (!canCapture()) return;
  state.capture = {session:state.session, pet:state.pet, site:state.target};
  $('capture-context').textContent = `${names[state.pet]} · ${state.target} · 산책 ${state.serial}`;
  $('camera-error').textContent = '';
  $('camera').showModal();
};
$('cancel').onclick = () => { state.capture = null; $('camera').close(); };
$('shutter').onclick = () => {
  const target = state.capture;
  if (!target || target.session !== state.session || target.pet !== state.pet || target.site !== state.target || !canCapture()) {
    $('camera-error').textContent = '촬영할 수 없어요 · 현재 산책과 장소 접근 상태를 확인해 주세요'; return;
  }
  const attempt = claims.mark(state.session, state.pet, state.target, true);
  const capture = crypto.randomUUID();
  claims.submit(attempt, capture);
  state.jobs = state.jobs.filter(job => job.attempt.id !== attempt.id);
  const job = {attempt, capture, conflict:null}; state.jobs.push(job);
  evaluate(job, $('verdict').value);
  state.capture = null; $('camera').close(); render();
};
render();
try {
  const response = await fetch('territory-claim-scenarios.tsv');
  if (!response.ok) throw new Error('fixture fetch failed');
  const results = runTests(await response.text());
  $('tests').textContent = `공통 TSV 20단계 + 경계/충돌 6개 · ${results.length}개 통과`;
  document.documentElement.dataset.tests = 'passed';
} catch (error) { $('tests').textContent = `시나리오 실패: ${error.message}`; document.documentElement.dataset.tests = 'failed'; }

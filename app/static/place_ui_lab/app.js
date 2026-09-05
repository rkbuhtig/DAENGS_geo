'use strict';
// Source mapping: docs/explorations/facility/place-ui-web.md.
// Pure view experiment. Never infer missing facts, recompute evaluations, or call production APIs.
const $ = (id) => document.getElementById(id);
const categories = [['cafe','카페'],['restaurant','음식점'],['pet_shop','펫샵'],['shopping','일반 쇼핑'],['grooming','미용'],['boarding','위탁'],['hospital','동물병원'],['pharmacy','약국'],['travel','여행지'],['leisure','레저'],['pension','펜션'],['hotel','호텔'],['stay','숙박'],['museum','박물관'],['gallery','미술관'],['arts_center','문예회관'],['culture','문화시설'],['etc','기타']];
const centers = {gangnam:[37.4979,127.0276],seongsu:[37.5446,127.0559],haeundae:[35.1631,129.1589],jeju:[33.4996,126.5312]};
const reasons = {size_allowed:'크기 등급 허용',size_exceeded:'크기 등급 초과',weight_allowed:'무게 제한 허용',weight_exceeded:'무게 제한 초과',weight_boundary_unknown:'미만·이하 경계 확인 필요',dog_disallowed:'개 입장 불가',missing_dog_size:'개 크기 미상',missing_dog_weight:'개 무게 미상',missing_restriction:'시설 제한 정보 없음'};
const state = {mode:'current',region:'gangnam',dog:'large',kind:'cafe',parking:false,scenario:'results',selected:null};
let fixtures;
let searchMode='normal', appliedQuery='';
const categoryIcons=['☕','🍽','🐾','🛍','✂','🏠','✚','💊','🧭','🎡','🏡','🏨','🛏','🏛','🖼','🎭','🎫','⋯'];
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const identity = (hit) => JSON.stringify([hit.place.key.source,hit.place.key.ref]);
const label = () => categories.find(([kind]) => kind === state.kind)[1];
const group = () => fixtures?.cases[`${state.region}-${state.dog}${state.parking?'_parking':''}`]?.groups.find(g=>g.kind===state.kind);
const hits = () => state.scenario==='results' ? (group()?.results ?? []).filter(hit=>state.mode!=='proposed'||!appliedQuery||`${hit.place.name} ${hit.place.facts.address||''}`.toLocaleLowerCase().includes(appliedQuery.toLocaleLowerCase())) : [];
const distanceLabel = d => d < 1000 ? `${d}m` : `${(d/1000).toFixed(1)}km`;
const tone = value => ({compatible:'success',incompatible:'error',unknown:'warning'}[value] || 'muted');
function accessText(evaluation) {
  if (!evaluation) return '';
  const states = {compatible:state.mode==='current'?'입장 조건상 가능':'크기·체중 조건상 가능',incompatible:'조건 불일치',unknown:'정보 부족 · 확인 필요'};
  return `${states[evaluation.state] || '확인 필요'} · ${reasons[evaluation.reason] || evaluation.reason}`;
}
function restrictionHtml(hit) {
  if (state.mode!=='proposed') return '';
  const facts=hit.place.facts.restrictions, evaluation=hit.evaluations?.restrictions;
  const chips=evaluation?.chips ?? facts?.chips ?? [];
  let message='제한 정보 없음 · 방문 전 확인이 필요해요.';
  if(evaluation?.state==='incompatible') message='이 반려견에게 적용되는 입장 제한이 있어요.';
  else if(evaluation?.reason==='unverified_source_match') message='다른 원천에서 연결한 조건이에요. 시설에 확인해 주세요.';
  else if(facts?.parse_state==='partial'||facts?.parse_state==='raw_only') message='아래 원문에 추가 조건이 있어요.';
  else if(chips.length) message='아래 이용 조건도 확인해 주세요.';
  else if(facts?.state==='none_confirmed') message='원천에 별도 제한사항이 없다고 기록돼 있어요.';
  const raw=(facts?.parse_state==='partial'||facts?.parse_state==='raw_only') ? facts.raw : null;
  return `<div class="restrictions"><p class="${evaluation?.state==='incompatible'?'error':'warning'}">${escapeHtml(message)}</p><div class="restriction-chips">${chips.map(c=>`<span class="restriction-chip">${escapeHtml(c.label)}</span>`).join('')}</div>${raw?`<p class="raw-restriction">${escapeHtml(raw)}</p>`:''}<p class="source-date">원천 기록 ${escapeHtml(hit.place.classifications?.[0]?.as_of || '날짜 미상')} · 현재 운영 여부는 별도 확인</p></div>`;
}
function renderCards() {
  const g=group();
  if(state.scenario==='loading') return `<div class="message"><span class="spinner"></span>${label()} 찾는 중</div>`;
  if(state.scenario==='permission') return '<div class="message">현재 위치를 확인하면 주변 장소를 보여드릴게요.</div>';
  if(state.scenario==='error') return '<div class="message error">서버에 닿지 못했어요. 잠시 뒤 다시 시도해 주세요.<button type="button" id="retry">다시 시도</button></div>';
  if(!g) return `<div class="message">${label()} 응답은 이 검토판에 수집하지 않았습니다. 카페 또는 음식점을 선택하세요.</div>`;
  if(!hits().length) return `<div class="message">이 반경에서 ${label()} 결과를 찾지 못했습니다.</div>`;
  return `<p class="count">${hits().length}곳${g.truncated?' · 서버 한도에서 잘림':''}</p><div class="cards">${hits().map((hit,index)=>{
    const p=hit.place,f=p.facts,e=hit.evaluations?.dog_access;
    if(state.mode==='proposed')return drawerCard(hit,index);
    return `<article class="card${identity(hit)===state.selected?' selected':''}" tabindex="0" data-index="${index}" aria-label="${escapeHtml(p.name)} 선택"><h3>${escapeHtml(p.name)}</h3><p class="meta">${label()} · ${distanceLabel(p.distance_m)}</p><p class="${f.parking===true?'success':f.parking===false?'muted':'warning'}">${f.parking===true?'주차 가능':f.parking===false?'주차 불가':'주차 정보 없음'}</p>${e?`<p class="${tone(e.state)}">${escapeHtml(accessText(e))}</p>`:''}${restrictionHtml(hit)}${f.hours_text?`<p class="hours">영업시간 ${escapeHtml(f.hours_text)}</p>`:''}${f.address?`<p class="address">${escapeHtml(f.address)}</p>`:''}<button class="wide-button" type="button" data-demo="길찾기는 네이티브 앱에서 확인합니다. 이 검토판은 외부 경로 API를 호출하지 않습니다.">길찾기</button>${f.phone?'<button class="wide-button secondary" type="button" data-demo="전화 연결은 검토판에서 실행하지 않습니다.">전화하기</button>':''}</article>`;
  }).join('')}</div>`;
}
function drawerCard(hit,index){
  const p=hit.place,f=p.facts,allowed=f.pet_access?.allowed;
  const registration=allowed===true?'동반 가능 등록':allowed===false?'동반 불가 등록':'동반 여부 확인 필요';
  const status=allowed===true?'yes':allowed===false?'no':'unknown';
  const paw='<svg viewBox="0 0 32 32" aria-hidden="true"><ellipse cx="8" cy="10" rx="3.5" ry="4.5"/><ellipse cx="15" cy="6" rx="3.5" ry="4.5"/><ellipse cx="23" cy="10" rx="3.5" ry="4.5"/><path d="M7 24c0-5 5-11 9-11s9 6 9 11c0 7-6 3-9 3s-9 4-9-3Z"/></svg>';
  const source=p.key.source==='kcisa'?'공공데이터 · KCISA':p.key.source;
  return `<article class="card drawer-card${identity(hit)===state.selected?' selected':''}" data-index="${index}">
    <details class="facility-drawer">
      <summary aria-label="${escapeHtml(p.name)} 동반 조건" aria-controls="conditions-${index}">
        <h3>${escapeHtml(p.name)}</h3><p class="meta">${label()} · ${distanceLabel(p.distance_m)}</p>
        <span class="registration ${status}" role="img" aria-label="${registration}"><span class="paw-icon">${paw}<span class="status-mark" aria-hidden="true">${allowed===true?'✓':allowed===false?'×':'?'}</span></span><span class="registration-label" aria-hidden="true">${registration}</span></span>
        <svg class="drawer-chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
      </summary>
      <div class="drawer-body" id="conditions-${index}">
        <h4>동반 조건</h4>${restrictionHtml(hit)}
        <p>허용 크기: ${escapeHtml(f.pet_access?.raw?.size || '정보 없음')}</p>
        ${hit.evaluations?.dog_access?`<p class="${tone(hit.evaluations.dog_access.state)}">${escapeHtml(accessText(hit.evaluations.dog_access))}</p>`:''}
        <p class="source-date">${escapeHtml(source)} · ${escapeHtml(p.classifications?.[0]?.as_of || '날짜 미상')} 기준<br>현재 동반 정책은 방문 전 확인해 주세요.</p>
        <div class="visit-info"><p>${f.parking===true?'주차 가능':f.parking===false?'주차 불가':'주차 정보 없음'}</p>${f.hours_text?`<p class="hours">영업시간 ${escapeHtml(f.hours_text)}</p>`:''}${f.address?`<p class="address">${escapeHtml(f.address)}</p>`:''}</div>
        ${f.phone?'<button class="wide-button" type="button" data-demo="전화 연결은 검토판에서 실행하지 않습니다.">전화로 확인</button>':''}
        <button class="wide-button secondary" type="button" data-demo="길찾기는 네이티브 앱에서 확인합니다. 이 검토판은 외부 경로 API를 호출하지 않습니다.">길찾기</button>
      </div>
    </details>
  </article>`;
}
function renderMap() {
  const center=centers[state.region], ns='http://www.w3.org/2000/svg';
  $('map').innerHTML='<defs><pattern id="grid" width="30" height="30" patternUnits="userSpaceOnUse"><path d="M 30 0 L 0 0 0 30" fill="none" stroke="#e6e1d6" stroke-width="1"/></pattern></defs><rect width="390" height="370" fill="url(#grid)"/><circle cx="195" cy="203" r="132" fill="#ffffff25" stroke="#d4ccbd" stroke-dasharray="4 5"/><circle cx="195" cy="203" r="7" fill="#739ac5" stroke="white" stroke-width="3"/>';
  hits().forEach((hit,index)=>{
    const x=195+(hit.place.lng-center[1])*111320*Math.cos(center[0]*Math.PI/180)/3000*132;
    const y=203-(hit.place.lat-center[0])*111320/3000*132;
    const marker=document.createElementNS(ns,'g');
    marker.setAttribute('transform',`translate(${x},${y})`);
    marker.setAttribute('class',`map-marker${identity(hit)===state.selected?' selected':''}`);
    marker.setAttribute('tabindex','0');marker.setAttribute('role','button');
    marker.setAttribute('aria-label',`${index+1}. ${hit.place.name}`);
    marker.innerHTML=`<circle r="12"/><text text-anchor="middle" dy="3.5">${index+1}</text>`;
    marker.addEventListener('click',()=>select(index,true));
    marker.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();select(index,true);}});
    $('map').append(marker);
  });
}
function renderEvidence() {
  const hit=hits().find(h=>identity(h)===state.selected);
  $('selected-name').textContent=hit?.place.name || '표시할 장소가 없습니다';
  if(!hit){$('evidence').textContent='검색 완료 상태에서 카페·음식점을 선택하세요.';$('raw-response').textContent='';return;}
  const e=hit.evaluations || {},raw=hit.place.facts.pet_access?.raw || {};
  const block=(title,value)=>`<div class="evidence-block"><span>${escapeHtml(title)}</span><p>${escapeHtml(value)}</p></div>`;
  $('evidence').innerHTML=block('원천의 입장 가능 크기',raw.size || '정보 없음')+block('원천의 제한사항',raw.restrictions || '정보 없음')+block('크기·체중 평가',e.dog_access?`${e.dog_access.state} / ${e.dog_access.reason}`:'반려견 조건 없음')+block('제한사항 평가',e.restrictions?`${e.restrictions.state} / ${e.restrictions.reason}`:'반려견 조건 없음')+`<p class="explanation">${state.mode==='current'?'현재 앱 카드는 크기·체중 평가를 읽습니다. 서버의 제한 칩과 제한 평가를 카드에 옮기지 않습니다.':'보완안은 크기 평가와 이용 조건을 나눠 표시합니다. 서버 평가와 결과 순위는 바꾸지 않습니다.'}</p>`;
  $('raw-response').textContent=JSON.stringify(hit,null,2);
}
function select(index,scroll=false){
  const hit=hits()[index];if(!hit)return;state.selected=identity(hit);
  document.querySelectorAll('.card').forEach((card,i)=>card.classList.toggle('selected',i===index));
  renderMap();renderEvidence();
  if(scroll){
    const card=document.querySelector(`.card[data-index="${index}"]`), row=card?.parentElement;
    if(row)row.scrollLeft+=card.getBoundingClientRect().left-row.getBoundingClientRect().left-16;
  }
}
function render() {
  if(!hits().some(h=>identity(h)===state.selected))state.selected=hits()[0]?identity(hits()[0]):null;
  $('mode-label').textContent=state.mode==='current'?'현재 Android 표시':'실험 · 제한사항 보완안';
  document.querySelectorAll('[data-mode]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.mode===state.mode));
  $('categories').innerHTML=categories.map(([kind,name])=>`<button class="chip" type="button" data-kind="${kind}" aria-pressed="${kind===state.kind}" ${state.scenario==='loading'?'disabled':''}>${name}</button>`).join('');
  renderSearchTools();
  $('parking').setAttribute('aria-pressed',state.parking);$('parking').disabled=state.scenario==='loading';
  $('sort-label').textContent=state.parking?'500m 구간 안에서 주차 우선':'가까운 순';
  const g=group(),visible=hits(),evaluated=visible.map(h=>h.evaluations?.dog_access).filter(Boolean);
  const coverage=g?.sort?.coverage?.parking;
  $('coverage').innerHTML=(coverage&&state.scenario==='results'?`반환 결과 주차 정보 · 가능 ${coverage.known_true} · 불가 ${coverage.known_false} · 미상 ${coverage.unknown}<br>`:'')+(evaluated.length?`입장 평가 · 가능 ${evaluated.filter(e=>e.state==='compatible').length} · 불일치 ${evaluated.filter(e=>e.state==='incompatible').length} · 미상 ${evaluated.filter(e=>e.state==='unknown').length}`:'');
  $('location-message').textContent=state.scenario==='permission'?'위치 권한이 필요합니다. 검토판에서는 실제 권한을 요청하지 않습니다.':'';
  $('my-location').disabled=state.scenario==='permission'||state.scenario==='loading';
  $('results').innerHTML=renderCards();renderMap();renderEvidence();
  document.querySelectorAll('.card').forEach(card=>{
    card.addEventListener('click',()=>select(Number(card.dataset.index)));
    card.addEventListener('keydown',e=>{if(e.target===card&&(e.key==='Enter'||e.key===' ')){e.preventDefault();select(Number(card.dataset.index));}});
  });
  document.querySelectorAll('.facility-drawer').forEach(drawer=>{
    drawer.addEventListener('toggle',()=>{
      if(drawer.open)document.querySelectorAll('.facility-drawer').forEach(other=>{if(other!==drawer)other.open=false;});
    });
  });
  $('retry')?.addEventListener('click',()=>{state.scenario='results';$('scenario').value='results';render();});
}
let toastTimer;
function toast(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,4500);}
document.addEventListener('click',event=>{
  const demo=event.target.closest('[data-demo]');if(demo)toast(demo.dataset.demo);
  const kind=event.target.closest('[data-kind]');if(kind){state.kind=kind.dataset.kind;state.selected=null;render();const row=$('categories'),chip=row.querySelector(`[data-kind="${state.kind}"]`);row.scrollLeft+=chip.getBoundingClientRect().left-row.getBoundingClientRect().left-16;}
  const mode=event.target.closest('[data-mode]');if(mode){state.mode=mode.dataset.mode;const selectedIndex=hits().findIndex(h=>identity(h)===state.selected);render();if(selectedIndex>=0)select(selectedIndex,true);}
});
['region','dog','scenario'].forEach(id=>$(id).addEventListener('change',()=>{state[id]=$(id).value;state.selected=null;render();}));
$('parking').addEventListener('click',()=>{state.parking=!state.parking;render();});
$('my-location').addEventListener('click',()=>toast('위치는 선택한 지역의 고정 좌표입니다. 기기 GPS를 사용하지 않습니다.'));
$('brand').addEventListener('click',e=>e.preventDefault());
function example(region,name){appliedQuery='';$('search-feedback').textContent='';state.region=region;state.kind='cafe';state.scenario='results';state.dog='large';state.parking=false;['region','dog','scenario'].forEach(id=>$(id).value=state[id]);state.selected=null;render();select(hits().findIndex(h=>h.place.name===name),true);}
$('outdoor-example').addEventListener('click',()=>example('gangnam','정다방 카페'));
$('rooftop-example').addEventListener('click',()=>example('seongsu','구욱희씨'));
function setFiltersOpen(open){$('filter-sheet').hidden=!open;$('filter-toggle').setAttribute('aria-expanded',String(open));if(open)$('filter-dog').focus();else $('filter-toggle').focus();}
function renderSearchTools(){
  const proposed=state.mode==='proposed';
  document.querySelector('.phone').classList.toggle('search-layout',proposed);
  $('search-tools').hidden=!proposed;
  if(!proposed){$('filter-sheet').hidden=true;$('filter-toggle').setAttribute('aria-expanded','false');}
  const panel=document.querySelector('.panel');
  if(proposed){
    $('top-categories').append($('categories'));
    $('filter-parking').append($('parking').parentElement);
    $('categories').querySelectorAll('button').forEach((button,index)=>{button.innerHTML=`<span class="category-icon" aria-hidden="true">${categoryIcons[index]}</span><span>${escapeHtml(categories[index][1])}</span>`;});
  }else{
    panel.insertBefore($('categories'),$('coverage'));
    panel.insertBefore($('parking').parentElement,$('coverage'));
  }
  $('filter-dog').value=state.dog;
  $('active-filters').innerHTML='<span class="filter-tag">3km</span>'+(state.dog!=='baseline'?`<button type="button" data-clear-filter="dog" aria-label="반려견 조건 해제">${state.dog==='large'?'대형견':'소형견'} ×</button>`:'')+(state.parking?'<button type="button" data-clear-filter="parking" aria-label="주차 우선 해제">주차 우선 ×</button>':'')+(appliedQuery?`<button type="button" data-clear-filter="query" aria-label="검색어 해제">${escapeHtml(appliedQuery)} ×</button>`:'');
}
$('ai-toggle').addEventListener('click',()=>{
  searchMode=searchMode==='normal'?'ai':'normal';const ai=searchMode==='ai';
  $('ai-toggle').setAttribute('aria-pressed',String(ai));$('search-form').classList.toggle('ai-mode',ai);
  $('search-query').placeholder=ai?'원하는 동반 조건을 말해보세요':'장소명·주소 검색';
  $('search-query').setAttribute('aria-label',ai?'AI 검색 요청':'장소명·주소 검색');
  $('search-mode-note').textContent=ai?'AI 조건 검색 · 예시 체험 (실제 AI 호출 없음)':'일반 검색 · 선택 지역의 저장된 장소에서 검색';
  $('ai-example').hidden=!ai;$('search-feedback').textContent='';$('search-query').focus();
});
$('ai-example').addEventListener('click',()=>{$('search-query').value='대형견과 갈 카페, 주차 우선';$('search-query').focus();});
$('search-form').addEventListener('submit',event=>{
  event.preventDefault();const query=$('search-query').value.trim();
  if(searchMode==='ai'){
    if(query!=='대형견과 갈 카페, 주차 우선'){$('search-feedback').textContent='초안에서는 위 예시 문장만 체험할 수 있어요. 기존 검색 조건은 유지됩니다.';return;}
    appliedQuery='';state.kind='cafe';state.dog='large';$('dog').value='large';state.parking=true;
    $('search-feedback').textContent='예시 조건 적용: 카페 · 대형견 · 주차 우선. 실제 동반 제한은 카드에서 확인하세요.';
  }else{appliedQuery=query;$('search-feedback').textContent=query?'선택 지역의 저장된 장소명·주소에서 검색했어요.':'';}
  state.scenario='results';$('scenario').value='results';state.selected=null;render();
});
$('search-query').addEventListener('search',()=>{if(searchMode==='normal'&&!$('search-query').value){appliedQuery='';render();}});
$('filter-toggle').addEventListener('click',()=>setFiltersOpen($('filter-sheet').hidden));
['filter-close','filter-done'].forEach(id=>$(id).addEventListener('click',()=>setFiltersOpen(false)));
$('filter-sheet').addEventListener('keydown',event=>{if(event.key==='Escape')setFiltersOpen(false);});
$('filter-dog').addEventListener('change',()=>{state.dog=$('filter-dog').value;$('dog').value=state.dog;render();});
$('active-filters').addEventListener('click',event=>{
  const key=event.target.closest('[data-clear-filter]')?.dataset.clearFilter;
  if(key==='dog'){state.dog='baseline';$('dog').value='baseline';}
  if(key==='parking')state.parking=false;
  if(key==='query'){appliedQuery='';if(searchMode==='normal')$('search-query').value='';}
  if(key){$('search-feedback').textContent='';render();}
});
fetch('fixtures.json').then(response=>{if(!response.ok)throw Error('fixture response');return response.json();}).then(data=>{
  fixtures=data;$('capture-info').textContent=`2026-09-05 수집 · ${Object.keys(data.cases).length}개 응답 · 운영 서버 추가 호출 없음`;render();
}).catch(()=>{$('capture-info').textContent='응답 파일을 읽지 못했습니다. HTTP 서버로 이 폴더를 열어 주세요.';$('results').innerHTML='<div class="message error">검토 데이터를 불러오지 못했습니다.</div>';});

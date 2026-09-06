const $ = (id) => document.getElementById(id);
const names = { A: "골목 전봇대", B: "공원 입구", C: "산책길 보안등" };
const fixed = {
  A: { x: 120, y: 150 },
  B: { x: 125, y: 330 },
  C: { x: 310, y: 120 },
};
const colors = ["#428159", "#cf8751", "#7f6aaa"];
let game = null,
  allSeasons = [],
  sessionId = null,
  target = "A",
  busy = false;
let position = { x: 40, y: 380 };
let retry = null;
let toastTimer = null;
const errorText = {
  protected: "지금은 보호 중이에요. 보호가 끝난 뒤 다시 시도해 주세요.",
  site_not_ready: "장소 옆으로 이동해 주세요.",
  untrusted_contact: "위치 정보를 신뢰할 수 없어요.",
  active_season_exists: "진행 중인 시즌을 먼저 종료해 주세요.",
  season_ended: "종료된 시즌이에요.",
  site_changed:
    "사진 확인 중 주인이 바뀌었어요. 새 산책에서 다시 도전해 주세요.",
  attempt_closed: "이 시도는 종료됐어요. 새 산책에서 다시 도전해 주세요.",
  request_identity_conflict: "같은 요청 번호의 내용이 달라요.",
  not_recording: "산책을 시작하거나 재개해 주세요.",
};
function say(text) {
  clearTimeout(toastTimer);
  $("message").textContent = text;
  toastTimer = setTimeout(() => {
    $("message").textContent = "";
  }, 6000);
}
function pos(id) {
  const i = Object.keys(game?.sites || {}).indexOf(id);
  return fixed[id] || { x: 40 + (i % 4) * 95, y: 70 + Math.floor(i / 4) * 65 };
}
function walk() {
  return game?.sessions[sessionId];
}
function pet() {
  return walk()?.pet_ids[0];
}
function attempt() {
  return Object.values(game?.attempts || {}).find(
    (a) => a.session_id === sessionId && a.site_id === target,
  );
}
function distance() {
  const p = pos(target);
  return Math.hypot(position.x - p.x, position.y - p.y) / 2;
}
function active() {
  return game?.status === "ACTIVE";
}
function protectedSite() {
  const s = game?.sites[target];
  return !!(
    s?.owner &&
    s.owner.pet_id !== pet() &&
    game.now_ms < s.protected_until_ms
  );
}
function ready() {
  return (
    active() &&
    walk()?.phase === "RECORDING" &&
    distance() + 5 <= 20 &&
    !$("untrusted").checked
  );
}
function contact() {
  return {
    distance_m: distance(),
    accuracy_m: 5,
    trusted: !$("untrusted").checked,
  };
}
function escape(text) {
  return String(text).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
}
function time(ms) {
  return (
    new Date(ms).toLocaleString("ko-KR", {
      timeZone: "UTC",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    }) + " UTC"
  );
}
function number(n) {
  return n.toLocaleString("ko-KR", { maximumFractionDigits: 3 });
}
async function api(path, body) {
  const response = await fetch(
    `api/${path}`,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  const data = await response.json();
  if (!response.ok) {
    const code =
      typeof data.detail === "string" ? data.detail : "invalid_request";
    const e = new Error(errorText[code] || code);
    e.http = true;
    throw e;
  }
  return data;
}
async function sendEnvelope(envelope, seasonId) {
  return sendPending({ envelope, seasonId });
}
async function sendPending(pending) {
  retry = pending;
  localStorage.setItem("territory-season-retry", JSON.stringify(retry));
  try {
    const data = pending.creation
      ? await api("seasons", pending.creation)
      : await api(`seasons/${pending.seasonId}/commands`, pending.envelope);
    game = pending.creation ? data : data.game;
    retry = null;
    localStorage.removeItem("territory-season-retry");
    return pending.creation ? data : data.result;
  } catch (error) {
    if (error.http) {
      retry = null;
      localStorage.removeItem("territory-season-retry");
    }
    throw error;
  }
}
function command(command) {
  return sendEnvelope(
    { request_id: crypto.randomUUID(), command },
    game.season_id,
  );
}
async function act(fn) {
  if (busy) return;
  busy = true;
  render();
  try {
    await fn();
  } catch (error) {
    say(error.message);
  } finally {
    busy = false;
    render();
  }
}
function render() {
  const running = active(),
    a = attempt(),
    s = game?.sites[target],
    current = walk();
  $("retry").hidden = !retry;
  $("retry").disabled = busy;
  const locked = busy || !!retry;
  $("create").disabled =
    locked || allSeasons.some((s) => s.status === "ACTIVE");
  $("new-session").disabled = locked || !running;
  $("pause").disabled =
    locked || !running || !current || current.phase === "ENDED";
  $("pause").textContent = current?.phase === "PAUSED" ? "재개" : "일시정지";
  $("approach").disabled = busy || !running;
  $("mark").disabled = locked || !ready() || protectedSite() || !!a;
  $("photo").disabled =
    locked ||
    !ready() ||
    protectedSite() ||
    !!a?.resolution_code ||
    (a && !["NOT_SUBMITTED", "REJECTED"].includes(a.photo)) ||
    (s?.owner?.pet_id === pet() && s.owner.certification === "VERIFIED");
  $("finish").disabled = locked || !running;
  for (const button of document.querySelectorAll("[data-minutes]"))
    button.disabled = locked || !running;
  for (const id of ["pet", "target", "seasons"]) $(id).disabled = busy;
  $("walk-label").textContent = current
    ? `${game.pets[pet()]} · ${current.phase === "RECORDING" ? "산책 중" : current.phase === "PAUSED" ? "잠시 쉬는 중" : "산책 종료"}`
    : "새 산책을 시작해 주세요";
  $("status").textContent = game
    ? running
      ? "진행 중"
      : "시즌 결과"
    : "시작 전";
  if (!game) return;
  $("clock").textContent = `${time(game.now_ms)} · 종료 ${time(game.ends_ms)}`;
  $("site-title").textContent = `${target} · ${names[target] || "점령지"}`;
  $("distance").textContent =
    `${Math.round(distance())}m · ${ready() ? "점령 준비" : "접근 필요"}`;
  $("owner").textContent = s?.owner
    ? `${game.pets[s.owner.pet_id]}의 영역 · ${s.owner.certification === "VERIFIED" ? "인증" : "미인증"}`
    : "아직 누구의 영역도 아니에요";
  const remaining = s?.owner
    ? Math.max(0, Math.ceil((s.protected_until_ms - game.now_ms) / 1000))
    : 0;
  $("protection").textContent = remaining
    ? `보호 ${Math.floor(remaining / 60)}분 ${remaining % 60}초 남음`
    : s?.owner
      ? "보호 종료 · 다른 강아지가 도전할 수 있어요"
      : "";
  const dispositions = {
    GRANTED: "점령 성공",
    ALREADY_OWNED: "이미 내 영역이에요",
    PHOTO_REQUIRED: "사진 인증으로 탈취할 수 있어요",
    POLICY_UNDECIDED: "미인증 경쟁 · 사진 인증으로 도전해 주세요",
  };
  $("attempt").textContent = !running
    ? "시즌이 종료됐어요. 성적과 점령 기록은 오른쪽 시즌 결과에서 확인해 주세요."
    : a?.resolution_code
      ? errorText[a.resolution_code] || a.resolution_code
      : a
        ? dispositions[a.disposition]
        : "지도를 눌러 이동하고 영역표시해 보세요.";
  $("photo").textContent =
    a?.photo === "REJECTED" ? "샘플 사진 다시 제출" : "샘플 사진 제출";
  const petKeys = Object.keys(game.pets);
  $("sites").innerHTML = Object.entries(game.sites)
    .map(([id, site]) => {
      const p = pos(id),
        c = site.owner
          ? colors[petKeys.indexOf(site.owner.pet_id) % colors.length]
          : "#909b8a";
      return `<g data-site="${escape(id)}" role="button" tabindex="0" aria-label="${escape(names[id] || id)}" transform="translate(${p.x} ${p.y})"><circle r="21" fill="${c}" stroke="${id === target ? "#20372c" : "white"}" stroke-width="3"/><text text-anchor="middle" y="5" fill="white" font-size="13">${escape(id)}</text></g>`;
    })
    .join("");
  $("player").setAttribute(
    "transform",
    `translate(${position.x} ${position.y})`,
  );
  $("standings").innerHTML = game.standings
    .map(
      (r) =>
        `<tr><td>${r.rank} · ${escape(r.name)}</td><td>${number(r.points)}<small>점령 ${number(r.bonus)} / 점유 ${number(r.holding_points)}</small></td><td>${r.current_count}곳 · ×${r.multiplier}</td><td>${r.peak}곳<small>점령 ${r.claims}회 · 탈취 ${r.takeovers}회</small></td></tr>`,
    )
    .join("");
  $("rate").textContent =
    `이번 시즌: 점령 ${game.rules.claim_points}점 / 탈취 ${game.rules.takeover_points}점 · 영역당 ${game.rules.hourly_points}점/시간 · 반복 보너스 ${game.rules.repeat_bonus === "every_change" ? "매번" : "UTC 하루 한 번"} · 미인증 점유 ${game.rules.unverified_scores ? "포함" : "제외"}`;
  $("jobs").innerHTML =
    Object.values(game.attempts)
      .filter(
        (a) =>
          ["PENDING", "RETRY_PENDING", "REJECTED"].includes(a.photo) ||
          a.resolution_code,
      )
      .map(
        (a) =>
          `<div class="job"><p>${escape(game.pets[a.pet_id])} · ${escape(a.site_id)} · ${a.resolution_code ? escape(errorText[a.resolution_code] || a.resolution_code) : a.photo === "PENDING" ? "사진 확인 중" : a.photo === "REJECTED" ? "부적합 · 현장에서 다시 제출" : "통신 장애 · 기존 사진 재시도"}</p>${running && !a.resolution_code && a.photo === "PENDING" ? `<div class="actions"><button data-resolve="${escape(a.id)}" data-outcome="ACCEPTED">인증 성공</button><button data-resolve="${escape(a.id)}" data-outcome="REJECTED">부적합</button><button data-resolve="${escape(a.id)}" data-outcome="RETRYABLE_FAILURE">통신 장애</button></div>` : ""}${running && !a.resolution_code && a.photo === "RETRY_PENDING" ? `<button data-resume="${escape(a.id)}">기존 사진 재시도</button>` : ""}</div>`,
      )
      .join("") || '<p class="muted">대기 중인 사진이 없어요.</p>';
  for (const b of $("jobs").querySelectorAll("button")) b.disabled = locked;
  $("events").innerHTML =
    game.events
      .toReversed()
      .map(
        (e) =>
          `<div class="event">${time(e.at_ms)} · ${e.kind === "SEASON_FINALIZED" ? "시즌 결과 보존" : e.kind === "CLAIM_NOT_GRANTED" ? "사진 인증 · 점유 변경 불가" : `${escape(game.pets[e.pet_id])} · ${escape(e.site_id)} · ${e.kind === "CERTIFIED" ? "사진 인증 강화" : e.previous_pet_id ? "탈취" : "첫 점령"} +${e.bonus}점`}</div>`,
      )
      .join("") || '<p class="muted">첫 영역표시를 기다리고 있어요.</p>';
}
async function refreshSeasons(selectId) {
  allSeasons = await api("seasons");
  $("seasons").innerHTML =
    allSeasons
      .map(
        (s) =>
          `<option value="${escape(s.season_id)}">${escape(s.season_id)} · ${s.status === "ACTIVE" ? "진행 중" : "종료"}</option>`,
      )
      .join("") || "<option>시즌 없음</option>";
  if (selectId) $("seasons").value = selectId;
}
function restoreSession() {
  sessionId = localStorage.getItem(`territory-walk-${game.season_id}`);
  if (!game.sessions[sessionId]) sessionId = null;
}
function selectors() {
  $("pet").innerHTML = Object.entries(game.pets)
    .map(
      ([id, name]) => `<option value="${escape(id)}">${escape(name)}</option>`,
    )
    .join("");
  $("target").innerHTML = Object.keys(game.sites)
    .map(
      (id) =>
        `<option value="${escape(id)}">${escape(id)} · ${escape(names[id] || "점령지")}</option>`,
    )
    .join("");
  target = Object.keys(game.sites)[0];
}
$("create-form").onsubmit = (event) => {
  event.preventDefault();
  act(async () => {
    const starts = allSeasons.length
      ? (await api(`seasons/${allSeasons[0].season_id}`)).ends_ms
      : Date.UTC(2026, 8, 6);
    const body = {
      season_id: `season-${crypto.randomUUID().slice(0, 8)}`,
      starts_ms: starts,
      duration_ms: Number($("duration").value) * 86400000,
      rules: {
        claim_points: Number($("claim-points").value),
        takeover_points: Number($("takeover-points").value),
        hourly_points: Number($("hourly-points").value),
        extra_site_bps: Math.round(Number($("extra-bps").value) * 10000),
        maximum_bps: Math.round(Number($("maximum-bps").value) * 10000),
        repeat_bonus: $("repeat-bonus").value,
        unverified_scores: $("unverified-scores").checked,
      },
    };
    await sendPending({ creation: body });
    sessionId = null;
    selectors();
    await refreshSeasons(game.season_id);
    say("새 시즌을 시작했어요. 대표견을 고르고 산책을 시작해 보세요.");
  });
};
$("new-session").onclick = () =>
  act(async () => {
    if (walk() && walk().phase !== "ENDED")
      await command({ action: "phase", session_id: sessionId, phase: "ENDED" });
    const nextId = crypto.randomUUID();
    await command({
      action: "start_session",
      session_id: nextId,
      pet_ids: [$("pet").value],
    });
    sessionId = nextId;
    localStorage.setItem(`territory-walk-${game.season_id}`, nextId);
    say("새 산책을 시작했어요.");
  });
$("pause").onclick = () =>
  act(() =>
    command({
      action: "phase",
      session_id: sessionId,
      phase: walk().phase === "PAUSED" ? "RECORDING" : "PAUSED",
    }),
  );
$("target").onchange = () => {
  target = $("target").value;
  render();
};
$("approach").onclick = () => {
  const p = pos(target);
  position = { x: p.x + 10, y: p.y + 4 };
  render();
};
$("untrusted").onchange = render;
$("sites").onclick = (event) => {
  const id = event.target.closest("[data-site]")?.dataset.site;
  if (id && !busy) {
    target = id;
    $("target").value = id;
    render();
  }
  event.stopPropagation();
};
$("sites").onkeydown = (event) => {
  if (["Enter", " "].includes(event.key)) {
    event.preventDefault();
    event.target.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  }
};
$("map").onclick = (event) => {
  if (!busy) {
    const p = new DOMPoint(event.clientX, event.clientY).matrixTransform(
      $("map").getScreenCTM().inverse(),
    );
    position = { x: p.x, y: p.y };
    render();
  }
};
async function mark() {
  const result = await command({
    action: "mark",
    session_id: sessionId,
    pet_id: pet(),
    site_id: target,
    attempt_id: crypto.randomUUID(),
    ...contact(),
  });
  return result.attempt_id;
}
$("mark").onclick = () =>
  act(async () => {
    await mark();
    say("영역표시 결과를 확인해 주세요.");
  });
$("photo").onclick = () =>
  act(async () => {
    const id = attempt()?.id || (await mark());
    await command({
      action: "submit",
      attempt_id: id,
      capture_id: crypto.randomUUID(),
      ...contact(),
    });
    say("샘플 사진을 제출했어요. 아래에서 판정 결과를 선택해 주세요.");
  });
$("jobs").onclick = (event) => {
  const resolve = event.target.closest("[data-resolve]"),
    resume = event.target.closest("[data-resume]");
  if (resolve)
    act(async () => {
      const a = game.attempts[resolve.dataset.resolve];
      const result = await command({
        action: "resolve",
        attempt_id: a.id,
        capture_id: a.capture_id,
        outcome: resolve.dataset.outcome,
      });
      say(
        result.resolution_code
          ? errorText[result.resolution_code] || result.resolution_code
          : "사진 판정 결과를 반영했어요.",
      );
    });
  else if (resume)
    act(() => {
      const a = game.attempts[resume.dataset.resume];
      return command({
        action: "submit",
        attempt_id: a.id,
        capture_id: a.capture_id,
      });
    });
};
for (const button of document.querySelectorAll("[data-minutes]"))
  button.onclick = () =>
    act(async () => {
      await command({
        action: "advance",
        delta_ms: Number(button.dataset.minutes) * 60000,
      });
      await refreshSeasons(game.season_id);
    });
$("finish").onclick = () =>
  act(async () => {
    await command({ action: "finalize" });
    await refreshSeasons(game.season_id);
    say(
      "종료 시각까지 정산하고 결과를 보존했어요. 새 시즌을 시작할 수 있어요.",
    );
  });
$("seasons").onchange = () =>
  act(async () => {
    game = await api(`seasons/${$("seasons").value}`);
    restoreSession();
    selectors();
    say("선택한 시즌의 기록을 불러왔어요.");
  });
$("retry").onclick = () =>
  act(async () => {
    const pending = retry;
    await sendPending(pending);
    if (pending.envelope?.command.action === "start_session") {
      sessionId = pending.envelope.command.session_id;
      localStorage.setItem(`territory-walk-${game.season_id}`, sessionId);
    } else restoreSession();
    selectors();
    await refreshSeasons(game.season_id);
    say("같은 요청 번호로 결과를 복구했어요.");
  });
await act(async () => {
  try {
    retry = JSON.parse(localStorage.getItem("territory-season-retry"));
  } catch {
    retry = null;
  }
  await refreshSeasons();
  if (allSeasons.length) {
    game = await api(`seasons/${allSeasons[0].season_id}`);
    restoreSession();
    selectors();
  }
});

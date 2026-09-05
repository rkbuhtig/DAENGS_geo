// Debug reference adapter of APP TerritoryClaim + InMemoryTerritoryClaimRepository.
// Keep the shared TSV contract in sync; this is not a production authority.
function requireThat(value, message) { if (!value) throw new Error(message); }
export function access({ recording, trusted, distance, accuracy, age = 0, radius = 20 }) {
  if (!recording || !trusted || !Number.isFinite(distance) || distance < 0 ||
      !Number.isFinite(accuracy) || accuracy < 0 || age < 0 || age > 10) return 'UNAVAILABLE';
  return distance + accuracy <= radius ? 'READY' : 'APPROACHING';
}
export function disposition(site, pet) {
  if (!site.occupancy) return 'GRANTED';
  if (site.occupancy.pet === pet) return 'ALREADY_OWNED';
  return site.occupancy.certification === 'VERIFIED' ? 'PHOTO_REQUIRED' : 'POLICY_UNDECIDED';
}
export class Claims {
  constructor(ids = ['A', 'B', 'C']) {
    this.sites = new Map(ids.map(id => [id, { id, version: 0, occupancy: null }]));
    this.attempts = new Map();
    this.captures = new Map();
  }
  key(session, site) { return JSON.stringify([session, site]); }
  attempt(session, site) { return this.attempts.get(this.key(session, site)); }
  mark(session, pet, siteId, ready = true) {
    const key = this.key(session, siteId);
    const existing = this.attempts.get(key);
    if (existing) { requireThat(existing.pet === pet, 'session_identity_changed'); return existing; }
    requireThat(ready, 'not_ready');
    const site = this.sites.get(siteId);
    requireThat(site, 'unknown_site');
    const attempt = { id: key, session, pet, siteId, disposition: disposition(site, pet), photo: 'NOT_SUBMITTED', capture: null };
    if (attempt.disposition === 'GRANTED') {
      site.occupancy = { pet, session, attemptId: key, certification: 'UNVERIFIED' };
      site.version++;
    }
    attempt.version = site.version;
    this.attempts.set(key, attempt);
    return attempt;
  }
  submit(attempt, capture) {
    requireThat(capture, 'empty_capture');
    if (attempt.capture === capture) return this.resume(attempt);
    requireThat(['NOT_SUBMITTED', 'REJECTED'].includes(attempt.photo), 'capture_in_flight');
    requireThat(!this.captures.has(capture), 'reused_capture');
    this.captures.set(capture, attempt.id);
    attempt.capture = capture;
    attempt.photo = 'PENDING';
    return attempt;
  }
  resume(attempt) { if (attempt.photo === 'RETRY_PENDING') attempt.photo = 'PENDING'; return attempt; }
  resolve(attempt, capture, outcome) {
    requireThat(attempt.capture === capture, 'stale_capture');
    if (attempt.photo === 'VERIFIED') return attempt;
    requireThat(attempt.photo === 'PENDING', 'not_pending');
    if (outcome === 'REJECTED') { attempt.photo = 'REJECTED'; return attempt; }
    if (outcome === 'RETRYABLE_FAILURE') { attempt.photo = 'RETRY_PENDING'; return attempt; }
    requireThat(outcome === 'ACCEPTED', 'unknown_outcome');
    const site = this.sites.get(attempt.siteId);
    requireThat(site.version === attempt.version, 'site_changed');
    requireThat(!site.occupancy || site.occupancy.attemptId === attempt.id || site.occupancy.session !== attempt.session, 'new_session_required');
    site.occupancy = { pet: attempt.pet, session: attempt.session, attemptId: attempt.id, certification: 'VERIFIED' };
    attempt.version = ++site.version;
    attempt.disposition = 'GRANTED';
    attempt.photo = 'VERIFIED';
    return attempt;
  }
}

'use strict';

const GRID_CAP = 35; // 5 rows of 7, then the grid holds steady
const STEP_COUNT = 10;
const FOOTPRINT =
  '<ellipse cx="9" cy="10" rx="6" ry="9" fill="#2E5339"/>' +
  '<ellipse cx="9" cy="25" rx="4.5" ry="4.5" fill="#2E5339"/>';

const $ = (id) => document.getElementById(id);
const el = {
  screen: $('screen'),
  date: $('date'),
  badge: $('badge'),
  countdownLabel: $('countdown-label'),
  countdown: $('countdown'),
  ringWrap: $('ring-wrap'),
  ringTodo: $('ring-todo'),
  ringDone: $('ring-done'),
  walkBtn: $('walk-btn'),
  undoBtn: $('undo-btn'),
  loggedTime: $('logged-time'),
  streakNum: $('streak-num'),
  dots: $('dots'),
  overflow: $('overflow'),
  error: $('error'),
  steps: $('steps'),
};

const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

let deadline = 0; // performance.now() value at midnight
let refreshing = false;

// ---------- API ----------

async function api(method, path) {
  const res = await fetch(path, {
    method,
    headers: { Accept: 'application/json' },
    credentials: 'same-origin',
    redirect: 'manual',
  });
  // authentik redirects to its login page once the session runs out.
  if (res.type === 'opaqueredirect' || res.status === 401) {
    window.location.reload();
    throw new Error('Signed out');
  }
  if (!res.ok) throw new Error(`${method} ${path} failed (${res.status})`);
  return res.json();
}

function showError(message) {
  el.error.textContent = message;
  el.error.hidden = !message;
}

// ---------- Rendering ----------

function formatDate(isoDate) {
  return new Date(`${isoDate}T12:00:00Z`).toLocaleDateString('en-GB', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  }).replace(',', '');
}

function restartAnimation(node, className) {
  node.classList.remove(className);
  void node.offsetWidth; // force reflow so the animation plays again
  node.classList.add(className);
}

function renderDots(streak, walked, celebrate) {
  const total = walked ? streak : streak + 1; // +1 for today's empty slot
  const shown = Math.min(total, GRID_CAP);
  const filledShown = walked ? shown : shown - 1;

  const frag = document.createDocumentFragment();
  for (let i = 0; i < shown; i++) {
    const dot = document.createElement('span');
    dot.className = 'dot';
    const last = i === shown - 1;
    if (last && !walked) dot.classList.add('today');
    if (last && walked) {
      dot.classList.add('new');
      if (celebrate) dot.classList.add('pop-in');
    }
    frag.appendChild(dot);
  }
  el.dots.replaceChildren(frag);
  // Keep a short first row centred; from 7 on it's a week-wide grid.
  el.dots.style.gridTemplateColumns = `repeat(${Math.min(Math.max(shown, 1), 7)}, var(--dot))`;

  const hidden = streak - filledShown;
  el.overflow.hidden = total <= GRID_CAP;
  el.overflow.textContent = `Showing the last ${GRID_CAP} days · +${hidden} before that`;
}

function render(today, { celebrate = false } = {}) {
  el.date.textContent = formatDate(today.date);
  deadline = performance.now() + today.seconds_left * 1000;
  tick();

  el.screen.classList.toggle('is-walked', today.walked);
  el.countdownLabel.textContent = today.walked ? 'Next walk unlocks in' : 'Time left today';

  el.ringTodo.classList.remove('fade-out');
  el.ringTodo.hidden = today.walked;
  el.ringDone.hidden = !today.walked;
  el.loggedTime.textContent = today.logged_time ?? '';
  el.walkBtn.disabled = false;
  el.undoBtn.disabled = false;

  el.streakNum.textContent = today.streak;
  renderDots(today.streak, today.walked, celebrate);

  if (celebrate) {
    restartAnimation(el.ringDone, 'pop');
    restartAnimation(el.streakNum, 'bump');
  }
  el.screen.setAttribute('aria-busy', 'false');
}

// ---------- Countdown ----------

function tick() {
  const ms = Math.max(0, deadline - performance.now());
  const totalMinutes = Math.floor(ms / 60000);
  const h = String(Math.floor(totalMinutes / 60)).padStart(2, '0');
  const m = String(totalMinutes % 60).padStart(2, '0');
  el.countdown.textContent = `${h}:${m}`;
  if (ms === 0 && deadline > 0) refresh(); // midnight: a new day starts
}

// ---------- Footsteps ----------

function walkFootsteps() {
  const ring = el.ringWrap.getBoundingClientRect();
  const start = { x: 40, y: window.innerHeight - 30 };
  const end = { x: ring.left + ring.width / 2, y: ring.bottom + 6 };
  const ctrl = { x: start.x - 10, y: end.y + (start.y - end.y) * 0.35 };

  const frag = document.createDocumentFragment();
  for (let i = 0; i < STEP_COUNT; i++) {
    const t = i / (STEP_COUNT - 1);
    const u = 1 - t;
    const x = u * u * start.x + 2 * u * t * ctrl.x + t * t * end.x;
    const y = u * u * start.y + 2 * u * t * ctrl.y + t * t * end.y;
    const dx = 2 * u * (ctrl.x - start.x) + 2 * t * (end.x - ctrl.x);
    const dy = 2 * u * (ctrl.y - start.y) + 2 * t * (end.y - ctrl.y);
    const len = Math.hypot(dx, dy) || 1;
    const side = i % 2 ? 9 : -9; // alternate left and right feet
    const px = x + (-dy / len) * side;
    const py = y + (dx / len) * side;
    const angle = (Math.atan2(dy, dx) * 180) / Math.PI + 90;

    const step = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    step.setAttribute('viewBox', '0 0 18 30');
    step.setAttribute('class', 'step');
    step.innerHTML = FOOTPRINT;
    step.style.left = `${px - 9}px`;
    step.style.top = `${py - 15}px`;
    step.style.transform = `rotate(${angle}deg) scaleX(${i % 2 ? 1 : -1})`;
    step.style.animationDelay = `${i * 100}ms`;
    frag.appendChild(step);
  }
  el.steps.replaceChildren(frag);
  setTimeout(() => el.steps.replaceChildren(), 2800);
}

// ---------- Actions ----------

async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    render(await api('GET', '/api/today'));
    showError('');
  } catch (err) {
    showError("Couldn't reach Amble. Refresh the page to try again.");
    console.error(err);
  } finally {
    refreshing = false;
  }
}

async function logWalk() {
  el.walkBtn.disabled = true;
  try {
    const today = await api('POST', '/api/walks');
    showError('');
    if (reduceMotion.matches) {
      render(today);
      return;
    }
    el.ringTodo.classList.add('fade-out');
    walkFootsteps();
    setTimeout(() => render(today, { celebrate: true }), 1150);
  } catch (err) {
    el.walkBtn.disabled = false;
    showError("That didn't save. Give it another tap.");
    console.error(err);
  }
}

async function undoWalk() {
  el.undoBtn.disabled = true;
  try {
    render(await api('DELETE', '/api/walks/today'));
    showError('');
  } catch (err) {
    el.undoBtn.disabled = false;
    showError("Couldn't undo that. Try again.");
    console.error(err);
  }
}

async function loadMe() {
  try {
    const me = await api('GET', '/api/me');
    el.badge.textContent = me.initials;
    el.badge.setAttribute('aria-label', `Signed in as ${me.name}`);
    el.badge.title = me.name;
  } catch (err) {
    console.error(err);
  }
}

el.walkBtn.addEventListener('click', logWalk);
el.undoBtn.addEventListener('click', undoWalk);
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') refresh();
});
setInterval(tick, 1000);

loadMe();
refresh();

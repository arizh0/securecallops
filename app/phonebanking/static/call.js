// ── State machine ─────────────────────────────────────────────────────────
let currentAssignmentId = null;
let selectedOutcome = null;
let cooldownTimer = null;
const COOLDOWN = 20;
const CIRCUMFERENCE = 238.76;

const STATES = ["idle","loading","assigned","cooldown","exhausted"];

function setState(name) {
  STATES.forEach(s => {
    document.getElementById("state-" + s).classList.toggle("active", s === name);
  });
}

// ── Boot: restore state after page refresh ────────────────────────────────
(async function boot() {
  setState("loading");
  try {
    const r = await apiFetch("/pb/api/current");
    if (!r) return;
    if (r.state === "assigned") {
      currentAssignmentId = r.assignment_id;
      showAssigned();
    } else if (r.state === "cooldown") {
      startCooldown(r.wait_seconds);
    } else {
      setState("idle");
    }
  } catch(e) {
    setState("idle");
  }
})();

// ── Get next contact ──────────────────────────────────────────────────────
async function getNextContact() {
  setState("loading");
  const r = await apiFetch("/pb/api/next");
  if (!r) return;
  if (r.ok) {
    currentAssignmentId = r.assignment_id;
    showAssigned();
  } else if (r.cooldown) {
    startCooldown(r.wait_seconds);
  } else if (r.exhausted) {
    setState("exhausted");
  } else {
    setState("idle");
  }
}

// ── Show assigned state ───────────────────────────────────────────────────
function showAssigned() {
  selectedOutcome = null;
  document.querySelectorAll(".outcome-btn").forEach(b => b.classList.remove("selected"));
  document.getElementById("comments").value = "";
  document.getElementById("submit-error").style.display = "none";

  const img = document.getElementById("name-img");
  img.src = "";
  img.src = "/pb/api/name-image/" + currentAssignmentId;

  setState("assigned");
}

// ── Outcome selection ─────────────────────────────────────────────────────
function selectOutcome(btn) {
  document.querySelectorAll(".outcome-btn").forEach(b => b.classList.remove("selected"));
  btn.classList.add("selected");
  selectedOutcome = btn.getAttribute("data-value");
  document.getElementById("submit-error").style.display = "none";
}

// ── Initiate call (server-side redirect to tel:) ──────────────────────────
function initiateCall(evt) {
  evt.preventDefault();
  window.location.href = "/pb/api/call/" + currentAssignmentId;
}

// ── Submit outcome ────────────────────────────────────────────────────────
async function submitOutcome() {
  if (!selectedOutcome) {
    showSubmitError("Please select an outcome first.");
    return;
  }
  const btn = document.getElementById("submit-btn");
  btn.disabled = true;

  const comments = document.getElementById("comments").value.trim();
  const r = await apiFetch(
    "/pb/api/submit/" + currentAssignmentId,
    { method: "POST", body: JSON.stringify({ outcome: selectedOutcome, comments }) }
  );
  btn.disabled = false;

  if (!r) return;
  if (!r.ok) {
    showSubmitError("Submission failed \u2014 please try again.");
    return;
  }

  document.getElementById("name-img").src = "";
  currentAssignmentId = null;
  await getNextContact();
}

function showSubmitError(msg) {
  const el = document.getElementById("submit-error");
  el.textContent = msg;
  el.style.display = "block";
}

// ── Cooldown countdown ────────────────────────────────────────────────────
function startCooldown(seconds) {
  if (cooldownTimer) { clearInterval(cooldownTimer); cooldownTimer = null; }
  let remaining = Math.max(1, Math.ceil(seconds));
  setState("cooldown");
  updateCooldown(remaining);

  cooldownTimer = setInterval(() => {
    remaining -= 1;
    if (remaining <= 0) {
      clearInterval(cooldownTimer);
      cooldownTimer = null;
      getNextContact();
    } else {
      updateCooldown(remaining);
    }
  }, 1000);
}

function updateCooldown(remaining) {
  document.getElementById("countdown-num").textContent   = remaining;
  document.getElementById("countdown-label").textContent = remaining;

  const pct = remaining / COOLDOWN;
  const offset = CIRCUMFERENCE * (1 - pct);
  document.getElementById("ring-fill").style.strokeDashoffset = offset;

  const btn = document.getElementById("cooldown-btn");
  btn.disabled = remaining > 0;
}

// ── Logout ────────────────────────────────────────────────────────────────
async function logout() {
  await fetch("/pb/api/logout", { method: "POST", credentials: "include" });
  window.location.href = "/pb/login";
}

// ── Fetch helper ──────────────────────────────────────────────────────────
async function apiFetch(url, options = {}) {
  const defaults = {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
  };
  try {
    const r = await fetch(url, Object.assign({}, defaults, options,
      options.headers ? { headers: Object.assign({}, defaults.headers, options.headers) } : {}));
    if (r.status === 401) { window.location.href = "/pb/login"; return null; }
    if (!r.ok) {
      console.error("API error", r.status, url);
      return null;
    }
    return await r.json();
  } catch(e) {
    console.error("Fetch failed", url, e);
    return null;
  }
}

// ── Event listeners (replacing inline onclick/oncontextmenu attributes) ───
document.querySelector(".btn-logout").addEventListener("click", logout);
document.querySelector("#state-idle .btn-primary").addEventListener("click", getNextContact);
document.getElementById("cooldown-btn").addEventListener("click", getNextContact);
document.querySelectorAll(".outcome-btn").forEach(btn =>
  btn.addEventListener("click", function() { selectOutcome(this); })
);
document.getElementById("call-btn").addEventListener("click", initiateCall);
document.getElementById("submit-btn").addEventListener("click", submitOutcome);
document.getElementById("name-img").addEventListener("contextmenu", e => e.preventDefault());

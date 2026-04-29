let _email = "";

async function requestOtp() {
  const email = document.getElementById("email").value.trim();
  const status = document.getElementById("status");
  const btn = document.getElementById("btn-request");

  if (!email) { setErr(status, "Enter your email."); return; }

  setMsg(status, "Sending code\u2026");
  btn.disabled = true;

  try {
    const r = await fetch("/pb/api/login/request", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ email }),
    });
    if (r.ok) {
      _email = email;
      document.getElementById("step-email").style.display = "none";
      document.getElementById("step-code").style.display = "block";
      document.getElementById("code").focus();
    } else {
      setErr(status, "Failed to send code. Try again.");
      btn.disabled = false;
    }
  } catch (_) {
    setErr(status, "Network error.");
    btn.disabled = false;
  }
}

async function verifyOtp() {
  const code = document.getElementById("code").value.trim();
  const status = document.getElementById("status2");
  const btn = document.getElementById("btn-verify");

  if (!code) { setErr(status, "Enter the code."); return; }

  setMsg(status, "Verifying\u2026");
  btn.disabled = true;

  try {
    const r = await fetch("/pb/api/login/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ email: _email, code }),
    });
    if (r.ok) {
      window.location.href = "/pb/call";
    } else {
      const d = await r.json().catch(() => ({}));
      setErr(status, d.detail || "Invalid code.");
      btn.disabled = false;
    }
  } catch (_) {
    setErr(status, "Network error.");
    btn.disabled = false;
  }
}

function setErr(el, msg) { el.className = "status error"; el.textContent = msg; }
function setMsg(el, msg) { el.className = "status"; el.textContent = msg; }

document.getElementById("btn-request").addEventListener("click", requestOtp);
document.getElementById("email").addEventListener("keydown", e => { if (e.key === "Enter") requestOtp(); });
document.getElementById("btn-verify").addEventListener("click", verifyOtp);
document.getElementById("code").addEventListener("keydown", e => { if (e.key === "Enter") verifyOtp(); });
document.getElementById("btn-back").addEventListener("click", () => {
  document.getElementById("step-code").style.display = "none";
  document.getElementById("step-email").style.display = "block";
  document.getElementById("btn-request").disabled = false;
  setMsg(document.getElementById("status"), "");
  document.getElementById("code").value = "";
});

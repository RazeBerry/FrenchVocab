export const el = (id) => document.getElementById(id);

export function readStorage(key, fallback = "") {
  try { return localStorage.getItem(key) || fallback; } catch (_) { return fallback; }
}

export function writeStorage(key, value) {
  try { localStorage.setItem(key, value); } catch (_) { /* private mode */ }
}

export function clearStorage(key) {
  try { localStorage.removeItem(key); } catch (_) { /* private mode */ }
}

/* Messages default to the failure colour, so anything that is neither a
   failure nor a confirmation — a spelling correction, say — has to say so
   explicitly rather than shipping as red. */
export function setMessage(node, text, { ok = false, note = false } = {}) {
  node.textContent = text || "";
  node.classList.toggle("is-ok", Boolean(text) && ok);
  node.classList.toggle("is-note", Boolean(text) && note && !ok);
}

export function setBusy(button, busy, busyLabel = "Working") {
  button.disabled = busy;
  button.classList.toggle("is-loading", busy);
  button.setAttribute("aria-busy", String(busy));
  if (busy) button.dataset.idleLabel ||= button.textContent;
  button.textContent = busy ? busyLabel : (button.dataset.idleLabel || button.textContent);
}

export function makeButton(label, value, active = false) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.dataset.value = value;
  button.setAttribute("aria-pressed", String(active));
  return button;
}

/* A horizontally scrolling strip looks like a clipped one unless it says
   otherwise, and CSS cannot ask whether an element overflows. */
export function markScrollable(container) {
  container.classList.toggle(
    "is-scrollable",
    container.scrollWidth > container.clientWidth + 1,
  );
}

export function paragraph(className, text) {
  const node = document.createElement("p");
  if (className) node.className = className;
  node.textContent = text || "";
  return node;
}

export function ignoreCancelled(error) {
  return error?.name === "StaleRequestError"
    || error?.code === "request_aborted";
}

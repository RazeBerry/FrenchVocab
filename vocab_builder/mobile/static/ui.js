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

/* iOS does not shrink vh/dvh when the software keyboard opens. The layout
   viewport keeps the full screen height and only the *visual* viewport shrinks,
   so on a 14 Pro `.stage` went on reserving 54vh = 460px of an 852px screen
   while just 516px remained visible, leaving "Look it up" 145px below the fold
   of the screen the app opens to. visualViewport is the only thing that reports
   the real inset; Safari does not support the `interactive-widget` viewport key
   that would fix it declaratively.

   The threshold keeps Safari's collapsing address bar (~50px) from reading as a
   keyboard, which would strip the tab bar out from under a scroll. */
const KEYBOARD_MIN_INSET = 120;

export function trackKeyboardInset() {
  const viewport = window.visualViewport;
  if (!viewport) return;
  const apply = () => {
    // Layout height minus visual height, and nothing else. offsetTop says where
    // the visual viewport sits, not how tall it is, so subtracting it would
    // under-report whenever iOS scrolls to keep the caret visible — far enough
    // and the inset would fall back under the threshold mid-keystroke,
    // flickering the tab bar and the whole column with it.
    const inset = Math.max(0, window.innerHeight - viewport.height);
    const open = inset > KEYBOARD_MIN_INSET;
    document.documentElement.style.setProperty(
      "--kb",
      `${open ? Math.round(inset) : 0}px`,
    );
    document.documentElement.classList.toggle("is-keyboard", open);
  };
  viewport.addEventListener("resize", apply);
  viewport.addEventListener("scroll", apply);
  apply();
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

// A minimal stand-in for the browser globals the view modules touch, so their
// real code runs under Node. Elements are looked up by id and created on first
// use; nothing here lays out or paints.
export const nodes = {};
export const store = {};

function element(id = "") {
  const listeners = {};
  const classes = new Set();
  const attributes = {};
  return {
    id,
    hidden: false,
    disabled: false,
    value: "",
    placeholder: "",
    textContent: "",
    tabIndex: 0,
    dataset: {},
    style: {},
    scrollHeight: 30,
    scrollWidth: 0,
    clientWidth: 0,
    classList: {
      add: (...names) => names.forEach((name) => classes.add(name)),
      remove: (...names) => names.forEach((name) => classes.delete(name)),
      toggle(name, force) {
        const on = force === undefined ? !classes.has(name) : Boolean(force);
        if (on) classes.add(name);
        else classes.delete(name);
        return on;
      },
      contains: (name) => classes.has(name),
    },
    setAttribute(name, value) { attributes[name] = String(value); },
    getAttribute(name) { return attributes[name] ?? null; },
    addEventListener(type, handler) { (listeners[type] ||= []).push(handler); },
    removeEventListener(type, handler) {
      listeners[type] = (listeners[type] || []).filter((item) => item !== handler);
    },
    fire(type, extra = {}) {
      (listeners[type] || []).forEach((handler) => handler({ target: this, preventDefault() {}, ...extra }));
    },
    click() { this.fire("click"); },
    replaceChildren() {},
    appendChild(child) { return child; },
    append() {},
    focus() {},
    querySelector() { return null; },
    querySelectorAll() { return []; },
    closest() { return null; },
    getBoundingClientRect() { return { top: 0, bottom: 0, left: 0, height: 0 }; },
  };
}

globalThis.document = {
  getElementById: (id) => (nodes[id] ||= element(id)),
  createElement: () => element(),
  createTextNode: (text) => ({ textContent: text }),
  createDocumentFragment: () => element(),
  addEventListener() {},
  querySelector: () => null,
  querySelectorAll: () => [],
  documentElement: element("html"),
};
globalThis.localStorage = {
  getItem: (key) => store[key] ?? null,
  setItem: (key, value) => { store[key] = String(value); },
  removeItem: (key) => { delete store[key]; },
};
Object.defineProperty(globalThis, "navigator", { value: { onLine: true, maxTouchPoints: 0 } });
globalThis.window = globalThis;
globalThis.matchMedia = () => ({ matches: false, addEventListener() {} });
globalThis.getComputedStyle = () => ({ transitionDuration: "0s" });

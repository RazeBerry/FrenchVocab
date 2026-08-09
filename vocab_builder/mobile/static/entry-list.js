export function renderEntries(container, entries, options = {}) {
  container.replaceChildren();
  let letter = null;
  entries.forEach((entry) => {
    if (options.grouped) {
      const next = indexLetter(entry.word);
      if (next !== letter) {
        letter = next;
        const divider = element("p", "index-letter", letter);
        container.appendChild(divider);
      }
    }
    const row = document.createElement("button");
    row.type = "button";
    row.className = "index-row";
    row.setAttribute("aria-expanded", "false");
    row.appendChild(element("span", "index-word", entry.word));
    const abbreviation = abbreviateType(entry.word_type);
    if (abbreviation) row.appendChild(element("span", "index-type", abbreviation));
    row.appendChild(element("span", "index-gloss", entry.definitions?.[0] || ""));
    const detail = buildDetail(entry);
    row.addEventListener("click", () => toggleRow(container, row, detail));
    container.append(row, detail);
  });
}

export function renderEntryCard(container, entry) {
  container.replaceChildren();
  const title = element("h2", "entry-card-word", entry.word);
  const type = element("p", "eyebrow", knownType(entry.word_type));
  const detail = buildDetail(entry, true);
  detail.inert = false;
  detail.classList.add("is-open", "is-static");
  detail.style.height = "auto";
  container.append(type, title, detail);
}

function buildDetail(entry, staticDetail = false) {
  const detail = element("div", "index-detail");
  if (!staticDetail) detail.inert = true;
  const inner = element("div", "index-detail-inner");
  const type = knownType(entry.word_type);
  if (type) inner.appendChild(element("p", "full-type", type));
  if (entry.definitions?.length) {
    const senses = document.createElement("ol");
    entry.definitions.forEach((definition) => {
      senses.appendChild(element("li", "", definition));
    });
    inner.appendChild(senses);
  }
  (entry.examples || []).forEach((example) => {
    const wrapper = element("div", "example");
    wrapper.appendChild(element("p", "source", `« ${example.source} »`));
    if (example.target) wrapper.appendChild(element("p", "target", example.target));
    inner.appendChild(wrapper);
  });
  detail.appendChild(inner);
  return detail;
}

function toggleRow(container, row, detail) {
  const alreadyOpen = row.getAttribute("aria-expanded") === "true";
  const open = container.querySelector('.index-row[aria-expanded="true"]');
  if (open) {
    open.setAttribute("aria-expanded", "false");
    collapse(open.nextElementSibling);
  }
  if (alreadyOpen) return;
  row.setAttribute("aria-expanded", "true");
  expand(row, detail);
}

function collapse(detail) {
  detail.style.height = `${detail.scrollHeight}px`;
  void detail.offsetHeight;
  detail.classList.remove("is-open");
  detail.style.height = "0px";
  detail.inert = true;
}

function expand(row, detail) {
  detail.inert = false;
  detail.classList.add("is-open");
  detail.style.height = "0px";
  void detail.offsetHeight;
  detail.style.height = `${detail.scrollHeight}px`;
  detail.addEventListener("transitionend", function settle(event) {
    if (event.propertyName !== "height") return;
    detail.removeEventListener("transitionend", settle);
    detail.style.height = "auto";
    reveal(row, detail);
  });
}

/* The index opens in place. scrollIntoView aligned the whole panel and could
   throw the page half a screen, landing the tapped word under the sticky
   letter. Scroll down only, by the least that shows the panel, and never far
   enough to push the tapped row out of view — so the common case is no
   movement at all. */
function reveal(row, detail) {
  const chrome = document.querySelector(".tabbar");
  const floor = window.innerHeight - (chrome ? chrome.getBoundingClientRect().height : 0);
  const overflow = detail.getBoundingClientRect().bottom - floor;
  if (overflow <= 0) return;
  const sticky = detail.parentElement?.querySelector(".index-letter");
  const ceiling = sticky ? sticky.getBoundingClientRect().height : 0;
  const headroom = row.getBoundingClientRect().top - ceiling;
  const delta = Math.min(overflow, Math.max(0, headroom));
  if (delta <= 0) return;
  window.scrollBy({
    top: delta,
    behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
  });
}

function indexLetter(word) {
  const first = (word || "").trim().charAt(0);
  const base = first.normalize("NFD").replace(/[̀-ͯ]/g, "").toUpperCase();
  return /[A-Z]/.test(base) ? base : "#";
}

/* "Unknown" is the parser's placeholder for a missing part of speech, not a
   part of speech. Rendering it produced an "UNKN." badge on 7 French entries;
   an absent badge says the same thing without the noise. */
function knownType(type) {
  const value = (type || "").trim();
  return value.toLowerCase() === "unknown" ? "" : value;
}

function abbreviateType(type) {
  const value = knownType(type).toLowerCase();
  if (!value) return "";
  const pairs = [
    ["separable verb", "v. sep."], ["pronominal verb", "v. pron."],
    ["conjunction", "conj."], ["expression", "expr."],
    ["adjective", "adj."], ["adverb", "adv."], ["pronoun", "pron."],
    ["sentence", "sent."], ["noun", "n."], ["verb", "v."],
  ];
  return pairs.find(([full]) => value.startsWith(full))?.[1]
    || (value.length <= 5 ? value : `${value.slice(0, 4)}.`);
}

function element(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = text;
  return node;
}

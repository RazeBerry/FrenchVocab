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
    row.append(
      element("span", "index-word", entry.word),
      element("span", "index-type", abbreviateType(entry.word_type)),
      element("span", "index-gloss", entry.definitions?.[0] || ""),
    );
    const detail = buildDetail(entry);
    row.addEventListener("click", () => toggleRow(container, row, detail));
    container.append(row, detail);
  });
}

export function renderEntryCard(container, entry) {
  container.replaceChildren();
  const title = element("h2", "entry-card-word", entry.word);
  const type = element("p", "eyebrow", entry.word_type || "Unknown");
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
  if (entry.word_type) inner.appendChild(element("p", "full-type", entry.word_type));
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
  expand(detail);
}

function collapse(detail) {
  detail.style.height = `${detail.scrollHeight}px`;
  void detail.offsetHeight;
  detail.classList.remove("is-open");
  detail.style.height = "0px";
  detail.inert = true;
}

function expand(detail) {
  detail.inert = false;
  detail.classList.add("is-open");
  detail.style.height = "0px";
  void detail.offsetHeight;
  detail.style.height = `${detail.scrollHeight}px`;
  detail.addEventListener("transitionend", function settle(event) {
    if (event.propertyName !== "height") return;
    detail.removeEventListener("transitionend", settle);
    detail.style.height = "auto";
    detail.scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth",
      block: "nearest",
    });
  });
}

function indexLetter(word) {
  const first = (word || "").trim().charAt(0);
  const base = first.normalize("NFD").replace(/[̀-ͯ]/g, "").toUpperCase();
  return /[A-Z]/.test(base) ? base : "#";
}

function abbreviateType(type) {
  const value = (type || "").trim().toLowerCase();
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
  if (text !== undefined) node.textContent = text;
  return node;
}

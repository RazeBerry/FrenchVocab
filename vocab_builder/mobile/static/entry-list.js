/* Day groups are built here, from the `timestamp` every history record already
   carries, so the ledger costs the server nothing. Labels are Today, Yesterday,
   then weekday and date; each heading carries its own count. */
const CALENDAR_DAY = new Intl.DateTimeFormat(undefined, {
  weekday: "short",
  day: "numeric",
  month: "short",
});

/* One immutable lookup shared by every row. Constructing these nested arrays
   inside abbreviateType allocated them again for every word in every render. */
const TYPE_ABBREVIATIONS = [
  ["separable verb", "v. sep."], ["pronominal verb", "v. pron."],
  ["conjunction", "conj."], ["expression", "expr."],
  ["adjective", "adj."], ["adverb", "adv."], ["pronoun", "pron."],
  ["sentence", "sent."], ["noun", "n."], ["verb", "v."],
];

export function renderEntries(container, entries, options = {}) {
  const fragment = document.createDocumentFragment();
  const rows = [];
  const append = (entry) => {
    rows.push(appendRow(fragment, container, entry, options));
  };
  /* Alphabetical dividers would contradict a history-ordered list, so the two
     groupings are separate options and only one can run. */
  if (options.groupBy === "day") {
    dayGroups(entries).forEach((group) => {
      fragment.appendChild(divider("index-day", group.label, group.entries.length));
      group.entries.forEach(append);
    });
  } else if (options.grouped) {
    /* Counted from the rows actually rendered rather than from the server's
       census, so the heading stays true when a type chip narrows the list.
       Over the whole collection the two agree: each row names the letter the
       server filed it under, from the same key it sorted and counted by. */
    letterGroups(entries).forEach((group) => {
      fragment.appendChild(divider("index-letter", group.letter, group.entries.length));
      group.entries.forEach(append);
    });
  } else {
    entries.forEach(append);
  }
  // Build off-DOM and publish once: style and accessibility trees see one
  // coherent list instead of hundreds of incremental insertions.
  container.replaceChildren(fragment);
  return rows;
}

function appendRow(target, container, entry, options) {
  const row = document.createElement("button");
  row.type = "button";
  row.className = "index-row";
  row.setAttribute("aria-expanded", "false");
  // The receipt names the word the server wrote, which the vocabulary file may
  // have capitalized; the row is found by that word rather than by position,
  // because a concurrent save can put another word above it.
  if (options.justSaved && sameWord(entry.word, options.justSaved)) {
    row.classList.add("is-just-saved");
    if (options.landing) row.classList.add("is-landing");
  }
  row.appendChild(element("span", "index-word", entry.word));
  const abbreviation = abbreviateType(entry.word_type);
  if (abbreviation) row.appendChild(element("span", "index-type", abbreviation));
  // Finder rows carry `gloss`; richer history and random-card records carry
  // definitions. Both use the same row renderer without hauling cold detail
  // through index and search responses.
  row.appendChild(glossNode(entry.gloss ?? entry.definitions?.[0] ?? "", options.highlight));
  const mark = mergeMark(entry);
  if (mark) row.appendChild(mark);
  // A finder row has no detail to show yet: 573 of them would be 573 panels
  // built for the one that gets opened. The owner fills it on open instead.
  const detail = options.loadDetail ? emptyDetail() : buildDetail(entry);
  row.addEventListener("click", () => {
    if (options.loadDetail && row.getAttribute("aria-expanded") !== "true") {
      // Before the tween, so a cached entry is measured at its real height.
      options.loadDetail(entry, detail);
    }
    toggleRow(container, row, detail);
  });
  target.append(row, detail);
  return row;
}

/* The searched fragment is a real <mark>, not a CSS decoration: a screen
   reader announces the element and nothing else can say which word matched. */
function glossNode(text, needle) {
  const node = element("span", "index-gloss");
  const seek = (needle || "").toLocaleLowerCase();
  if (!seek) {
    node.textContent = text;
    return node;
  }
  const haystack = text.toLocaleLowerCase();
  let at = 0;
  for (let found = haystack.indexOf(seek); found !== -1; found = haystack.indexOf(seek, at)) {
    node.appendChild(document.createTextNode(text.slice(at, found)));
    node.appendChild(element("mark", "", text.slice(found, found + seek.length)));
    at = found + seek.length;
  }
  node.appendChild(document.createTextNode(text.slice(at)));
  return node;
}

/* A merge that added two senses used to look exactly like a new word. The
   counts are the ones the save itself recorded — recomputing them here would
   let the ledger disagree with what landed on disk. */
function mergeMark(entry) {
  if (entry.action !== "merge") return null;
  const clauses = [
    addedClause(entry.added?.definitions, "sense"),
    addedClause(entry.added?.examples, "example"),
  ].filter(Boolean);
  if (clauses.length === 0) return null;
  const mark = element("span", "index-mark", "merged · ");
  mark.appendChild(element("strong", "", clauses.join(", ")));
  return mark;
}

function addedClause(count, singular) {
  const value = Number(count) || 0;
  if (value <= 0) return "";
  return `+${value} ${singular}${value === 1 ? "" : "s"}`;
}

/* One divider object. `.index-divider` carries the sticky chip; the kind adds
   only its layout, and the count is a real element either way. */
function divider(kind, label, count) {
  const heading = element("p", `index-divider ${kind}`, label);
  // The letter rail jumps to this heading, so the heading names itself rather
  // than the rail re-deriving where each bucket starts.
  if (kind === "index-letter") heading.dataset.letter = label;
  heading.appendChild(element("span", "index-count", String(count)));
  return heading;
}

function letterGroups(entries) {
  const groups = [];
  let letter = null;
  entries.forEach((entry) => {
    const next = entry.letter;
    if (next !== letter) {
      letter = next;
      groups.push({ letter, entries: [] });
    }
    groups[groups.length - 1].entries.push(entry);
  });
  return groups;
}

function dayGroups(entries) {
  const groups = [];
  let key = null;
  entries.forEach((entry) => {
    const next = dayKey(entry.timestamp);
    if (next !== key) {
      key = next;
      groups.push({ label: dayLabel(new Date(entry.timestamp)), entries: [] });
    }
    groups[groups.length - 1].entries.push(entry);
  });
  return groups;
}

/* The day a record belongs to, in the reader's own timezone: history stores
   UTC, and a word kept at 23:30 local is still that evening's word. */
export function dayKey(timestamp) {
  const date = new Date(timestamp);
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

function dayLabel(date) {
  const today = new Date();
  const key = dayKey(date);
  if (key === dayKey(today)) return "Today";
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (key === dayKey(yesterday)) return "Yesterday";
  // Assembled from parts so the order stays weekday, day, month whatever the
  // reader's locale would otherwise impose.
  const parts = CALENDAR_DAY.formatToParts(date);
  const part = (type) => parts.find((entry) => entry.type === type)?.value || "";
  return `${part("weekday")} ${part("day")} ${part("month")}`;
}

function sameWord(left, right) {
  return (left || "").trim().toLocaleLowerCase() === (right || "").trim().toLocaleLowerCase();
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
  detail.appendChild(detailInner(entry));
  return detail;
}

function emptyDetail() {
  const detail = element("div", "index-detail");
  detail.inert = true;
  detail.appendChild(element("div", "index-detail-inner"));
  return detail;
}

/* The panel body, so a view that loads its entries lazily can build the same
   content from the record it fetched instead of restating the layout. */
export function detailInner(entry) {
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
  return inner;
}

function toggleRow(container, row, detail) {
  const alreadyOpen = row.getAttribute("aria-expanded") === "true";
  const open = container.querySelector('.index-row[aria-expanded="true"]');
  if (open) {
    open.setAttribute("aria-expanded", "false");
    const panel = open.nextElementSibling;
    // A panel closing above the tapped row would carry that row up with it
    // for the length of the tween. Chrome anchors the scroll position through
    // that; Safari does not. Close it in one step and hand its height back to
    // the scroll position in the same frame, so the row under the finger
    // stays where it was. A panel below can close at its own pace.
    const above = !alreadyOpen
      && Boolean(open.compareDocumentPosition(row) & Node.DOCUMENT_POSITION_FOLLOWING);
    if (above) collapseInPlace(panel);
    else collapse(panel);
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

function collapseInPlace(detail) {
  const height = detail.getBoundingClientRect().height;
  detail.style.transition = "none";
  detail.classList.remove("is-open");
  detail.style.height = "0px";
  detail.inert = true;
  void detail.offsetHeight;
  detail.style.transition = "";
  window.scrollBy({ top: -height, behavior: "auto" });
}

/* The record arrived while the panel was already open. Mid-tween the pinned
   height is simply retargeted, and the open tween's own transitionend still
   releases it. Once settled at auto, height cannot animate from auto, so pin
   what is on screen, swap the content, and tween to the new measurement. */
export function refit(detail, paint) {
  const settled = detail.style.height === "auto";
  const from = settled ? detail.getBoundingClientRect().height : 0;
  if (settled) detail.style.height = `${from}px`;
  paint();
  if (!settled) {
    detail.style.height = `${detail.scrollHeight}px`;
    return;
  }
  void detail.offsetHeight;
  const to = detail.scrollHeight;
  if (Math.abs(to - from) < 1) {
    detail.style.height = "auto";
    return;
  }
  detail.style.height = `${to}px`;
  releaseWhenSettled(detail);
}

/* Released on the event and on a timer: a zero-duration tween under reduced
   motion, or a close that lands mid-flight, can swallow transitionend and
   would otherwise leave the panel pinned at a stale height. */
function releaseWhenSettled(detail) {
  const release = () => {
    detail.removeEventListener("transitionend", onEnd);
    window.clearTimeout(timer);
    if (detail.classList.contains("is-open")) detail.style.height = "auto";
  };
  const onEnd = (event) => {
    if (event.propertyName === "height") release();
  };
  detail.addEventListener("transitionend", onEnd);
  const timer = window.setTimeout(release, tweenMilliseconds(detail) + 50);
}

function tweenMilliseconds(node) {
  const value = getComputedStyle(node).transitionDuration.split(",")[0].trim();
  return value.endsWith("ms") ? parseFloat(value) : parseFloat(value) * 1000;
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
  const sticky = detail.parentElement?.querySelector(".index-divider");
  const ceiling = sticky ? sticky.getBoundingClientRect().height : 0;
  const headroom = row.getBoundingClientRect().top - ceiling;
  const delta = Math.min(overflow, Math.max(0, headroom));
  if (delta <= 0) return;
  window.scrollBy({
    top: delta,
    behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
  });
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
  return TYPE_ABBREVIATIONS.find(([full]) => value.startsWith(full))?.[1]
    || (value.length <= 5 ? value : `${value.slice(0, 4)}.`);
}

function element(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = text;
  return node;
}

/* Local dashboard updates: preserve existing nodes and the reader's position. */
(() => {
  "use strict";
  const main = document.querySelector("main[data-dashboard]");
  if (!main) return;
  const interval = Number(main.dataset.refreshSeconds) * 1000;
  const status = document.getElementById("refresh-status");
  let timer, request;
  const reading = () => Boolean(window.getSelection()?.toString());
  const paused = () => document.hidden || reading();

  function morph(current, incoming) {
    if (current.isEqualNode(incoming)) return current;
    if (current.nodeType !== incoming.nodeType || current.nodeName !== incoming.nodeName) {
      const replacement = incoming.cloneNode(true);
      current.replaceWith(replacement);
      return replacement;
    }
    if (current.nodeType !== Node.ELEMENT_NODE) {
      current.nodeValue = incoming.nodeValue;
      return current;
    }
    for (const attribute of [...current.attributes]) {
      if (!incoming.hasAttribute(attribute.name)) current.removeAttribute(attribute.name);
    }
    for (const attribute of incoming.attributes) {
      if (current.getAttribute(attribute.name) !== attribute.value) {
        current.setAttribute(attribute.name, attribute.value);
      }
    }
    // IDs belong to fixed panels. Optional panels can appear without displacing
    // the identity (and scroll position) of their unchanged neighbours.
    let cursor = current.firstChild;
    const children = [...incoming.childNodes];
    for (const [index, child] of children.entries()) {
      let match = cursor;
      if (child.nodeType === Node.ELEMENT_NODE && child.id) {
        match = [...current.children].find(node => node.id === child.id);
      } else if (match?.nodeType === Node.ELEMENT_NODE && match.id) {
        match = null;
      } else if (match && !match.isEqualNode(child)) {
        // A paragraph inserted above the reader must not rename every existing
        // paragraph. Keep exact unchanged siblings, including their identity.
        const remaining = [];
        for (let node = cursor; node; node = node.nextSibling) remaining.push(node);
        const equal = remaining.find(node => node.isEqualNode(child));
        if (equal) match = equal;
        else if (children.slice(index + 1).some(node => match.isEqualNode(node))) match = null;
      }
      if (!match) {
        current.insertBefore(child.cloneNode(true), cursor);
      } else {
        if (match !== cursor) current.insertBefore(match, cursor);
        cursor = morph(match, child).nextSibling;
      }
    }
    while (cursor) {
      const next = cursor.nextSibling;
      cursor.remove();
      cursor = next;
    }
    return current;
  }

  function apply(page) {
    const incoming = page.querySelector("main[data-dashboard]");
    if (!incoming) throw new Error("Invalid dashboard response");
    const scroll = window.scrollY;
    const candidates = [...main.querySelectorAll("h2,h3,p,.work-card,.ledger-item"),
      ...main.querySelectorAll("[data-panel]")];
    const anchors = candidates.filter(node => {
      const rect = node.getBoundingClientRect();
      return rect.bottom > 0 && rect.top < innerHeight;
    }).map(node => [node, node.getBoundingClientRect().top]);
    // The navigation and refresh status stay local; replace only data regions.
    for (const id of ["dashboard-header", "dashboard-content", "dashboard-sources"]) {
      const current = document.getElementById(id);
      const next = incoming.querySelector(`#${id}`);
      if (!current || !next) throw new Error("Incomplete dashboard response");
    }
    for (const id of ["dashboard-header", "dashboard-content", "dashboard-sources"]) {
      morph(document.getElementById(id), incoming.querySelector(`#${id}`));
    }
    const anchor = anchors.find(([node]) => node.isConnected);
    if (scroll === 0) window.scrollTo(window.scrollX, 0);
    else if (anchor) window.scrollBy(0, anchor[0].getBoundingClientRect().top - anchor[1]);
    else window.scrollTo(window.scrollX, scroll);
  }

  function schedule() {
    clearTimeout(timer);
    if (interval > 0 && !document.hidden) timer = setTimeout(refresh, interval);
  }

  async function refresh() {
    if (request || paused()) { schedule(); return; }
    request = new AbortController();
    const timeout = setTimeout(() => request?.abort(), Math.max(10000, interval));
    try {
      const response = await fetch(location.pathname, {cache: "no-store", signal: request.signal});
      if (!response.ok) throw new Error("Refresh unavailable");
      const page = new DOMParser().parseFromString(await response.text(), "text/html");
      if (paused()) return;
      apply(page);
      status.textContent = interval > 0 ? `Live · every ${interval / 1000}s` : "Snapshot updated";
    } catch (error) {
      if (!document.hidden) status.textContent = "Update unavailable · showing last snapshot";
    } finally {
      clearTimeout(timeout);
      request = null;
      schedule();
    }
  }

  document.querySelector('[data-refresh]')?.addEventListener("click", event => {
    event.preventDefault();
    clearTimeout(timer);
    refresh();
  });
  document.addEventListener("visibilitychange", () => {
    clearTimeout(timer);
    if (document.hidden) request?.abort();
    else if (interval > 0) refresh();
  });
  document.addEventListener("selectionchange", () => {
    if (reading()) status.textContent = "Updates paused · text selected";
    else status.textContent = interval > 0 ? `Live · every ${interval / 1000}s` : "Manual refresh";
  });
  schedule();
})();

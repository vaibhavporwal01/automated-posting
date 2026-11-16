// Posting console. Mirrors the server's message rules for instant feedback;
// the server stays the source of truth and its errors are shown as-is.

(() => {
  "use strict";

  const MAX_LENGTH = 200;
  const LINK_PATTERN = /(?:\b[a-zA-Z][a-zA-Z0-9+.\-]*:\/\/|\bwww\.)\S+/gi;
  const TRAILING = /[.,;:!?'")\]}>]+$/;
  const EXAMPLE =
    "Check out our latest business platform and grow your online visibility. https://example.com";

  const el = {
    form: document.getElementById("composer"),
    message: document.getElementById("message"),
    ruler: document.getElementById("ruler"),
    counter: document.getElementById("counter"),
    detected: document.getElementById("detected"),
    checks: document.getElementById("checks"),
    formError: document.getElementById("form-error"),
    publish: document.getElementById("publish"),
    example: document.getElementById("use-example"),
    destinations: document.getElementById("destinations"),
    destinationsNote: document.getElementById("destinations-note"),
    summary: document.getElementById("summary"),
    resultsBody: document.getElementById("results-body"),
    raw: document.getElementById("raw"),
    rawJson: document.getElementById("raw-json"),
    kbdMod: document.getElementById("kbd-mod"),
  };

  let readyCount = 0;
  let busy = false;

  // ------------------------------------------------------------- ruler

  const ticks = [];
  for (let i = 0; i < MAX_LENGTH; i += 1) {
    const tick = document.createElement("span");
    el.ruler.appendChild(tick);
    ticks.push(tick);
  }

  if (/Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent)) {
    el.kbdMod.textContent = "⌘";
  }

  // ------------------------------------------------------------- rules

  function findLinks(text) {
    const links = [];
    for (const match of text.matchAll(LINK_PATTERN)) {
      const value = match[0].replace(TRAILING, "");
      if (value) links.push({ value, start: match.index, end: match.index + value.length });
    }
    return links;
  }

  function isPublicHttpUrl(value) {
    let url;
    try {
      url = new URL(value);
    } catch (_) {
      return false;
    }
    if (url.protocol !== "http:" && url.protocol !== "https:") return false;
    if (url.username || url.password) return false;
    const host = url.hostname;
    if (!host.includes(".")) return false;
    if (/^(127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|0\.)/.test(host)) return false;
    const tld = host.split(".").pop();
    return /^[a-z]{2,63}$|^xn--/i.test(tld) || /^\d+$/.test(tld);
  }

  function evaluate(raw) {
    const text = raw.trim();
    const links = findLinks(text);
    return {
      text,
      length: text.length,
      links,
      lengthOk: text.length > 0 && text.length <= MAX_LENGTH,
      oneLink: links.length === 1,
      urlOk: links.length === 1 && isPublicHttpUrl(links[0].value),
    };
  }

  // ------------------------------------------------------------- composer state

  function setCheck(name, state) {
    const item = el.checks.querySelector(`[data-check="${name}"]`);
    item.classList.toggle("is-pass", state === true);
    item.classList.toggle("is-fail", state === false);
  }

  function render() {
    const state = evaluate(el.message.value);
    const over = state.length > MAX_LENGTH;

    ticks.forEach((tick, index) => {
      const filled = index < state.length;
      const inLink = state.links.some((link) => index >= link.start && index < link.end);
      tick.classList.toggle("is-filled", filled && !inLink);
      tick.classList.toggle("is-link", filled && inLink);
    });
    el.ruler.classList.toggle("is-over", over);

    el.counter.innerHTML = `<strong>${state.length}</strong> of ${MAX_LENGTH} characters`;
    el.counter.classList.toggle("is-over", over);
    el.message.setAttribute("aria-invalid", over ? "true" : "false");

    if (state.links.length === 0) {
      el.detected.textContent = "No link yet";
    } else if (state.links.length === 1) {
      const link = state.links[0].value;
      el.detected.replaceChildren("Link: ", anchor(link, link));
    } else {
      el.detected.textContent = `${state.links.length} links found, keep one`;
    }

    const touched = state.length > 0;
    setCheck("length", touched ? state.lengthOk : null);
    setCheck("one-link", touched ? state.oneLink : null);
    setCheck("valid-url", touched && state.links.length === 1 ? state.urlOk : touched && state.links.length > 1 ? false : null);

    el.publish.disabled = busy || !(state.lengthOk && state.oneLink && state.urlOk) || readyCount === 0;
    return state;
  }

  function publishLabel() {
    if (busy) return "Publishing…";
    if (readyCount === 0) return "No platforms ready";
    return `Publish to ${readyCount} platform${readyCount === 1 ? "" : "s"}`;
  }

  function showFormError(message) {
    el.formError.textContent = message;
    el.formError.hidden = !message;
  }

  // ------------------------------------------------------------- destinations

  async function loadPlatforms() {
    try {
      const response = await fetch("/platforms");
      const platforms = await response.json();
      el.destinations.replaceChildren(
        ...platforms.map((platform) => {
          const item = document.createElement("li");
          const ready = platform.configured && platform.enabled;
          item.className = ready ? "is-ready" : "is-off";

          const name = document.createElement("span");
          name.className = "destinations__name";
          name.textContent = platform.name;

          const docs = anchor(platform.docs_url, "API docs");
          docs.className = "destinations__docs";

          const state = document.createElement("span");
          state.className = "destinations__state";
          state.textContent = !platform.enabled
            ? "Turned off in ENABLED_PLATFORMS"
            : platform.configured
              ? "Ready"
              : `Needs ${platform.missing.join(", ")}`;

          item.append(name, docs, state);
          return item;
        })
      );
      readyCount = platforms.filter((p) => p.configured && p.enabled).length;
      el.destinationsNote.textContent =
        readyCount === platforms.length
          ? `All ${readyCount} platforms have credentials and will receive the post.`
          : `${readyCount} of ${platforms.length} platforms will receive the post. Add keys to .env to enable the rest.`;
    } catch (_) {
      el.destinationsNote.textContent = "Could not load the platform list. Is the server running?";
    }
    el.publish.textContent = publishLabel();
    render();
  }

  // ------------------------------------------------------------- results

  function anchor(href, text) {
    const a = document.createElement("a");
    a.href = href;
    a.textContent = text;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    return a;
  }

  function cell(content, className) {
    const td = document.createElement("td");
    if (className) td.className = className;
    if (content instanceof Node) td.appendChild(content);
    else if (content === null || content === undefined || content === "") {
      const dash = document.createElement("span");
      dash.className = "muted";
      dash.textContent = "–";
      dash.setAttribute("aria-label", "none");
      td.appendChild(dash);
    } else td.textContent = content;
    return td;
  }

  function shortUrl(url) {
    try {
      const parsed = new URL(url);
      return parsed.host.replace(/^www\./, "") + parsed.pathname.replace(/\/$/, "");
    } catch (_) {
      return url;
    }
  }

  function renderResults(data) {
    const rows = (data.results || []).map((result) => {
      const tr = document.createElement("tr");
      const status = document.createElement("span");
      status.className = `status status--${result.status}`;
      status.textContent = result.status === "success" ? "Published" : "Failed";

      let link = null;
      if (result.posted_url) {
        link = anchor(result.posted_url, shortUrl(result.posted_url));
        link.title = result.posted_url;
      }

      tr.append(
        cell(result.platform, "platform"),
        cell(status),
        cell(link, "url"),
        cell(result.status === "success" ? (result.public_access ? "Yes" : "No") : null, "nowrap"),
        cell(result.date, "nowrap"),
        cell(result.time, "nowrap"),
        cell(result.error, result.error ? "error" : "")
      );
      return tr;
    });

    el.resultsBody.replaceChildren(...rows);

    const summary = data.summary || {};
    const seconds = ((summary.duration_ms || 0) / 1000).toFixed(1);
    el.summary.innerHTML = "";
    const strong = document.createElement("strong");
    strong.textContent = `${summary.succeeded} of ${summary.total} published`;
    el.summary.append(
      strong,
      ` in ${seconds}s. Run ${data.run_id}, times in ${data.timezone}.`
    );
    if (data.skipped && data.skipped.length) {
      el.summary.append(` Skipped: ${data.skipped.map((s) => s.platform).join(", ")}.`);
    }

    el.rawJson.textContent = JSON.stringify(data, null, 2);
    el.raw.hidden = false;
  }

  // ------------------------------------------------------------- publish

  async function publish() {
    const state = render();
    if (el.publish.disabled) return;

    busy = true;
    showFormError("");
    el.publish.classList.add("is-busy");
    el.publish.textContent = publishLabel();
    render();

    try {
      const response = await fetch("/posting", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: state.text }),
      });
      const data = await response.json();

      if (response.status === 200 || response.status === 502) {
        renderResults(data);
        if (response.status === 502) showFormError("Every platform failed. See the Error column for details.");
      } else {
        showFormError((data.error && data.error.message) || `The server answered HTTP ${response.status}.`);
      }
    } catch (_) {
      showFormError("Could not reach the server. Check that uvicorn is running on port 4000.");
    } finally {
      busy = false;
      el.publish.classList.remove("is-busy");
      el.publish.textContent = publishLabel();
      render();
    }
  }

  // ------------------------------------------------------------- wiring

  el.message.addEventListener("input", () => {
    showFormError("");
    render();
  });

  el.message.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      publish();
    }
  });

  el.form.addEventListener("submit", (event) => {
    event.preventDefault();
    publish();
  });

  el.example.addEventListener("click", () => {
    el.message.value = EXAMPLE;
    el.message.focus();
    render();
  });

  // Exposed so a saved response (for example docs/sample-response.json) can be shown again.
  window.postingConsole = { renderResults };

  render();
  loadPlatforms();
})();

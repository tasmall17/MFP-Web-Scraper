/* my-favorite-professor -- the front end.
 *
 * No framework and no build step, so that cloning the repo and running one
 * command is the whole setup. The server is the only source of truth; this
 * file renders it and sends things back.
 *
 * Two things worth knowing before reading on:
 *
 *  - The API key is never here. Settings sends one up; the server only ever
 *    sends back whether a key exists.
 *  - Answers arrive as server-sent events over POST, so they stream in as
 *    Claude writes them rather than landing all at once.
 */

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
};

const state = {
  settings: null,
  topics: [],
  topic: null,        // topic directory name
  note: null,         // note id
  doc: null,          // rendered note
  history: [],        // [{role, content}]
  busy: false,
};

/* ── subject colour ────────────────────────────────────────────────
 * Each subject gets a stable hue so you can tell at a glance which
 * professor you're in. Hashed from the name, picked from a fixed set --
 * an arbitrary hue would eventually land somewhere unreadable.
 */
const HUES = [
  { a: "#5b4fd6", w: "#f0eefc" },  // violet
  { a: "#0f766e", w: "#e7f4f2" },  // teal
  { a: "#b4530a", w: "#fdf1e6" },  // amber
  { a: "#2563a5", w: "#e9f1fa" },  // blue
  { a: "#8b3a62", w: "#fbecf3" },  // plum
  { a: "#3f7a2e", w: "#eef6ea" },  // moss
];

function hueFor(name) {
  let h = 0;
  for (const ch of name || "") h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return HUES[h % HUES.length];
}

function applyHue(name) {
  const { a, w } = hueFor(name);
  document.documentElement.style.setProperty("--accent", a);
  document.documentElement.style.setProperty("--accent-wash", w);
}

/* ── talking to the server ─────────────────────────────────────── */

async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* not json */ }
    throw new Error(detail);
  }
  return res.json();
}

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { node.hidden = true; }, 3200);
}

/* ── subjects ──────────────────────────────────────────────────── */

function extLabel(topic) {
  return "." + (topic ? topic.stem : "??");
}

function renderSubjects() {
  const list = $("#ext-list");
  list.replaceChildren();

  if (!state.topics.length) {
    list.append(el("p", "note", "No subjects yet. Add one below."));
  }

  for (const topic of state.topics) {
    const button = el("button");
    button.type = "button";
    button.setAttribute("aria-current", String(topic.name === state.topic));
    const swatch = el("span", "swatch");
    swatch.style.background = hueFor(topic.name).a;
    button.append(swatch, el("span", null, extLabel(topic)));
    button.append(el("span", "count", String(topic.notes.length)));
    button.onclick = () => { selectTopic(topic.name); closePops(); };
    list.append(button);
  }

  const current = state.topics.find((t) => t.name === state.topic);
  $("#ext-label").textContent = extLabel(current);
  $(".empty-mark") && ($(".empty-mark").textContent = extLabel(current));

  const picker = $("#upload-topic");
  picker.replaceChildren();
  for (const topic of state.topics) {
    const option = el("option", null, `${extLabel(topic)}  —  ${topic.name}`);
    option.value = topic.name;
    if (topic.name === state.topic) option.selected = true;
    picker.append(option);
  }
  if (!state.topics.length) {
    const option = el("option", null, "Add a subject first");
    option.value = "";
    picker.append(option);
  }
}

function selectTopic(name) {
  state.topic = name;
  applyHue(name);
  renderSubjects();
  renderRail();
  const topic = state.topics.find((t) => t.name === name);
  if (topic && topic.notes.length) openNote(topic.notes[0].id);
  else showEmptyReading();
}

/* ── the rail ──────────────────────────────────────────────────── */

function renderRail() {
  const body = $("#rail-body");
  body.replaceChildren();

  const topic = state.topics.find((t) => t.name === state.topic);
  if (!topic || !topic.notes.length) {
    body.append(el("p", "rail-empty", "Nothing here yet. Add a file to get started."));
    return;
  }

  const groups = [
    ["Yours", topic.notes.filter((n) => n.source === "user")],
    ["Claude found", topic.notes.filter((n) => n.source === "claude")],
  ];

  for (const [label, notes] of groups) {
    if (!notes.length) continue;
    const group = el("div", "group");
    const head = el("div", "group-label");
    head.append(el("span", null, label), el("span", "n", String(notes.length)));
    group.append(head);

    for (const note of notes) {
      const button = el("button", "item");
      button.type = "button";
      button.setAttribute("aria-current", String(note.id === state.note));
      button.append(el("span", null, note.title));
      if (note.words) button.append(el("span", "meta", `${note.words.toLocaleString()} words`));
      button.onclick = () => openNote(note.id);
      group.append(button);
    }
    body.append(group);
  }
}

/* ── the reading ───────────────────────────────────────────────── */

function showEmptyReading() {
  state.note = null;
  state.doc = null;
  const body = $("#reading-body");
  body.replaceChildren();
  const empty = el("div", "empty");
  const topic = state.topics.find((t) => t.name === state.topic);
  empty.append(el("p", "empty-mark", extLabel(topic)));
  empty.append(el("h2", null, "Pick what you're studying"));
  const p = el("p", null,
    "Add a Markdown, text or PDF file and it becomes your first reading. " +
    "Or save a page while you're reading it:");
  empty.append(p);
  empty.append(el("code", "empty-cmd", `mfp -${topic ? topic.stem : "py"} https://example.com/article`));
  const button = el("button", "primary", "Add materials");
  button.onclick = () => openSheet("upload");
  empty.append(button);
  body.append(empty);
  resetProfessor();
}

async function openNote(id) {
  try {
    const doc = await api(`/api/note?id=${encodeURIComponent(id)}`);
    state.note = id;
    state.doc = doc;
    state.history = [];

    const body = $("#reading-body");
    body.replaceChildren();

    const wrap = el("article", "doc");
    const head = el("div", "doc-head");
    const kicker = el("div", "doc-kicker");
    const tag = el("span", doc.source === "claude" ? "tag claude" : "tag",
                   doc.source === "claude" ? "Claude found this" : "Yours");
    kicker.append(tag);
    if (doc.words) kicker.append(el("span", null, `${doc.words.toLocaleString()} words`));
    if (doc.origin) kicker.append(el("span", null, doc.origin.replace(/^local:/, "")));
    head.append(kicker, el("h1", null, doc.title));
    wrap.append(head);

    const prose = el("div", "prose");
    prose.innerHTML = doc.html;   // rendered and escaped server-side
    wrap.append(prose);
    body.append(wrap);
    $("#reading").scrollTop = 0;

    renderRail();
    resetProfessor();
  } catch (err) {
    toast(err.message);
  }
}

/* ── Professor-Claude ──────────────────────────────────────────── */

function resetProfessor() {
  const log = $("#prof-log");
  log.replaceChildren();
  $("#prof-meta").textContent = "";
  state.history = [];

  const sub = $("#prof-sub");
  if (!state.doc) {
    sub.textContent = "Open a reading to ask about it";
    log.append(el("p", "prof-empty", "Nothing open yet."));
    return;
  }

  sub.textContent = state.doc.title;
  const empty = el("div", "prof-empty");
  empty.append(el("p", null, "Ask about anything in this reading. Try:"));
  const list = el("ul");
  for (const line of [
    "Explain this section in plain terms",
    "Give me a concrete example",
    "What do I need to understand before this?",
  ]) list.append(el("li", null, line));
  empty.append(list);
  log.append(empty);
}

function addMessage(kind, who, text) {
  const log = $("#prof-log");
  log.querySelector(".prof-empty")?.remove();

  const msg = el("div", `msg msg-${kind}`);
  msg.append(el("p", "msg-who", who));
  const body = el("div", "msg-body");
  if (kind === "prof") body.innerHTML = "";
  else body.textContent = text;
  msg.append(body);
  log.append(msg);
  log.scrollTop = log.scrollHeight;
  return body;
}

/* A deliberately tiny renderer for streamed answers: paragraphs, fenced code,
 * inline code, bold, and links. The reading pane gets proper server-side
 * Markdown; this only has to keep up with text arriving a token at a time. */
function renderAnswer(text) {
  const escape = (s) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  const parts = text.split(/```/);
  return parts.map((part, index) => {
    if (index % 2 === 1) {
      const body = part.replace(/^[\w+-]*\n/, "");
      return `<pre><code>${escape(body)}</code></pre>`;
    }
    return part
      .split(/\n{2,}/)
      .filter((block) => block.trim())
      .map((block) => {
        let html = escape(block.trim())
          .replace(/`([^`]+)`/g, "<code>$1</code>")
          .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
          .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g,
                   '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
          .replace(/\n/g, "<br>");
        return `<p>${html}</p>`;
      })
      .join("");
  }).join("");
}

async function ask(question) {
  if (state.busy || !state.doc) return;
  if (!state.settings?.has_key) {
    toast("Add your API key in Settings first");
    openSheet("settings");
    return;
  }

  state.busy = true;
  $("#prof-send").disabled = true;
  addMessage("you", "You", question);
  const target = addMessage("prof", "Professor-Claude", "");
  target.innerHTML = '<p style="color:var(--slate-dim)">Thinking…</p>';
  $("#prof-meta").textContent = "";

  let answer = "";
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        note_id: state.note,
        question,
        history: state.history,
      }),
    });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch { /* not json */ }
      throw new Error(detail);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // SSE frames are separated by a blank line; a partial frame stays in
      // the buffer until the rest of it arrives.
      const frames = buffer.split("\n\n");
      buffer = frames.pop();

      for (const frame of frames) {
        const line = frame.split("\n").find((l) => l.startsWith("data: "));
        if (!line) continue;
        const event = JSON.parse(line.slice(6));

        if (event.type === "delta") {
          answer += event.text;
          target.innerHTML = renderAnswer(answer);
          $("#prof-log").scrollTop = $("#prof-log").scrollHeight;
        } else if (event.type === "error") {
          target.parentElement.className = "msg msg-err";
          target.textContent = event.message;
          answer = "";
        } else if (event.type === "done") {
          answer = event.text || answer;
          target.innerHTML = renderAnswer(answer);
          showUsage(event.usage);
        }
      }
    }

    if (answer) {
      state.history.push({ role: "user", content: question });
      state.history.push({ role: "assistant", content: answer });
      addClickedButton(target.parentElement);
    }
  } catch (err) {
    target.parentElement.className = "msg msg-err";
    target.textContent = err.message;
  } finally {
    state.busy = false;
    $("#prof-send").disabled = false;
    $("#prof-log").scrollTop = $("#prof-log").scrollHeight;
  }
}

function showUsage(usage) {
  if (!usage) return;
  const read = usage.cache_read_input_tokens || 0;
  const written = usage.cache_creation_input_tokens || 0;
  const bits = [`${usage.output_tokens || 0} out`];
  if (read) bits.push(`${read.toLocaleString()} cached`);
  else if (written) bits.push(`${written.toLocaleString()} cached for next time`);
  else bits.push(`reading too short to cache (needs ${usage.cache_min_tokens})`);
  $("#prof-meta").textContent = bits.join(" · ");
}

/* The strongest signal for the learning profile is the one you give on
 * purpose. Passive signals fill in around it. */
function addClickedButton(message) {
  const button = el("button", "clicked", "That clicked");
  button.type = "button";
  button.dataset.on = "0";
  button.onclick = () => {
    button.dataset.on = button.dataset.on === "1" ? "0" : "1";
    button.textContent = button.dataset.on === "1" ? "Noted — that clicked" : "That clicked";
    if (button.dataset.on === "1") toast("Noted. Professor-Claude will lean this way.");
  };
  message.append(button);
}

/* ── settings ──────────────────────────────────────────────────── */

function renderSettings() {
  const settings = state.settings;
  $("#avatar-initials").textContent = settings.initials || "··";
  $("#initials").value = settings.initials || "";
  $("#lib-hint").textContent = settings.library || "";
  $("#mirror-path").textContent = settings.mirror_path;
  $("#mirror-toggle").checked = settings.mirror_to_downloads !== false;

  const status = $("#key-status");
  if (settings.has_key) {
    status.textContent = settings.key_from_env
      ? "Using ANTHROPIC_API_KEY from your environment."
      : "A key is saved.";
    status.dataset.ok = "1";
  } else {
    status.textContent = "No key yet. Professor-Claude can't answer without one.";
    status.dataset.ok = "0";
  }

  const choices = $("#model-choices");
  choices.replaceChildren();
  for (const model of settings.models) {
    const button = el("button", "choice");
    button.type = "button";
    button.setAttribute("aria-pressed", String(model.id === settings.model));
    const text = el("span");
    text.append(el("span", "name", model.label));
    text.append(el("span", "blurb", model.blurb));
    button.append(text);
    button.onclick = () => saveSettings({ model: model.id });
    choices.append(button);
  }

  // Effort is not a parameter every model takes -- sending it to one that
  // doesn't is an API error, so the control disappears rather than pretending.
  const current = settings.models.find((m) => m.id === settings.model);
  const field = $("#effort-field");
  if (current && current.supports_effort) {
    field.hidden = false;
    const segmented = $("#effort");
    segmented.replaceChildren();
    for (const level of current.efforts) {
      const button = el("button", null, level);
      button.type = "button";
      button.setAttribute("aria-pressed", String(level === settings.effort));
      button.onclick = () => saveSettings({ effort: level });
      segmented.append(button);
    }
  } else {
    field.hidden = true;
    $("#effort-note").textContent = "";
  }
}

async function saveSettings(patch) {
  try {
    state.settings = await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    renderSettings();
    $("#settings-saved").textContent = "Saved.";
    setTimeout(() => { $("#settings-saved").textContent = ""; }, 1800);
  } catch (err) {
    toast(err.message);
  }
}

/* ── uploads ───────────────────────────────────────────────────── */

async function uploadFiles(files) {
  const topic = $("#upload-topic").value;
  if (!topic) { toast("Add a subject first"); return; }

  const log = $("#upload-log");
  for (const file of files) {
    const row = el("li");
    row.dataset.state = "busy";
    row.append(el("span", "name", file.name), el("span", "info", "adding…"));
    log.prepend(row);

    const form = new FormData();
    form.append("file", file);
    form.append("topic", topic);

    try {
      const result = await api("/api/upload", { method: "POST", body: form });
      row.dataset.state = "ok";
      const bits = [`${result.words.toLocaleString()} words`];
      if (result.images) bits.push(`${result.images} images`);
      if (result.updated) bits.push("replaced");
      row.querySelector(".info").textContent = bits.join(" · ");
      await refreshTopics(result.topic);
      if (result.note) openNote(result.note.id);
    } catch (err) {
      row.dataset.state = "err";
      row.querySelector(".info").textContent = err.message;
    }
  }
}

/* ── popovers and sheets ───────────────────────────────────────── */

function closePops() {
  for (const id of ["ext-pop", "avatar-pop"]) $("#" + id).hidden = true;
  $("#ext").setAttribute("aria-expanded", "false");
  $("#avatar").setAttribute("aria-expanded", "false");
}

function togglePop(popId, buttonId) {
  const pop = $("#" + popId);
  const open = pop.hidden;
  closePops();
  pop.hidden = !open;
  $("#" + buttonId).setAttribute("aria-expanded", String(open));
}

function openSheet(name) {
  closePops();
  if (name === "settings") renderSettings();
  $("#" + name).showModal();
}

/* ── boot ──────────────────────────────────────────────────────── */

async function refreshTopics(preferred) {
  const data = await api("/api/topics");
  state.topics = data.topics;
  const wanted = preferred || state.topic;
  const found = state.topics.find((t) => t.name === wanted);
  state.topic = found ? found.name : (state.topics[0]?.name ?? null);
  applyHue(state.topic || "");
  renderSubjects();
  renderRail();
}

function wire() {
  $("#ext").onclick = () => togglePop("ext-pop", "ext");
  $("#avatar").onclick = () => togglePop("avatar-pop", "avatar");

  document.addEventListener("click", (event) => {
    if (!event.target.closest(".pop") && !event.target.closest("#ext")
        && !event.target.closest("#avatar")) closePops();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closePops();
  });

  for (const button of document.querySelectorAll("[data-open]")) {
    button.onclick = () => openSheet(button.dataset.open);
  }

  $("#new-topic-form").onsubmit = async (event) => {
    event.preventDefault();
    const input = $("#new-topic");
    const name = input.value.trim();
    if (!name) return;
    try {
      const result = await api("/api/topics", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      input.value = "";
      await refreshTopics(result.topic.name);
      selectTopic(result.topic.name);
      closePops();
      if (result.action === "bound") {
        toast(`"${name}" goes into ${result.matched}`);
      }
    } catch (err) {
      toast(err.message);
    }
  };

  // Settings
  $("#api-key").onchange = (event) => {
    const value = event.target.value.trim();
    if (value) { saveSettings({ api_key: value }); event.target.value = ""; }
  };
  $("#key-clear").onclick = () => saveSettings({ api_key: null });
  $("#initials").onchange = (event) => saveSettings({ initials: event.target.value });
  $("#mirror-toggle").onchange = (event) =>
    saveSettings({ mirror_to_downloads: event.target.checked });
  $("#open-profile").onclick = (event) => {
    event.preventDefault();
    toast(`Your profile lives in ${state.settings.profile_dir}`);
  };

  // Uploads
  const drop = $("#drop");
  const input = $("#file-input");
  drop.onclick = () => input.click();
  input.onchange = () => { uploadFiles([...input.files]); input.value = ""; };
  for (const type of ["dragenter", "dragover"]) {
    drop.addEventListener(type, (e) => { e.preventDefault(); drop.dataset.over = "1"; });
  }
  for (const type of ["dragleave", "drop"]) {
    drop.addEventListener(type, (e) => { e.preventDefault(); drop.dataset.over = "0"; });
  }
  drop.addEventListener("drop", (e) => uploadFiles([...e.dataTransfer.files]));

  // Professor
  const shell = $(".shell");
  $("#prof-close").onclick = () => shell.classList.add("prof-hidden");
  $("#prof-open").onclick = () => {
    shell.classList.remove("prof-hidden");
    $("#prof-input").focus();
  };

  const field = $("#prof-input");
  field.addEventListener("input", () => {
    field.style.height = "auto";
    field.style.height = Math.min(field.scrollHeight, 128) + "px";
  });
  field.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      $("#prof-form").requestSubmit();
    }
  });
  $("#prof-form").onsubmit = (event) => {
    event.preventDefault();
    const question = field.value.trim();
    if (!question) return;
    field.value = "";
    field.style.height = "auto";
    ask(question);
  };
}

async function boot() {
  wire();
  try {
    state.settings = await api("/api/settings");
    $("#cfg-path").textContent = "~/.config/my-favorite-professor/config.json";
    renderSettings();
    await refreshTopics();
    const topic = state.topics.find((t) => t.name === state.topic);
    if (topic && topic.notes.length) openNote(topic.notes[0].id);
    else showEmptyReading();

    // First run: no key means nothing works, so say so straight away.
    if (!state.settings.has_key) openSheet("settings");
  } catch (err) {
    toast("Couldn't reach the server: " + err.message);
  }
}

boot();

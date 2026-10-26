"use strict";

const app = {state: null, strings: {}, lang: "en", view: "home", filterChannel: null, videoSearch: "", videoSort: "date", desc: true, busy: false, dirtyForm: false};
const $ = (selector) => document.querySelector(selector);
const e = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"})[c]);
const t = (key) => app.strings[key] || key;
const selected = (actual, expected) => String(actual ?? "") === String(expected ?? "") ? " selected" : "";
const checked = (value) => value ? " checked" : "";
const escAttr = (value) => e(value);
const dateText = (value) => value ? new Date(value).toLocaleString(app.lang) : "—";
const sizeText = (n) => n >= 1024 ** 3 ? (n / 1024 ** 3).toFixed(2) + " GB" : (n / 1024 ** 2).toFixed(1) + " MB";
const icon = {home: "⌂", videos: "▣", cloud: "☁", export: "↥", import: "↧", settings: "⚙"};

async function loadLocale(lang) {
  const response = await fetch(`/locale/${encodeURIComponent(lang)}`);
  if (!response.ok) throw Error("Cannot load language files");
  app.strings = await response.json();
  app.lang = lang;
  document.documentElement.lang = lang;
}

async function refresh(quiet=false) {
  const response = await fetch("/state");
  if (response.status === 401) { location.reload(); return; }
  if (!response.ok) throw Error("Cannot refresh application state");
  const nextState = await response.json();
  const unchanged = quiet && JSON.stringify(nextState) === JSON.stringify(app.state);
  app.state = nextState;
  if (app.state.settings.language && app.state.settings.language !== app.lang) await loadLocale(app.state.settings.language);
  if (unchanged) return;
  if (quiet && app.dirtyForm) renderNavigation();
  else render();
}

async function action(name, payload={}) {
  const response = await fetch("/action", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({action: name, payload})});
  const output = await response.json();
  if (!response.ok) throw Error(typeof output.detail === "string" ? output.detail : "Operation failed");
  return output.result;
}

async function perform(name, payload, message) {
  if (app.busy) return;
  app.busy = true;
  try { await action(name, payload); app.dirtyForm = false; await refresh(); toast(message || t("saved")); }
  catch(error) { toast(error.message, true); }
  finally { app.busy = false; }
}

function toast(message, error=false) {
  const element = $("#toast");
  element.textContent = message;
  element.className = error ? "show error" : "show";
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => element.className = "", 4000);
}

function pill(text, type="neutral") { return `<span class="pill ${type}">${e(text)}</span>`; }
function heading(kicker, name, description, right="") {
  return `<section class="page-heading"><div><div class="eyebrow">${e(kicker)}</div><h1>${e(name)}</h1><p>${e(description)}</p></div>${right}</section>`;
}
function panel(content, title="", desc="") {
  return `<section class="panel">${title ? `<div class="panel-heading"><h2>${e(title)}</h2>${desc ? `<p>${e(desc)}</p>` : ""}</div>` : ""}${content}</section>`;
}
function field(key, name, value="", type="text", extra="") {
  return `<label class="form-field"><span>${e(t(key))}</span><input name="${e(name)}" type="${type}" value="${escAttr(value)}" ${extra}></label>`;
}
function selectField(key, name, options, current) {
  return `<label class="form-field"><span>${e(t(key))}</span><select name="${e(name)}">${options.map(o => `<option value="${e(o[0])}"${selected(current,o[0])}>${e(o[1])}</option>`).join("")}</select></label>`;
}
function checkbox(key, name, value) {
  return `<label class="toggle-field"><span>${e(t(key))}</span><input type="checkbox" name="${e(name)}"${checked(value)}><span class="toggle-track"></span></label>`;
}
function navButton(label, view, symbol, active=false, secondary="") {
  return `<button class="nav-item${active ? " active" : ""}" data-nav="${e(view)}"><span class="nav-icon">${symbol}</span><span class="nav-name">${e(label)}</span>${secondary}</button>`;
}
function status(channel) {
  const info = app.state.statuses[channel.id] || {};
  return `<span class="badges">${!channel.enabled ? pill(t("disabled"), "red") : pill(t("enabled"), "green")}${info.recording ? pill(t("recording"), "purple") : ""}${info.live === true ? pill(t("live"), "green") : (info.live === false ? pill(t("offline")) : "")}</span>`;
}
function renderNavigation() {
  const profileMenu = app.state.profiles.map(p => `<div class="profile-node">
    ${navButton(p.name, `profile:${p.id}`, "◫", app.view === `profile:${p.id}`, p.enabled ? "" : pill(t("disabled"), "red"))}
    ${app.state.channels.filter(c => c.profile_id === p.id).map(c => `<button class="channel-node${app.view === `channel:${c.id}` ? " active" : ""}" data-nav="channel:${c.id}"><span class="branch-line"></span><span class="channel-name">@${e(c.username)}</span>${app.state.statuses[c.id]?.recording ? '<span class="nav-live">●</span>' : ''}${!c.enabled ? '<span class="nav-disabled">×</span>' : ''}</button>`).join("")}</div>`).join("");
  $("#navigation").innerHTML = navButton(t("home"), "home", icon.home, app.view === "home") +
    `<div class="nav-group-title">${e(t("profiles"))}<button type="button" data-click="newProfile" title="${e(t("newProfile"))}">+</button></div>` +
    `<div class="profile-list">${profileMenu}</div><div class="nav-group-title">${e(t("library"))}</div>` +
    ["videos", "cloud", "export", "import", "settings"].map(k => navButton(t(k), k, icon[k], app.view === k)).join("");
  $("#logoutButton").textContent = t("signOut");
  $("#refreshButton").textContent = "↻ " + t("refresh");
}

function renderHome() {
  const profiles = app.state.profiles.length, channels = app.state.channels.length, videos = app.state.videos.filter(v => v.exists).length;
  const recording = Object.values(app.state.statuses).filter(s => s.recording).length;
  const stats = [[t("profiles"),profiles,"◫"],[t("channels"),channels,"◉"],[t("recordings"),videos,"▣"],[t("activeNow"),recording,"◌"]];
  return heading(t("workspace"), t("overview"), t("homeIntro"), `<button class="btn primary" data-click="newProfile">+ ${e(t("newProfile"))}</button>`) +
    `<div class="stat-grid">${stats.map(a => `<div class="stat-card"><span class="stat-icon">${a[2]}</span><div class="stat-value">${a[1]}</div><div class="stat-label">${e(a[0])}</div></div>`).join("")}</div>` +
    panel(`<div class="list-stack">${app.state.channels.length ? app.state.channels.map(c => `<button class="stream-row" data-nav="channel:${c.id}"><span class="stream-avatar">${e(c.username[0]?.toUpperCase())}</span><span class="stream-meta"><strong>@${e(c.username)}</strong><small>${e(app.state.profiles.find(p => p.id === c.profile_id)?.name || "")} · ${e(c.platform)}</small></span>${status(c)}<span class="chevron">›</span></button>`).join("") : `<div class="empty">${e(t("noChannels"))}</div>`}</div>`, t("trackedChannels"), t("trackedIntro"));
}

function renderProfile(id) {
  const p = app.state.profiles.find(x => x.id === id);
  if (!p) return `<p>${e(t("notFound"))}</p>`;
  const accounts = [["", t("noAccount")], ...app.state.accounts.map(x => [x.id, `${x.alias} (${x.provider})`])];
  return heading(t("profileSettings"), p.name, t("profileIntro"), `<button class="btn ghost danger-text" data-click="deleteProfile" data-id="${id}">${e(t("deleteProfile"))}</button>`) +
    `<div class="two-column"><div>${panel(`<form data-form="profile" data-id="${id}" class="form-stack">
      ${field("profileName", "name", p.name, "text", "required maxlength=80")}
      ${checkbox("profileEnabled", "enabled", p.enabled)}
      ${checkbox("autoUpload", "auto_upload", p.auto_upload)}
      ${selectField("cloudAccount", "cloud_id", accounts, p.cloud_id)}
      ${field("cloudFolder", "cloud_folder", p.cloud_folder)}
      ${checkbox("deleteUploaded", "delete_uploaded", p.delete_uploaded)}
      ${field("deleteOld", "delete_older_hours", p.delete_older_hours ?? "", "number", "min=1 placeholder='—'")}
      <div class="form-actions"><button class="btn primary" type="submit">${e(t("saveChanges"))}</button></div></form>`, t("recordingPreferences"))}</div>
      <div>${panel(`<div class="info-stack"><div><span>${e(t("browserProfile"))}</span><strong>Firefox · ${e(p.directory)}</strong></div><div><span>${e(t("channels"))}</span><strong>${app.state.channels.filter(c => c.profile_id===id).length}</strong></div></div>
      <p class="help-text">${e(t("browserLoginInfo"))}</p>
      ${app.state.vnc_active === id ? `<div class="button-row"><a class="btn primary" href="https://${e(location.hostname)}:${app.state.vnc_port}/" target="_blank" rel="noopener">${e(t("openVnc"))} ↗</a><button class="btn ghost" data-click="finishVnc" data-id="${id}">${e(t("finishLogin"))}</button><button class="btn subtle" data-click="cancelVnc" data-id="${id}">${e(t("cancel"))}</button></div>` : `<button class="btn secondary" data-click="startVnc" data-id="${id}" ${app.state.vnc_active !== null ? "disabled" : ""}>◉ ${e(t("loginBrowser"))}</button>`}</div>`, t("browserSession"))}
      ${panel(`<form class="form-stack" data-form="channel-create" data-id="${id}">${selectField("platform", "platform", [["tiktok","TikTok"]], "tiktok")}${field("username", "username", "", "text", "required placeholder='@username'")}<button class="btn primary" type="submit">+ ${e(t("addChannel"))}</button></form>`, t("addChannel"))}</div></div>`;
}

function renderChannel(id) {
  const c = app.state.channels.find(x => x.id === id);
  if (!c) return `<p>${e(t("notFound"))}</p>`;
  const state = app.state.statuses[id] || {recording: false, manual: false, live: null, status: "idle"};
  const videos = app.state.videos.filter(v => v.channel_id === id && v.exists);
  return heading(e(c.platform).toUpperCase(), `@${c.username}`, t("channelIntro"), `<button class="btn ghost danger-text" data-click="deleteChannel" data-id="${id}">${e(t("deleteChannel"))}</button>`) +
   `<div class="two-column"><div>${panel(`<div class="status-row">${status(c)}<span class="muted">${e(t("status"))}: ${e(state.status)}</span></div>
     <div class="button-row">${state.recording ? (state.manual ? `<button class="btn danger" data-click="stopRecording" data-id="${id}">■ ${e(t("stopRecording"))}</button>` : `<button class="btn secondary" disabled>${e(t("automaticRecording"))}</button>`) : `<button class="btn primary" data-click="startRecording" data-id="${id}" ${state.status === "checking" ? "disabled" : ""}>● ${e(t("recordNow"))}</button>`}
     <button class="btn ghost" data-click="checkChannel" data-id="${id}">↻ ${e(t("checkLive"))}</button><button class="btn secondary" data-click="filterVideos" data-id="${id}">${e(t("viewVideos"))}</button></div>
     ${state.error ? `<p class="error">${e(state.error)}</p>` : ""}`, t("liveStatus"))}
     ${panel(`<form class="form-stack" data-form="channel" data-id="${id}">${field("username", "username", c.username,"text","required")}${field("platform", "platform", c.platform,"text","disabled")}
       ${checkbox("channelEnabled", "enabled", c.enabled)}${checkbox("autoRecord", "auto_record", c.auto_record)}<div class="form-actions"><button class="btn primary" type="submit">${e(t("saveChanges"))}</button></div></form>`, t("channelSettings"))}</div>
     <div>${panel(`<div class="stat-value">${videos.length}</div><p class="muted">${e(t("localVideos"))}</p><div class="divider"></div><p class="muted">${e(t("lastVideo"))}: ${videos.length ? e(dateText(videos[0].created_at)) : "—"}</p>`, t("statistics"))}
     ${panel(`<div class="info-stack"><div><span>${e(t("platform"))}</span><strong>${e(c.platform)}</strong></div><div><span>${e(t("profile"))}</span><strong>${e(app.state.profiles.find(p=>p.id===c.profile_id)?.name)}</strong></div></div>`, t("details"))}</div></div>`;
}

function videoRows() {
  let items = app.state.videos.filter(v => (!app.filterChannel || v.channel_id === app.filterChannel) && (!app.videoSearch || `${v.name} ${v.username}`.toLowerCase().includes(app.videoSearch.toLowerCase())));
  const compare = {name: v => v.name.toLowerCase(), date: v => v.created_at, channel: v => v.username.toLowerCase(), size: v => v.size}[app.videoSort];
  items.sort((a,b) => ((compare(a) < compare(b)) ? -1 : (compare(a) > compare(b) ? 1 : 0)) * (app.desc ? -1 : 1));
  return items.length ? items.map(v => `<tr><td><div class="filename">▣ <strong>${e(v.name)}</strong></div><small>${e(v.profile_name)} / ${e(v.platform)}</small></td><td>@${e(v.username)}</td><td>${e(dateText(v.created_at))}</td><td>${e(sizeText(v.size))}</td><td class="actions-cell">${v.exists ? `<button class="small-button" data-click="playVideo" data-id="${v.id}">${e(t("play"))}</button><a class="small-button" href="/videos/${v.id}/download">${e(t("download"))}</a>` : pill(t("missing"),"red")}</td></tr>`).join("") : `<tr><td colspan="5" class="empty">${e(t("noVideos"))}</td></tr>`;
}
function renderVideos() {
  const filter = app.filterChannel ? app.state.channels.find(x => x.id === app.filterChannel) : null;
  return heading(t("library"), t("videos"), t("videosIntro"), filter ? `<button class="btn ghost" data-click="clearFilter">${e(t("clearFilter"))} · @${e(filter.username)}</button>` : "") +
    panel(`<div class="filterbar"><input id="videoSearch" value="${e(app.videoSearch)}" placeholder="${e(t("searchVideos"))}" aria-label="${e(t("searchVideos"))}"><select id="videoSort"><option value="date"${selected(app.videoSort,"date")}>${e(t("date"))}</option><option value="name"${selected(app.videoSort,"name")}>${e(t("name"))}</option><option value="channel"${selected(app.videoSort,"channel")}>${e(t("channel"))}</option><option value="size"${selected(app.videoSort,"size")}>${e(t("size"))}</option></select><button class="btn ghost" data-click="sortOrder">${app.desc ? "↓" : "↑"}</button></div>
    <div class="table-wrap"><table><thead><tr><th>${e(t("file"))}</th><th>${e(t("channel"))}</th><th>${e(t("date"))}</th><th>${e(t("size"))}</th><th></th></tr></thead><tbody id="videoRows">${videoRows()}</tbody></table></div>`, t("recordedFiles"));
}
function renderCloud() {
  return heading(t("integrations"), t("cloud"), t("cloudIntro")) + `<div class="two-column"><div>${panel(app.state.accounts.length ? `<div class="list-stack">${app.state.accounts.map(a => `<div class="account-row"><span class="cloud-symbol">☁</span><div><strong>${e(a.alias)}</strong><small>${e(a.email)} · ${e(a.provider.toUpperCase())}</small></div><button class="small-button danger-text" data-click="deleteAccount" data-id="${a.id}">${e(t("delete"))}</button></div>`).join("")}</div>` : `<div class="empty">${e(t("noAccounts"))}</div>`, t("connectedAccounts"))}</div><div>${panel(`<form class="form-stack" data-form="cloud"><div class="provider-logo">MEGA <small>${e(t("storageProvider"))}</small></div>${field("alias","alias","","text","required")}${field("email","email","","email","required")}${field("password","password","","password","required autocomplete='off'")}<button class="btn primary" type="submit">+ ${e(t("addAccount"))}</button></form>`, t("addAccount"))}</div></div>`;
}
function renderExport() {
  return heading(t("dataManagement"), t("export"), t("exportIntro")) + panel(`<form class="form-stack narrow" data-form="export"><p>${e(t("exportInfo"))}</p>${field("encryptionPassphrase","passphrase","","password","required")}<button class="btn primary" type="submit">↥ ${e(t("downloadBackup"))}</button></form>`, t("encryptedBackup"));
}
function renderImport() {
  return heading(t("dataManagement"), t("import"), t("importIntro")) + panel(`<form class="form-stack narrow" data-form="import"><div class="warning">⚠ ${e(t("importWarning"))}</div><label class="form-field"><span>${e(t("backupFile"))}</span><input name="file" type="file" accept=".zip" required></label>${field("encryptionPassphrase","passphrase","","password","required")}<button class="btn danger" type="submit">↧ ${e(t("replaceData"))}</button></form>`, t("restoreBackup"));
}
function renderSettings() {
  const s = app.state.settings;
  return heading(t("preferences"), t("settings"), t("settingsIntro")) + panel(`<form class="form-stack narrow" data-form="settings">${selectField("language","language",[["en","English"],["es","Español"],["pt","Português"]],s.language)}
    <label class="form-field"><span>${e(t("encryptionPassphrase"))}</span><div class="input-tools"><input id="passphraseField" type="password" name="passphrase" value="${e(s.passphrase)}" autocomplete="off"><button type="button" class="small-button" data-click="togglePassphrase">${e(t("show"))}</button><button type="button" class="small-button" data-click="copyPassphrase">${e(t("copy"))}</button></div></label>
    <p class="help-text">${e(t("passphraseWarning"))}</p><button class="btn primary" type="submit">${e(t("saveChanges"))}</button></form>`, t("generalSettings"));
}

function render() {
  if (!app.state) return;
  renderNavigation();
  const [part, id] = app.view.split(":");
  const pages = {home: renderHome, videos: renderVideos, cloud: renderCloud, export: renderExport, import: renderImport, settings: renderSettings};
  $("#content").innerHTML = part === "profile" ? renderProfile(Number(id)) : part === "channel" ? renderChannel(Number(id)) : (pages[part] || renderHome)();
  $("#content").querySelectorAll('[data-click="finishVnc"]').forEach(button => {
    button.addEventListener("click", async event => {
      event.preventDefault();
      event.stopPropagation();
      if (app.busy) { console.warn("vnc.finish ignored: another operation is running"); return; }
      button.disabled = true;
      try { await perform("vnc.finish", {id: Number(button.dataset.id)}, t("loginSaved")); }
      finally { if (button.isConnected) button.disabled = false; }
    });
  });
  $("#currentLocation").textContent = part === "profile" ? t("profiles") : part === "channel" ? t("channels") : t(part === "home" ? "overview" : part);
  $("#footerStatus").textContent = t("localRecorder");
  $("#refreshStatus").textContent = "● " + t("connected");
}

function formObject(form) {
  const result = Object.fromEntries(new FormData(form).entries());
  for (const checkbox of form.querySelectorAll('input[type="checkbox"]')) result[checkbox.name] = checkbox.checked;
  return result;
}

async function formSubmit(form) {
  const id = Number(form.dataset.id);
  const data = formObject(form);
  if (form.dataset.form === "profile") {
    data.id = id;
    if (!data.cloud_id) data.cloud_id = null;
    await perform("profile.update", data);
  } else if (form.dataset.form === "channel-create") {
    data.profile_id = id;
    await perform("channel.create", data, t("channelAdded"));
    form.reset();
  } else if (form.dataset.form === "channel") {
    data.id = id;
    delete data.platform;
    await perform("channel.update", data);
  } else if (form.dataset.form === "cloud") {
    await perform("account.create", data);
    form.reset();
  } else if (form.dataset.form === "settings") {
    await perform("settings.update", data);
  } else if (form.dataset.form === "export") {
    const response = await fetch("/export", {method: "POST", headers: {"Content-Type":"application/json"},body: JSON.stringify({passphrase: data.passphrase})});
    if (!response.ok) { const err = await response.json(); throw Error(err.detail); }
    const href = URL.createObjectURL(await response.blob());
    const link = document.createElement("a"); link.href = href; link.download = "oso-stream-record-backup.zip"; link.click();
    setTimeout(() => URL.revokeObjectURL(href), 10000);
    toast(t("backupDownloaded"));
  } else if (form.dataset.form === "import") {
    if (!confirm(t("confirmImport"))) return;
    const upload = new FormData(form);
    upload.set("confirm", "REPLACE");
    const response = await fetch("/import", {method:"POST",body:upload});
    if (!response.ok) { const err = await response.json(); throw Error(err.detail); }
    app.view = "home";
    app.filterChannel = null;
    await refresh();
    toast(t("importSuccess"));
  }
}

async function clickAction(button) {
  const name = button.dataset.click;
  const id = Number(button.dataset.id);
  if (name === "newProfile") {
    const title = prompt(t("profileName"));
    if (title?.trim()) await perform("profile.create", {name: title.trim()});
  } else if (name === "deleteProfile" || name === "deleteChannel" || name === "deleteAccount") {
    if (!confirm(t("confirmDelete"))) return;
    await perform(({deleteProfile:"profile.delete",deleteChannel:"channel.delete",deleteAccount:"account.delete"})[name], {id});
    app.view = "home";
    render();
  } else if (name === "startRecording") await perform("channel.start", {id}, t("checkingLive"));
  else if (name === "stopRecording") await perform("channel.stop", {id});
  else if (name === "checkChannel") await perform("channel.check", {id}, t("checkingLive"));
  else if (name === "startVnc") await perform("vnc.start", {id}, t("vncReady"));
  else if (name === "finishVnc") await perform("vnc.finish", {id}, t("loginSaved"));
  else if (name === "cancelVnc") await perform("vnc.cancel", {id});
  else if (name === "filterVideos") {app.filterChannel = id; app.view = "videos"; render();}
  else if (name === "clearFilter") {app.filterChannel = null; render();}
  else if (name === "sortOrder") {app.desc = !app.desc; render();}
  else if (name === "togglePassphrase") { const input = $("#passphraseField"); input.type = input.type === "password" ? "text" : "password"; }
  else if (name === "copyPassphrase") {await navigator.clipboard.writeText($("#passphraseField").value);toast(t("copied"));}
  else if (name === "playVideo") {
    const video = app.state.videos.find(v => v.id === id);
    const windowNode = document.createElement("dialog");
    windowNode.className = "modal player-modal";
    windowNode.innerHTML = `<div class="player-title"><strong>${e(video.name)}</strong><button class="small-button" data-close-player>✕</button></div><video controls autoplay playsinline src="/videos/${id}/watch"></video><p class="muted">${e(t("playbackNote"))}</p>`;
    document.body.appendChild(windowNode);
    windowNode.querySelector("[data-close-player]").addEventListener("click", () => windowNode.close());
    windowNode.addEventListener("close", () => {windowNode.querySelector("video").pause(); windowNode.remove();});
    windowNode.showModal();
  }
}

document.addEventListener("click", async event => {
  const node = event.target.closest("[data-nav], [data-click]");
  if (node?.dataset.nav) { app.dirtyForm = false; app.view = node.dataset.nav; render(); }
  else if (node?.dataset.click) { try {await clickAction(node);} catch(error) {toast(error.message,true);} }
});
document.addEventListener("submit", async event => {
  const form = event.target.closest("[data-form]");
  if (!form) return;
  event.preventDefault();
  if (app.busy) return;
  try {await formSubmit(form);} catch(error) {toast(error.message,true);}
});
document.addEventListener("input", event => {
  if (event.target.id === "videoSearch") {app.videoSearch = event.target.value; $("#videoRows").innerHTML = videoRows();}
  else if (event.target.closest("form[data-form]")) app.dirtyForm = true;
});
document.addEventListener("change", event => {
  if (event.target.id === "videoSort") {app.videoSort = event.target.value; $("#videoRows").innerHTML = videoRows();}
});
$("#refreshButton").addEventListener("click", () => refresh().catch(err => toast(err.message,true)));
document.querySelectorAll("[data-lang]").forEach(button => button.addEventListener("click", async () => {
  try {await action("settings.update",{language:button.dataset.lang}); $("#languageDialog").close();await refresh();}
  catch(error) {toast(error.message,true);}
}));

(async function initialize() {
  try {
    await loadLocale("en");
    await refresh();
    if (!app.state.settings.language) $("#languageDialog").showModal();
    setInterval(() => {if (!document.hidden && !app.busy && $("#languageDialog").open === false) refresh(true).catch(() => $("#refreshStatus").textContent = "● " + t("disconnected"));}, 10000);
  } catch(error) {$("#content").textContent = error.message;}
})();

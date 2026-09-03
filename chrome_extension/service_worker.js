importScripts("local_config.js");
const ENDPOINT = "http://127.0.0.1:8765";
const TOKEN = globalThis.JARVIS_BRIDGE_TOKEN;
const headers = {"Content-Type": "application/json", "X-Jarvis-Bridge": TOKEN};

chrome.alarms.create("jarvis-sync", {periodInMinutes: 0.05});
chrome.alarms.onAlarm.addListener(sync);
chrome.tabs.onActivated.addListener(sync);
chrome.tabs.onUpdated.addListener((_id, info) => { if (info.status === "complete") sync(); });

async function activeTab() {
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  return tab;
}

function snapshotPage() {
  const visible = el => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && r.bottom >= 0 && r.top <= innerHeight;
  };
  const selector = el => {
    if (el.id) return `#${CSS.escape(el.id)}`;
    const tag = el.tagName.toLowerCase();
    const name = el.getAttribute("name");
    if (name) return `${tag}[name="${CSS.escape(name)}"]`;
    return tag;
  };
  const nodes = [...document.querySelectorAll("a,button,input,textarea,select,[role=button],[role=link]")]
    .filter(visible).slice(0, 250).map(el => ({
      tag: el.tagName.toLowerCase(), selector: selector(el),
      text: (el.innerText || el.getAttribute("aria-label") || el.placeholder || "").trim().slice(0, 300),
      type: el.type || "", disabled: !!el.disabled,
      sensitive: el.type === "password" || /password|otp|card|cvv/i.test(`${el.name} ${el.id} ${el.autocomplete}`)
    }));
  return {title: document.title, url: location.href, text: document.body.innerText.slice(0, 12000), elements: nodes};
}

function executeCommand(command) {
  if (!command) return {ok: true};
  const findText = text => [...document.querySelectorAll("a,button,[role=button],[role=link]")]
    .find(el => (el.innerText || el.getAttribute("aria-label") || "").trim().toLowerCase().includes(text.toLowerCase()));
  let el = null;
  if (command.action === "click_text") el = findText(command.target);
  if (["click_selector", "set_value", "focus"].includes(command.action)) el = document.querySelector(command.target);
  if (command.action === "navigate") { location.href = command.target; return {ok: true}; }
  if (command.action === "scroll") { scrollBy(0, Number(command.value || 600)); return {ok: true}; }
  if (!el) return {ok: false, error: "element not found"};
  if (el.type === "password" || /password|otp|card|cvv/i.test(`${el.name} ${el.id} ${el.autocomplete}`)) return {ok: false, error: "sensitive field blocked"};
  if (command.action.startsWith("click")) el.click();
  if (command.action === "focus") el.focus();
  if (command.action === "set_value") {
    el.focus(); el.value = command.value;
    el.dispatchEvent(new Event("input", {bubbles: true}));
    el.dispatchEvent(new Event("change", {bubbles: true}));
  }
  return {ok: true};
}

async function sync() {
  try {
    const tab = await activeTab();
    if (!tab?.id || !/^https?:/.test(tab.url || "")) return;
    const [{result}] = await chrome.scripting.executeScript({target: {tabId: tab.id}, func: snapshotPage});
    await fetch(`${ENDPOINT}/snapshot`, {method: "POST", headers, body: JSON.stringify({...result, tab_id: tab.id})});
    const response = await fetch(`${ENDPOINT}/command`, {headers});
    const {command} = await response.json();
    if (command) {
      let result;
      try {
        if (command.action === "open_tab") result = {ok: true, tab: await chrome.tabs.create({url: command.target})};
        else if (command.action === "close_tab") { await chrome.tabs.remove(Number(command.target || tab.id)); result = {ok: true}; }
        else if (command.action === "activate_tab") { result = {ok: true, tab: await chrome.tabs.update(Number(command.target), {active: true})}; }
        else if (command.action === "list_tabs") result = {ok: true, tabs: (await chrome.tabs.query({currentWindow: true})).map(t => ({id:t.id,title:t.title,url:t.url,active:t.active}))};
        else if (command.action === "downloads") result = {ok: true, downloads: (await chrome.downloads.search({limit: 30})).map(d => ({id:d.id,filename:d.filename,state:d.state,url:d.url}))};
        else { const [{result: pageResult}] = await chrome.scripting.executeScript({target: {tabId: tab.id}, func: executeCommand, args: [command]}); result = pageResult; }
      } catch (error) { result = {ok: false, error: String(error)}; }
      await fetch(`${ENDPOINT}/result`, {method: "POST", headers, body: JSON.stringify({...result, request_id: command.request_id})});
    }
  } catch (_) {}
}

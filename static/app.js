'use strict';
const $ = id => document.getElementById(id);
const state = { items: [], used: 0, quota: 20 * 1024 ** 3, filter: 'all', mode: 'file', files: [], busy: false, xhr: null, text: '', deleteId: null };
let toastTimer;
function toast(message, error = false) { $('toast').textContent = message; $('toast').classList.toggle('error-toast', error); $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('toast').hidden = true; }, 4200); }
function size(bytes) { if (!bytes) return '0 B'; const units = ['B', 'KB', 'MB', 'GB']; const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), 3); return `${(bytes / 1024 ** index).toLocaleString('zh-CN', { maximumFractionDigits: index ? 2 : 0 })} ${units[index]}`; }
function timeLabel(timestamp) { const date = new Date(timestamp * 1000); const now = new Date(); const day = date.toLocaleDateString('zh-CN'); const prefix = day === now.toLocaleDateString('zh-CN') ? '今天' : `${date.getMonth() + 1}月${date.getDate()}日`; return `${prefix} ${date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })}`; }
function loginView() { $('workspace').hidden = true; $('login-view').hidden = false; for (const d of document.querySelectorAll('dialog[open]')) d.close(); state.items = []; $('items-grid').replaceChildren(); $('preview-body').textContent = ''; $('password').value = ''; }
async function api(url, options = {}) {
  const response = await fetch(url, { credentials: 'same-origin', ...options, headers: { 'X-Requested-With': 'FileTransfer', ...options.headers } });
  let result; try { result = await response.json(); } catch { result = {}; }
  if (response.status === 401 && url !== '/api/login') loginView();
  if (!response.ok) throw new Error(result.error || `请求失败（${response.status}），请稍后重试。`);
  return result;
}
const json = body => ({ headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
async function refresh({ quiet = false } = {}) {
  if (!quiet) $('loading').hidden = false;
  $('load-error').hidden = true;
  try {
    const data = await api('/api/items');
    Object.assign(state, { items: data.items, used: data.used, quota: data.quota });
    $('account-name').textContent = data.username;
    $('login-view').hidden = true; $('workspace').hidden = false;
    const percent = state.used / state.quota * 100;
    $('storage-used').textContent = size(state.used); $('storage-total').textContent = size(state.quota);
    $('footer-usage').textContent = `已使用 ${size(state.used)} / ${size(state.quota)}`;
    $('storage-percent').textContent = `${percent > 0 && percent < 1 ? '< 1' : Math.round(percent)}%`;
    $('storage-bar').value = percent;
    $('available-space').textContent = `可用空间：${size(Math.max(0, state.quota - state.used))} / ${size(state.quota)}`;
    render(); return true;
  } catch (error) {
    if (!$('workspace').hidden) { $('load-error').hidden = false; if (quiet) toast(error.message, true); }
    else if ($('login-view').hidden) { loginView(); $('login-error').textContent = '无法连接服务器，请检查网络后重试。'; }
    return false;
  } finally { $('loading').hidden = true; }
}
function el(tag, className, text) { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; }
function action(label, symbol, onClick, className = '') { const button = el('button', className, symbol); button.title = label; button.setAttribute('aria-label', label); button.addEventListener('click', onClick); return button; }
function render() {
  const query = $('search').value.trim().toLocaleLowerCase();
  const filtered = state.items.filter(item => (state.filter === 'all' || item.kind === state.filter) && `${item.name} ${item.preview}`.toLocaleLowerCase().includes(query));
  const files = state.items.filter(i => i.kind === 'file').length;
  $('count-all').textContent = state.items.length; $('count-file').textContent = files; $('count-text').textContent = state.items.length - files;
  $('result-count').textContent = `${filtered.length} 项内容`;
  const grid = $('items-grid'); grid.replaceChildren();
  for (const item of filtered) {
    const card = el('article', 'item-card'); const heading = el('div', 'card-heading');
    const extension = item.name.includes('.') ? item.name.split('.').pop().toLowerCase() : 'file';
    let badgeClass = 'file-badge';
    if (item.kind === 'text') badgeClass += ' text-badge';
    else if (['png', 'jpg', 'jpeg', 'webp', 'gif', 'heic', 'svg'].includes(extension)) badgeClass += ' image-badge';
    else if (['zip', 'rar', '7z', 'gz', 'tar'].includes(extension)) badgeClass += ' archive-badge';
    else if (extension === 'pdf') badgeClass += ' pdf-badge';
    heading.append(el('div', badgeClass, item.kind === 'text' ? 'Aa' : extension.slice(0, 5)), el('span', 'card-type', item.kind === 'text' ? 'TEXT NOTE' : 'FILE'));
    const title = el(item.kind === 'text' ? 'button' : 'h2', item.kind === 'text' ? 'item-name card-open' : 'item-name', item.name);
    title.title = item.name;
    if (item.kind === 'text') title.addEventListener('click', () => openText(item));
    card.append(heading, title);
    if (item.kind === 'text') card.append(el('p', 'item-preview', item.preview));
    else card.append(el('p', 'item-file-info', `${size(item.size)} · ${extension.toUpperCase().slice(0, 12)} 文件`));
    card.append(el('div', 'card-spacer'));
    const bottom = el('div', 'card-bottom'); const timestamp = el('time', 'item-time', timeLabel(item.created_at)); timestamp.dateTime = new Date(item.created_at * 1000).toISOString();
    timestamp.title = new Date(item.created_at * 1000).toLocaleString('zh-CN');
    const actions = el('div', 'card-actions');
    if (item.kind === 'text') actions.append(action('查看文本', '≡', () => openText(item)), action('复制文本', '⧉', () => copyItem(item)));
    const download = el('a', '', '↓'); download.href = `/api/items/${item.id}/download`; download.download = ''; download.title = '下载'; download.setAttribute('aria-label', `下载 ${item.name}`); actions.append(download);
    actions.append(action('删除', '×', () => askDelete(item), 'delete-action'));
    bottom.append(timestamp, actions); card.append(bottom); grid.append(card);
  }
  $('empty').hidden = filtered.length > 0;
  const noMatch = query || (state.items.length && state.filter !== 'all');
  $('empty-title').textContent = noMatch ? '这里暂时没有匹配的内容。' : '给下一台设备，留点内容。';
  $('empty-copy').textContent = noMatch ? '换个关键词，或上传一份新内容。' : '上传一个文件，或放下一段文字。\n无论手机还是电脑，登录就能接着用。';
  $('empty-upload').textContent = noMatch ? '上传内容 ↗' : '上传第一份内容 ↗';
}
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); }
  catch {
    const textarea = el('textarea'); textarea.value = text; textarea.setAttribute('readonly', '');
    const parent = [...document.querySelectorAll('dialog[open]')].pop() || document.body;
    parent.append(textarea); textarea.select(); const copied = document.execCommand('copy'); textarea.remove();
    if (!copied) throw new Error('浏览器未允许复制，请打开文本后手动选择复制。');
  }
  toast('已复制到当前设备的剪贴板。');
}
async function copyItem(item) { try { const data = await api(`/api/items/${item.id}/text`); await copyText(data.text); } catch (error) { toast(error.message, true); } }
async function openText(item) {
  try { const data = await api(`/api/items/${item.id}/text`); state.text = data.text; $('preview-title').textContent = item.name; $('preview-body').textContent = data.text; $('preview-download').href = `/api/items/${item.id}/download`; $('text-dialog').showModal(); }
  catch (error) { toast(error.message, true); }
}
function askDelete(item) { state.deleteId = item.id; $('delete-name').textContent = item.name; $('delete-error').textContent = ''; $('delete-dialog').showModal(); }
function setMode(mode) {
  state.mode = mode; $('file-pane').hidden = mode !== 'file'; $('text-pane').hidden = mode !== 'text';
  for (const name of ['file', 'text']) { $(`${name}-tab`).classList.toggle('active', mode === name); $(`${name}-tab`).setAttribute('aria-selected', String(mode === name)); }
  $('submit-upload').textContent = mode === 'file' ? '开始上传 ↑' : '保存文本 ↗'; $('upload-error').textContent = '';
}
function newUpload() { if (state.busy) return; $('upload-error').textContent = ''; $('upload-progress').hidden = true; $('upload-dialog').showModal(); }
function chooseFiles(files) { for (const file of files) if (!state.files.some(f => f.name === file.name && f.size === file.size && f.lastModified === file.lastModified)) state.files.push(file); renderSelected(); }
function renderSelected() {
  $('selected-files').replaceChildren();
  for (const [index, file] of state.files.entries()) {
    const row = el('div', 'selected-file'); row.append(el('span', '', file.name), el('span', '', size(file.size)), action('移除文件', '×', () => { state.files.splice(index, 1); renderSelected(); }, 'icon-button')); $('selected-files').append(row);
  }
}
function setBusy(busy) {
  state.busy = busy;
  for (const node of $('upload-dialog').querySelectorAll('input,textarea,button')) node.disabled = busy;
  $('cancel-upload').disabled = false; $('cancel-upload').textContent = busy ? '停止上传' : '取消';
}
function uploadFile(file, index, total) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest(); state.xhr = xhr;
    xhr.open('POST', `/api/files?name=${encodeURIComponent(file.name)}`);
    xhr.setRequestHeader('X-Requested-With', 'FileTransfer'); xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    $('progress-label').textContent = `上传 ${index + 1}/${total}：${file.name}`; $('progress-value').textContent = '0%'; $('upload-bar').value = 0;
    xhr.upload.onprogress = event => { if (event.lengthComputable) { const p = Math.round(event.loaded / event.total * 100); $('upload-bar').value = p; $('progress-value').textContent = p === 100 ? '正在保存…' : `${p}%`; } };
    xhr.onload = () => { state.xhr = null; if (xhr.status >= 200 && xhr.status < 300) resolve(); else { let data = {}; try { data = JSON.parse(xhr.responseText); } catch {} if (xhr.status === 401) loginView(); reject(new Error(data.error || `上传失败（${xhr.status}），请检查网络后重试。`)); } };
    xhr.onerror = () => { state.xhr = null; reject(new Error('网络连接中断。已完成的文件已保留，请重试未完成的文件。')); };
    xhr.onabort = () => { state.xhr = null; reject(new Error('上传已停止，已完成的文件已保留。')); };
    xhr.send(file);
  });
}
async function submitUpload() {
  if (state.busy) return;
  $('upload-error').textContent = '';
  if (state.mode === 'text' && !$('text-body').value.trim()) { $('upload-error').textContent = '先写点内容再保存吧。'; $('text-body').focus(); return; }
  if (state.mode === 'file' && !state.files.length) { $('upload-error').textContent = '请先选择要上传的文件。'; return; }
  const totalBytes = state.mode === 'file' ? state.files.reduce((sum, f) => sum + f.size, 0) : new Blob([$('text-body').value]).size;
  if (totalBytes > state.quota - state.used) { $('upload-error').textContent = '剩余空间不足，请减少文件或先删除一些内容。'; return; }
  if (state.mode === 'text' && totalBytes > 1024 ** 2) { $('upload-error').textContent = '单条文本最多支持 1MB。'; return; }
  setBusy(true); let succeeded = 0;
  try {
    if (state.mode === 'text') { await api('/api/text', { method: 'POST', ...json({ title: $('text-title').value, text: $('text-body').value }) }); $('text-title').value = ''; $('text-body').value = ''; $('text-count').textContent = '0 字'; }
    else {
      $('upload-progress').hidden = false; const queue = [...state.files];
      for (const [index, file] of queue.entries()) { await uploadFile(file, index, queue.length); state.files = state.files.filter(f => f !== file); succeeded++; }
      $('file-input').value = ''; renderSelected();
    }
    $('upload-dialog').close(); toast(state.mode === 'text' ? '文本已保存，其他设备现在就能打开。' : `${succeeded} 个文件已上传。`);
    await refresh({ quiet: true });
  } catch (error) { $('upload-error').textContent = error.message; if (succeeded) await refresh({ quiet: true }); renderSelected(); }
  finally { setBusy(false); $('upload-progress').hidden = true; }
}
$('login-form').addEventListener('submit', async event => {
  event.preventDefault(); $('login-error').textContent = ''; $('login-button').disabled = true;
  try { await api('/api/login', { method: 'POST', ...json({ username: $('username').value.trim(), password: $('password').value }) }); $('password').value = ''; await refresh(); }
  catch (error) { $('login-error').textContent = error.message; }
  finally { $('login-button').disabled = false; }
});
$('logout').addEventListener('click', async () => { try { await api('/api/logout', { method: 'POST' }); loginView(); } catch (error) { toast(error.message, true); } });
$('filters').addEventListener('click', event => { const button = event.target.closest('[data-filter]'); if (!button) return; state.filter = button.dataset.filter; for (const b of $('filters').children) b.classList.toggle('active', b === button); $('page-title').replaceChildren(document.createTextNode({ all: '全部内容', file: '我的文件', text: '我的文本' }[state.filter]), el('span', 'heading-dot', '.')); render(); });
$('search').addEventListener('input', render);
$('refresh').addEventListener('click', () => refresh({ quiet: true })); $('retry').addEventListener('click', () => refresh());
$('new-upload').addEventListener('click', newUpload); $('empty-upload').addEventListener('click', newUpload);
$('file-tab').addEventListener('click', () => setMode('file')); $('text-tab').addEventListener('click', () => setMode('text'));
$('text-body').addEventListener('input', () => { $('text-count').textContent = `${$('text-body').value.length.toLocaleString('zh-CN')} 字`; });
$('file-input').addEventListener('change', event => { chooseFiles(event.target.files); event.target.value = ''; });
for (const name of ['dragenter', 'dragover']) $('dropzone').addEventListener(name, event => { event.preventDefault(); if (!state.busy) $('dropzone').classList.add('dragging'); });
for (const name of ['dragleave', 'drop']) $('dropzone').addEventListener(name, event => { event.preventDefault(); $('dropzone').classList.remove('dragging'); });
$('dropzone').addEventListener('drop', event => { if (!state.busy) chooseFiles(event.dataTransfer.files); });
$('submit-upload').addEventListener('click', submitUpload);
$('cancel-upload').addEventListener('click', () => { if (state.busy) { if (state.xhr) state.xhr.abort(); return; } $('upload-dialog').close(); });
for (const button of document.querySelectorAll('.close-dialog')) button.addEventListener('click', () => button.closest('dialog').close());
$('upload-dialog').addEventListener('cancel', event => { if (state.busy) { event.preventDefault(); if (state.xhr) state.xhr.abort(); } });
$('preview-copy').addEventListener('click', () => copyText(state.text).catch(error => toast(error.message, true)));
$('cancel-delete').addEventListener('click', () => $('delete-dialog').close());
$('confirm-delete').addEventListener('click', async () => { $('confirm-delete').disabled = true; try { await api(`/api/items/${state.deleteId}`, { method: 'DELETE' }); $('delete-dialog').close(); toast('已删除，空间已释放。'); await refresh({ quiet: true }); } catch (error) { $('delete-error').textContent = error.message; } finally { $('confirm-delete').disabled = false; } });
document.addEventListener('keydown', event => { if (event.key === '/' && !$('workspace').hidden && !document.querySelector('dialog[open]') && !['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) { event.preventDefault(); $('search').focus(); } });
document.addEventListener('visibilitychange', () => { if (!document.hidden && !$('workspace').hidden && !state.busy && !document.querySelector('dialog[open]')) refresh({ quiet: true }); });
setInterval(() => { if (!document.hidden && !$('workspace').hidden && !state.busy && !document.querySelector('dialog[open]')) refresh({ quiet: true }); }, 30000);
refresh();

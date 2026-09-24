const root = document.getElementById('app');
const toastRegion = document.getElementById('toastRegion');

const glyphs = {
  activity: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
  arrow: '<path d="M5 12h14m-6-6 6 6-6 6"/>',
  back: '<path d="m15 18-6-6 6-6"/>',
  bell: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9ZM10 21h4"/>',
  bolt: '<path d="m13 2-9 12h7l-1 8 10-12h-7l1-8Z"/>',
  bot: '<rect x="4" y="7" width="16" height="13" rx="3"/><path d="M12 7V4m-2 0h4M8 13h.01M16 13h.01M9 17h6"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18"/>',
  chart: '<path d="M3 3v18h18M7 16l4-5 3 3 5-7"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  chevron: '<path d="m9 18 6-6-6-6"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  close: '<path d="M18 6 6 18M6 6l12 12"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
  edit: '<path d="m16 4 4 4M4 20l4.5-1 11-11a2.8 2.8 0 0 0-4-4l-11 11L4 20Z"/>',
  external: '<path d="M13 5h6v6M19 5l-9 9"/><path d="M19 13v5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/>',
  filter: '<path d="M4 7h16M7 12h10m-7 5h4"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 4.5 1.5c-.5.6-2 1.2-2 2.5M12 17h.01"/>',
  inbox: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 13h5l2 3h4l2-3h5"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5m0-8h.01"/>',
  layers: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  link: '<path d="M10 13a5 5 0 0 0 7.1 0l2-2a5 5 0 0 0-7.1-7.1l-1.2 1.2"/><path d="M14 11a5 5 0 0 0-7.1 0l-2 2A5 5 0 0 0 12 20.1l1.2-1.2"/>',
  lock: '<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  message: '<path d="M20 11.5a8.5 8.5 0 0 1-8.5 8.5 9 9 0 0 1-3.5-.7L3 21l1.7-5A8.5 8.5 0 1 1 20 11.5Z"/>',
  more: '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  refresh: '<path d="M20 11a8 8 0 0 0-14-5L3 9m0-5v5h5M4 13a8 8 0 0 0 14 5l3-3m0 5v-5h-5"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  send: '<path d="m22 2-7 20-4-9-9-4 20-7ZM22 2 11 13"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19 13a7 7 0 0 0 0-2l2-1.5-2-3.5-2.4 1a7 7 0 0 0-1.7-1L14.5 3h-5L9 6a7 7 0 0 0-1.7 1l-2.4-1-2 3.5L5 11a7 7 0 0 0 0 2l-2.1 1.5 2 3.5 2.4-1a7 7 0 0 0 1.7 1l.5 3h5l.4-3a7 7 0 0 0 1.7-1l2.4 1 2-3.5L19 13Z"/>',
  signout: '<path d="M9 5H5v14h4m4-11 4 4-4 4m4-4H9"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/>',
  sparkles: '<path d="m12 3 1.7 5.3L19 10l-5.3 1.7L12 17l-1.7-5.3L5 10l5.3-1.7L12 3ZM19 17l.6 1.4L21 19l-1.4.6L19 21l-.6-1.4L17 19l1.4-.6L19 17Z"/>',
  trash: '<path d="M4 7h16m-14 0 1 13h10l1-13M9 7V4h6v3m-5 4v6m4-6v6"/>',
  users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2m20 0v-2a4 4 0 0 0-3-3.9M14 3.1a4 4 0 0 1 0 7.8"/><circle cx="9" cy="7" r="4"/>',
  warning: '<path d="m11 3-9 16a1.5 1.5 0 0 0 1.3 2h17.4a1.5 1.5 0 0 0 1.3-2L13 3a1.2 1.2 0 0 0-2 0ZM12 9v4m0 4h.01"/>',
};

function icon(name, size = 17) {
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${glyphs[name] || glyphs.info}</svg>`;
}

function safe(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
}

const number = value => new Intl.NumberFormat('ru-RU').format(Number(value) || 0);
const formatDate = value => value && !Number.isNaN(new Date(value).getTime())
  ? new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(value)) : '—';
const formatTime = value => value && !Number.isNaN(new Date(value).getTime())
  ? new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }).format(new Date(value)) : '—';
const initials = name => String(name || '?').trim().split(/\s+/).slice(0, 2).map(part => part[0] || '').join('').toUpperCase();
const displayName = person => person.first_name || person.title || (person.username ? `@${person.username}` : `Чат ${person.chat_id}`);
const canSend = () => Boolean(state.status?.telegram?.connected && !state.status?.demo);
const canUseAccounts = () => Boolean(state.status?.accounts?.enabled && !state.status?.demo);
const canDraftAI = () => Boolean(state.status?.ai?.configured);
const statuses = { draft: 'Черновик', scheduled: 'Запланирована', sending: 'Отправка', completed: 'Завершена', partial: 'С ошибками', failed: 'Ошибка' };
const navItems = [
  { id: 'overview', label: 'Обзор', icon: 'layers', group: 'main' },
  { id: 'campaigns', label: 'Рассылки', icon: 'send', group: 'main' },
  { id: 'people', label: 'Аудитория', icon: 'users', group: 'main' },
  { id: 'inbox', label: 'Входящие', icon: 'inbox', group: 'main' },
  { id: 'accounts', label: 'Telegram-аккаунты', icon: 'users', group: 'main' },
  { id: 'channels', label: 'Каналы и чаты', icon: 'message', group: 'main' },
  { id: 'ai', label: 'AI-студия', icon: 'sparkles', group: 'tools' },
  { id: 'analytics', label: 'Аналитика', icon: 'chart', group: 'tools' },
  { id: 'settings', label: 'Настройки', icon: 'settings', group: 'tools' },
];

const replyAttemptsKey = 'teleflow-account-reply-attempts';
const authLockKey = 'teleflow-panel-auth-lock';

function readReplyAttempts() {
  try {
    const attempts = JSON.parse(sessionStorage.getItem(replyAttemptsKey) || '[]');
    if (!Array.isArray(attempts)) return [];
    return attempts.filter(item => item && typeof item.accountId === 'string' && /^[1-9]\d{0,18}$/.test(item.accountId)
      && typeof item.dialogId === 'string' && /^-?\d{1,19}$/.test(item.dialogId)
      && typeof item.requestId === 'string' && /^[0-9a-f-]{36}$/.test(item.requestId));
  } catch { return []; }
}

const state = {
  route: location.hash.slice(1).split('?')[0] || 'overview',
  loading: true, authGate: false, sidebarOpen: false, pending: false,
  status: null, campaigns: [], subscribers: [], chats: [], inbox: [], rules: [], analytics: null,
  selectedChat: null, messages: [], contact: null, modal: null, aiText: '',
  accounts: [], selectedAccount: null, accountDialogs: [], accountDialogsTruncated: false,
  selectedAccountDialog: null, accountConversation: null, accountLoading: false, replyAttempts: readReplyAttempts(),
  filters: { campaigns: 'all', people: 'all', campaignSearch: '', audienceSearch: '', inboxSearch: '' },
};

let authVersion = 0;

function replyAttemptFor(accountId, dialogId) {
  return state.replyAttempts.find(item => item.accountId === String(accountId) && item.dialogId === String(dialogId));
}

function persistReplyAttempts(attempts) {
  sessionStorage.setItem(replyAttemptsKey, JSON.stringify(attempts.map(({ accountId, dialogId, requestId }) => ({ accountId, dialogId, requestId }))));
  state.replyAttempts = attempts;
}

function rememberReplyAttempt(accountId, dialogId, requestId) {
  const attempts = state.replyAttempts.filter(item => item.accountId !== accountId || item.dialogId !== dialogId);
  attempts.push({ accountId, dialogId, requestId, status: 'checking' });
  try { persistReplyAttempts(attempts); }
  catch { throw new Error('Не удалось сохранить идентификатор попытки в этой вкладке; сообщение не отправлено'); }
}

function forgetReplyAttempt(accountId, dialogId, requestId = null) {
  persistReplyAttempts(state.replyAttempts.filter(item => item.accountId !== accountId || item.dialogId !== dialogId || (requestId && item.requestId !== requestId)));
}

function lockWorkspace({ signOut = false } = {}) {
  authVersion += 1;
  if (signOut) { try { sessionStorage.removeItem(replyAttemptsKey); } catch { /* Private storage may be disabled. */ } }
  Object.assign(state, {
    loading: false, authGate: true, sidebarOpen: false, pending: false, status: null,
    campaigns: [], subscribers: [], chats: [], inbox: [], rules: [], analytics: null,
    selectedChat: null, messages: [], contact: null, modal: null, aiText: '',
    accounts: [], selectedAccount: null, accountDialogs: [], accountDialogsTruncated: false,
    selectedAccountDialog: null, accountConversation: null, accountLoading: false, replyAttempts: [],
    filters: { campaigns: 'all', people: 'all', campaignSearch: '', audienceSearch: '', inboxSearch: '' },
  });
  render();
}

function broadcastAuthLock(signOut) {
  try { localStorage.setItem(authLockKey, JSON.stringify({ signOut, nonce: crypto.randomUUID() })); }
  catch { /* Other tabs still recheck authorization when they become visible. */ }
}

function recheckAuthorization() {
  if (state.status?.auth_required && !state.authGate) {
    api('/campaigns').catch(error => { if (!state.authGate) toast(error.message, true); });
  }
}

async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...(options.headers || {}) },
    credentials: 'same-origin',
  });
  let payload;
  try { payload = await response.json(); } catch { payload = {}; }
  if (!response.ok) {
    if (response.status === 401 && payload.error === 'Authentication required' && !state.authGate) {
      lockWorkspace();
      broadcastAuthLock(false);
    }
    const error = new Error(payload.error || `Ошибка запроса (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return payload;
}

function toast(message, error = false) {
  const element = document.createElement('div');
  element.className = `toast${error ? ' error' : ''}`;
  element.innerHTML = `${icon(error ? 'warning' : 'check', 16)}<span>${safe(message)}</span>`;
  toastRegion.append(element);
  setTimeout(() => element.remove(), 4500);
}

async function loadAll({ silent = false } = {}) {
  const version = authVersion;
  if (!silent) { state.loading = true; render(); }
  try {
    const status = await api('/status');
    if (version !== authVersion) return;
    state.status = status;
    const [campaigns, subscribers, chats, inbox, rules, analytics, accounts] = await Promise.all([
      api('/campaigns'), api('/subscribers'), api('/chats'), api('/inbox'), api('/rules'), api('/analytics'),
      canUseAccounts() ? api('/accounts') : Promise.resolve({ items: [] }),
    ]);
    if (version !== authVersion) return;
    Object.assign(state, {
      campaigns: campaigns.items || [], subscribers: subscribers.items || [], chats: chats.items || [],
      inbox: inbox.items || [], rules: rules.items || [], analytics, accounts: accounts.items || [],
      authGate: false,
    });
    if (state.selectedAccount && !state.accounts.some(item => String(item.id) === state.selectedAccount)) {
      state.selectedAccount = null; state.accountDialogs = []; state.selectedAccountDialog = null;
      state.accountConversation = null;
    }
    if (state.selectedChat && !state.inbox.some(chat => String(chat.chat_id) === String(state.selectedChat))) {
      state.selectedChat = null; state.messages = [];
    }
    render();
  } catch (error) {
    if (version === authVersion && !state.authGate) toast(error.message, true);
  } finally { if (version === authVersion) { state.loading = false; render(); } }
}

function navigate(route) {
  if (!navItems.some(item => item.id === route)) route = 'overview';
  state.sidebarOpen = false;
  if (location.hash !== `#${route}`) location.hash = route;
  else { state.route = route; render(); }
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function brand() {
  return `<div class="brand"><span class="brand-mark">${icon('send', 19)}</span><span class="brand-name">tele<span>flow</span><small>Telegram workspace</small></span></div>`;
}

function sidebar() {
  const links = group => navItems.filter(item => item.group === group).map(item => `<button type="button" class="nav-link${state.route === item.id ? ' active' : ''}" data-nav="${item.id}" ${state.route === item.id ? 'aria-current="page"' : ''}>${icon(item.icon, 17)}<span>${item.label}</span>${item.id === 'inbox' && state.inbox.length ? `<span class="nav-counter">${state.inbox.length}</span>` : ''}</button>`).join('');
  return `<button type="button" class="side-overlay${state.sidebarOpen ? ' open' : ''}" data-action="close-sidebar" aria-label="Закрыть меню"></button>
    <aside class="sidebar${state.sidebarOpen ? ' open' : ''}" aria-label="Навигация">
      ${brand()}
      <nav><div class="nav-section"><p class="nav-label">Рабочее пространство</p>${links('main')}</div><div class="nav-section"><p class="nav-label">Инструменты</p>${links('tools')}</div></nav>
      <div class="sidebar-bottom"><div class="help-box"><div class="help-box-icon">${icon('help', 17)}</div><strong>Нужна помощь?</strong><p>Подключите бота и начните работу за несколько минут.</p><button type="button" data-nav="settings">Инструкция по запуску ${icon('arrow', 13)}</button></div>
      <div class="sidebar-foot"><span class="sidebar-foot-icon">${icon('shield', 16)}</span><span><strong>Безопасная отправка</strong><small>${canUseAccounts() ? 'Подписка или ручной ответ' : 'Только по подписке'}</small></span></div></div>
    </aside>`;
}

function topbar() {
  const page = navItems.find(item => item.id === state.route) || navItems[0];
  const botName = state.status?.telegram?.username;
  return `<header class="topbar"><div class="topbar-left"><button type="button" class="icon-button menu-toggle" data-action="toggle-sidebar" aria-label="Открыть меню">${icon('menu', 19)}</button><div class="breadcrumb">Рабочее пространство <span>/</span> <strong>${page.label}</strong></div></div>
    <div class="topbar-right"><button type="button" class="icon-button bordered" data-action="refresh" aria-label="Обновить данные" title="Обновить">${icon('refresh', 16)}</button>
    <button type="button" class="connection-pill${canSend() ? '' : ' disconnected'}" data-nav="settings"><i class="signal"></i>${canSend() ? `@${safe(botName || 'бот подключён')}` : state.status?.demo ? 'Демо-режим' : 'Бот не подключён'}</button>${state.status?.auth_required ? `<button type="button" class="btn btn-secondary btn-small topbar-exit" data-action="sign-out" aria-label="Выйти из панели" ${state.pending ? 'disabled' : ''}>${icon('signout', 13)}<span>Выйти</span></button>` : ''}<span class="account-avatar">TF</span></div></header>`;
}

function banner() {
  if (state.status?.demo) return `<div class="demo-banner">${icon('info', 15)}<span><strong>Демо-пространство.</strong> Создавайте черновики и изучайте панель. Отправка сообщений в Telegram здесь выключена.${state.status.public_demo ? ' Данные видны другим посетителям до перезапуска: не вводите личную информацию.' : ''}</span><button type="button" class="text-link" data-nav="settings">Как подключить бота ${icon('arrow', 12)}</button></div>`;
  if (!canSend()) return `<div class="demo-banner">${icon('info', 15)}<span>Подключите Telegram-бота, чтобы принимать подписчиков и отправлять сообщения. Черновики можно готовить уже сейчас.</span><button type="button" class="text-link" data-nav="settings">Настроить ${icon('arrow', 12)}</button></div>`;
  return '';
}

function heading(title, subtitle, actions = '') {
  return `<div class="page-heading"><div><span class="eyebrow">TeleFlow / ${safe(title)}</span><h1>${safe(title)}</h1><p>${safe(subtitle)}</p></div>${actions ? `<div class="heading-actions">${actions}</div>` : ''}</div>`;
}

function stat(label, value, hint, ico, style = '') {
  return `<div class="stat-card"><div class="stat-top"><span>${label}</span><span class="stat-icon ${style}">${icon(ico, 17)}</span></div><strong class="stat-value">${number(value)}</strong><div class="stat-hint">${hint}</div></div>`;
}

function statGrid() {
  const totals = state.analytics?.totals || {};
  return `<div class="stats-grid">${stat('Подписчики', totals.subscribers ?? state.subscribers.filter(item => item.opted_in).length, 'Запустили вашего бота', 'users')}${stat('Кампании', totals.campaigns ?? state.campaigns.length, 'Всего создано', 'layers', 'blue')}${stat('Отправлено', totals.sent ?? 0, 'Успешные доставки', 'send', 'orange')}${stat('Входящие', state.inbox.length, 'Диалоги с подписчиками', 'inbox', 'purple')}</div>`;
}

function chart() {
  const today = new Date();
  const rows = (state.analytics?.daily || []);
  const map = new Map(rows.map(row => [row.date, row]));
  const days = Array.from({ length: 7 }, (_, index) => {
    const date = new Date(Date.UTC(today.getFullYear(), today.getMonth(), today.getDate() - 6 + index));
    const key = date.toISOString().slice(0, 10);
    return { date, sent: Number(map.get(key)?.sent) || 0, failed: Number(map.get(key)?.failed) || 0 };
  });
  const max = Math.max(1, ...days.map(day => day.sent));
  return `<div class="chart" role="img" aria-label="Отправленные сообщения за последние 7 дней">${days.map(day => `<div class="chart-day" title="${new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', timeZone: 'UTC' }).format(day.date)}: отправлено ${day.sent}, ошибок ${day.failed}"><div class="chart-bar-track"><div class="chart-bar${day.sent ? '' : ' no-data'}" style="height:${day.sent ? Math.max(8, (day.sent / max) * 94) : 3}%"></div></div><span>${new Intl.DateTimeFormat('ru-RU', { weekday: 'short', timeZone: 'UTC' }).format(day.date)}</span></div>`).join('')}</div><div class="chart-caption"><span class="legend">Доставлено</span><span>Последние 7 дней · UTC</span></div>`;
}

function badge(status) { return `<span class="badge ${safe(status)}">${safe(statuses[status] || status)}</span>`; }

function empty(ico, title, description, action = '', compact = false) {
  return `<div class="empty-state${compact ? ' empty-compact' : ''}"><div class="empty-icon">${icon(ico, compact ? 18 : 23)}</div><h3>${title}</h3><p>${description}</p>${action}</div>`;
}

function campaignActions(item) {
  const title = safe(item.title);
  if (['draft', 'scheduled'].includes(item.status)) {
    return `<button type="button" data-action="edit-campaign" data-id="${item.id}" aria-label="Редактировать ${title}" title="Редактировать">${icon('edit', 14)}</button><button type="button" data-action="schedule-campaign" data-id="${item.id}" aria-label="Запланировать ${title}" title="Запланировать">${icon('calendar', 14)}</button><button type="button" data-action="send-campaign" data-id="${item.id}" aria-label="Отправить ${title}" title="Отправить" ${canSend() ? '' : 'disabled'}>${icon('send', 14)}</button><button type="button" data-action="delete-campaign" data-id="${item.id}" aria-label="Удалить ${title}" title="Удалить">${icon('trash', 14)}</button>`;
  }
  if (['partial', 'failed'].includes(item.status) && item.failed_count) {
    return `<button type="button" data-action="retry-campaign" data-id="${item.id}" aria-label="Повторить неудачные отправки: ${title}" title="Повторить неудачные отправки" ${canSend() ? '' : 'disabled'}>${icon('refresh', 14)}</button>`;
  }
  return '';
}

function campaignRows(items, compact = false) {
  if (!items.length) return empty('send', 'Пока нет рассылок', 'Создайте первую кампанию — её можно сохранить как черновик, даже без подключённого бота.', `<button type="button" class="btn btn-small" data-action="new-campaign">${icon('plus', 14)} Новая рассылка</button>`, compact);
  return `<div class="table-wrap"><table><thead><tr><th>Кампания</th><th>Аудитория</th><th>Статус</th><th>${compact ? 'Дата' : 'Отправлено'}</th>${compact ? '' : '<th aria-label="Действия"></th>'}</tr></thead><tbody>${items.map(item => `<tr><td><div class="item-name"><span class="item-icon">${icon(item.target_type === 'chat' ? 'message' : 'send', 15)}</span><span><strong>${safe(item.title)}</strong><span class="subtext">${formatDate(item.created_at)}</span></span></div></td><td>${item.target_type === 'chat' ? safe(state.chats.find(chat => String(chat.id) === String(item.chat_id))?.title || 'Канал / чат') : 'Подписчики бота'}</td><td>${badge(item.status)}</td><td>${compact ? (item.scheduled_at ? formatTime(item.scheduled_at) : formatDate(item.created_at)) : `${number(item.sent_count || 0)}${item.failed_count ? ` <span class="subtext">Ошибок: ${number(item.failed_count)}</span>` : ''}`}</td>${compact ? '' : `<td><div class="table-actions">${campaignActions(item)}</div></td>`}</tr>`).join('')}</tbody></table></div>`;
}

function overview() {
  const hasBot = canSend();
  const hasAudience = state.subscribers.some(item => item.opted_in) || state.chats.length > 0;
  const hasCampaign = state.campaigns.length > 0;
  const checklist = [
    { done: hasBot, title: 'Подключите Telegram-бота', caption: 'Добавьте токен через настройки сервера' },
    { done: hasAudience, title: 'Соберите аудиторию', caption: 'Подписчики запускают бота сами' },
    { done: hasCampaign, title: 'Создайте первую рассылку', caption: 'Подготовьте текст и выберите получателей' },
  ];
  return `${heading('Обзор', 'Ваша аудитория, сообщения и результаты — в одном месте.', `<button class="btn" type="button" data-action="new-campaign">${icon('plus', 15)} Новая рассылка</button>`)}${banner()}
    <section class="hero"><div class="hero-content"><div class="hero-kicker">${icon('bolt', 13)} ВАШ TELEGRAM, ВАШИ ПРАВИЛА</div><h2>Меньше рутины.<br/>Больше диалога.</h2><p>Публикуйте в своих каналах, общайтесь с подписчиками и создавайте кампании из одного спокойного рабочего пространства.</p><button class="btn" type="button" data-action="new-campaign">Создать кампанию ${icon('arrow', 14)}</button></div><div class="hero-visual" aria-hidden="true"><div class="orbit"></div><div class="hero-float primary"><span class="float-icon">${icon('send', 15)}</span><span><strong>Новая кампания</strong><small>Подготовьте сообщение для подписчиков</small></span></div><div class="hero-float secondary"><span class="float-icon orange">${icon('message', 15)}</span><span><strong>Один кабинет</strong><small>Сообщения, аудитория и аналитика</small></span></div></div></section>
    ${statGrid()}
    <div class="dashboard-grid"><div class="dashboard-stack"><section class="panel panel-pad"><div class="panel-head"><div><h2>Динамика отправки</h2><p>Сколько сообщений доставлено за неделю</p></div><button type="button" class="text-link" data-nav="analytics">Вся аналитика ${icon('arrow', 13)}</button></div>${chart()}</section>
    <section class="panel"><div class="panel-head" style="padding:19px 19px 0"><div><h2>Последние кампании</h2><p>Черновики и запланированные отправки</p></div><button type="button" class="text-link" data-nav="campaigns">Все рассылки ${icon('arrow', 13)}</button></div>${campaignRows(state.campaigns.slice(0, 4), true)}</section></div>
    <div class="dashboard-stack"><section class="panel panel-pad"><div class="panel-head"><div><h2>С чего начать</h2><p>Три шага до первой отправки</p></div></div><div class="checklist">${checklist.map((step, i) => `<div class="check-item"><span class="check-number${step.done ? ' done' : ''}">${step.done ? icon('check', 14) : String(i + 1).padStart(2, '0')}</span><div><strong>${step.title}</strong><p>${step.caption}</p></div></div>`).join('')}</div><div class="checklist-cta"><button class="text-link" type="button" data-nav="${hasBot ? (hasAudience ? 'campaigns' : 'people') : 'settings'}">${hasBot ? 'Продолжить работу' : 'Перейти к настройке'} ${icon('arrow', 13)}</button></div></section>
    <section class="teaser-panel"><span class="teaser-icon">${icon('sparkles', 17)}</span><h3>Идеи для текста? Поможет AI</h3><p>Сформулируйте задачу и получите черновик. Перед отправкой текст остаётся под вашим контролем.</p><button type="button" class="text-link" data-nav="ai">Открыть AI-студию ${icon('arrow', 13)}</button></section></div></div>`;
}

function campaignsPage() {
  const { campaigns: filter, campaignSearch: search } = state.filters;
  const filtered = state.campaigns.filter(item => (filter === 'all' || (filter === 'finished' ? ['completed', 'partial', 'failed'].includes(item.status) : item.status === filter)) && `${item.title} ${item.body}`.toLowerCase().includes(search.toLowerCase()));
  const tabs = [['all', 'Все'], ['draft', 'Черновики'], ['scheduled', 'Запланировано'], ['finished', 'Завершённые']];
  return `${heading('Рассылки', 'Подготовка, планирование и отправка сообщений своей аудитории.', `<button class="btn" type="button" data-action="new-campaign">${icon('plus', 15)} Новая рассылка</button>`)}${banner()}
    <div class="toolbar"><div class="tabs" role="group" aria-label="Фильтр рассылок">${tabs.map(([id, label]) => `<button type="button" class="tab${filter === id ? ' active' : ''}" data-action="filter-campaigns" data-filter="${id}">${label}</button>`).join('')}</div><label class="search-field">${icon('search', 15)}<input type="search" data-search="campaignSearch" value="${safe(search)}" placeholder="Найти рассылку" aria-label="Найти рассылку" /></label></div>
    <section class="panel">${filtered.length ? campaignRows(filtered) : state.campaigns.length ? empty('search', 'Ничего не найдено', 'Попробуйте изменить поиск или фильтр.') : campaignRows([], false)}</section>
    <div class="notice" style="margin-top:17px">${icon('shield', 16)}<p><strong>Без незапрошенных сообщений.</strong> Рассылки подписчикам идут только тем, кто сам запустил вашего бота и не отключил уведомления командой /stop. Публикация в каналах доступна, если бот — администратор.</p></div>`;
}

function audiencePage() {
  const active = state.subscribers.filter(item => item.opted_in).length;
  const filtered = state.subscribers.filter(item => (state.filters.people === 'all' || (state.filters.people === 'active' ? item.opted_in : !item.opted_in)) && `${item.first_name || ''} ${item.username || ''} ${item.chat_id}`.toLowerCase().includes(state.filters.audienceSearch.toLowerCase()));
  const bot = state.status?.telegram?.username;
  return `${heading('Аудитория', 'Люди, которые сами запустили вашего Telegram-бота.', `<button type="button" class="btn btn-secondary" data-action="sync" ${canSend() ? '' : 'disabled'}>${icon('refresh', 14)} Синхронизировать</button>`)}${banner()}
    <div class="page-grid"><div><div class="stats-grid" style="grid-template-columns:repeat(2,minmax(0,1fr))">${stat('Активные подписчики', active, 'Могут получать сообщения', 'users')}${stat('Отписались', state.subscribers.length - active, 'Больше не получают рассылки', 'shield', 'orange')}</div>
    <div class="toolbar"><div class="tabs" role="group" aria-label="Фильтр подписчиков">${[['all','Все'],['active','Подписаны'],['off','Отписались']].map(([id,label]) => `<button class="tab${state.filters.people === id ? ' active' : ''}" type="button" data-action="filter-people" data-filter="${id}">${label}</button>`).join('')}</div><label class="search-field">${icon('search', 15)}<input type="search" data-search="audienceSearch" value="${safe(state.filters.audienceSearch)}" placeholder="Имя или @username" aria-label="Найти подписчика" /></label></div>
    <section class="panel">${filtered.length ? `<div class="table-wrap"><table><thead><tr><th>Подписчик</th><th>Telegram ID</th><th>Дата подписки</th><th>Статус</th></tr></thead><tbody>${filtered.map(item => `<tr><td><div class="item-name"><span class="avatar">${safe(initials(displayName(item)))}</span><span><strong>${safe(displayName(item))}</strong><span class="subtext">${item.username ? `@${safe(item.username)}` : 'Без username'}</span></span></div></td><td>${safe(item.chat_id)}</td><td>${formatDate(item.joined_at)}</td><td><span class="dot${item.opted_in ? '' : ' off'}"></span>${item.opted_in ? 'Подписан' : 'Отписался'}</td></tr>`).join('')}</tbody></table></div>` : state.subscribers.length ? empty('search','Ничего не найдено','Измените поисковый запрос или фильтр.') : empty('users','Здесь появятся подписчики','Поделитесь ссылкой на бота. Пользователи появятся здесь после команды /start.')}</section></div>
    <div class="dashboard-stack"><section class="panel panel-pad"><div class="panel-head"><div><h2>Пригласите подписчиков</h2><p>Ссылка для вашего сайта или канала</p></div></div>${bot ? `<div class="code-line">https://t.me/${safe(bot)}?start=subscribe</div><button type="button" class="btn btn-secondary btn-small" data-action="copy-bot-link" style="margin-top:13px">${icon('copy', 13)} Скопировать ссылку</button>` : `<div class="notice warm">${icon('info', 15)}<p>Сначала подключите бота в настройках, затем появится его ссылка для подписки.</p></div>`}<p class="settings-note">Telegram разрешает боту написать пользователю только после того, как он сам запустит диалог.</p></section>
    <section class="panel panel-pad"><div class="panel-head"><div><h2>Приватность по умолчанию</h2><p>Подписка и отписка под контролем пользователя</p></div></div><div class="guide-list"><div class="guide-step"><span>01</span><div><strong>/start — подписаться</strong><p>Бот запоминает согласие на сообщения.</p></div></div><div class="guide-step"><span>02</span><div><strong>/stop — отписаться</strong><p>После этой команды рассылки не приходят.</p></div></div></div></section></div></div>`;
}

function inboxPage() {
  const chats = state.inbox.filter(item => `${item.first_name || ''} ${item.username || ''} ${item.last_text || ''}`.toLowerCase().includes(state.filters.inboxSearch.toLowerCase()));
  const selected = state.inbox.find(item => String(item.chat_id) === String(state.selectedChat));
  const contact = state.contact || selected;
  return `${heading('Входящие', 'Диалоги с людьми, которые написали вашему боту.', `<button type="button" class="btn btn-secondary" data-action="sync" ${canSend() ? '' : 'disabled'}>${icon('refresh', 14)} Проверить сообщения</button>`)}${banner()}
    <section class="panel inbox-shell${selected ? ' has-selection' : ''}"><div class="conversation-list"><div class="inbox-list-head"><label class="search-field">${icon('search', 15)}<input type="search" data-search="inboxSearch" value="${safe(state.filters.inboxSearch)}" placeholder="Поиск диалога" aria-label="Найти диалог" /></label></div>${chats.length ? chats.map(item => `<button class="conversation${String(item.chat_id) === String(state.selectedChat) ? ' selected' : ''}" type="button" data-action="select-chat" data-id="${safe(item.chat_id)}"><span class="avatar">${safe(initials(displayName(item)))}</span><span class="conversation-copy"><strong>${safe(displayName(item))}</strong><p>${safe(item.last_text || 'Нет сообщений')}</p></span><time class="conversation-time">${item.last_at ? formatDate(item.last_at) : ''}</time></button>`).join('') : empty('inbox', state.inbox.length ? 'Диалог не найден' : 'Пока тихо', state.inbox.length ? 'Попробуйте другой запрос.' : 'Как только подписчики напишут боту, их сообщения появятся здесь.', '', true)}</div>
    <div class="chat-area">${selected ? `<div class="chat-head"><button type="button" class="icon-button chat-back" data-action="back-inbox" aria-label="К списку диалогов">${icon('back', 16)}</button><span class="avatar">${safe(initials(displayName(contact)))}</span><span><strong>${safe(displayName(contact))}</strong><small>${contact?.username ? `@${safe(contact.username)} · ` : ''}${contact?.opted_in ? 'Подписан' : 'Отписался'}</small></span></div>
    <div class="chat-messages" id="chatMessages">${state.messages.length ? state.messages.map(item => `<div class="message ${item.direction === 'out' ? 'out' : 'in'}"><div class="message-bubble">${safe(item.body)}</div><time>${formatTime(item.created_at)}</time></div>`).join('') : empty('message', 'Начало диалога', 'Сообщения появятся здесь.', '', true)}</div>
    <div class="chat-compose"><form id="replyForm" class="composer"><input name="body" maxlength="4096" placeholder="Напишите ответ…" aria-label="Текст ответа" autocomplete="off" required ${contact?.opted_in && canSend() ? '' : 'disabled'} /><button type="button" class="icon-button bordered" data-action="suggest-reply" title="Предложить ответ с AI" aria-label="Предложить ответ с AI" ${canDraftAI() && contact?.opted_in ? '' : 'disabled'}>${icon('sparkles', 16)}</button><button class="btn" type="submit" ${contact?.opted_in && canSend() ? '' : 'disabled'}>${icon('send', 14)} Отправить</button></form><div class="composer-hint">${contact?.opted_in ? (canSend() ? 'AI-подсказки не отправляются без вашего подтверждения.' : 'Для ответа подключите Telegram-бота.') : 'Пользователь отписался — отправка отключена.'}</div></div>` : empty('message','Выберите диалог','Сообщения подписчика откроются здесь.', '', false)}</div></section>`;
}

function channelsPage() {
  return `${heading('Каналы и чаты', 'Публикуйте в тех каналах и группах, где ваш бот — администратор.', `<button type="button" class="btn" data-action="new-chat" ${canSend() ? '' : 'disabled'}>${icon('plus', 15)} Добавить канал</button>`)}${banner()}
    <div class="page-grid"><section class="panel">${state.chats.length ? `<div class="table-wrap"><table><thead><tr><th>Канал или группа</th><th>ID</th><th>Тип</th><th aria-label="Действия"></th></tr></thead><tbody>${state.chats.map(item => `<tr><td><div class="item-name"><span class="item-icon blue">${icon('message', 15)}</span><span><strong>${safe(item.title)}</strong><span class="subtext">${item.username ? `@${safe(item.username)}` : 'Приватный чат'}</span></span></div></td><td>${safe(item.id)}</td><td>${item.type === 'channel' ? 'Канал' : 'Группа'}</td><td><div class="table-actions"><button type="button" data-action="delete-chat" data-id="${safe(item.id)}" title="Убрать канал" aria-label="Убрать ${safe(item.title)}">${icon('trash', 14)}</button></div></td></tr>`).join('')}</tbody></table></div>` : empty('message', 'Каналы пока не добавлены', 'Добавьте свой канал или группу, где бот имеет права администратора. После этого можно будет публиковать сообщения.')}</section>
    <section class="panel panel-pad"><div class="panel-head"><div><h2>Как подключить канал</h2><p>Только ваши каналы и группы</p></div></div><div class="guide-list"><div class="guide-step"><span>01</span><div><strong>Добавьте бота</strong><p>В настройках канала назначьте его администратором с правом публикации.</p></div></div><div class="guide-step"><span>02</span><div><strong>Укажите @username или ID</strong><p>Для приватного канала используйте числовой ID.</p></div></div><div class="guide-step"><span>03</span><div><strong>Мы проверим права</strong><p>Без прав администратора канал не появится в списке.</p></div></div></div></section></div>`;
}

function rulesPanel() {
  return `<section class="panel panel-pad"><div class="panel-head"><div><h2>Автоответы по ключевым словам</h2><p>Бот ответит подписчику на входящее сообщение, если найдёт фразу</p></div><span class="stat-icon">${icon('bolt', 16)}</span></div>
    ${state.rules.length ? `<div style="margin-bottom:19px">${state.rules.map(rule => `<div class="rule-row"><span class="item-icon">${icon('message', 15)}</span><div class="rule-copy"><strong>«${safe(rule.keyword)}»</strong><p>${safe(rule.reply)}</p></div><small>${number(rule.hits || 0)} сраб.</small><button type="button" class="switch${rule.enabled ? ' on' : ''}" role="switch" aria-checked="${!!rule.enabled}" aria-label="${rule.enabled ? 'Выключить' : 'Включить'} правило ${safe(rule.keyword)}" data-action="toggle-rule" data-id="${rule.id}"></button><button type="button" class="icon-button" data-action="delete-rule" data-id="${rule.id}" title="Удалить правило" aria-label="Удалить правило ${safe(rule.keyword)}">${icon('trash', 14)}</button></div>`).join('')}</div>` : `<div class="notice" style="margin-bottom:17px">${icon('info', 16)}<p>Правил пока нет. Например: фраза «цена» → ответ с вашей ссылкой на тарифы.</p></div>`}
    <form id="ruleForm" class="inline-form"><div class="field"><label for="ruleKeyword">Ключевое слово</label><input id="ruleKeyword" name="keyword" maxlength="80" placeholder="Например, тариф" required /></div><div class="field"><label for="ruleReply">Ответ</label><input id="ruleReply" name="reply" maxlength="4096" placeholder="Расскажите о своём предложении" required /></div><button type="submit" class="btn">${icon('plus', 14)} Добавить</button></form><p class="settings-note">Правила работают только для людей, запустивших вашего бота. Команда /stop всегда имеет приоритет.</p></section>`;
}

function aiPage() {
  return `${heading('AI-студия', 'Черновики для рассылок и ответы на сообщения — с финальным решением за вами.')}${banner()}
    <div class="ai-layout" style="margin-bottom:18px"><section class="panel panel-pad"><div class="panel-head"><div><h2>Помощник по текстам</h2><p>Опишите задачу — получите готовый черновик</p></div><span class="stat-icon">${icon('sparkles', 16)}</span></div>
    ${!canDraftAI() ? `<div class="notice warm" style="margin-bottom:17px">${icon('info', 16)}<p>AI пока не подключён. Добавьте OPENAI_API_KEY в окружение сервера, чтобы генерировать текст.</p></div>` : ''}
    <form id="aiForm"><div class="field"><label for="aiPrompt">О чём написать?</label><textarea id="aiPrompt" name="prompt" maxlength="3000" placeholder="Например: анонс вебинара по дизайну в четверг, участие бесплатное, ссылка на запись в конце…" required ${canDraftAI() ? '' : 'disabled'}></textarea></div><div class="split-fields"><div class="field"><label for="aiKind">Формат</label><select id="aiKind" name="kind" ${canDraftAI() ? '' : 'disabled'}><option value="broadcast">Текст рассылки</option><option value="reply">Ответ подписчику</option></select></div><div class="field"><label for="aiTone">Тон</label><select id="aiTone" name="tone" ${canDraftAI() ? '' : 'disabled'}><option value="friendly">Дружелюбный</option><option value="professional">Деловой</option><option value="concise">Краткий</option></select></div></div><button type="submit" class="btn" ${canDraftAI() ? '' : 'disabled'}>${icon('sparkles', 15)} Сгенерировать черновик</button></form></section>
    <div class="result-card"><span class="result-label">${icon('sparkles', 14)} ВАШ РЕЗУЛЬТАТ</span>${state.aiText ? `<div class="result-text">${safe(state.aiText)}</div><div class="result-actions"><button type="button" class="btn btn-small" data-action="use-ai-text">Использовать ${icon('arrow', 13)}</button><button type="button" class="btn btn-secondary btn-small" data-action="copy-ai-text">${icon('copy', 13)} Копировать</button></div>` : `<div class="result-text placeholder">Здесь появится ваш текст. Отредактируйте его перед отправкой — вы полностью контролируете итоговое сообщение.</div>`}</div></div>
    ${rulesPanel()}`;
}

function analyticsPage() {
  const totals = state.analytics?.totals || {};
  return `${heading('Аналитика', 'Реальные данные об отправках и активности вашей аудитории.')}${banner()}${statGrid()}
    <div class="page-grid"><section class="panel panel-pad"><div class="panel-head"><div><h2>Доставки за неделю</h2><p>Учитываются только подтверждённые отправки Telegram</p></div></div>${chart()}</section><section class="panel panel-pad"><div class="panel-head"><div><h2>Итоги отправки</h2><p>За всё время работы</p></div></div><div class="guide-list"><div class="guide-step"><span>${icon('check', 14)}</span><div><strong>${number(totals.sent || 0)} доставлено</strong><p>Telegram подтвердил отправку.</p></div></div><div class="guide-step"><span>${icon('warning', 13)}</span><div><strong>${number(totals.failed || 0)} ошибок</strong><p>Сообщение не было доставлено.</p></div></div><div class="guide-step"><span>${icon('users', 13)}</span><div><strong>${number(totals.subscribers || 0)} подписчиков</strong><p>Сейчас могут получать сообщения.</p></div></div></div></section></div>
    <section class="panel" style="margin-top:18px"><div class="panel-head" style="padding:19px 19px 0"><div><h2>Результаты кампаний</h2><p>Статус и успешные отправки</p></div></div>${campaignRows(state.campaigns.filter(item => ['completed','partial','failed','sending'].includes(item.status)), true)}</section>`;
}

function accountReplyNotice(attempt, unresolved) {
  if (unresolved.length) {
    const unknown = unresolved.filter(item => item.state === 'unknown');
    return `<div class="notice warm">${icon('warning', 15)}<p>${unknown.length ? 'Исход отправки неизвестен. Проверьте этот диалог в Telegram, прежде чем писать снова.' : 'Отправка ещё выполняется. Обновите диалог, чтобы проверить её состояние.'} Повторное сообщение может продублироваться.</p></div>
      ${unknown.map(item => `<button type="button" class="btn btn-secondary btn-small account-recheck" data-action="review-account-reply" data-id="${safe(item.request_id)}">Проверил Telegram · попытка ${formatTime(item.created_at)}</button>`).join('')}
      ${unresolved.some(item => item.state === 'pending') ? `<button type="button" class="btn btn-secondary btn-small account-recheck" data-action="refresh-account-dialog">${icon('refresh', 13)} Проверить состояние</button>` : ''}`;
  }
  if (!attempt) return '';
  if (attempt.status === 'sent') return `<div class="notice">${icon('check', 15)}<p>Ответ уже отправлен и записан в TeleFlow. Не отправляйте его повторно.</p></div><button type="button" class="btn btn-secondary btn-small account-recheck" data-action="acknowledge-reply">Понятно — новый ответ</button>`;
  if (attempt.status === 'missing') return `<div class="notice warm">${icon('warning', 15)}<p>Запись об этой попытке не найдена. Перед новым ответом проверьте диалог в Telegram: прежнее сообщение могло быть доставлено.</p></div><button type="button" class="btn btn-secondary btn-small account-recheck" data-action="acknowledge-reply">Проверил Telegram — новый ответ</button>`;
  return `<div class="notice warm">${icon('warning', 15)}<p>Состояние попытки пока не подтверждено. Не отправляйте ответ повторно до проверки.</p></div><button type="button" class="btn btn-secondary btn-small account-recheck" data-action="refresh-account-dialog">${icon('refresh', 13)} Проверить состояние</button>`;
}

function accountInbox() {
  const selected = state.accountDialogs.find(item => String(item.id) === state.selectedAccountDialog);
  const conversation = state.accountConversation;
  const unresolved = conversation?.unresolved || [];
  const attempt = replyAttemptFor(state.selectedAccount, state.selectedAccountDialog);
  const blocked = Boolean(attempt || unresolved.length);
  const canReply = Boolean(conversation?.can_send && !blocked && !state.accountLoading && !state.pending);
  const kind = { private: 'Личный диалог', channel: 'Ваш канал', group: 'Ваша группа' };
  return `<section class="panel inbox-shell account-inbox${selected ? ' has-selection' : ''}">
    <div class="conversation-list"><div class="inbox-list-head"><strong>Существующие диалоги</strong><p>Первые 100 чатов аккаунта · только доступные для ответа</p></div>
      ${state.accountLoading && !state.accountDialogs.length ? `<div class="account-loading" role="status">Загружаем диалоги…</div>` : state.accountDialogs.length ? state.accountDialogs.map(item => `<button class="conversation${String(item.id) === state.selectedAccountDialog ? ' selected' : ''}" type="button" data-action="select-account-dialog" data-id="${safe(item.id)}" ${state.accountLoading ? 'disabled' : ''}><span class="avatar">${safe(initials(item.name))}</span><span class="conversation-copy"><strong>${safe(item.name)}</strong><small>${safe(kind[item.kind] || item.kind)}</small></span></button>`).join('') : empty('inbox', 'Диалогов пока нет', 'Можно отвечать только в существующих личных диалогах или публиковать в своих чатах.', '', true)}
      ${state.accountDialogsTruncated ? `<div class="account-footnote">Показаны только первые 100 диалогов. Поиск по всей истории пока недоступен.</div>` : ''}</div>
    <div class="chat-area">${selected ? `<div class="chat-head"><button type="button" class="icon-button chat-back" data-action="back-account-dialogs" aria-label="К списку диалогов">${icon('back', 16)}</button><span class="avatar">${safe(initials(selected.name))}</span><span><strong>${safe(selected.name)}</strong><small>${safe(kind[selected.kind] || selected.kind)}</small></span></div>
      <div class="chat-messages" id="accountMessages">${state.accountLoading && !conversation ? `<div class="account-loading" role="status">Загружаем историю…</div>` : conversation?.items?.length ? conversation.items.map(item => `<div class="message ${item.out ? 'out' : 'in'}"><div class="message-bubble">${safe(item.body)}</div><time>${formatTime(item.created_at)}</time></div>`).join('') : empty('message', 'История пуста', 'Здесь видны последние 40 сообщений; медиафайлы не загружаются.', '', true)}</div>
      <div class="chat-compose">${accountReplyNotice(attempt, unresolved)}
        <form id="accountReplyForm" class="composer"><input name="body" maxlength="4096" placeholder="Написать ответ…" aria-label="Текст ответа аккаунта" autocomplete="off" required ${canReply ? '' : 'disabled'} /><button class="btn" type="submit" ${canReply ? '' : 'disabled'}>${icon('send', 14)} Отправить</button></form>
        <div class="composer-hint">${selected.kind === 'private' ? 'Только ручной ответ в диалоге с входящим сообщением. /start бота не считается согласием.' : 'Публикация вручную: только ваш канал или группа.'}${conversation && !conversation.can_send && selected.kind === 'private' && !blocked ? ' В этом личном диалоге нет входящего сообщения среди последних 100 — отправка запрещена.' : ''}</div></div>` : empty('message', 'Выберите диалог', 'История откроется после выбора существующего чата.', '', false)}</div></section>`;
}

function accountsPage() {
  const introduction = `${heading('Telegram-аккаунты', 'Отдельный от бота кабинет для своих существующих диалогов и каналов.')}
    <div class="notice warm account-warning">${icon('lock', 17)}<p><strong>StringSession даёт полный доступ к вашему Telegram-аккаунту.</strong> Создавайте её только на доверенном устройстве, вводите исключительно на защищённой установке TeleFlow и не передавайте в чат, ссылки, логи или публичное демо. TeleFlow не сохраняет сессию в браузере; не разрешайте менеджеру паролей запоминать это поле.</p></div>`;
  if (!canUseAccounts()) return `${introduction}<section class="panel panel-pad account-disabled"><span class="setting-icon">${icon('shield', 20)}</span><h2>Доступно только в защищённой установке</h2><p>В демо личные аккаунты отключены. Для своего сервера установите дополнительные зависимости, задайте TELEFLOW_API_ID, TELEFLOW_API_HASH, TELEFLOW_SESSION_KEY и обязательный TELEFLOW_PASSWORD; за пределами localhost нужен HTTPS и TELEFLOW_PUBLIC_ORIGIN. Генерируйте готовую авторизованную StringSession локально по инструкции в README.</p><p>Демо не просит ключи и не отправляет сообщения в Telegram.</p></section>`;
  const active = state.accounts.find(item => String(item.id) === state.selectedAccount);
  return `${introduction}<div class="account-layout"><section class="panel panel-pad account-import"><div class="panel-head"><div><h2>Подключить свой аккаунт</h2><p>Импорт уже авторизованной Telethon StringSession · вход по номеру здесь не выполняется</p></div></div>
    <form id="accountImportForm" autocomplete="off"><div class="field"><label for="accountLabel">Метка аккаунта</label><input id="accountLabel" name="label" maxlength="80" placeholder="Например, основной" autocomplete="off" /></div><div class="field"><label for="accountSession">StringSession</label><input id="accountSession" name="session" type="password" maxlength="8192" placeholder="Вставьте готовую сессию" autocomplete="off" spellcheck="false" required /><small class="field-help">Поле очищается сразу после отправки. Сессия хранится на сервере только в зашифрованном виде.</small></div><button class="btn" type="submit" ${state.pending ? 'disabled' : ''}>${icon('plus', 14)} Подключить</button></form></section>
    <section class="panel panel-pad account-list-panel"><div class="panel-head"><div><h2>Подключённые аккаунты</h2><p>Видны всем, кто знает пароль этой панели</p></div><span class="stat-icon">${icon('users', 17)}</span></div>${state.accounts.length ? `<div class="account-cards">${state.accounts.map(item => `<button type="button" class="account-card${String(item.id) === state.selectedAccount ? ' selected' : ''}" data-action="select-account" data-id="${safe(item.id)}" ${state.accountLoading ? 'disabled' : ''}><span class="avatar">${safe(initials(item.display_name))}</span><span><strong>${safe(item.display_name)}</strong><small>${item.username ? `@${safe(item.username)}` : `ID ${safe(item.id)}`}</small></span>${icon('chevron', 16)}</button>`).join('')}</div>` : empty('users', 'Аккаунтов пока нет', 'Подключите только аккаунт, который принадлежит вам.', '', true)}</section></div>
    ${active ? `<div class="account-tools"><div><strong>${safe(active.display_name)}</strong><small>Ручные действия в Telegram · без автоматических рассылок</small></div><div class="account-actions"><button type="button" class="btn btn-secondary btn-small" data-action="refresh-account" ${state.accountLoading || state.pending ? 'disabled' : ''}>${icon('refresh', 13)} Обновить диалоги</button><button type="button" class="btn btn-danger btn-small" data-action="revoke-account" data-id="${safe(active.id)}" ${state.accountLoading || state.pending ? 'disabled' : ''}>Отозвать сессию</button><button type="button" class="text-link" data-action="forget-account" data-id="${safe(active.id)}" ${state.accountLoading || state.pending ? 'disabled' : ''}>Только удалить локально</button></div></div>${accountInbox()}` : `<section class="panel">${empty('inbox', 'Выберите аккаунт', 'После выбора увидите его существующие диалоги. TeleFlow не ищет незнакомых адресатов.', '', false)}</section>`}`;
}

function settingsPage() {
  const telegram = state.status?.telegram || {};
  return `${heading('Настройки', 'Подключения и безопасность вашего рабочего пространства.')}${banner()}
    <div class="settings-grid"><section class="panel panel-pad"><div class="setting-top"><span class="setting-icon">${icon('bot', 19)}</span><div><h2>Telegram Bot API</h2><p>Подписчики, сообщения и публикация в своих каналах</p></div></div><div class="setting-status"><strong>${telegram.connected && !state.status?.demo ? `${icon('check', 13)} Подключён` : `${icon('info', 13)} Не подключён`}</strong><span>${telegram.connected && !state.status?.demo ? `@${safe(telegram.username || 'бот')}` : 'Ожидает настройки'}</span></div>
    <div class="guide-list"><div class="guide-step"><span>01</span><div><strong>Создайте бота в @BotFather</strong><p>Telegram выдаст токен. Не публикуйте его и не вводите в сторонние формы.</p></div></div><div class="guide-step"><span>02</span><div><strong>Добавьте токен на сервере</strong><p>Перед запуском установите переменную окружения:</p><code class="code-line" style="margin-top:7px">TELEFLOW_BOT_TOKEN=ваш_токен</code></div></div><div class="guide-step"><span>03</span><div><strong>Перезапустите приложение</strong><p>Подписчики смогут написать вашему боту после команды /start.</p></div></div></div>
    ${telegram.error && telegram.error !== 'TELEFLOW_BOT_TOKEN is not configured' ? `<div class="notice warm" style="margin-top:17px">${icon('warning', 15)}<p>${safe(telegram.error)}</p></div>` : ''}<div style="margin-top:19px;display:flex;gap:8px;flex-wrap:wrap"><button type="button" class="btn btn-secondary btn-small" data-action="refresh">${icon('refresh', 13)} Проверить статус</button><button type="button" class="btn btn-secondary btn-small" data-action="sync" ${canSend() ? '' : 'disabled'}>${icon('inbox', 13)} Получить сообщения</button></div></section>
    <section class="panel panel-pad"><div class="setting-top"><span class="setting-icon blue">${icon('sparkles', 19)}</span><div><h2>AI-помощник</h2><p>Черновики текстов и подсказки для ответов</p></div></div><div class="setting-status"><strong>${canDraftAI() ? `${icon('check', 13)} Настроен` : `${icon('info', 13)} Не настроен`}</strong><span>OpenAI API</span></div><p class="settings-note">Для AI-функций добавьте ключ в окружение сервера. Ключ остаётся на сервере и не передаётся браузеру.</p><code class="code-line" style="margin-top:14px">OPENAI_API_KEY=ваш_ключ</code><button type="button" class="text-link" style="margin-top:17px" data-nav="ai">Перейти в AI-студию ${icon('arrow', 13)}</button></section>
    <section class="panel panel-pad"><div class="setting-top"><span class="setting-icon">${icon('shield', 19)}</span><div><h2>Доступ и данные</h2><p>Защита при размещении за пределами локального компьютера</p></div></div><p class="settings-note">Для доступа из сети установите пароль <code>TELEFLOW_PASSWORD</code>, укажите доверенный адрес <code>TELEFLOW_PUBLIC_ORIGIN</code> и используйте HTTPS. Токен бота и ключ AI не сохраняются в браузере.</p><div class="notice" style="margin-top:15px">${icon('lock', 15)}<p>База данных хранится локально на сервере. Не публикуйте её и включите резервное копирование при постоянном использовании.</p></div></section>
    <section class="panel panel-pad"><div class="setting-top"><span class="setting-icon blue">${icon('info', 19)}</span><div><h2>Границы интеграции</h2><p>Отдельные правила для бота и личных аккаунтов</p></div></div><p class="settings-note">Бот работает через Bot API и отправляет сообщения только подписчикам или в проверенные свои чаты. Опциональный Telethon-модуль даёт владельцу аккаунта ручной доступ к существующим диалогам, но не собирает участников чужих групп, не рассылает незнакомым людям и не накручивает реакции. /start бота не даёт права писать от личного аккаунта.</p><button type="button" class="text-link" style="margin-top:17px" data-nav="accounts">Telegram-аккаунты ${icon('arrow', 13)}</button></section></div>`;
}

function modal() {
  if (!state.modal) return '';
  const data = state.modal;
  let title = '', description = '', content = '', wide = false;
  if (data.type === 'campaign') {
    const item = data.id ? state.campaigns.find(campaign => campaign.id === data.id) : null;
    title = item ? 'Редактировать рассылку' : 'Новая рассылка';
    description = 'Подготовьте текст для ваших подписчиков или своего канала.';
    wide = true;
    const target = item?.target_type || 'subscribers';
    content = `<form id="campaignForm"><div class="modal-grid"><div><div class="field"><label for="campaignTitle">Название кампании</label><input id="campaignTitle" name="title" maxlength="120" value="${safe(item?.title || '')}" placeholder="Например, Анонс нового выпуска" required autofocus /></div>
      <div class="field"><span>Получатели</span><div class="target-options"><label class="target-choice"><input type="radio" name="target_type" value="subscribers" ${target === 'subscribers' ? 'checked' : ''} /><span>${icon('users', 17)}<strong>Подписчики</strong><small>Те, кто запустил бота</small></span></label><label class="target-choice"><input type="radio" name="target_type" value="chat" ${target === 'chat' ? 'checked' : ''} /><span>${icon('message', 17)}<strong>Канал / группа</strong><small>Где бот — администратор</small></span></label></div></div>
      <div class="field" id="chatTargetWrap" ${target === 'chat' ? '' : 'hidden'}><label for="campaignChat">Выберите канал или группу</label><select id="campaignChat" name="chat_id"><option value="">Выберите из списка</option>${state.chats.map(chat => `<option value="${safe(chat.id)}" ${String(item?.chat_id) === String(chat.id) ? 'selected' : ''}>${safe(chat.title)}</option>`).join('')}</select>${state.chats.length ? '' : `<small class="field-help">Сначала добавьте канал в разделе «Каналы и чаты».</small>`}</div>
      <div class="field"><label for="campaignBody">Текст сообщения</label><textarea id="campaignBody" name="body" maxlength="4096" placeholder="Здравствуйте! Расскажите, что нового у вашего проекта…" required>${safe(item?.body || data.prefill || '')}</textarea><small class="field-help"><span id="bodyCount">${(item?.body || data.prefill || '').length}</span> / 4096 символов · отправляется как обычный текст</small></div></div>
      <div class="modal-preview"><span class="modal-preview-label">Предпросмотр сообщения</span><div class="preview-chat"><div class="preview-chat-top"><span class="avatar">TF</span><strong>Ваш Telegram-бот</strong></div><div class="preview-chat-bubble" id="previewMessage">${safe(item?.body || data.prefill || 'Ваше сообщение появится здесь…')}</div></div></div></div>
      <div class="modal-footer"><button class="btn btn-secondary" type="button" data-action="close-modal">Отмена</button><button class="btn" type="submit" ${state.pending ? 'disabled' : ''}>${icon('check', 14)} Сохранить черновик</button></div></form>`;
  } else if (data.type === 'schedule') {
    const item = state.campaigns.find(campaign => campaign.id === data.id);
    title = 'Запланировать отправку'; description = item?.title || '';
    const min = new Date(Date.now() + 60000);
    const datetime = item?.scheduled_at ? new Date(item.scheduled_at) : new Date(Date.now() + 3600000);
    const local = new Date(datetime.getTime() - datetime.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    const localMin = new Date(min.getTime() - min.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    content = `<form id="scheduleForm"><div class="field"><label for="scheduleTime">Дата и время в вашем часовом поясе</label><input id="scheduleTime" name="scheduled_at" type="datetime-local" min="${localMin}" value="${local}" required /></div><div class="notice">${icon('clock', 15)}<p>Сообщение будет отправлено, пока сервер приложения работает и бот подключён.</p></div><div class="modal-footer"><button type="button" class="btn btn-secondary" data-action="close-modal">Отмена</button><button type="submit" class="btn" ${state.pending ? 'disabled' : ''}>${icon('calendar', 14)} Запланировать</button></div></form>`;
  } else if (data.type === 'chat') {
    title = 'Добавить канал или чат'; description = 'Перед подключением назначьте бота администратором.';
    content = `<form id="chatForm"><div class="field"><label for="chatId">@username или числовой ID</label><input id="chatId" name="chat_id" placeholder="@my_channel или -1001234567890" maxlength="120" required /></div><div class="modal-note">${icon('shield', 15)} Бот должен иметь право публиковать сообщения. Мы проверим это перед добавлением.</div><div class="modal-footer"><button type="button" class="btn btn-secondary" data-action="close-modal">Отмена</button><button type="submit" class="btn" ${state.pending ? 'disabled' : ''}>${icon('plus', 14)} Добавить</button></div></form>`;
  } else if (data.type === 'send') {
    const item = state.campaigns.find(campaign => campaign.id === data.id);
    title = 'Отправить рассылку?'; description = 'Подтвердите отправку. Это действие нельзя отменить.';
    const count = item?.target_type === 'chat' ? 1 : state.subscribers.filter(sub => sub.opted_in).length;
    content = `<div class="modal-note"><strong>${safe(item?.title || '')}</strong><br/>Получатели: ${item?.target_type === 'chat' ? 'один ваш канал / чат' : `${number(count)} подписчиков`}. Сообщение будет отправлено через вашего бота.</div><div class="modal-footer"><button class="btn btn-secondary" type="button" data-action="close-modal">Отмена</button><button class="btn" type="button" data-action="confirm-send" data-id="${data.id}" ${state.pending ? 'disabled' : ''}>${icon('send', 14)} Отправить</button></div>`;
  } else if (data.type === 'retry') {
    const item = state.campaigns.find(campaign => campaign.id === data.id);
    title = 'Повторить неудачные отправки?'; description = 'Подтвердите новую попытку отправки.';
    content = `<div class="modal-note"><strong>${safe(item?.title || '')}</strong><br/>Получатели: ${number(item?.failed_count || 0)} с ошибками. Уже отправленные сообщения не повторяются; отписавшиеся будут пропущены.</div><div class="modal-footer"><button class="btn btn-secondary" type="button" data-action="close-modal">Отмена</button><button class="btn" type="button" data-action="confirm-retry" data-id="${data.id}" ${state.pending ? 'disabled' : ''}>${icon('refresh', 14)} Повторить</button></div>`;
  } else if (data.type === 'delete') {
    title = 'Удалить безвозвратно?'; description = 'Это действие нельзя отменить.';
    content = `<p style="color:var(--muted);font-size:11px;line-height:1.7;margin:0">${safe(data.label || 'Выбранный объект')} будет удалён из рабочего пространства.</p><div class="modal-footer"><button class="btn btn-secondary" type="button" data-action="close-modal">Отмена</button><button class="btn btn-danger" type="button" data-action="confirm-delete" ${state.pending ? 'disabled' : ''}>${icon('trash', 14)} Удалить</button></div>`;
  } else if (data.type === 'account-revoke' || data.type === 'account-forget') {
    const account = state.accounts.find(item => String(item.id) === data.id);
    const forget = data.type === 'account-forget';
    title = forget ? 'Забыть аккаунт без отзыва?' : 'Отозвать Telegram-сессию?';
    description = account?.display_name || 'Выбранный аккаунт';
    content = `<div class="notice warm">${icon('warning', 16)}<p>${forget ? 'Удалится только зашифрованная копия в TeleFlow. Telegram-сессия останется действующей — завершите её вручную в настройках Telegram «Устройства».' : 'TeleFlow запросит выход в Telegram и только после подтверждения удалит локальную сессию. Эта авторизация перестанет работать и в других копиях.'}</p></div><div class="modal-footer"><button type="button" class="btn btn-secondary" data-action="close-modal">Отмена</button><button type="button" class="btn btn-danger" data-action="${forget ? 'confirm-forget-account' : 'confirm-revoke-account'}" ${state.pending ? 'disabled' : ''}>${icon('trash', 14)} ${forget ? 'Только удалить локально' : 'Отозвать и удалить'}</button></div>`;
  } else if (data.type === 'account-review') {
    title = 'Вы проверили диалог в Telegram?';
    description = 'Проверьте, было ли доставлено сообщение с неизвестным исходом.';
    content = `<div class="notice warm">${icon('warning', 16)}<p>TeleFlow не знает результат этой попытки. Подтверждение только снимет блокировку новых ответов в этом диалоге; оно не отправляет сообщение и не доказывает доставку. При нескольких попытках проверьте каждую.</p></div><div class="modal-footer"><button type="button" class="btn btn-secondary" data-action="close-modal">Ещё не проверил</button><button type="button" class="btn" data-action="confirm-review-account-reply" ${state.pending ? 'disabled' : ''}>Проверил в Telegram</button></div>`;
  } else if (data.type === 'account-local-review') {
    title = 'Вы проверили диалог в Telegram?';
    description = 'Запись о попытке отсутствует в TeleFlow.';
    content = `<div class="notice warm">${icon('warning', 16)}<p>Найдите это сообщение в Telegram перед новым ответом. Подтверждение снимет только блокировку в этой вкладке: оно не отправляет сообщение и не доказывает, что прежняя попытка не была доставлена.</p></div><div class="modal-footer"><button type="button" class="btn btn-secondary" data-action="close-modal">Ещё не проверил</button><button type="button" class="btn" data-action="confirm-acknowledge-reply">Проверил в Telegram</button></div>`;
  }
  return `<div class="modal-layer" data-action="close-modal"><section class="modal${wide ? ' wide' : ''}" role="dialog" aria-modal="true" aria-label="${safe(title)}"><div class="modal-header"><div><h2>${safe(title)}</h2><p>${safe(description)}</p></div><button type="button" class="icon-button" data-action="close-modal" aria-label="Закрыть окно">${icon('close', 18)}</button></div><div class="modal-body">${content}</div></section></div>`;
}

function loginPage() {
  return `<div class="login-screen"><div class="login-card">${brand()}<h1>Добро пожаловать</h1><p>Рабочее пространство защищено. Введите пароль, который настроен на сервере.</p><form id="loginForm"><div class="field"><label for="loginPassword">Пароль доступа</label><input id="loginPassword" name="password" type="password" placeholder="Введите пароль" autocomplete="current-password" required autofocus /></div><button class="btn" type="submit">Войти ${icon('arrow', 15)}</button></form></div></div>`;
}

function render() {
  if (state.authGate) { root.innerHTML = loginPage(); return; }
  if (state.loading && !state.status) { root.innerHTML = `<div class="initial-loader"><span class="loader"></span><span>Загружаем рабочее пространство…</span></div>`; return; }
  const pages = { overview, campaigns: campaignsPage, people: audiencePage, inbox: inboxPage, accounts: accountsPage, channels: channelsPage, ai: aiPage, analytics: analyticsPage, settings: settingsPage };
  if (!pages[state.route]) state.route = 'overview';
  root.innerHTML = `<div class="app-shell">${sidebar()}<div class="main">${topbar()}<main class="content">${pages[state.route]()}</main></div>${modal()}</div>`;
  if (!canSend()) root.querySelectorAll('[data-action="schedule-campaign"]').forEach(button => {
    button.disabled = true;
    button.title = 'Подключите Telegram-бота для планирования';
  });
  if (state.modal) root.querySelector('.modal [autofocus]')?.focus();
  if (state.route === 'inbox' && state.selectedChat) {
    const messages = document.getElementById('chatMessages');
    if (messages) messages.scrollTop = messages.scrollHeight;
  }
  if (state.route === 'accounts' && state.selectedAccountDialog) {
    const messages = document.getElementById('accountMessages');
    if (messages) messages.scrollTop = messages.scrollHeight;
  }
}

async function selectAccount(accountId) {
  if (state.accountLoading) return;
  state.selectedAccount = String(accountId);
  state.selectedAccountDialog = null; state.accountConversation = null;
  state.accountDialogs = []; state.accountDialogsTruncated = false;
  state.accountLoading = true; render();
  try {
    const result = await api(`/accounts/${encodeURIComponent(accountId)}/dialogs`);
    if (state.selectedAccount === String(accountId)) {
      state.accountDialogs = result.items || [];
      state.accountDialogsTruncated = Boolean(result.truncated);
    }
  } catch (error) { toast(error.message, true); }
  finally { state.accountLoading = false; render(); }
}

async function inspectReplyAttempt(accountId, dialogId) {
  const attempt = replyAttemptFor(accountId, dialogId);
  if (!attempt) return;
  try {
    const result = await api(`/accounts/${encodeURIComponent(accountId)}/dialogs/${encodeURIComponent(dialogId)}/replies/${attempt.requestId}`);
    if (state.authGate || replyAttemptFor(accountId, dialogId) !== attempt) return;
    if (result.reviewed || result.state === 'rejected') {
      forgetReplyAttempt(accountId, dialogId, attempt.requestId);
      if (result.state === 'rejected') toast('Предыдущая отправка отклонена; можно подготовить новый ответ');
    } else {
      attempt.status = result.state;
      if (result.state === 'sent') toast('Ответ уже отправлен; не повторяйте его');
    }
  } catch (error) {
    if (state.authGate || replyAttemptFor(accountId, dialogId) !== attempt) return;
    attempt.status = error.status === 404 ? 'missing' : 'unavailable';
    if (error.status !== 404) toast(error.message, true);
  }
}

async function selectAccountDialog(dialogId) {
  if (state.accountLoading || !state.selectedAccount) return;
  const accountId = state.selectedAccount;
  state.selectedAccountDialog = String(dialogId);
  state.accountConversation = null; state.accountLoading = true; render();
  try {
    const result = await api(`/accounts/${encodeURIComponent(accountId)}/dialogs/${encodeURIComponent(dialogId)}`);
    if (state.selectedAccount === accountId && state.selectedAccountDialog === String(dialogId)) {
      state.accountConversation = result;
      await inspectReplyAttempt(accountId, String(dialogId));
    }
  } catch (error) { if (!state.authGate) toast(error.message, true); }
  finally { state.accountLoading = false; render(); }
}

async function selectChat(chatId) {
  state.selectedChat = chatId;
  state.contact = null; state.messages = [];
  render();
  try {
    const result = await api(`/inbox/${encodeURIComponent(chatId)}`);
    if (String(state.selectedChat) !== String(chatId)) return;
    state.messages = result.items || [];
    state.contact = result.contact || null;
    render();
  } catch (error) { toast(error.message, true); }
}

async function doAction(element) {
  const action = element.dataset.action;
  const id = element.dataset.id;
  if (action === 'toggle-sidebar') { state.sidebarOpen = !state.sidebarOpen; render(); return; }
  if (action === 'close-sidebar') { state.sidebarOpen = false; render(); return; }
  if (action === 'close-modal') { state.modal = null; render(); return; }
  if (action === 'refresh') { await loadAll(); if (!state.authGate) toast('Данные обновлены'); return; }
  if (action === 'sign-out') {
    if (state.pending) return;
    state.pending = true; render();
    try {
      await api('/signout', { method: 'POST' });
      lockWorkspace({ signOut: true });
      broadcastAuthLock(true);
      toast('Вы вышли из панели');
    } catch (error) { toast(error.message, true); }
    finally { state.pending = false; render(); }
    return;
  }
  if (action === 'select-account') { if (!state.pending) await selectAccount(id); return; }
  if (action === 'select-account-dialog') { if (!state.pending) await selectAccountDialog(id); return; }
  if (action === 'refresh-account') { if (!state.pending && state.selectedAccount) await selectAccount(state.selectedAccount); return; }
  if (action === 'refresh-account-dialog') { if (!state.pending && state.selectedAccountDialog) await selectAccountDialog(state.selectedAccountDialog); return; }
  if (action === 'back-account-dialogs') { state.selectedAccountDialog = null; state.accountConversation = null; render(); return; }
  if (action === 'acknowledge-reply' && !state.accountConversation?.unresolved?.length) {
    const attempt = replyAttemptFor(state.selectedAccount, state.selectedAccountDialog);
    if (attempt?.status === 'sent') {
      try { forgetReplyAttempt(attempt.accountId, attempt.dialogId); render(); }
      catch (error) { toast(error.message, true); }
    } else if (attempt?.status === 'missing') {
      state.modal = { type: 'account-local-review', accountId: attempt.accountId, dialogId: attempt.dialogId, requestId: attempt.requestId }; render();
    }
    return;
  }
  if (action === 'confirm-acknowledge-reply' && state.modal?.type === 'account-local-review') {
    if (state.pending) return;
    const { accountId, dialogId, requestId } = state.modal;
    state.pending = true;
    try {
      await inspectReplyAttempt(accountId, dialogId);
      if (replyAttemptFor(accountId, dialogId)?.requestId === requestId && replyAttemptFor(accountId, dialogId)?.status === 'missing' && !state.accountConversation?.unresolved?.length) {
        forgetReplyAttempt(accountId, dialogId, requestId);
        state.modal = null;
        toast('Попытка проверена; нового сообщения не отправлено');
      } else { state.modal = null; await selectAccountDialog(dialogId); }
    } catch (error) { toast(error.message, true); }
    finally { state.pending = false; render(); }
    return;
  }
  if (action === 'review-account-reply' && state.accountConversation?.unresolved?.some(item => item.request_id === id && item.state === 'unknown')) {
    state.modal = { type: 'account-review', accountId: state.selectedAccount, dialogId: state.selectedAccountDialog, requestId: id }; render(); return;
  }
  if (action === 'confirm-review-account-reply') {
    if (state.pending || state.modal?.type !== 'account-review') return;
    const { accountId, dialogId, requestId } = state.modal;
    state.pending = true; render();
    try {
      await api(`/accounts/${encodeURIComponent(accountId)}/dialogs/${encodeURIComponent(dialogId)}/review`, {
        method: 'POST', body: JSON.stringify({ request_id: requestId, confirm: 'checked_in_telegram' }),
      });
      state.modal = null; forgetReplyAttempt(accountId, dialogId, requestId);
      await selectAccountDialog(dialogId);
      toast('Попытка отмечена как проверенная; нового сообщения не отправлено');
    } catch (error) { toast(error.message, true); }
    finally { state.pending = false; render(); }
    return;
  }
  if (action === 'revoke-account' || action === 'forget-account') {
    if (state.pending || state.accountLoading) return;
    state.modal = { type: action === 'revoke-account' ? 'account-revoke' : 'account-forget', id }; render(); return;
  }
  if (action === 'confirm-revoke-account' || action === 'confirm-forget-account') {
    if (state.pending || !state.modal) return;
    const accountId = state.modal.id;
    state.pending = true; render();
    try {
      if (action === 'confirm-revoke-account') await api(`/accounts/${encodeURIComponent(accountId)}`, { method: 'DELETE' });
      else await api(`/accounts/${encodeURIComponent(accountId)}/forget`, { method: 'POST', body: JSON.stringify({ confirm: 'forget_without_revocation' }) });
      state.modal = null;
      state.selectedAccount = null; state.selectedAccountDialog = null; state.accountConversation = null;
      state.accountDialogs = []; state.accountDialogsTruncated = false;
      persistReplyAttempts(state.replyAttempts.filter(item => item.accountId !== String(accountId)));
      await loadAll({ silent: true });
      toast(action === 'confirm-revoke-account' ? 'Сессия отозвана в Telegram и удалена' : 'Локальная копия удалена; завершите сессию в Telegram вручную');
    } catch (error) { toast(error.message, true); }
    finally { state.pending = false; render(); }
    return;
  }
  if (action === 'new-campaign') { state.modal = { type: 'campaign' }; render(); return; }
  if (action === 'edit-campaign') { state.modal = { type: 'campaign', id: Number(id) }; render(); return; }
  if (action === 'schedule-campaign') {
    if (!canSend()) return toast('Для планирования подключите Telegram-бота', true);
    state.modal = { type: 'schedule', id: Number(id) }; render(); return;
  }
  if (action === 'send-campaign') {
    if (!canSend()) return toast('Для отправки подключите Telegram-бота', true);
    state.modal = { type: 'send', id: Number(id) }; render(); return;
  }
  if (action === 'retry-campaign') {
    if (!canSend()) return toast('Для повторной отправки подключите Telegram-бота', true);
    state.modal = { type: 'retry', id: Number(id) }; render(); return;
  }
  if (action === 'delete-campaign') { state.modal = { type: 'delete', kind: 'campaigns', id, label: state.campaigns.find(item => String(item.id) === id)?.title }; render(); return; }
  if (action === 'delete-chat') { state.modal = { type: 'delete', kind: 'chats', id, label: state.chats.find(item => String(item.id) === id)?.title }; render(); return; }
  if (action === 'delete-rule') { state.modal = { type: 'delete', kind: 'rules', id, label: `Правило «${state.rules.find(item => String(item.id) === id)?.keyword || ''}»` }; render(); return; }
  if (action === 'new-chat') { state.modal = { type: 'chat' }; render(); return; }
  if (action === 'filter-campaigns') { state.filters.campaigns = element.dataset.filter; render(); return; }
  if (action === 'filter-people') { state.filters.people = element.dataset.filter; render(); return; }
  if (action === 'select-chat') { await selectChat(id); return; }
  if (action === 'back-inbox') { state.selectedChat = null; state.messages = []; render(); return; }
  if (action === 'copy-bot-link') {
    try { await navigator.clipboard.writeText(`https://t.me/${state.status.telegram.username}?start=subscribe`); toast('Ссылка скопирована'); }
    catch { toast('Браузер не разрешил копирование. Выделите ссылку вручную.', true); }
    return;
  }
  if (action === 'copy-ai-text') {
    try { await navigator.clipboard.writeText(state.aiText); toast('Текст скопирован'); }
    catch { toast('Браузер не разрешил копирование', true); }
    return;
  }
  if (action === 'use-ai-text') { state.modal = { type: 'campaign', prefill: state.aiText }; render(); return; }
  if (action === 'sync') {
    try { const result = await api('/sync', { method: 'POST' }); await loadAll({ silent: true }); toast(`Обновлено: ${number(result.processed || 0)} событий`); }
    catch (error) { toast(error.message, true); }
    return;
  }
  if (action === 'toggle-rule') {
    try { await api(`/rules/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify({ enabled: element.getAttribute('aria-checked') !== 'true' }) }); await loadAll({ silent: true }); toast('Правило обновлено'); }
    catch (error) { toast(error.message, true); }
    return;
  }
  if (action === 'suggest-reply') {
    if (!canDraftAI()) return;
    try {
      const lastMessages = state.messages.slice(-6).map(message => `${message.direction === 'in' ? 'Подписчик' : 'Вы'}: ${message.body}`).join('\n');
      const result = await api('/ai/draft', { method: 'POST', body: JSON.stringify({ kind: 'reply', tone: 'friendly', prompt: 'Предложи короткий полезный ответ на последнее сообщение подписчика.', context: lastMessages }) });
      const input = root.querySelector('#replyForm input[name="body"]');
      if (input) { input.value = result.text || ''; input.focus(); toast('Черновик ответа готов — проверьте перед отправкой'); }
    } catch (error) { toast(error.message, true); }
    return;
  }
  if (action === 'confirm-send' || action === 'confirm-retry' || action === 'confirm-delete') {
    if (state.pending) return;
    state.pending = true;
    try {
      if (action === 'confirm-send') {
        await api(`/campaigns/${encodeURIComponent(id)}/send`, { method: 'POST' });
        toast('Кампания поставлена в очередь отправки');
      } else if (action === 'confirm-retry') {
        await api(`/campaigns/${encodeURIComponent(id)}/retry`, { method: 'POST' });
        toast('Неудачные отправки поставлены в очередь');
      } else {
        await api(`/${state.modal.kind}/${encodeURIComponent(state.modal.id)}`, { method: 'DELETE' });
        toast('Удалено');
      }
      state.modal = null;
      await loadAll({ silent: true });
    } catch (error) { toast(error.message, true); }
    finally { state.pending = false; render(); }
  }
}

root.addEventListener('click', event => {
  const nav = event.target.closest('[data-nav]');
  if (nav) { event.preventDefault(); navigate(nav.dataset.nav); return; }
  const action = event.target.closest('[data-action]');
  if (!action || action.disabled) return;
  if (action.classList.contains('modal-layer') && event.target !== action) return;
  event.preventDefault();
  doAction(action);
});

root.addEventListener('submit', async event => {
  const form = event.target;
  if (!form.id) return;
  event.preventDefault();
  if (state.pending) return;
  const values = Object.fromEntries(new FormData(form));
  state.pending = true;
  const submitter = event.submitter;
  if (submitter) submitter.disabled = true;
  try {
    if (form.id === 'loginForm') {
      await api('/login', { method: 'POST', body: JSON.stringify({ password: values.password }) });
      authVersion += 1;
      state.authGate = false; state.replyAttempts = readReplyAttempts();
      await loadAll();
      if (!state.authGate) toast('Добро пожаловать');
    } else if (form.id === 'accountImportForm') {
      if (!canUseAccounts()) throw new Error('Подключение аккаунтов недоступно в демо');
      const body = JSON.stringify({ session: values.session, label: values.label?.trim() || null });
      form.elements.session.value = '';
      values.session = '';
      const result = await api('/accounts', { method: 'POST', body });
      await loadAll({ silent: true });
      toast('Аккаунт подключён; сессия не сохраняется в браузере');
      await selectAccount(result.item.id);
    } else if (form.id === 'accountReplyForm') {
      if (!canUseAccounts() || !state.accountConversation?.can_send || replyAttemptFor(state.selectedAccount, state.selectedAccountDialog)) throw new Error('Отправка здесь недоступна');
      const accountId = state.selectedAccount;
      const dialogId = state.selectedAccountDialog;
      if (!accountId || !dialogId || !values.body?.trim()) throw new Error('Выберите диалог и напишите ответ');
      const requestId = crypto.randomUUID();
      rememberReplyAttempt(accountId, dialogId, requestId);
      try {
        const result = await api(`/accounts/${encodeURIComponent(accountId)}/dialogs/${encodeURIComponent(dialogId)}/reply`, {
          method: 'POST', body: JSON.stringify({ body: values.body.trim(), request_id: requestId }),
        });
        if (!Number.isSafeInteger(result.message?.id) || result.message.id < 1) throw new Error('Отправка не подтверждена; проверьте Telegram');
      } catch (error) {
        if ([400, 403, 404, 429].includes(error.status)) forgetReplyAttempt(accountId, dialogId, requestId);
        else if (error.status !== 401) {
          await selectAccountDialog(dialogId);
          const attempt = replyAttemptFor(accountId, dialogId);
          if (error.status === 409 && attempt?.status === 'missing') forgetReplyAttempt(accountId, dialogId, requestId);
          if (attempt?.status === 'sent') return;
        }
        throw error;
      }
      forgetReplyAttempt(accountId, dialogId, requestId);
      await selectAccountDialog(dialogId);
      toast('Ответ отправлен');
    } else if (form.id === 'campaignForm') {
      const target = values.target_type || 'subscribers';
      if (target === 'chat' && !values.chat_id) throw new Error('Выберите канал или группу');
      const payload = { title: values.title.trim(), body: values.body.trim(), target_type: target, chat_id: target === 'chat' ? values.chat_id : null };
      if (!payload.title || !payload.body) throw new Error('Укажите название и текст рассылки');
      const id = state.modal?.id;
      await api(id ? `/campaigns/${id}` : '/campaigns', { method: id ? 'PUT' : 'POST', body: JSON.stringify(payload) });
      state.modal = null; await loadAll({ silent: true }); toast(id ? 'Изменения сохранены' : 'Черновик сохранён');
    } else if (form.id === 'scheduleForm') {
      const date = new Date(values.scheduled_at);
      if (Number.isNaN(date.getTime()) || date.getTime() <= Date.now()) throw new Error('Выберите время в будущем');
      await api(`/campaigns/${state.modal.id}/schedule`, { method: 'POST', body: JSON.stringify({ scheduled_at: date.toISOString() }) });
      state.modal = null; await loadAll({ silent: true }); toast('Отправка запланирована');
    } else if (form.id === 'chatForm') {
      await api('/chats', { method: 'POST', body: JSON.stringify({ chat_id: values.chat_id.trim() }) });
      state.modal = null; await loadAll({ silent: true }); toast('Канал добавлен');
    } else if (form.id === 'ruleForm') {
      await api('/rules', { method: 'POST', body: JSON.stringify({ keyword: values.keyword.trim(), reply: values.reply.trim() }) });
      await loadAll({ silent: true }); toast('Автоответ добавлен');
    } else if (form.id === 'aiForm') {
      const response = await api('/ai/draft', { method: 'POST', body: JSON.stringify({ prompt: values.prompt.trim(), kind: values.kind, tone: values.tone }) });
      state.aiText = response.text || ''; render(); toast('Черновик готов');
    } else if (form.id === 'replyForm') {
      if (!values.body?.trim()) throw new Error('Напишите текст ответа');
      await api(`/inbox/${encodeURIComponent(state.selectedChat)}/reply`, { method: 'POST', body: JSON.stringify({ body: values.body.trim() }) });
      await selectChat(state.selectedChat);
      await loadAll({ silent: true }); toast('Ответ отправлен');
    }
  } catch (error) { toast(error.message, true); }
  finally {
    state.pending = false;
    if (submitter?.isConnected) submitter.disabled = false;
    else render();
  }
});

root.addEventListener('input', event => {
  if (event.target.dataset.search) {
    const name = event.target.dataset.search;
    const position = event.target.selectionStart;
    state.filters[name] = event.target.value;
    render();
    const input = root.querySelector(`[data-search="${name}"]`);
    input?.focus();
    try { input?.setSelectionRange(position, position); } catch { /* Search inputs need not support selection. */ }
  }
  if (event.target.id === 'campaignBody') {
    const preview = root.querySelector('#previewMessage');
    if (preview) preview.textContent = event.target.value || 'Ваше сообщение появится здесь…';
    const count = root.querySelector('#bodyCount');
    if (count) count.textContent = event.target.value.length;
  }
});

root.addEventListener('change', event => {
  if (event.target.name === 'target_type') {
    const group = root.querySelector('#chatTargetWrap');
    if (group) group.hidden = event.target.value !== 'chat';
  }
});

window.addEventListener('hashchange', () => {
  const route = location.hash.slice(1).split('?')[0] || 'overview';
  state.route = navItems.some(item => item.id === route) ? route : 'overview';
  state.sidebarOpen = false;
  render();
});

window.addEventListener('storage', event => {
  if (event.key !== authLockKey || !event.newValue) return;
  try { lockWorkspace({ signOut: JSON.parse(event.newValue).signOut === true }); }
  catch { lockWorkspace(); }
});

document.addEventListener('visibilitychange', () => {
  if (!document.hidden) recheckAuthorization();
});

document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && state.modal) { state.modal = null; render(); }
});

loadAll();
setInterval(() => {
  if (document.hidden || state.loading || state.authGate) return;
  if (state.route === 'accounts' || state.modal || state.pending || ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) {
    recheckAuthorization();
    return;
  }
  loadAll({ silent: true });
}, 30000);

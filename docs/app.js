const cases = {
  overlap: "I'm 28 and have a cough. I took Tylenol Regular Strength tablets. None of the listed health factors apply.",
  ambiguous: "I'm 28 and have a headache. I took Tylenol. None of the listed health factors apply.",
  warning: "I'm 45 and have a headache. I took Tylenol Extra Strength tablets. I have liver disease.",
};

const transcript = document.querySelector('#transcript');
const choices = document.querySelector('#choices');
const findings = document.querySelector('#findings');
const status = document.querySelector('#engine-status');
const input = document.querySelector('#message');
const send = document.querySelector('#send');
const reset = document.querySelector('#reset');
const presets = [...document.querySelectorAll('[data-case]')];
const controls = [input, send, reset, ...presets];
let products = {};
let ready = false;
let waiting = true;
const worker = new Worker(new URL('./chat-worker.js', import.meta.url), { type: 'module' });

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function sourceLink(name, url) {
  const anchor = element('a', name);
  anchor.href = url;
  anchor.target = '_blank';
  anchor.rel = 'noopener noreferrer';
  return anchor;
}

function appendBubble(text, kind, sources = []) {
  const bubble = element('article', '', `bubble ${kind}`);
  bubble.append(element('span', kind === 'bot' ? 'MEDLABEL' : 'YOU', 'speaker'), element('p', text));
  if (sources.length) {
    const links = element('div', '', 'links');
    links.append(...sources.map(([name, url]) => sourceLink(name, url)));
    bubble.append(links);
  }
  transcript.append(bubble);
  transcript.scrollTop = transcript.scrollHeight;
}

function renderChoices(reply) {
  choices.replaceChildren();
  choices.hidden = !reply.choices.length;
  if (choices.hidden) return;

  const option = (text, prominent = false) => {
    const button = element('button', text, prominent ? 'reply-btn primary' : 'reply-btn');
    button.type = 'button';
    button.addEventListener('click', () => sendMessage(text));
    return button;
  };

  if (reply.choices.length <= 5 || reply.status === 'confirm_intake') {
    choices.append(...reply.choices.map(text => option(text, text === 'Confirm details')));
    return;
  }

  const select = element('select');
  select.setAttribute('aria-label', reply.comparison.length ? 'Choose a product or case action' : 'Choose a suggested reply');
  select.append(new Option(reply.comparison.length ? 'Open a label or change the case' : 'Choose a reply', ''));
  select.append(...reply.choices.map(text => new Option(text, text)));
  select.addEventListener('change', () => {
    if (select.value) sendMessage(select.value);
  });
  choices.append(select);
}

function renderFindings(reply) {
  if (!reply.comparison.length) {
    if (['question', 'confirm_intake', 'verify_product', 'urgent', 'outside_scope'].includes(reply.status)) {
      findings.replaceChildren();
      findings.hidden = true;
    }
    return;
  }

  const rows = reply.comparison;
  const flagged = rows.filter(item => item.flags.length).length;
  const heading = element('h2', 'Label comparison');
  const detail = element('p', `${rows.length} exact labels · ${flagged} with case-specific flags. Review the source label for the full warnings.`);
  const table = element('table');
  table.setAttribute('aria-label', 'Versioned product labels and findings');
  const header = table.createTHead().insertRow();
  ['Exact product label', 'Active ingredients', 'Selected findings'].forEach(name => {
    const th = element('th', name);
    th.scope = 'col';
    header.append(th);
  });
  const body = table.createTBody();

  rows.forEach(item => {
    const product = products[item.key];
    const row = body.insertRow();
    const label = element('th');
    label.scope = 'row';
    label.append(sourceLink(product.product, product.label_url));
    row.append(label);
    row.insertCell().textContent = product.normalized_active_ingredients.split(' | ').join(', ');
    const result = row.insertCell();
    if (item.flags.length) {
      result.append(element('span', 'Review flag', 'badge'));
      result.append(...item.flags.map(flag => element('p', flag)));
    }
    if (item.notes.length) {
      result.append(element('span', 'Label note', 'badge note'));
      result.append(...item.notes.map(note => element('p', note)));
    }
    if (!item.flags.length && !item.notes.length) {
      result.append(element('p', 'No flag in these selected checks.'));
    }
  });

  const wrap = element('div', '', 'table-wrap');
  wrap.append(table);
  findings.replaceChildren(heading, detail, wrap);
  findings.hidden = false;
  requestAnimationFrame(() => findings.scrollIntoView({ block: 'nearest' }));
}

function setWaiting(next) {
  waiting = next;
  for (const control of controls) control.disabled = next || !ready;
  if (waiting) status.textContent = ready ? 'Comparing case details…' : 'Loading chat engine…';
  else status.textContent = ready ? 'Ready · Runs in your browser' : 'Chat engine unavailable';
  status.classList.toggle('ready', ready && !waiting);
}

function request(type, message) {
  setWaiting(true);
  choices.hidden = true;
  if (type === 'reset' || type === 'case') {
    transcript.replaceChildren();
    findings.replaceChildren();
    findings.hidden = true;
  }
  if (message) appendBubble(message, 'user');
  worker.postMessage({ type, message });
}

function sendMessage(value) {
  const message = value.trim();
  if (!ready || waiting || !message) return;
  input.value = '';
  request('message', message);
}

function highlightCase(selected) {
  for (const button of presets) {
    const active = button.dataset.case === selected;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
  }
}

document.querySelector('#composer').addEventListener('submit', event => {
  event.preventDefault();
  sendMessage(input.value);
});
reset.addEventListener('click', () => {
  highlightCase('');
  input.value = '';
  request('reset');
});
for (const button of presets) {
  button.setAttribute('aria-pressed', 'false');
  button.addEventListener('click', () => {
    highlightCase(button.dataset.case);
    input.value = '';
    request('case', cases[button.dataset.case]);
  });
}

function showError(message, terminal) {
  if (terminal) ready = false;
  setWaiting(false);
  appendBubble(message, 'bot');
}

worker.onmessage = ({ data }) => {
  if (data.type === 'error') {
    showError(data.message, !ready);
    return;
  }
  if (data.type === 'ready') {
    ready = true;
    products = data.products;
    transcript.replaceChildren();
  }
  setWaiting(false);
  appendBubble(data.reply.text, 'bot', data.reply.sources);
  renderChoices(data.reply);
  renderFindings(data.reply);
};
worker.onerror = () => showError('The chat engine could not load. Reload the page to try again.', true);

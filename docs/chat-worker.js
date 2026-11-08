import { loadPyodide } from './vendor/pyodide/pyodide.mjs';

async function readText(name) {
  const response = await fetch(new URL(name, import.meta.url));
  if (!response.ok) throw new Error(`Failed to load ${name}`);
  return response.text();
}

const setup = Promise.all([
  loadPyodide({ indexURL: new URL('./vendor/pyodide/', import.meta.url).href }),
  readText('catalog.csv'), readText('matcher.json'),
  readText('browser_runtime.py'), readText('engine.py'),
]).then(([runtime, catalog, index, adapter, engine]) => {
  runtime.globals.set('CATALOG_CSV', catalog);
  runtime.globals.set('MATCHER_JSON', index);
  runtime.runPython(adapter + '\n\n' + engine + '\n\nweb_chat = Chat()');
  const products = JSON.parse(runtime.runPython('json.dumps(catalog)'));
  const reply = JSON.parse(runtime.runPython('json.dumps(asdict(web_chat.reset()))'));
  self.postMessage({ type: 'ready', products, reply });
  return runtime;
});

setup.catch(() => self.postMessage({ type: 'error', message: 'The chat engine could not load. Reload the page to try again.' }));

self.onmessage = async ({ data }) => {
  try {
    const runtime = await setup;
    let reply;
    if (data.type === 'reset' || data.type === 'case') {
      reply = JSON.parse(runtime.runPython('json.dumps(asdict(web_chat.reset()))'));
    }
    if (data.type === 'message' || data.type === 'case') {
      runtime.globals.set('web_input', data.message);
      reply = JSON.parse(runtime.runPython('json.dumps(asdict(web_chat.submit(web_input)))'));
    }
    if (reply) self.postMessage({ type: 'reply', reply });
  } catch {
    self.postMessage({ type: 'error', message: 'The chat could not finish this turn. Start a new case or reload the page.' });
  }
};

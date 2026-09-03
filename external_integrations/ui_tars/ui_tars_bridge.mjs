import { GUIAgent } from '@ui-tars/sdk';
import { NutJSOperator } from '@ui-tars/operator-nut-js';

const task = process.argv.slice(2).join(' ').trim();
if (!task) {
  console.error('Task UI-TARS mancante.');
  process.exit(2);
}

const baseURL = process.env.UI_TARS_BASE_URL;
const apiKey = process.env.UI_TARS_API_KEY;
const model = process.env.UI_TARS_MODEL;
if (!baseURL || !apiKey || !model) {
  console.error('Impostare UI_TARS_BASE_URL, UI_TARS_API_KEY e UI_TARS_MODEL.');
  process.exit(3);
}

let lastData = null;
const guiAgent = new GUIAgent({
  model: { baseURL, apiKey, model },
  operator: new NutJSOperator(),
  onData: ({ data }) => { lastData = data ?? lastData; },
  onError: ({ error }) => { console.error(String(error)); },
});

try {
  const result = await guiAgent.run(task);
  let serializableResult = null;
  try {
    serializableResult = JSON.parse(JSON.stringify(result ?? null));
  } catch {
    serializableResult = String(result ?? '');
  }
  let serializableLast = null;
  try {
    serializableLast = JSON.parse(JSON.stringify(lastData ?? null));
  } catch {
    serializableLast = String(lastData ?? '');
  }
  console.log(JSON.stringify({
    ok: true,
    message: 'Task UI-TARS completato.',
    result: serializableResult,
    lastData: serializableLast,
  }));
} catch (error) {
  console.error(error?.stack || String(error));
  process.exit(1);
}

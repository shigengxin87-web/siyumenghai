import { env, pipeline } from 'https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.8.1';

env.allowRemoteModels = false;
env.allowLocalModels = true;
env.localModelPath = new URL('./assets/models/', self.location.href).href;

const MODEL_CONFIG = {
  model: 'whisper-base',
  options: { device: 'wasm', dtype: 'q8' }
};

let transcriber = null;

async function load() {
  try {
    self.postMessage({
      status: 'loading',
      data: '首次使用需下载约 80MB 识别模型（只下载一次）…'
    });
    transcriber = await pipeline('automatic-speech-recognition', MODEL_CONFIG.model, {
      ...MODEL_CONFIG.options,
      progress_callback: (progress) => self.postMessage(progress)
    });
    self.postMessage({ status: 'ready' });
  } catch (error) {
    self.postMessage({ status: 'error', message: error?.message || String(error) });
  }
}

async function run({ audio, language = 'zh' }) {
  try {
    if (!transcriber) await load();
    const result = await transcriber(audio, {
      language,
      task: 'transcribe',
      chunk_length_s: 30,
      stride_length_s: 5,
      return_timestamps: true
    });
    self.postMessage({ status: 'complete', result });
  } catch (error) {
    self.postMessage({ status: 'error', message: error?.message || String(error) });
  }
}

self.addEventListener('message', (event) => {
  const { type, data } = event.data || {};
  if (type === 'load') load();
  if (type === 'run') run(data || {});
});

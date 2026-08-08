/*
 * Chinese speech recognition worker.
 * sherpa-onnx + Paraformer-small run entirely in the browser via WebAssembly.
 * No audio or text is sent to an AI API.
 */

const ASSET_BASE = new URL('./assets/paraformer-zh-small/', self.location.href).href;
const isPthread = self.name?.startsWith('em-pthread');

let recognizer = null;
let vad = null;
let ready = false;

self.Module = {
  locateFile(path) {
    return new URL(path, ASSET_BASE).href;
  },
  setStatus(status) {
    if (isPthread || !status) return;
    const match = status.match(/Downloading data\.\.\. \((\d+)\/(\d+)\)/);
    if (match) {
      const loaded = Number(match[1]);
      const total = Number(match[2]);
      self.postMessage({
        status: 'progress',
        progress: total ? loaded / total * 100 : 0,
        loaded,
        total
      });
    } else {
      self.postMessage({ status: 'loading', data: status });
    }
  },
  onRuntimeInitialized() {
    if (isPthread) return;
    try {
      recognizer = new OfflineRecognizer({
        featConfig: { sampleRate: 16000, featureDim: 80 },
        modelConfig: {
          tokens: './tokens.txt',
          numThreads: Math.min(4, Math.max(1, navigator.hardwareConcurrency || 2)),
          provider: 'cpu',
          debug: 0,
          paraformer: { model: './paraformer.onnx' }
        },
        decodingMethod: 'greedy_search'
      }, Module);

      vad = createVad(Module, {
        sileroVad: {
          model: './silero_vad.onnx',
          threshold: 0.45,
          minSilenceDuration: 0.38,
          minSpeechDuration: 0.18,
          maxSpeechDuration: 24,
          windowSize: 512
        },
        tenVad: { model: '' },
        sampleRate: 16000,
        numThreads: 1,
        provider: 'cpu',
        debug: 0,
        bufferSizeInSeconds: 30
      });

      ready = true;
      self.postMessage({ status: 'ready' });
    } catch (error) {
      self.postMessage({ status: 'error', message: readableError(error) });
    }
  }
};

importScripts(
  './assets/paraformer-zh-small/sherpa-onnx-asr.js',
  './assets/paraformer-zh-small/sherpa-onnx-vad.js',
  './assets/paraformer-zh-small/sherpa-onnx-wasm-main-vad-asr.js'
);

function readableError(error) {
  return error instanceof Error ? error.message : String(error || '识别组件运行失败');
}

function recognize(samples) {
  const stream = recognizer.createStream();
  try {
    stream.acceptWaveform(16000, samples);
    recognizer.decode(stream);
    return String(recognizer.getResult(stream)?.text || '').trim();
  } finally {
    stream.free();
  }
}

function collectSpeechSegments(audio) {
  vad.reset();
  const windowSize = 512;
  for (let offset = 0; offset < audio.length; offset += windowSize) {
    const window = new Float32Array(windowSize);
    window.set(audio.subarray(offset, Math.min(offset + windowSize, audio.length)));
    vad.acceptWaveform(window);
  }
  vad.flush();

  const segments = [];
  while (!vad.isEmpty()) {
    const segment = vad.front();
    vad.pop();
    if (segment.samples.length >= 1600) segments.push(segment);
  }
  return segments;
}

async function transcribe(audio) {
  const speechSegments = collectSpeechSegments(audio);
  const source = speechSegments.length
    ? speechSegments
    : [{ samples: audio, start: 0 }];
  const results = [];

  for (let index = 0; index < source.length; index += 1) {
    const segment = source[index];
    const text = recognize(segment.samples);
    if (text) {
      results.push({
        text,
        start: segment.start / 16000,
        end: (segment.start + segment.samples.length) / 16000
      });
    }
    self.postMessage({
      status: 'recognizing',
      current: index + 1,
      total: source.length
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
  }

  return {
    text: results.map((item) => item.text).join('\n'),
    segments: results
  };
}

if (!isPthread) {
  self.addEventListener('message', async (event) => {
    if (event.data?.type === 'load') {
      if (ready) self.postMessage({ status: 'ready' });
      return;
    }
    if (event.data?.type !== 'run') return;
    if (!ready) {
      self.postMessage({ status: 'error', message: '中文识别模型尚未加载完成' });
      return;
    }

    try {
      const audio = event.data?.data?.audio;
      if (!(audio instanceof Float32Array) || !audio.length) {
        throw new Error('没有读取到视频声音');
      }
      const result = await transcribe(audio);
      self.postMessage({ status: 'complete', result });
    } catch (error) {
      self.postMessage({ status: 'error', message: readableError(error) });
    }
  });
}

/*
 * Chinese speech recognition worker.
 * sherpa-onnx + Paraformer-small run entirely in the browser via WebAssembly.
 * No audio or text is sent to an AI API.
 */

const ASSET_BASE = new URL('./assets/paraformer-zh-small/', self.location.href).href;
const ASSET_VERSION = '20260808-parallel-1';
const DATA_SIZE = 82547881;
const WASM_SIZE = 19267173;
const TOTAL_SIZE = DATA_SIZE + WASM_SIZE;
const isPthread = self.name?.startsWith('em-pthread');

let recognizer = null;
let vad = null;
let ready = false;
const assetLoaded = { data: 0, wasm: 0 };

function reportAssetProgress(kind, loaded) {
  assetLoaded[kind] = loaded;
  self.postMessage({
    status: 'progress',
    progress: (assetLoaded.data + assetLoaded.wasm) / TOTAL_SIZE * 100,
    loaded: assetLoaded.data + assetLoaded.wasm,
    total: TOTAL_SIZE
  });
}

async function responseBytes(response, expectedSize, onProgress) {
  if (!response.ok) throw new Error(`识别组件下载失败（${response.status}）`);
  if (!response.body) {
    const bytes = new Uint8Array(await response.arrayBuffer());
    onProgress(bytes.length);
    return bytes;
  }
  const chunks = [];
  const reader = response.body.getReader();
  let loaded = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    loaded += value.length;
    onProgress(Math.min(loaded, expectedSize));
  }
  const bytes = new Uint8Array(loaded);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.length;
  }
  return bytes;
}

async function loadAsset(filename, expectedSize, partCount, kind) {
  const url = new URL(`${filename}?v=${ASSET_VERSION}`, ASSET_BASE).href;
  const cache = typeof caches === 'undefined'
    ? null
    : await caches.open('siyumenghai-chinese-asr-v1').catch(() => null);
  const cached = cache ? await cache.match(url) : null;
  if (cached) {
    const bytes = new Uint8Array(await cached.arrayBuffer());
    if (bytes.length === expectedSize) {
      reportAssetProgress(kind, expectedSize);
      return bytes;
    }
    await cache?.delete(url);
  }

  const head = await fetch(url, { method: 'HEAD', cache: 'no-store' });
  const supportsRange = /bytes/i.test(head.headers.get('Accept-Ranges') || '');
  let bytes;
  let usedRanges = false;
  if (!supportsRange || partCount < 2) {
    bytes = await responseBytes(
      await fetch(url, { cache: 'no-store' }),
      expectedSize,
      (loaded) => reportAssetProgress(kind, loaded)
    );
  } else {
    usedRanges = true;
    const loadedParts = new Array(partCount).fill(0);
    const partSize = Math.ceil(expectedSize / partCount);
    const parts = await Promise.all(loadedParts.map(async (_, index) => {
      const start = index * partSize;
      const end = Math.min(expectedSize - 1, start + partSize - 1);
      const expectedPartSize = end - start + 1;
      const partUrl = `${url}&part=${index}`;
      const cachedPart = cache ? await cache.match(partUrl) : null;
      if (cachedPart) {
        const part = new Uint8Array(await cachedPart.arrayBuffer());
        if (part.length === expectedPartSize) {
          loadedParts[index] = part.length;
          reportAssetProgress(kind, loadedParts.reduce((sum, value) => sum + value, 0));
          return part;
        }
        await cache?.delete(partUrl);
      }
      const response = await fetch(url, {
        headers: { Range: `bytes=${start}-${end}` },
        cache: 'no-store'
      });
      if (response.status !== 206) throw new Error('当前网络不支持并行下载');
      const part = await responseBytes(response, expectedPartSize, (loaded) => {
        loadedParts[index] = loaded;
        reportAssetProgress(kind, loadedParts.reduce((sum, value) => sum + value, 0));
      });
      if (part.length !== expectedPartSize) throw new Error('识别组件分段下载不完整');
      if (cache) {
        try {
          await cache.put(partUrl, new Response(part));
        } catch {
          // Recognition can continue even if private mode prevents persistent cache writes.
        }
      }
      return part;
    }));
    bytes = new Uint8Array(expectedSize);
    let offset = 0;
    for (const part of parts) {
      bytes.set(part, offset);
      offset += part.length;
    }
  }

  if (bytes.length !== expectedSize) throw new Error('识别组件下载不完整，请重试');
  if (cache && !usedRanges) cache.put(url, new Response(bytes)).catch(() => {});
  return bytes;
}

self.Module = {
  locateFile(path) {
    return new URL(path, ASSET_BASE).href;
  },
  setStatus(status) {
    if (isPthread || !status) return;
    if (!status.startsWith('Downloading data')) {
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

async function bootstrap() {
  if (isPthread) {
    importScripts('./assets/paraformer-zh-small/sherpa-onnx-wasm-main-vad-asr.js');
    return;
  }
  try {
    const [data, wasm] = await Promise.all([
      loadAsset('sherpa-onnx-wasm-main-vad-asr.data', DATA_SIZE, 8, 'data'),
      loadAsset('sherpa-onnx-wasm-main-vad-asr.wasm', WASM_SIZE, 4, 'wasm')
    ]);
    Module.getPreloadedPackage = () => data.buffer;
    Module.wasmBinary = wasm;
    importScripts(
      './assets/paraformer-zh-small/sherpa-onnx-asr.js',
      './assets/paraformer-zh-small/sherpa-onnx-vad.js',
      './assets/paraformer-zh-small/sherpa-onnx-wasm-main-vad-asr.js'
    );
  } catch (error) {
    self.postMessage({ status: 'error', message: readableError(error) });
  }
}

bootstrap();

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

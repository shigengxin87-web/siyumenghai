class Utf8Decoder {
  constructor() { this.pending = [] }
  push(data) {
    const bytes = this.pending.concat(Array.from(new Uint8Array(data)))
    let text = '', i = 0
    while (i < bytes.length) {
      const b = bytes[i], size = b < 128 ? 1 : b >= 194 && b <= 223 ? 2 : b >= 224 && b <= 239 ? 3 : b >= 240 && b <= 244 ? 4 : 0
      if (!size) { text += '\uFFFD'; i++; continue }
      if (i + size > bytes.length) break
      let cp = b & (size === 1 ? 127 : (1 << (7 - size)) - 1), valid = true
      for (let j = 1; j < size; j++) { if ((bytes[i+j] & 192) !== 128) { valid = false; break } cp = (cp << 6) | (bytes[i+j] & 63) }
      if (!valid || cp > 0x10ffff || (cp >= 0xd800 && cp <= 0xdfff) || (size === 2 && cp < 128) || (size === 3 && cp < 2048) || (size === 4 && cp < 65536)) { text += '\uFFFD'; i++; continue }
      text += String.fromCodePoint(cp); i += size
    }
    this.pending = bytes.slice(i)
    return text
  }
}
class EventReader {
  constructor(onEvent) { this.buffer = ''; this.onEvent = onEvent }
  push(text, final) {
    this.buffer += text
    const lines = this.buffer.split('\n'); this.buffer = lines.pop()
    if (final && this.buffer.trim()) { lines.push(this.buffer); this.buffer = '' }
    for (const line of lines) { if (line.trim()) this.onEvent(JSON.parse(line)) }
  }
}
module.exports = { Utf8Decoder, EventReader }

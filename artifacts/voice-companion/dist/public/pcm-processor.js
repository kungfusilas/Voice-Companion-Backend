/**
 * AudioWorklet processor: captures mic samples and posts Int16 PCM chunks.
 *
 * The worklet runs at the AudioContext sample rate (typically 44100 or 48000 Hz).
 * We accumulate 100 ms worth of samples before posting to reduce message overhead,
 * then convert Float32 → Int16 in a single tight loop.
 *
 * The backend tells Deepgram the actual sample_rate, so no downsampling is needed.
 */
class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    // 100 ms buffer at the native sample rate
    this._chunkSize = Math.round(sampleRate * 0.1);
    this._buf = [];
    this._count = 0;
  }

  process(inputs) {
    const ch = inputs[0]?.[0];
    if (!ch) return true;

    this._buf.push(ch.slice()); // copy (the underlying buffer is reused)
    this._count += ch.length;

    if (this._count >= this._chunkSize) {
      // Merge accumulated chunks
      const merged = new Float32Array(this._count);
      let off = 0;
      for (const c of this._buf) {
        merged.set(c, off);
        off += c.length;
      }
      this._buf = [];
      this._count = 0;

      // Float32 → Int16
      const out = new Int16Array(merged.length);
      for (let i = 0; i < merged.length; i++) {
        const s = Math.max(-1, Math.min(1, merged[i]));
        out[i] = s < 0 ? s * 32768 : s * 32767;
      }
      // Transfer ownership — avoids copying in the structured-clone step
      this.port.postMessage(out.buffer, [out.buffer]);
    }
    return true;
  }
}

registerProcessor("pcm-processor", PCMProcessor);

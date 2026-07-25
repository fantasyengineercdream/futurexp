export const STEP_SAMPLE_RATE = 24_000;

export function floatToPcm16(input: Float32Array): Int16Array {
  return Int16Array.from(input, (value) => {
    const clamped = Math.max(-1, Math.min(1, value));
    return clamped < 0 ? Math.round(clamped * 32768) : Math.round(clamped * 32767);
  });
}

export function resampleLinear(input: Float32Array, fromRate: number, toRate = STEP_SAMPLE_RATE): Float32Array {
  if (fromRate === toRate) return input;
  const output = new Float32Array(Math.max(1, Math.round((input.length * toRate) / fromRate)));
  for (let index = 0; index < output.length; index += 1) {
    const position = (index * fromRate) / toRate;
    const left = Math.min(Math.floor(position), input.length - 1);
    const right = Math.min(left + 1, input.length - 1);
    const mix = position - left;
    output[index] = input[left] * (1 - mix) + input[right] * mix;
  }
  return output;
}

export function pcm16ToBase64(input: Int16Array): string {
  const bytes = new Uint8Array(input.buffer, input.byteOffset, input.byteLength);
  let binary = "";
  for (let index = 0; index < bytes.length; index += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
  }
  return btoa(binary);
}

export function base64ToPcm16(value: string): Int16Array {
  const binary = atob(value);
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  return new Int16Array(bytes.buffer);
}

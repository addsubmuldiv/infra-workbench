type RandomSource=Pick<Crypto,'getRandomValues'>&Partial<Pick<Crypto,'randomUUID'>>;

// macOS 12.0's system WebView predates crypto.randomUUID. Keep IDs random on
// that engine without relying on a user-agent string or Math.random.
export function browserId(source:RandomSource=globalThis.crypto):string{
  if(source.randomUUID)return source.randomUUID();
  const bytes=source.getRandomValues(new Uint8Array(16));
  bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
  const hex=Array.from(bytes,value=>value.toString(16).padStart(2,'0')).join('');
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}

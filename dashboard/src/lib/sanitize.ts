// Strips terminal escape sequences and control characters from attacker text.

// ESC [ params intermediates final  (CSI), also the single-byte C1 CSI (0x9B).
const CSI = /(?:\u001b\[|\u009b)[0-?]*[ -/]*[@-~]/g;
// ESC ] ... (BEL | ESC \ | ST 0x9C), also the single-byte C1 OSC (0x9D).
// eslint-disable-next-line no-control-regex
const OSC = /(?:\u001b\]|\u009d)[^\u0007\u001b\u009c]*(?:\u0007|\u001b\\|\u009c)/g;
// C0 (except \t 0x09 and \n 0x0A), DEL, and C1 controls.
// eslint-disable-next-line no-control-regex
const CONTROLS = /[\u0000-\u0008\u000b-\u001f\u007f-\u009f]/g;

export function stripControlChars(value: string): string {
  return value.replace(OSC, "").replace(CSI, "").replace(CONTROLS, "");
}

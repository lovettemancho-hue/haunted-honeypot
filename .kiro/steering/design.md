---
inclusion: fileMatch
fileMatchPattern: "dashboard/**"
---

# Design system: Ghost Hunter Cam

The dashboard looks like the viewfinder of a paranormal investigator's night-vision camcorder. The theme must serve the function: threat meters, timecodes and tape replays are real features, not decoration.

## Colour tokens
| Token | Hex | Use |
|---|---|---|
| `--bg` | `#111111` | Page background |
| `--bg-deep` | `#0B0B0B` | Header, control bars |
| `--panel` | `#1C1C1C` | Cards and panels |
| `--terminal` | `#050505` | Tape replay and code blocks |
| `--border` | `#3A3A3A` | Panel borders, dividers |
| `--border-soft` | `#2A2A2A` | Row dividers, empty meter segments |
| `--text` | `#F2F2F2` | Primary text |
| `--text-terminal` | `#D6D6D6` | Text inside terminals |
| `--muted` | `#A8A8A8` | Labels, secondary text (passes 4.5:1 on `--panel`) |
| `--hazard` | `#FFD400` | Primary accent: active nav, primary buttons, Class 5, viewfinder corners |
| `--hazard-dim` | `#B39500` | Mid meter segments |
| `--rec` | `#FF3B30` | REC dot, live indicators, highest-danger marks only |

Text on `--hazard` is always `#111111`. Never put white text on yellow.

## Typography
- **Chakra Petch** (500/600/700) for UI and headings. Headings and labels are UPPERCASE with 1–2px letter-spacing.
- **Share Tech Mono** for IPs, timecodes, commands, ATT&CK IDs and code.
- Load both from Google Fonts.

## Signature elements
- **Viewfinder corners:** 2px `--hazard` L-shaped brackets on hero panels (EMF meter, tape replay). Use sparingly, at most one or two per screen.
- **REC indicator:** red dot + Share Tech Mono timecode in the header.
- **EMF threat meter:** 10 vertical segments rising in height, coloured grey → `--hazard-dim` → `--hazard`; unused segments dashed.
- **Severity chips:** Class 5 = solid `--hazard` with dark text; Class 3 = `--hazard` outline; Class 1 = `--border` outline with `--muted` text.
- **GHOST tag:** small solid yellow tag marking responses invented by the LLM in replays.
- Faint horizontal scanline texture on the page background (very low opacity).

## Rules
- Square corners everywhere (no border radius), except the REC dot.
- No emoji, no gradients other than the scanline texture.
- Touch targets ≥ 44px. Real `<button>`, `<a href>`, `<input>` + `<label>` elements.
- Every themed term is paired with a plain-language description (see `product.md` vocabulary).
- Layouts must work at phone width: side panels stack, wide tables scroll horizontally inside their panel.
- Attacker-supplied strings are always shown in Share Tech Mono and escaped.

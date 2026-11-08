---
inclusion: fileMatch
fileMatchPattern: "dashboard/**"
---

# Design system: Frankenstein Lab Cam

The dashboard is the security camera of a mad scientist's lab: attackers are specimens being studied on the table. It keeps the camcorder foundations (REC timecode, live indicators, threat meter) and adds lab details (electric green, copper bolts, stitched seams). The theme must serve the function: the voltage meter, tapes and containment lever are real features, not decoration.

## Colour tokens
| Token | Hex | Use |
|---|---|---|
| `--bg` | `#0C110A` | Page background |
| `--bg-deep` | `#080C07` | Header, control bars |
| `--panel` | `#151C12` | Cards and panels |
| `--panel-inset` | `#111710` | Checklist rows, inset areas |
| `--terminal` | `#060904` | Tape replay and code blocks |
| `--border` | `#2E3B27` | Panel borders |
| `--border-soft` | `#222C1D` | Row dividers, empty meter track |
| `--seam` | `#4E5E44` | Stitched (dashed) seams and dashed chips |
| `--text` | `#EAF2E3` | Primary text |
| `--text-terminal` | `#D4E0CB` | Text inside terminals |
| `--muted` | `#A7B59C` | Labels, secondary text (passes 4.5:1 on `--panel`) |
| `--volt` | `#A6FF3D` | Primary accent: active nav, primary buttons, Class 5, headings |
| `--volt-dim` | `#6FA52F` | Mid meter segments |
| `--on-volt` | `#0C1405` | Text on `--volt` (never white on green) |
| `--copper` | `#C97B3A` | Bolts on hero panels, primary-button borders. Never for text. |
| `--rec` | `#FF3B30` | REC dot, live indicators, highest-danger marks only |

## Typography
- **Creepster** for page titles (H1) only, in `--volt`. Never for body text, labels or data.
- **Chakra Petch** (500/600/700) for UI and section headings. Section headings and labels are UPPERCASE with 1–2px letter-spacing.
- **Share Tech Mono** for IPs, timecodes, commands, ATT&CK IDs and code.
- Load all three from Google Fonts.

## Signature elements
- **Copper bolts:** 10–11px copper circles inset ~9px in the corners of hero panels (voltage meter, tape replay, containment call-out). At most two or three bolted panels per screen.
- **Stitched seams:** 2px dashed `--seam` lines as section separators, table header underlines and the replay control bar's top edge.
- **Header status:** REC dot + `REC · LAB 09 · <uptime>` in Share Tech Mono, and a `STATUS: IT'S ALIVE` badge outlined in `--volt` while the trap is running.
- **Lab voltage meter (threat):** 10 vertical segments rising in height, coloured `--border` → dim greens → `--volt`; unused segments are dashed outlines.
- **Severity chips:** Class 5 = solid `--volt` with `--on-volt` text; Class 3 = `--volt` outline; Class 1 = `--border` outline with `--muted` text.
- **STITCHED tag:** small solid `--volt` tag in replays marking responses the LLM invented ("stitched together by the AI").
- **Lightning-bolt logo** (stroke icon) next to the product name.

## Rules
- Square corners everywhere except the round bolts, the REC dot and live dots.
- No emoji. No gradients.
- Touch targets ≥ 44px. Real `<button>`, `<a href>`, `<input>` + `<label>` elements.
- Every themed term is paired with a plain-language description (see `product.md` vocabulary).
- Layouts must work at phone width: side panels stack, wide tables scroll horizontally inside their panel.
- Attacker-supplied strings are always shown in Share Tech Mono and escaped.

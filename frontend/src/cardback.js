// Generative back-of-card patterns for blind (Layer 1) cards. Per the design
// notes, every blind card gets its OWN pattern instead of one shared back
// image, to visually reinforce that even the owner doesn't know what's under
// any given card — no two backs match, so there's nothing to "recognize".
//
// The pattern is derived deterministically from a seed string (player id +
// slot index), so a card keeps its pattern across re-renders and reconnects
// instead of reshuffling visually every state frame.

// xmur3 string hash → 32-bit seed for the PRNG.
function hashString(str) {
  let h = 1779033703 ^ str.length
  for (let i = 0; i < str.length; i++) {
    h = Math.imul(h ^ str.charCodeAt(i), 3432918353)
    h = (h << 13) | (h >>> 19)
  }
  h = Math.imul(h ^ (h >>> 16), 2246822507)
  h = Math.imul(h ^ (h >>> 13), 3266489909)
  return (h ^= h >>> 16) >>> 0
}

// mulberry32 — tiny deterministic PRNG, plenty for decorative scatter.
function mulberry32(seed) {
  let a = seed
  return function () {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

// Deliberately stays inside the card-back teal family — the backs must read
// as "unknown", never compete with --gold (power) or --danger (forced) cues.
// Skewed light against the #1f3230 back: at 42px wide the pattern has to
// survive the blind row's dimmed state or the whole idea is invisible.
const INKS = ['#3a5c56', '#4e6f6a', '#6b8d86']

const SHAPE_TYPES = ['dot', 'ring', 'diamond', 'dash']

// Returns a plain description of the pattern (not JSX) so the generator can
// be unit-eyeballed in isolation and the Card component stays presentational.
export function generateBackPattern(seed) {
  const rand = mulberry32(hashString(String(seed)))
  const shapes = []
  const count = 9 + Math.floor(rand() * 6)
  for (let i = 0; i < count; i++) {
    shapes.push({
      type: SHAPE_TYPES[Math.floor(rand() * SHAPE_TYPES.length)],
      x: 4 + rand() * 34,
      y: 5 + rand() * 48,
      size: 2.5 + rand() * 4,
      rotate: Math.floor(rand() * 360),
      ink: INKS[Math.floor(rand() * INKS.length)],
      opacity: 0.55 + rand() * 0.4,
    })
  }
  return shapes
}

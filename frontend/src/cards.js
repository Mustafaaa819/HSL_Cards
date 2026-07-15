// Card specs are the wire format from docs/WS_PROTOCOL.md: "<rank><suit>",
// ranks 2-10 J Q K A, suits C D H S. Everything the UI knows about a card
// derives from the spec string here, so real SVG assets later only need a
// spec -> asset-path lookup in the Card component.
const SUIT_SYMBOLS = { C: '♣', D: '♦', H: '♥', S: '♠' }
const RANK_ORDER = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
const POWER_RANKS = new Set(['2', '7', '10', 'J'])

export function parseCard(spec) {
  const suit = spec.slice(-1)
  const rank = spec.slice(0, -1)
  return {
    spec,
    rank,
    suit,
    symbol: SUIT_SYMBOLS[suit] ?? '?',
    red: suit === 'H' || suit === 'D',
    power: POWER_RANKS.has(rank),
  }
}

export function prettyCard(spec) {
  const { rank, symbol } = parseCard(spec)
  return `${rank}${symbol}`
}

// Display-only sort (rank low->high, suit as tiebreaker). The server doesn't
// care about hand order; this just keeps a big post-pickup hand scannable.
export function sortHand(specs) {
  const rankIndex = (spec) => RANK_ORDER.indexOf(parseCard(spec).rank)
  return [...specs].sort((a, b) => {
    const byRank = rankIndex(a) - rankIndex(b)
    return byRank !== 0 ? byRank : a.localeCompare(b)
  })
}

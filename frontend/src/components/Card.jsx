import { parseCard } from '../cards.js'

// The ONE component every card in the UI renders through. Phase 6 swaps the
// placeholder face (rank + suit text) for real SVG card assets here, and
// nowhere else. `hidden` renders a card back (blind cards, opponents' hands).
//
// Sizes: xs (opponent face-up minis) / sm (own blind + face-up rows) /
// md (own hand) / lg (top of the discard pile).
export default function Card({ spec, hidden = false, size = 'md', dimmed = false, onClick, label }) {
  const interactive = typeof onClick === 'function'
  const Tag = interactive ? 'button' : 'div'

  const classes = ['card', `card--${size}`]
  if (dimmed) classes.push('card--dimmed')

  if (hidden) {
    classes.push('card--back')
    return (
      <Tag
        type={interactive ? 'button' : undefined}
        className={classes.join(' ')}
        onClick={onClick}
        aria-label={label ?? 'Face-down card'}
      >
        <span className="card-back-mark" aria-hidden="true">✦</span>
      </Tag>
    )
  }

  const { rank, symbol, red, power } = parseCard(spec)
  classes.push('card--face', red ? 'card--red' : 'card--black')
  if (power) classes.push('card--power')

  return (
    <Tag
      type={interactive ? 'button' : undefined}
      className={classes.join(' ')}
      onClick={onClick}
      aria-label={label ?? `${rank}${symbol}`}
    >
      <span className="card-rank">{rank}</span>
      <span className="card-suit" aria-hidden="true">{symbol}</span>
    </Tag>
  )
}

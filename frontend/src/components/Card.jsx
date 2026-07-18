import { useMemo } from 'react'
import { parseCard } from '../cards.js'
import { generateBackPattern } from '../cardback.js'

// The ONE component every card in the UI renders through. A later phase swaps
// the placeholder face (rank + suit text) for real SVG card assets here, and
// nowhere else. `hidden` renders a card back (blind cards, opponents' hands).
// A hidden card with a `patternSeed` gets its own generated back pattern —
// used for blind Layer 1 cards, where even the owner doesn't know the card,
// so no two backs should look alike.
//
// Sizes: xs (opponent face-up minis) / sm (own blind + face-up rows) /
// md (own hand) / lg (top of the discard pile).
//
// `rejected` marks the card the server just refused — the toast says why,
// this says which. `selected` marks a card picked into a pending
// multi-card throw (GameScreen's "Throw multiples" mode).
export default function Card({
  spec,
  hidden = false,
  patternSeed = null,
  size = 'md',
  dimmed = false,
  rejected = false,
  selected = false,
  onClick,
  label,
}) {
  const interactive = typeof onClick === 'function'
  const Tag = interactive ? 'button' : 'div'

  const classes = ['card', `card--${size}`]
  if (dimmed) classes.push('card--dimmed')
  if (rejected) classes.push('card--rejected')
  if (selected) classes.push('card--selected')

  if (hidden) {
    classes.push('card--back')
    return (
      <Tag
        type={interactive ? 'button' : undefined}
        className={classes.join(' ')}
        onClick={onClick}
        aria-label={label ?? 'Face-down card'}
      >
        {patternSeed != null ? (
          <BackPattern seed={patternSeed} />
        ) : (
          <span className="card-back-mark" aria-hidden="true">✦</span>
        )}
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

// Scatter pattern is scaled by the viewBox, so one 42×58 coordinate space
// works for every card size. Memoized: the scatter is deterministic per
// seed, so there's no reason to regenerate it on every state frame.
function BackPattern({ seed }) {
  const shapes = useMemo(() => generateBackPattern(seed), [seed])
  return (
    <svg
      className="card-back-pattern"
      viewBox="0 0 42 58"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
    >
      <rect x="3" y="3" width="36" height="52" rx="3" fill="none" stroke="#34504c" strokeWidth="1" />
      {shapes.map((s, i) => {
        const common = { fill: s.ink, opacity: s.opacity }
        if (s.type === 'dot') {
          return <circle key={i} cx={s.x} cy={s.y} r={s.size / 2} {...common} />
        }
        if (s.type === 'ring') {
          return (
            <circle
              key={i}
              cx={s.x}
              cy={s.y}
              r={s.size / 2}
              fill="none"
              stroke={s.ink}
              strokeWidth="0.8"
              opacity={s.opacity}
            />
          )
        }
        if (s.type === 'diamond') {
          const h = s.size / 2
          return (
            <path
              key={i}
              d={`M ${s.x} ${s.y - h} L ${s.x + h} ${s.y} L ${s.x} ${s.y + h} L ${s.x - h} ${s.y} Z`}
              {...common}
            />
          )
        }
        return (
          <rect
            key={i}
            x={s.x - s.size / 2}
            y={s.y - 0.5}
            width={s.size}
            height="1"
            transform={`rotate(${s.rotate} ${s.x} ${s.y})`}
            {...common}
          />
        )
      })}
    </svg>
  )
}

# Card art provenance

Base artwork: "Vector Playing Card Library" v3.2 by Chris Aguilar
(https://totalnonsense.com/open-source-vector-playing-cards/), licensed under
LGPL 3.0 (https://www.gnu.org/licenses/lgpl-3.0.html).

These 52 files are the "STANDARD BORDERED / Single Cards" set, recolored to
match the project's dark theme. The recolor is a straight find-and-replace of
fill colors, using the exact mapping the original artist already shipped in
their own "Inverted" color variant (derived by diffing that variant against
the standard color sheet, not guessed):

| Original (COLOR)     | Recolored             | Role                        |
|-----------------------|------------------------|------------------------------|
| default/none (black)  | `#ffffff`              | suit ink, rank text          |
| `#000000`, `#100f08`  | `#ffffff`              | explicit black ink           |
| `#c8102e`              | `#d40000`              | red suit ink                 |
| `#ffaaaa`              | `#ff5555`              | red shading tint             |
| `#004c97`              | `#f6f6f6`              | face-card blue accent        |
| `#ffcd00`              | `#000000`              | face-card gold accent        |
| `#006614`              | `#000000`              | minor/hidden accent          |
| card body background   | `fill:none` (transparent) | lets the app's own dark card container (`#14181A`) show through instead of baking in a flat color |

No jokers included — the game uses a plain 52-card deck.

Filenames follow the game's own wire format from `docs/WS_PROTOCOL.md`:
`<rank><suit>.svg`, ranks `2-10 J Q K A`, suits `C D H S` (e.g. `10H.svg`,
`AS.svg`, `JC.svg`).

Regenerate with `reskin.py` (see chat history / project notes) if the source
Vector Cards pack or the mapping ever needs to change.

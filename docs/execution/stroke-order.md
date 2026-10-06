# Stroke order

Written by an AI agent, not by hand. It records the choices taken while drawing the stroke order on
cards, which Bru asked for on 2026-10-06. [The design](../instructions/design.md) remains the source
of truth: where this contradicts it, the design wins and the code is wrong.

> Kanji have a specific writing order. […] Whenever a card is just one symbol, I want it fetched and
> included in the card.

## What gets a drawing

**Any card whose term is one character, in a language decker has an order for**: `Symbol: 所`, the
kana `あ`, and the word 人 as much as the shape, because a card whose answer is one character is
asking the learner to write that character. A word of two characters gets nothing: its order is its
characters' orders, and each of those is its own card under `--teach-script`. A concept or a rule
is prose and never a character, whatever its length.

The drawing is on the **answer of both cards**, under the readings. On the production card's
question it would be the answer.

It is on by default — the request was *automatically* — and `--no-strokes` turns it off. A deck
that has no character to draw downloads nothing.

## The order is the language's, not the character's

The same character is written differently in Japan, the PRC and Taiwan — 必, 田, 生 and 馬 are the
classic cases — so the source is chosen by **`--target-lang`**, never by the character or by the
Wiktionary section that glossed it. A kanji glossed from Translingual in a Japanese deck is still
drawn the Japanese way.

| target | source | covers | licence |
|---|---|---|---|
| `ja` | [KanjiVG](https://kanjivg.tagaini.net), release `r20260714` | kanji, hiragana, katakana — 6,700 files | CC BY-SA 3.0 |
| `zh`, `zh-hans`, `zh-hant` | [Make Me a Hanzi](https://github.com/skishore/makemeahanzi) `graphics.txt` | 9,574 hanzi, PRC order | Arphic Public License |

- **KanjiVG's file is used nearly as it is**, numbers and licence comment included; only the
  direction arrows below are added, and the comment says so. Only the scripts the deck is teaching
  to write are drawn — a Latin `A` or a digit in a Japanese text is in KanjiVG too,
  and is not drawn.
- **Make Me a Hanzi has outlines, not drawings**, so decker draws them: filled strokes, a red number
  at each stroke's first median point, nudged up and left so it sits off the stroke. Checked by
  rendering 我, whose seven strokes come out in the standard order.
- **Every stroke shows its direction**, which the first version did not — the numbers said where a
  stroke starts and nothing said where it goes, Bru's catch the same day. The strokes are drawn grey,
  and over each runs a dashed red line ending in an arrowhead, as twpen draws it. Nothing is guessed:
  KanjiVG's paths and Make Me a Hanzi's medians are both recorded in the order the brush moves, so
  the arrow is the data drawn again, thinner. The numbers go on top, in near-black, so no arrow
  hides one.
- **Traditional characters get the PRC order.** Make Me a Hanzi covers them, but Taiwan's standard
  differs for a minority of characters, and no openly licensed Taiwanese set was found. A `zh-hant`
  deck is therefore occasionally drawn in the mainland hand; it is the one known inaccuracy.
- **Cantonese (`yue`) is not drawn**: Hong Kong's order is a third standard, and drawing the PRC's
  would be a card that looks right and teaches the wrong hand. Korean, and the alphabets, have no
  source yet.

## What it does not use, and why

**twpen.com**, which Bru pointed at, draws exactly the picture asked for, but it was turned down on
two counts. Its pages say *版權所有* — all rights reserved — and a deck is something a learner
shares; and it is a Taiwanese site drawing Taiwan's order, which for a Japanese deck is the wrong
standard on precisely the characters where the standards disagree.

**No per-character fetch from anywhere.** Each source is one archive (12 MB and 30 MB), downloaded
once into `~/.cache/decker/strokes/` and read locally. Asking a server for each character a text
contains would tell it what the text is, which is what a mirror run exists to avoid; one archive
asked for once says only that the reader studies Japanese. The download goes through the same
helper as the title dump (`wiktionary.download`), waiting out a dropped host the same way.

## In the deck

- The drawing is an SVG media file named `decker-strokes-<source>-<codepoint>-d<N>.svg`: Anki keeps
  every deck's media in one folder by bare name, so the name says whose it is — and which drawing,
  `DRAWING` in `decker/strokes.py`. A collection holding a file of that name keeps its own copy, so a
  drawing decker has since changed (the arrows were `d2`) has to arrive under a new name.
- A `Strokes` field is **appended** to both note types, as `Equivalent` and `Readings` were, so a
  collection that already holds decker's note types gains a column rather than having its existing
  ones renumbered. Note identities do not change: a rebuilt deck updates the notes it made.
- In night mode the drawing is inverted, since both sources draw black strokes on nothing.
- The licence travels as Wiktionary's does: a `Stroke order: …` line under the card's Wiktionary
  credit, and once in the deck's description.

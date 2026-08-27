# v1 design

## Source format normalization

Omit. Expect text as input.

We'll also assume English as the mother language.

## Sentencing and term extraction

Merge both through the use of Stanza, which already divides input into sentences.

### Term extraction

Terms are gonna be Wiktionary page titles, identified by their Universal Dependencies' dependency
tree.

#### One-time setup

Download the whole list of English Wiktionary page titles. For each, apply Stanza, and from the
dependency tree produce its UD dependency tree, where the arrow's label (deprel) are represented as
mere nodes, and store them (pointing to the original page title).

Optimizations may come later.

#### Subtree identification

For every sentence, find all Wiktionary trees that are subtrees of the sentence. Then, discard every
Wiktionary subtree that's a subtree of another Wiktionary subtree that has been identified. It's
okay, however, if two subtrees have share a branch.

From the resulting set of trees, extract their Wiktionary page titles. Those are terms corresponding
to that sentence.

## Definition fetching

Wiktionary *first*. Form-of entries are welcome. Fetch all that is available:
- Etymology
- IPA phonetics
- Definition
- Examples
- Actual audio

The whole page should be cached (without audio).

Sense disambiguation must be done via ollama to a local parametrizable model. Default: "gemma4".

### Test cases

Do not test.

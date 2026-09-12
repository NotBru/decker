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

Optionally, allow the use of Wiktionary mirrors (such as a local one, which may incidentally lack
audio). This serves a privacy concern.

The whole page should be cached (without audio), keyed independently of the mirror.

Sense disambiguation must be done via ollama to a parametrizable model. Default: "gemma4".

Only word definitions create a production pair. Concept and morphological rules cards (explained
below) don't.

### Concept identification

We identify concepts as any of the entries in Wiktionary's `Appendix:Glossary`. Detection is done
through any link to them **inside the definition**, and should produce a `Concept: {concept}` card
*without a production pair*.

This includes many concepts that the reader may already know, such as “colloquial” but saturates
quickly: there are only a few hundred of these.

The concept card's titles and explanations must be translated to the mother language.

### Morphological rules

We'll define morphological rules as rules that take a basic word (either the lemma, or the one
another is derived from in e.g. a diminutive) and take it to a feature bundle (Wiktionary's form-of
prose, normalized to their concept).

A database of the following should be kept:
- Feature bundle
- Representative word
- Rule description
- Target language

For every new word, an LLM is prompted as to whether any of the existing rules (for that
feature-bundle and target language) apply. If not, another prompt defines whether there exists a
regular rule from the base word to the feature bundle that this word is obeying. If so, that word
becomes a representative of a new rule, that's subsequently associated to the feature bundle and
representative word pair. The rule that's being obeyed is written by the LLM as well.

For rules that are already explained, particular instances should be kept according to the following
rule: keep the first 4 such examples of a rule, then halve the frequency every 4 *shown* examples.
Dropping an example means keeping the base word's card but not the current instance.

The explanation card should depend on the first 2 examples, so that it appears only after the user
has been exposed to them.

The rules should be translated to the mother language.

## Deck construction

No further notes on the overall design.

Translate via ollama as above. Default "gemma4" as well.

## Shuffling and Anki output

No further notes on the overall design.

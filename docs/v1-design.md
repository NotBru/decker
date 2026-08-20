# v1 design

## Source format normalization

Omit. Expect text as input.

## Sentencing and term extraction

Merge both through the use of Stanza, which already divides input into sentences.

### Term extraction

Terms are gonna be Wiktionary page titles, identified by a binary tree corresponding to a normalized
polish notation representation of the Universal Dependencies' dependency tree that Stanza produces
for them.

#### One-time setup

Download the whole list of Wiktionary page titles. For each, apply Stanza, and from the dependency
tree produce its UD dependency tree, where the arrow's label are represented as mere nodes, and
store them (pointing to the original page title).

Optimizations may come later.

#### Subtree identification

For every sentence, find all Wiktionary trees that are subtrees of the sentence. Then, discard every
Wiktionary subtree that's a subtree of another Wiktionary subtree that has been identified. It's
okay, however, if two subtrees have share a branch.

From the resulting set of trees, extract their Wiktionary page titles. Those are terms corresponding
to that sentence.

### Test cases

Do not test.

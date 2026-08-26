# Design document

The tool is a pipeline.

## Stage overview

### 1. Source format normalization

#### Input

The original media

#### Output

A string with the transliteration of all that is in the target language in the original media

### 2. Sentencing

#### Input

Source format normalization's output

#### Output

A list of strings, each of which should be a sentence

### 3. Term extraction

#### Input

Sentencing's output

#### Output

List of `(sentence, list of terms)` pairs (all the sentences), where the list of terms contains
all the terms that appear in the sentence, in the inflected form they appear in.

### 4. Definition fetching

#### Input

Term extraction's output, and optionally a pre-existing list of glosses (defined below).

#### Output

A list of glosses

Each gloss is composed by:
- The actual form its corresponding term takes in the text
- The lemmatized form of the term
- Data
  - Etymology
  - IPA phonetics
  - Definition
  - Examples
- A set of glosses this gloss may depend upon


The stage makes, for every term in the received list of terms, at least one gloss corresponding to
it. If it's inflected, it should also fetch and make another gloss for precisely the lemmatized
form, upon which the inflected one depends.

The inflected gloss' definition should explain its relationship to the lemmatized one. E.g., for
“corrió”, it should explain that it's the indicative past tense for “correr” in first person.

Glosses *must not* be repeated (as identified by their actual form in the source and definition).

The glosses' index must be increasing with their ocurrence in the original source.

This stage must do sense disambiguation from the Wiktionary page, so as not to clog the produced
cards with useless translations.

### 5. Deck construction

#### Input

Definition fetching's output

#### Output

A list of cards.

For every gloss, it should make at least two cards:
- Recognition card
  - Challenge
    - Term as it appears in the source
    - Examples
  - Answer
    - Etymology
    - IPA phonetics
    - Definition
  - Dependencies
- Production card
  - Challenge
    - Definition
  - Answer
    - Term as it appears in the source
    - IPA phonetics
    - Etymology
  - Dependencies

The production card must depend on the recognition card. This stage will later also have a
translation stage, in case the fetched language doesn't match the mother language.

### 6. Shuffling

#### Input

Deck consturction's output

#### Output

A list of shuffled cards, with two properties:

- A card's dependency appears necessarily before. Use stable topological sort keyed by shuffled
  indexes.
- The shuffling only happens inside windows of 20 cards

### 7. Anki output

#### Input

Shuffling's output

#### Output

Dump an Anki deck to disk

## Future possibilities

### Concept identification

#### Input

Definition fetching's output

#### Output

A longer list of cards.

For every card whose lemmatized form differs from the actual form, its definition should have been a
description of how the card relates to the lemma. The terminology inside is usually from linguistics,
for example “dative plural of Hund”. Here, both “dative” and “plural” don't convey meaning but
rather the features of that particular instance. Each of these terms (or them altogether) are thus a
dependency of the original card.

Thus, the terminology should acquire their own cards, and the original card should be made dependent
on that. However, only when the mother language doesn't feature the same concept already.

### Inflection rules

#### Input

Concept identification's output

#### Output

A less redundant list of cards.

Whenever there's a closed rule for a given inflection, the rule should be explained in a card a few
cards after the first three examples.

### Etymology resolution

This stage could actually fetch the etymology up until a point where it's explained in the mother
language.

## Details

### V1

See [v1 design doc](./v1-design.md).

## Test cases

See [test cases](./test-cases.md) document.

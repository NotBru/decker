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

### 3. Word extraction

#### Input

Sentencing's output

#### Output

List of `(sentence, list of terms)` pairs (all the sentences), where the list of terms contains
all the terms that appear in the sentence, lemmatized.

### 4. Definition fetching

#### Input

Word extraction's output

#### Output

A list of cards.

Each card is composed by:
- Its index
- Its lemmatized form
- Its actual form in the text (it may be already lemmatized)
- The data that'll be available in Anki (definition, audio, IPA, examples)

For every lemmatized term, a card is introduced with its data. If the original term is inflected, an
inflected card should be introduced as well.

The inflected card should explain its relationship to the lemmatized one. E.g., for “corrió”, it
should explain that it's the indicative past tense for “correr” in first person.

Cards *must not* be repeated.

### 5. Shuffling

#### Input

Definition fetching's output

#### Output

A list of shuffled index, with two properties:

- A card's dependency appears necessarily before
- The shuffling only happens inside windows of 20 cards

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

## Details

### Definition fetching

The main source of truth here must be Wiktionary. The inflected form must be looked up first

All lookups must be cached.

## Test cases

See [test cases](./test-cases.md) document.

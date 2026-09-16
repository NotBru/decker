# Words Wiktionary has no entry for

`docs/instructions/` is the source of truth: where this contradicts the design, the design wins and
this document is what needs correcting. **This stage adds a card type the design does not describe**
— a word explained by a model rather than quoted from Wiktionary — on Bru's instruction of
2026-09-16. If the design should say so, that is the human's to write.

## What it is for

Every run over real text has terms the definer cannot gloss. The ten-language survey counted them:
eighteen distinct in the Spanish sample, twenty in the Japanese. decker's answer was to print a line
and drop the word, which is right for most of them and wrong for two kinds — a misspelling, where the
learner loses a word of the text for a reason that has nothing to do with them, and a foreign word
the reader would not know, where no entry exists because it is not a word of the language and the
reader is stuck anyway.

So: one model call per distinct entry-less surface, asking which of four things it is, and acting.

| answer | what happens |
|---|---|
| `misspelling` | the word that was meant is looked up and glossed, and the card is fronted with *that* spelling — a card teaching the text's typo would teach the typo |
| `foreign`, widely known | dropped; `pizza` in a German text needs no card |
| `foreign`, not known | taught, with the model's one-sentence explanation |
| `native` | a word of the language the dictionary lacks — regional, rare, very new — taught the same way |
| `unrecognizable` | dropped, as before |

`--unknowns off` restores the old behaviour, `fix` is the default above, and `all` also teaches the
foreign words a reader is expected to know. The explanation is asked for in English and the
translation stage turns it into the mother language afterwards, exactly as a morphological rule's
prose is handled.

A card made this way **credits the model and links nowhere**: there is no entry — that is what put the
word here — so `anki.py` prints the attribution alone rather than a Wiktionary link and a licence
that covers none of its text, and the card carries no production pair, a learner not being able to
produce a foreign word from a sentence about it.

## The two measurements that shaped it

**A three-way split has nowhere to put a word of the language.** The first version offered
`misspelling`, `foreign` and `unrecognizable`. Asked where `perro` belonged, `qwen3.5:4b` answered
*foreign, and widely known* — the answer that throws a word away. A word the extractor found, the
parser lemmatised, and Wiktionary has no page for is the most interesting thing this stage sees, so
`native` was added, and `perro` then came back as native, "It means 'dog'".

**The first prompt produced fabrications, and the real distribution is what showed it.** Run over the
eighteen entry-less terms of the survey's Spanish sample, `qwen3.5:4b` called `und` *a Spanish word
meaning 'and'* and `petite` *little, in Spanish*. Both would have become cards, and a learner cannot
tell a confident wrong card from a right one. Roughly seven of sixteen were right.

The prompt now says outright that a word printed inside a Spanish text is not thereby a Spanish word,
requires `native` only where the model is confident speakers use it as their own, asks a foreign word
to name its language, and says that an explanation it is unsure of is worse than no card. On the same
sixteen:

| | `qwen3.5:4b` | `gemma4:latest` |
|---|---|---|
| fabricated a word of the language | **0** (was 2) | 0 |
| dropped as foreign-and-known | 9 | 9 |
| taught with an explanation | 3 | 5 |
| dropped as unrecognizable | 2 | 0 |

`und` is the one that separates them: `gemma4:latest` says *it means 'and' in German*, `qwen3.5:4b`
takes it for a fragment and drops it. Dropping is the cheaper error and the default model makes it.

## What it does not fix

The explanations are a model's, with a model's accuracy. Asked about `chirola` — Rioplatense slang
for loose change — `qwen3.5:4b` invented *a species of bird*. Nothing in the stage can catch that;
what the card does is say who wrote it, the same admission a rule card makes. The stage's own
judgement of "widely known" is likewise a judgement: `verre` and `petite` are dropped as household
words, which for a Spanish learner they are not. `--unknowns all` is the lever for a reader who would
rather see them.

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
| `misspelling` | the word that was meant is looked up and glossed, and the card is fronted with *that* spelling — a card teaching the text's typo would teach the typo; a word drawn out for effect (`すげー`, `けどぉ`) counts, corrected to the word without the stretch |
| `name` | a person, place, group or thing in the text, whatever its language — taught with one sentence that starts with the name in Latin letters and says what kind of name it is, and nothing about the story |
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

## Some of these words are the fetcher's fault, not the dictionary's

A word arriving here is a claim that Wiktionary has no entry, and the claim can be wrong. `грез` in a
Russian text was asked about and came back *a Polish word*. No lever in this stage improves that,
because the entry exists and the lookup was at fault twice over: the lemma `греза` is a redirect to
`грёза`, which the fetcher read as a page with no senses, and the form `грез` is spelled `грёз` in
the dictionary, which the title lookup never tried. Bru found it, 2026-09-16; both are fixed, in
[Definition fetching](definition-fetching.md) and [Term extraction](term-extraction.md).

Asking the model harder would not have worked, and it is worth saying why, because the obvious
reading of that bug is that the fallback should have spotted a typo. It is not a typo. Asked plainly,
`qwen3.5:4b` answers that `грез` is a Russian word meaning *dreams* — `native`, no correction — and
it is right: `е` for `ё` is how Russian is printed. The disagreement is between the text's spelling
and the dictionary's, which is a fact to look up and not a judgement to make. The stage is the last
resort, so a wrong answer here is worth reading as a question about the stage before it.

## Words with no page at all, and names (2026-10-18)

Until this date only a term that matched *some* title reached the stage — a page that exists, with no
section in the language. A word that matched no title was never a term: it was not glossed, not
asked about, and not mentioned even at `-vv`. On Gokurakugai that was `タオ`, the name of the man
the first page is calling for, while the `さん` after it was carded; and 74 other surfaces —
`アルマ`, `ユキ`, `西雪` and the other names; `すげー`, `ずーっと` and every other drawn-out word;
`メシ`, `テメエ`, `臭え`; `獣人`, `手描き`; the sound effects. That is the silent drop Bru ruled out
(no degraded runs, 2026-10-18), so term extraction now makes each run of untitled tokens a term with
no entries, and it comes here like any other entry-less term. The cost on that volume is 106 more
occurrences, 75 distinct, so 75 calls: a fraction of a cent on Haiku.

`name` is the answer that made this worth doing. Asked before it existed, a model files a name under
`foreign` (`タオ` is Chinese) or `native`, and the old prompt told it outright that a foreign name
stays foreign; neither says what a reader needs, which is that the word is *somebody*. The prompt
asks for the name romanized first because the first wording, "giving it in Latin letters", came back
as "Tao is a name in Latin letters, here written in katakana as the name of a character speaking" —
and Tao is spoken *to*.

**No spoilers.** The first wording asked for whom a name names "as far as the passage shows", and
`タオ` came back as the man who answers the office's phone. Bru, the same day: no context in an
explanation. The prompt now says an explanation says what the word is and never what happens in the
text — no character, event or place of the story, nothing about who speaks to whom — since the card
is read before the story. `タオ` is now "Tao is a given name, used here for a character." The
passage is still sent: it is what the kind of word is judged by.

That rule had two holes, found by the whole volume through Sonnet 5.5 on 2026-10-19. The passage
marks the word `⟨like this⟩`, as the sense prompt's does, but this prompt never said so, and Sonnet
took the marks for the manga's own: `タオ`, `アルマ` and `宝来` were each "shown in angle brackets".
And `マガ` is no character, event or place, so nothing forbade it being explained as the volume's
monster — reanimated corpses that drink blood and eat flesh — which the story itself says three
bubbles later. The prompt now says what the marks are and that an explanation never mentions them;
that an explanation is what a dictionary would say, not what the passage shows the word doing; and
that a word the work coins or gives a meaning of its own is explained by its meaning outside the
work. On the bubbles concerned the names came back as "Yaya is a given name" and "Horai is the name
of a shop", `マガ` was judged unrecognizable and has no card — less than "a reading of 禍,
calamity", but nothing false and nothing told early — and `ガッツ`, which had been "the name of a
character", became the widely known borrowing it is. `血袋` is still "a person or animal used as a
source of blood", which is closer to the volume than to a dictionary, since no dictionary has it.

Over the whole volume (`decks/japanese.apkg`, rebuilt with `--update`, 179,446 tokens in and 11,426
out to re-ask the 107 words): no explanation mentions the marks, `マガ` has no card, and 24
explanations stand where there were 23. Two still lean on the text. `宝来` is "a restaurant or
eatery where one can run a tab", read off `宝来のツケが先だ`; and `血袋` is "a living creature
kept or used as a source of blood". Neither tells the plot. Tuning the prompt until those two pass
would be fitting it to them, the trap the `よお` clause above fell into.

The drawn-out clause was tuned on one bubble and not past it: `よお` at the end of
`出てくださいよお` is a stretched `よ`, and Haiku corrects it to `よう` with or without the sentence
saying "the word with the stretch taken out". よお/よう is a real spelling ambiguity, and a prompt
tuned until one example passes is a prompt fitted to that example.

Nothing is dropped by part of speech on the way: the parser tagged `っす` as a symbol in one
sentence, and a rule dropping symbols would have thrown away a word. Punctuation and numbers are
still dropped at extraction, the numbers with a line naming them.

## What it does not fix

The explanations are a model's, with a model's accuracy. Asked about `chirola` — Rioplatense slang
for loose change — `qwen3.5:4b` invented *a species of bird*. Nothing in the stage can catch that;
what the card does is say who wrote it, the same admission a rule card makes. The stage's own
judgement of "widely known" is likewise a judgement: `verre` and `petite` are dropped as household
words, which for a Spanish learner they are not. `--unknowns all` is the lever for a reader who would
rather see them.

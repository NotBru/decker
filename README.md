# Decker

This tool should take source material (text, audio, video, whatever), a target language that the
user wants to learn, their mother language, and construct an Anki deck that teaches, in the mother
language, the concepts required for the user to understand the parts of the source material that are
in the target language.

## Structure

### `docs/instructions/`

Everything inside this directory is intended to be written only by humans, so as to have a clear
ownership division. It also keeps human reasoning and decisions separate from AI.

### `docs/execution/`

This directory is intended to persist design choices/notes from AI agents.

### `docs/instructions/design.md`

This document should be the single source of truth for the design. Purposefully terse, so that a
human reader can get the gist of it quickly. Details may be offloaded to other documents, thus
making them part of the source of truth, but only as long as it's referenced by this document.

# When a remote stops answering

Written by an AI agent, not by hand. It records a choice taken while building decker.
[The v1 design](../instructions/v1/design.md) remains the source of truth: where this contradicts
it, the design wins and the code is wrong.

## The rule

**A dropped connection costs a run time, never content.** If a run was told to use a remote and
that remote stops answering, decker waits for it to come back, says so, and then carries on as if
nothing had happened. It does not go without the remote, and it does not switch to another one.
Bru asked for this on 2026-09-27: "no change in the connectivity can change parameters and degrade
runs. If the tunnel is down and the instruction is to use the tunnel, wait for it. If Wiktionary is
down, wait for it to be reachable again. And have them logged."

## Why

Before this, every failure to reach a remote became a *result*:

- An ollama question that could not be asked returned no answer, so that term kept every sense (or
  wrote no rule, or kept its English). The warning was printed **once per run**, so after the first
  failure the rest were silent.
- A Wiktionary fetch was tried five times over about fifteen seconds and then dropped, which cost
  the deck that gloss.
- A mirror that did not answer looked, to the glossary code, exactly like a mirror that *lacked*
  `Appendix:Glossary`. The run switched to reading it from Wikimedia, which is precisely a dropped
  connection changing a run's settings.

A full Bike Russian run (17,527 terms, a four-hour job) found this out twice in one afternoon. The
laptop lost its connection for a few minutes, the tunnel to the GPU box reset once, and each run
carried on with sense disambiguation off. The first run also lost its morphological rules. The only
evidence was one line near the top of a log that did not change again for hours.

## How

`decker/reach.py` has a `Gate` per remote: one per ollama host, and one per HTTP origin
(`https://en.wiktionary.org`, a mirror, `upload.wikimedia.org`, `dumps.wikimedia.org`). When a
request fails because the remote could not be reached, the caller asks the gate to wait:

- The first thread to arrive probes the remote. If the probe gets through straight away, the failure
  was a blip or the request's own: the caller asks again, and after `BLIPS` (3) of those it treats
  the failure as the request's, as before.
- If the probe fails, that is an outage. It is logged in red:
  `[decker] ollama at http://172.17.0.1:11435 unreachable (Connection reset by peer); waiting for it,
  the run carries on unchanged once it answers`. The gate then probes every 2, 4, 8 and after that
  every 10 seconds. While the wait lasts it says "still unreachable after …" every five minutes, so
  a long outage does not read like a hung run.
- Every other thread that needs the same remote waits on the same gate. The prefetcher, the gloss
  loop and the four stages that ask a model therefore make one outage and one pair of log lines, not
  one per thread.
- When a probe gets through, the gate logs `reachable again after 3m12s; carrying on`, releases
  everyone, and the failed request is made again.
- The end of glossing, and the end of card-building, print a summary of every outage waited out
  since the last summary: `waited out outages, deck unaffected: ollama at … 2 times (4m10s)`.

The probes are cheap on purpose. Ollama is asked for its model list (`/api/tags`). A MediaWiki is
asked for `meta=siteinfo` on its API, not its front page: in a Wikimedia outage the caches can keep
serving the front page's redirect while every API call returns 503, and the API is what a run
needs. Any other host is asked for `/`, and any status under 500 counts as "there".

## What counts as unreachable

- **ollama**: the builtin `ConnectionError` (which the client raises for a refused connection, and
  which also covers a reset) and httpx's `TransportError` family (a hang-up mid-answer, a read
  error, a timeout). A 404 for a model the host does not hold is an *answer*: it degrades the run
  as before and names the models the host does hold. So does a reply that is not JSON.
- **HTTP**: a connection that cannot be made or is dropped (`URLError`, `TimeoutError`), and a 5xx
  that persists through the usual backoff *and* that the rest of the site shares, which the probe
  decides. A 5xx the site does not share is that page's own and is given up on and counted, as
  before. A 429 is always waited out now, as long as the server keeps asking; before, it was dropped
  after five tries. A 404 is an answer and a 403 still stops the run.

## When a run still degrades

Only when nobody asked for the remote. If there is no `--ollama-host` and no `OLLAMA_HOST`, and
the default `localhost:11434` has never answered during this run, the run goes without a model, as
the README says. The logic is that a machine with no ollama on it has not *lost* anything. But once
that default host has answered, losing it is an outage like any other.

## What it costs

A run whose remote never comes back never finishes. That is the trade Bru asked for: a run that
stops (and says why every five minutes) is visible, while a run that finishes as a different deck
is not.

Ctrl+C works as it does everywhere else, with one caveat. The first press asks the phase to end
between terms, but the term being processed is still waiting, so the wait says the skip will take
effect once the remote answers. The second press stops the run immediately.

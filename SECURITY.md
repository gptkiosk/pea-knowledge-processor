# Security

## Reporting a problem

Please do not open a public issue for a security problem. Use GitHub's private vulnerability reporting on this repository (Security, "Report a vulnerability"). Say what you found, how to reproduce it, and what it would let someone do. You will get an answer as soon as the maintainer can give one.

## What this project defends against

The pipeline reads files written by strangers and publishes files that an app on someone's phone will read. So:

- **Fetching.** https only; the host name is resolved, every address it resolves to must be public, and the connection goes to the address that was checked; redirects are checked again from the start; no cookies or credentials; size and time caps, also after decompression; robots.txt obeyed.
- **Parsing.** Strict JSON (no NaN, no duplicate keys). XML that declares entities is refused unread. Every number that becomes a time is checked first. No step is slower than linear in the input.
- **Publisher text.** Markup, addresses, control and direction characters are removed before text becomes output, and the validator refuses any file where one is left. The only addresses in the format are the source's site and the item's own link, both checked.
- **Model output.** The call has no tools. The answer is read member by member; quotes must be in the transcript word for word; what identifies an item never comes from the model; anything invalid means the extractive digest is used.
- **Publishing.** The output is validated as a whole before it replaces the previous one. A source that does not validate is not published; the others are. A failed run publishes nothing.
- **CI.** Actions pinned to full commit SHAs. No default permissions. The fetch job has no secrets; only the digest job is given the model key; only the publish job can deploy. Pull requests run tests with no secrets.
- **The app.** Checks every file's size and SHA-256 against the index, then the schema and the text rules, and refuses with a typed reason (docs/APP-CONTRACT.md).

## What it does not defend against

- A compromise of this repository or of the GitHub account that owns it: whoever can push to `main` decides what apps read. Protect the branch and the account.
- `store.json` is the root of trust and is not signed; its integrity rests on https and on GitHub Pages.
- Text that is misleading but well-formed. The format carries what a publisher said; it does not check that it is true.
- The pattern that spots text addressed to an assistant can be evaded. The defence is that readers treat every text as quoted data.

## Secrets

The only secret is `OPENROUTER_API_KEY`, optional, held as a repository secret. It is never written to the output, the work folder or the logs. Tests use a made-up key against a local server.

# Adding and testing podcast sources

Adding a new podcast to the PEA curated catalog is designed to be simple, repeatable, and verified against the real ingestion pipeline before anything enters `config/sources.json`.

## 1. Requesting a podcast from the PEA iOS app

1. Open **PEA → Settings → Knowledge sources → Browse curated sources**.
2. Scroll to **Request a source** and tap **Request a podcast**.
3. Enter the **Podcast name** and (ideally) its **RSS feed / `agent.json` URL** or **Official website URL**, plus optional notes about where transcripts live.
4. Tap **Open request in Safari**.
   - PEA validates the URLs locally (public `https://` only, no credentials) and opens a pre-filled GitHub Issue Form (`request-podcast.yml`) on the active catalog's repository.
   - Nothing is sent automatically and nothing from your chats, profile, or account is included.
5. Submit the issue on GitHub.

## 2. What automated ingestion testing runs

When an issue with the `source-request` label is opened or edited, `.github/workflows/test-source-request.yml` runs with **zero secrets** (`contents: read`, `issues: write` only) and posts a Markdown test report comment on the issue:

1. **Public HTTPS validation & feed auto-discovery** — validates the URL against SSRF/private-host rules, detects `agent_index`, `json_feed`, or RSS/Atom `feed`, and automatically inspects `<link rel="alternate">` tags if only a website homepage was supplied.
2. **`robots.txt` compliance & feed parsing** — fetches via `pea_knowledge.fetch.Fetcher` (obeying `robots.txt`) and parses episodes with `pea_knowledge.adapters.parse`.
3. **Transcript availability & discussability rule** — checks up to the newest 5 episodes with `pipeline.normalize_transcript` to confirm at least 60% (`min_full_transcript_share`) and at least 2 episodes (`min_discussable_items`) have readable transcripts.
4. **Phone-style probe (`probe.probe`)** — fetches the newest discussable transcript using the iPhone app's exact headers (`PEA/0.10.1`), size cap (1.5 MB), content-type checks, and normalizer, catching Cloudflare/403 blocks before onboarding.
5. **Brief contract check** — generates a sample extractive digest and brief and verifies `validate.check_brief_alone`.
6. **Starter `config/sources.json` block** — prints a ready-to-review JSON snippet defaulting to `"publish": "digest_only"`.

### Verdicts

| Verdict | Meaning | Next step |
| --- | --- | --- |
| **PASS** | Feed, transcripts, phone probe, and brief contract all succeeded. | Review publisher terms (`docs/SOURCES-TERMS.md`), fill in `description`, `overview`, `topics`, and `terms` in the starter JSON, add to `config/sources.json`, and open a PR. |
| **NEEDS_TRANSCRIPT_RULE** | Feed parsed cleanly, but did not carry enough inline `<podcast:transcript>` tags. | If transcripts live on episode web pages, add a `transcript_page` rule (see existing examples in `config/sources.json`) and re-test locally. |
| **FAIL** | Feed unreachable, invalid URL, blocked by `robots.txt`, or failed the iPhone probe / brief contract. | Review the failing check row in the report before onboarding. |

## 3. Testing a candidate locally (60-second curator workflow)

You can run the exact same ingestion tester from your terminal before editing `config/sources.json`:

```bash
python3 -m pea_knowledge test-source \
  --name "Example Podcast" \
  --feed-url "https://feeds.example.org/show.xml" \
  --website-url "https://example.org/" \
  --markdown
```

Add `--strict` if you want a non-zero exit code unless the verdict is `PASS`, or omit `--markdown` for raw JSON output.

## 4. Onboarding checklist before merging

1. **Terms check (`docs/SOURCES-TERMS.md`):** confirm `robots.txt`, licence, and terms of use. Keep `"publish": "digest_only"` unless the publisher explicitly grants redistribution rights for full transcripts.
2. **Add to `config/sources.json`:** paste the verified entry, fill in plain-English `description` and `overview`, pick valid `topics` from `config/topics.json`, and choose an outline icon from the schema list.
3. **Run the repository checks:**
   ```bash
   python3 -I -m unittest
   python3 -m pea_knowledge contract
   ```
4. **Open a pull request** linking the `source-request` issue. Once merged, the next scheduled `process.yml` run publishes the show to the curated catalog and it appears in PEA under **Browse curated sources**.

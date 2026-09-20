# Dedicated resource commands

`organizations list` discovers accessible organizations without saving or requiring a default.
With personal authorization, a configured organization must still match its bound credentials;
without a selected organization the read-only discovery command works normally.

```sh
dinero organizations list --json
dinero contacts list --organization 123 --page 0 --page-size 100 --json
dinero products list --organization 123 --free-text-search 'Consulting' --json
```

Contact and product lists expose `--fields`, `--query-filter`, `--changes-since`, `--page`,
`--page-size` (1–1000), and `--deleted-only` / `--no-deleted-only`. The two boolean options are
mutually exclusive. Omission sends no value and leaves the API default intact. A list request
fetches one page only, preserving the full server response and its pagination metadata.

Get/update/delete take the resource GUID as an argument. Create/update accept `--input FILE|-`
and convenience options. Input is a strict UTF-8 JSON object. Unknown fields are retained;
fields present in both input and options are rejected. Updates send the supplied full payload,
without fetching or merging the existing record.

Contacts require `Name`, `CountryKey`, `IsPerson`, `IsMember`, `UseCvr`; products require
`BaseAmountValue`, `Quantity`, `AccountNumber`, `Unit`. Use `--help` for available options.
No country, account, quantity, unit or boolean business defaults are invented.

Example contact payload (use only for an authorized creation):

```json
{"Name":"Acme A/S","CountryKey":"DK","IsPerson":false,"IsMember":false,"UseCvr":false}
```

```sh
dinero contacts create --organization 123 --input contact.json --json
dinero contacts create --organization 123 --name 'Acme A/S' --country-key DK \
  --no-is-person --no-is-member --no-use-cvr --json
```

PowerShell accepts the same one-line commands; prefer `--input contact.json` to avoid pipeline
encoding differences. Default output is human-readable; `--json` outputs one unchanged API
result. Common errors go to stderr with nonzero status. Create/update/delete mutate records;
delete has no interactive prompt, request body or automatic retry. No live mutations are needed
for command verification.

Agents must use these dedicated commands. If a required operation is not implemented, add it
through the issue/PR workflow before agent use; do not use the raw escape hatch or direct HTTP.

## Accounting reads

```sh
dinero entries list --organization 123 --from-date 2026-01-01 --to-date 2026-09-20 --no-include-primo --json
dinero entries changes --organization 123 --changes-from 2026-09-01T00:00:00Z --json
dinero accounts entry --organization 123 --fields AccountNumber,Name,VatCode,Category,IsHidden --json
dinero accounts purchase --organization 123 --json
dinero accounts deposit --organization 123 --fields AccountNumber,Name,IsDefault,IsHidden --json
dinero accounting-years list --organization 123 --json
dinero vat-types list --organization 123 --json
dinero files list --organization 123 --file-status Unused --page 0 --page-size 1000 --json
```

Dates for entries use ISO date/date-time syntax and are sent unchanged, including offsets.
Neither a period nor includePrimo is invented: omit it to preserve Dinero's default, or specify
`--include-primo`/`--no-include-primo`. Opposing flags fail. These entry/lookup endpoints have no
pagination or generic query filter. Only entry accounts expose `--category-filter`.

Files return archive metadata and links, not PDF/image bytes. Filters are `--extensions`
(comma-separated), `--uploaded-before`/`--uploaded-after` (YYYY/MM/DD), and
`--file-status All|Used|Unused`. File pagination is explicit and only one page is retrieved.
An unused file can be a duplicate, invoice, receipt or unrelated attachment; its presence alone
does not prove that a separate expense remains to be booked. No read command mutates records.

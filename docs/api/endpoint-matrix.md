# Endpoint matrix

Verified against [Dinero OpenAPI](https://api.dinero.dk/openapi/v1/swagger.json) on 2026-09-20.
The checked structural extraction is [endpoint-matrix.json](endpoint-matrix.json); it records the
source SHA-256, exact query names/types/defaults, path arguments and request field inventories.
All dedicated commands in this matrix are implemented. Versions and resource differences below
remain part of the command contract.

The three expense operations added in contract 1.1 were rechecked on 2026-10-11; their
source checksum is recorded separately as `expense_operations_verification` in the JSON.

`{organizationId}` is resolved from `--organization` or configuration, never an implicit account.
`{guid}` is a positional resource GUID. All other path parameters remain positional.

| Command | HTTP | Path | JSON body schema |
| --- | --- | --- | --- |
| `organizations list` | GET | `/v1/organizations` | None |
| `contacts list` | GET | `/v1/{organizationId}/contacts` | None |
| `contacts get` | GET | `/v1/{organizationId}/contacts/{guid}` | None |
| `contacts create` | POST | `/v1/{organizationId}/contacts` | ContactCreateModel |
| `contacts update` | PUT | `/v1/{organizationId}/contacts/{guid}` | ContactUpdateModel |
| `contacts delete` | DELETE | `/v1/{organizationId}/contacts/{guid}` | None |
| `products list` | GET | `/v1/{organizationId}/products` | None |
| `products get` | GET | `/v1/{organizationId}/products/{guid}` | None |
| `products create` | POST | `/v1/{organizationId}/products` | ProductCreateModel |
| `products update` | PUT | `/v1/{organizationId}/products/{guid}` | ProductUpdateModel |
| `products delete` | DELETE | `/v1/{organizationId}/products/{guid}` | None |
| `invoices list` | GET | `/v1/{organizationId}/invoices` | None |
| `invoices get` | GET | `/v1/{organizationId}/invoices/{guid}` | None |
| `invoices create` | POST | `/v1/{organizationId}/invoices` | InvoiceCreateModel |
| `invoices update` | PUT | `/v1.2/{organizationId}/invoices/{guid}` | InvoiceUpdateModel |
| `invoices delete` | DELETE | `/v1/{organizationId}/invoices/{guid}` | TimestampObject |
| `invoices book` | POST | `/v1/{organizationId}/invoices/{guid}/book` | BookModel |
| `invoices send` | POST | `/v1/{organizationId}/invoices/{guid}/email` | ApiMailoutModel |
| `purchase-vouchers create` | POST | `/v1.2/{organizationId}/vouchers/purchase` | PurchaseVoucherCreateModelV2 |
| `purchase-vouchers get` | GET | `/v1/{organizationId}/vouchers/purchase/{guid}` | None |
| `purchase-vouchers update` | PUT | `/v1.1/{organizationId}/vouchers/purchase/{guid}` | PurchaseVoucherUpdateModel |
| `purchase-vouchers delete` | DELETE | `/v1/{organizationId}/vouchers/purchase/{guid}` | TimestampObject |
| `purchase-vouchers book` | POST | `/v1/{organizationId}/vouchers/purchase/{guid}/book` | BookModel |
| `entries list` | GET | `/v1/{organizationId}/entries` | None |
| `entries changes` | GET | `/v1/{organizationId}/entries/changes` | None |
| `accounts entry` | GET | `/v1/{organizationId}/accounts/entry` | None |
| `accounts purchase` | GET | `/v1/{organizationId}/accounts/purchase` | None |
| `accounts deposit` | GET | `/v1/{organizationId}/accounts/deposit` | None |
| `accounting-years list` | GET | `/v1/{organizationId}/accountingyears` | None |
| `vat-types list` | GET | `/v1/{organizationId}/vatTypes` | None |
| `files list` | GET | `/v1/{organizationId}/files` | None |
| `files download` | GET | `/v1/{organizationId}/files/{fileGuid}` | None; binary response |
| `purchase-vouchers get-by-file` | GET | `/v1/{organizationId}/vouchers/purchase/fileguid/{fileGuid}` | None; UUID array response |
| `purchase-vouchers similar` | POST | `/v1/{organizationId}/vouchers/purchase/similar` | PurchaseVoucherCreateModelV2 |

## Resource differences

- Organizations list uses v1 to expose its `fields` option. It needs authorization but no organization selection. v1.1 organizations remains available through the escape hatch.
- Contacts use v1 consistently in the initial command set. v2 list/update variants, restore and notes remain escape-hatch operations; changing default endpoint versions is an explicit contract change.
- Invoice update uses v1.2. Invoice list supports start/end date, field selection, text/status/query filters, changes/deleted filters, page/pageSize and sort/sortOrder; see the JSON extraction for exact names. `send` means the email endpoint, not EAN delivery.
- Purchase voucher create uses v1.2, update v1.1, and get/delete/book v1. There is no dedicated purchase-voucher list endpoint in this specification; do not invent a `list` command. There is no `expenses` alias hiding these distinctions.
- Entries list uses `fromDate`, `toDate`, `includePrimo`; changes uses `changesFrom`, `changesTo`, `includePrimo`. Neither has page/pageSize/queryFilter. No entries mutation is planned.
- Contact/product DELETE has no body. Invoice/purchase DELETE uses `TimestampObject`; book uses `BookModel`. Do not turn these into a uniform DELETE implementation.

## Request construction

Kebab-case options map to the exact camel/Pascal-case API names; the JSON extraction is authoritative
for query mapping (for example `--page-size` → `pageSize`, `--include-primo` → `includePrimo`).
Only explicitly supplied query options are transmitted, leaving defaults to Dinero. Expose boolean
options as paired flags: `--deleted-only` sends `deletedOnly=true`, `--no-deleted-only`
sends `deletedOnly=false`, and omission sends neither. Similarly use `--include-primo` /
`--no-include-primo`; reject supplying both members of a pair. This distinction preserves
server defaults, including includePrimo=true. Pagination is zero-based, pageSize is 1–1000 where
supported, and one invocation fetches one page; there is no hidden auto-pagination.

Use `--input FILE` or `--input -` for every operation with a JSON body, including DELETE.
Request summaries list the top-level fields and schema-required fields; nested types, constraints
and conditional business requirements remain defined by the linked OpenAPI schema and Dinero.
Schema metadata is not permission to fabricate missing values (notably booleans or timestamps).
Convenience options map directly, e.g. contact `--name` → `Name`, `--email` → `Email`,
and voucher `--timestamp` → `Timestamp`. The payload combination rule is in the CLI contract.

## Deliberate escape-hatch scope

Notes, file upload, invoice PDF exports, payments, reminders, EAN, credit notes, restore, totals/fetch
and other auxiliary endpoints do not gain dedicated commands in this matrix.
Agents must add dedicated commands before using any remaining operation. The manual escape
hatch supports only JSON requests and responses. Its initial JSON-only
transport does not support multipart upload or binary/PDF download. Original archive files use
the dedicated `files download` binary extension; its success media type is unspecified in OpenAPI,
so no PDF-only restriction is imposed. `get-by-file` preserves the array of GUIDs; `similar` returns
SimilarPurchaseVoucherReadModel and does not promise AI accounting suggestions. Neither command
automatically selects, creates or books a draft. Never reconstruct bearer-token HTTP in an agent skill.

Discovery of future endpoints uses the official OpenAPI, not guessed resource symmetry.
When changing this matrix, re-fetch the source, review the diff and update verification date/hash.

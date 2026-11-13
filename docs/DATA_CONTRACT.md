# Account and access-guide schema (version 1)

Account records live under `policy.json` → `labs[lab_id].users[]`. Runtime keys (`name`, `uid`, `port`, `container`) are distinct from optional `profile` metadata:

- `schema_version`: 1
- `display_name`, `student_id`, `email`, `joined_on`, `expires_on`, `notes`
- Dates use YYYY-MM-DD. End date is a record, not an automatic account suspension.
- Empty metadata is null; the UI and PDF display N/A. Unknown profile keys survive edits.
- Password plaintext is never stored in metadata or included in guides. Changes update the account shadow hash.

Guide settings live under `web.json`: `document_defaults` merged with `document_labs[lab_id]`. Supported fields are `schema_version`, `access_host`, `environment_ko`, `environment_en`, `permissions_ko`, `permissions_en`, and `extra_fields`. An extra field has `id`, `label_ko`, `label_en`, `value_ko`, `value_en` (or fallback `label` and `value`). Up to 12 fields are supported. Future incompatible versions require an explicit migration.

`documents.compose` is the shared preview/PDF contract. GPU, CPU, memory, storage and account connection fields come from the registered lab and current snapshot; the form supplies only lab, language and additional notes. No request-supplied specifications or passwords are rendered. Configured environment descriptions must be reviewed when environments change outside Orvia; image updates through Orvia refresh them from observed version output.

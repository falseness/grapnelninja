# Playgama upload handoff (TASK-249)

The upload is blocked as of 2026-10-09. A read-only MCP initialization request to
`https://developer.playgama.com/api/mcp` returned HTTP 401 Unauthorized. This
session has no exposed/configured Playgama MCP connection or authenticated browser
profile. No upload or listing mutation was attempted; TASK-249 remains pending.
Access checks, verified source hashes and explicitly blocked remote evidence are
recorded under `artifacts/TASK-249/` (untracked). They are not upload receipts or
proof of remote state.

Resume with authenticated developer tooling and console access:

1. Open existing application `cmuu1nvs30d00hj0h49c07spq`. Record verified identity,
   latest actual archive ID, moderation, archive history and unrelated listing
   fields before changing anything. Do not assume the historical archive is current.
2. Upload the exact `artifacts/TASK-248/grapnelninja-playgama.zip` (104539 bytes;
   SHA256 `4180a9c142b441fae256aa4b5ea281c122a2bc25a7354d38142668a0c35f1b98`).
3. Upload the three final covers identified by `artifacts/TASK-247/artwork.json`.
   Select current real gameplay screenshots from its ten native candidates and
   replace listing screenshots through the console. Preserve historical archives
   and unrelated fields; do not create an application or start campaigns.
4. Record source hash to returned archive/media ID mappings, successful processing
   and Bridge detection. Read back all three cover orientations and the chosen
   screenshot set, capture the native listing, and compare preserved remote fields.
5. Replace the blocked evidence with actual before/after records and receipts;
   update the manifest and inspect every required proof artifact. Run all three
   TASK-249 test steps before changing its status to `to-verify`.

Do not store credentials or signed upload URLs in evidence. Keep `artifacts/`
and `screenshots/` out of commits. Existing itch deliverables remain untouched.

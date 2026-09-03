# Evidence archive contract

Export official Telegram channels as JSON and HTML. Preserve the unmodified export under
`evidence/telegram/<channel>/export_<UTC-date>/`, then extract each registered post to a
standalone UTF-8 text or JSON file. Put its project-relative path and SHA-256 in
`config/source_post_registry_v1.csv`.

Run `python3 scripts/verify_evidence_archive.py`. Live URLs establish discoverability;
the local export and hash establish the exact version used by the experiment. Screenshots
and PDF captures are useful supplements, but the machine-readable JSON/text is canonical.

Do not mark a source archived merely because a web page is still reachable.

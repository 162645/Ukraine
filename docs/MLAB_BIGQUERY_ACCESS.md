# M-Lab BigQuery access

- Configured date: 2026-09-14
- gcloud CLI: Google Cloud SDK 584.0.0
- bq CLI: 2.1.38
- Active account: configured (user account; no tokens recorded here)
- Default project: `measurement-lab`
- Application Default Credentials: configured (`~/.config/gcloud/application_default_credentials.json` exists; contents are not recorded)
- Python SDK: `google-cloud-bigquery` 3.45.0 import succeeds
- bq smoke query: PASS (UA rows for 2024-08-26; count-only query)
- Python SDK smoke query: blocked by the server-side Python HTTPS transport through the SSH-forwarded proxy (`SSLEOFError`); the SDK is installed and importable.

The server currently has no project data copied into the repository. Future M-Lab queries should keep the country filter server-side (`client.Geo.CountryCode = 'UA'`), restrict to IPv4 fields, and specify an explicit research time range. No credential, token, cookie, or private JSON content is stored in this file.

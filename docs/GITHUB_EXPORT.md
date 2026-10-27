# Exporting action items to GitHub Issues

After a meeting is summarized, the action items you approve can be filed as
issues in one GitHub repository.

```
POST /api/meetings/{id}/action-items/github-issues
X-Export-Key: <GITHUB_EXPORT_KEY>

{"items": [0, 2]}
```

`items` are indexes into the meeting's `action_items` (from `GET /insights`),
1 to 20 of them. The response lists one issue per item, in the order given:

```json
{
  "repository": "acme/roadmap",
  "issues": [
    {"action_item": "Alice drafts the release notes", "number": 41,
     "url": "https://github.com/acme/roadmap/issues/41", "created": true}
  ]
}
```

## Setup

Set these in `backend/.env` (export stays off, with a 503, until all three are set):

| Variable | Value |
| --- | --- |
| `GITHUB_TOKEN` | A fine-grained token limited to the one repository, with **Issues: read and write**. |
| `GITHUB_REPOSITORY` | `owner/name` |
| `GITHUB_EXPORT_KEY` | A random secret that callers send in `X-Export-Key`, e.g. `python -c "import secrets; print(secrets.token_urlsafe(32))"`. |

Optional: `GITHUB_ISSUE_LABEL` (default `meetsense`), `GITHUB_API_URL` (for
GitHub Enterprise Server), `GITHUB_TIMEOUT_SECONDS` (default 15). Create the
label in the repository beforehand so a token with only issue access can apply it.

The export key matters because the API has no user accounts: without it, anyone
who can reach the server could file issues with the server's token.

## No duplicates

Each issue body ends with a hidden marker naming the meeting and a hash of the
action item (case and spacing ignored):

```
<!-- meetsense-export meeting=<meeting id> item=<16 hex digits> -->
```

Before filing, the server lists the repository's issues with the export label,
open and closed, and reuses any issue whose marker matches; those come back with
`"created": false`. Exports for the same meeting run one at a time. So a double
click, a retry after a timeout, or a request that failed halfway (502) never
files an item twice. Removing the label from an issue, or editing out its
marker, makes the next export file that item again.

Limits: only the 1,000 most recent labeled issues are checked, and the item text
is the hash input, so regenerating insights with reworded action items produces
new issues.

## Errors

| Status | Meaning |
| --- | --- |
| 401 | Missing or wrong `X-Export-Key` |
| 404 | Unknown meeting, or no insights yet (call `POST /summarize` first) |
| 422 | Empty, oversized or out-of-range `items` |
| 429 | More than 5 exports a minute from one client |
| 502 | GitHub refused or could not be reached; retrying is safe |
| 503 | Export is not configured |

GitHub's error bodies are not passed to clients; the server logs the status code
and GitHub's message, never the token.

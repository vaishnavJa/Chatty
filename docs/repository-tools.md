# Repository tool contract

The expanded tool module fixes every GitHub API endpoint to `vaishnavJa/Chatty`.
It uses the existing `gh` login and does not read, create, print, or change tokens.
No dependencies were added.

The app must send every name in `WRITE_TOOLS` through its concrete approval UI
and durable `execute_call` ledger. `execute()` is a low-level internal boundary,
not an alternative authorized dispatcher. Do not retry an uncertain mutation with
a new call ID. Timeout, invalid JSON, and unconfirmed successful mutation
responses are classified as uncertain; definitive GitHub 4xx rejections are not.

Exports:

- `TOOL_SCHEMAS`: 20 OpenAI function schemas with additional properties disabled.
- `READ_TOOLS`, `WRITE_TOOLS`: disjoint frozen sets (9 reads, 11 writes).
- `TOOL_CAPABILITIES`: labels, approval requirements, and destructive flags.
- `validate(name, arguments)`: `None` or `{ok: false, error: ...}` without I/O.
- `execute(name, arguments)`: data or a sanitized `GitHubToolError`.

| Area | Reads | Writes |
| --- | --- | --- |
| Repository | `get_repository` | — |
| Issues | `get_issue`, `list_issue_comments` | `update_issue`, `add_issue_comment`, `update_issue_comment` |
| Pull requests | `get_pull_request`, `list_pull_request_files` | `create_pull_request`, `update_pull_request`, `merge_pull_request` |
| Branches | `list_branches` | `create_branch`, `delete_branch` |
| Files | `list_repository_files`, `read_repository_file` | `update_repository_file`, `delete_repository_file` |
| Actions | `list_workflow_runs` | `rerun_workflow` |

Issue IDs use `issue_number`; discussion comments use `comment_id`; PRs use
`pull_number`. `update_issue` can replace title, body, labels, assignees,
milestone and open/closed state. Supplying an empty label/assignee list clears
it; `milestone: null` clears the milestone. Omitted fields are preserved.

Merging requires `expected_head_sha`; the API enforces the current head and
normal branch rules. New PRs default to drafts. Branch creation requires an
existing commit SHA in the repository and never overwrites an existing branch.
Deletion refuses the current default branch and branches marked protected.

File mutations require an explicit existing `branch`. Replacing or deleting a
file additionally requires its current blob `expected_sha`. For creation only,
omit `expected_sha`; an existing path then fails without mutation. Concurrent
changes are rejected by GitHub's SHA precondition. File writes use JSON on
stdin, with the UTF-8 content encoded as Base64; text is never interpolated into
a shell. Success returns the commit URL and new blob SHA when applicable.

Reads and writes exclude credential/private-key filenames and real environment
files (including `openai.env.md`). `.env.example`, `.env.sample`, and
`.env.template` remain available. Credential-management source modules such as
`credentials.py`, `credentials.ts` and `credentials.js` are ordinary repository
code and remain accessible, including inside source directories named
`credentials` or `secrets`. Credential data files and hidden credential stores
still remain excluded. Directory listings may show sensitive filenames
but never their content; PR patches for sensitive old or new paths are omitted.

File reads resolve Git tree modes and request the exact blob SHA. They never
follow the Contents API's implicit symlink dereferencing. Symlinks, submodules,
non-UTF-8/binary content, and files above 64 KiB are not read aloud. Truncated
repository trees fail closed. Files must be relative repository paths without
traversal or URL syntax; ref expressions, cross-repository refs, and arbitrary
API paths are unsupported. Text file writes are limited to 64 KiB.

Requests have a 30-second CLI timeout. Responses are spooled to temporary files
and read with a 2 MiB bound. List operations return bounded pages (1–100 entries),
with an explicit page number. `has_more` for REST pages means another page may
exist. Directory listing pages are local slices of GitHub's maximum 1,000
entries; the result warns when that upstream limit may truncate a directory.
Comment bodies and PR patches share a 128 KiB text budget per page.

Workflow reruns may deploy or incur costs and therefore use destructive approval
classification. Repository deletion/creation, settings, secrets, hooks,
permission administration, arbitrary commands, force pushes and protection
bypasses are not exposed.

## Primary API references

- [GitHub CLI API: JSON input and methods](https://cli.github.com/manual/gh_api)
- [Issues: update an issue](https://docs.github.com/en/rest/issues/issues#update-an-issue)
- [Issue comments](https://docs.github.com/en/rest/issues/comments)
- [Pull requests and SHA-checked merging](https://docs.github.com/en/rest/pulls/pulls#merge-a-pull-request)
- [Git references](https://docs.github.com/en/rest/git/refs)
- [Repository contents and symlink behavior](https://docs.github.com/en/rest/repos/contents)
- [Git trees](https://docs.github.com/en/rest/git/trees)
- [Git blobs](https://docs.github.com/en/rest/git/blobs)
- [Workflow runs](https://docs.github.com/en/rest/actions/workflow-runs)

## Verification

`tests/test_repository_tools.py` uses subprocess fixtures only. It covers every
operation's endpoint/method/payload, literal text preservation, schema/path/ref
rejection, branch and SHA protections, symlink exclusion, receipts, bounded
content, sanitized errors, and uncertain-write classification. No real GitHub
mutations are used during testing.

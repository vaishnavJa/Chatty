# GitHub Project tools

The backend selects one Project from the private server environment:

```dotenv
CHATTY_PROJECT_OWNER=<project-owner-login>
CHATTY_PROJECT_NUMBER=<positive-project-number>
```

Use the existing GitHub CLI login with `project` scope for writes (`read:project`
is enough for reads). Project configuration, credentials, and private board
metadata do not belong in committed examples or public issue bodies.

The tool registry exposes:

| Tool | Arguments | Result |
| --- | --- | --- |
| `get_project` | none | Project ID, URL, title, description and visibility from GitHub |
| `list_project_fields` | none | Field IDs, names, data types, and select options |
| `list_project_items` | optional `limit` from 1 to 100 | Items with field values, total count, and truncation flag |
| `add_project_item` | `url` | Membership for an existing Chatty issue or pull request |
| `update_project_item` | `item_id`, `field_name`, `value` | Updated item and field acknowledgement |
| `archive_project_item` | `item_id`, `archived` | Archive or restore acknowledgement |
| `remove_project_item` | `item_id` | Membership removal acknowledgement; repository issue remains |
| `update_project_details` | one or more of `title`, `description`, `readme` | Updated project details |

Read fields before editing. Field and single-select option names match uniquely,
ignoring case. For example, use the returned `Status` option name as the value;
the server resolves its ID. Text, numeric, date (`YYYY-MM-DD`), and single-select
fields are supported. Use `null` to clear a field. Native issue fields such as
Title, Assignees, and Labels must use the corresponding repository tools.
Iteration fields and creating/deleting project fields are not implemented.

Every write must pass the backend's approval and durable call ledger. This
module does not obtain approval itself. `TOOL_CAPABILITIES` marks all writes as
requiring approval; membership removal also carries the destructive flag.
Timeouts or unconfirmed mutation responses are uncertain and must be checked
before any retry. Project/owner arguments, arbitrary queries, visibility changes,
permission administration, and project deletion are not exposed.

The server reads and validates the configured project's identity, resolves field
IDs from that project's fields, and verifies each existing item's `project.id`
before changing it. Archived memberships can be restored. Addition accepts only
canonical `https://github.com/vaishnavJa/Chatty/issues/<number>` or `/pull/<number>`
URLs. No operation automatically copies private project data into repository
issues or comments.

Implementation uses installed `gh` 2.85.0 argument help and the documented node-ID
flags. That version's `field-list` JSON omits `dataType`, so a fixed GraphQL query
reads field types and options. Its `project edit` ignores empty strings, so a fixed
`updateProjectV2` mutation with a temporary JSON input file preserves explicit
empty descriptions/readmes and literal multiline text. No shell interpolation is
used. Field pagination is bounded to 1,000 fields; item listing returns at most
100 items and reports truncation.

References: [GitHub Projects API](https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/using-the-api-to-manage-projects),
[CLI item-edit flags](https://cli.github.com/manual/gh_project_item-edit),
[CLI 2.85 project query/output definitions](https://github.com/cli/cli/blob/v2.85.0/pkg/cmd/project/shared/queries/queries.go),
[CLI 2.85 project edit behavior](https://github.com/cli/cli/blob/v2.85.0/pkg/cmd/project/edit/edit.go).

Fixture tests use mocked subprocess responses and never mutate GitHub:

```sh
PYTHONPATH=src python -m pytest tests/test_project_tools.py -q
ruff check src/chatty/integrations/github/project_tools.py tests/test_project_tools.py
```

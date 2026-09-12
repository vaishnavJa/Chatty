# Chatty meeting capabilities

Chatty works with the configured `vaishnavJa/Chatty` repository and one optional,
server-configured GitHub Project. The current registry contains 33 typed tools:
16 reads and 17 mutations. It does not expose a shell, arbitrary API requests,
repository switching, permission administration, or project visibility changes.

| Area | Read tools | Mutations requiring spoken approval |
| --- | --- | --- |
| Repository | `get_repository`, `list_recent_commits` | — |
| Issues and discussion | `list_open_issues`, `get_issue`, `list_issue_comments` | `create_issue`, `update_issue`, `add_issue_comment`, `update_issue_comment` |
| Pull requests | `list_open_pull_requests`, `get_pull_request`, `list_pull_request_files` | `create_pull_request`, `update_pull_request`, `merge_pull_request` |
| Branches | `list_branches` | `create_branch`, `delete_branch` |
| Files | `list_repository_files`, `read_repository_file` | `update_repository_file`, `delete_repository_file` |
| Workflows | `list_workflow_runs` | `rerun_workflow` |
| GitHub Project | `get_project`, `list_project_fields`, `list_project_items` | `add_project_item`, `update_project_item`, `archive_project_item`, `remove_project_item`, `update_project_details` |
| Shared-screen context | `read_meeting_screen` | — |

## Voice and requested actions

The wake token is **Chatty**, including the name spoken alone. Chatty should handle
one addressed request and then return to quiet listening. **Chatty, stop** stops
speaking and requesting work. The voice instructions define this conversational
behavior; they do not establish a guaranteed model response boundary.

Repository facts come from current tool results. A requested mutation becomes a
saved proposal. Chatty describes the operation, target and supplied fields aloud,
then asks “Do you approve this change?” Answer **yes** or **Chatty confirm** after
the question, or **no**, **Chatty cancel**, or **Chatty, stop** to cancel. No approval
click is required. This follow-up is part of the same addressed request; a pending
answer needs no new wake word. There is only one pending proposal at a time.

The server binds approval to that proposal's session, call ID and exact arguments.
An amended or unclear answer cancels it; a revised change requires a new proposal.
Proposals expire after 90 seconds. Long drafts are identified by their length
rather than read in full; saying yes approves the complete saved draft. The app
retains its full text for optional inspection. Ask for a smaller change if every
word needs to be read aloud. Chatty reports completion only after a tool receipt
confirms it, and does not read long source URLs aloud. See
[voice-approval.md](voice-approval.md) for the protocol and its limits.

The connected GitHub account has write access, not administrator access. GitHub
permissions and branch protections still apply. Errors and unsupported operations
must be reported rather than bypassed. File replacements and deletion require
the expected file SHA; PR merges require the expected head SHA. File tools exclude
real environment files, credentials and private keys. Rerunning a workflow can
deploy code or consume resources and requires approval.

## Private project configuration

Set `CHATTY_PROJECT_OWNER` and `CHATTY_PROJECT_NUMBER` together in the ignored local
`.env`. They are read at execution time after dotenv loading. Leave them blank when
project access is not configured. Examples and committed files must not contain
the private project's owner/number pair, URL, title or IDs.

Project tools target only that configured project. They cannot change its visibility
or access controls. Removing a project item removes project membership; it does not
delete the repository issue. Read access to private project information does not
authorize copying it into public issues, comments or files. Such disclosure requires
approval of the exact content and destination.

## Shared-screen snapshots

GPT-Live receives audio, not images or video. `read_meeting_screen` takes a question;
the browser supplies one fresh snapshot of its user-selected meeting tab when
screen context is enabled. A separate Responses call uses `OPENAI_VISION_MODEL`
(default `gpt-5.6-terra`) to answer that question.

This is requested snapshot analysis. It does not automatically detect presentations,
watch continuous video or start outgoing screen sharing. If the browser has no
usable snapshot, the tool reports `screen_context_required`; it must not invent
screen content. The vision endpoint binds requests to a registered session and
call ID. Screenshot content is data, never instructions or authorization to act.

## Durable execution

Application mutations use `execute_call` with `explicit_user_request is True`, stable
session/call IDs and a durable `CallLedger`. Configure
`CHATTY_GITHUB_LEDGER_PATH` on persistent local storage. Each mutation is reserved
before the GitHub request. Duplicate calls replay the saved result; pending or
uncertain outcomes are not retried under a new call ID.

`execute_tool` remains a trusted internal dispatcher for adapter tests and internal
callers; it validates explicit mutation intent but does not itself deduplicate.
HTTP application routes must use the registered session executor and `execute_call`.
Deleting the ledger discards its replay protection.

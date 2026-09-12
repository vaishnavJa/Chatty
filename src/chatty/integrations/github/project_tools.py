"""Typed operations on one server-configured GitHub Project.

The caller must obtain approval and reserve every write in the durable ledger.
Private project data is for the connected session, never automatic issue comments.
No tool can select a different owner/project or change visibility/permissions.
"""

import datetime
import json
import math
import os
import re
import tempfile

from chatty.integrations.github import transport
from chatty.integrations.github.transport import REPOSITORY, GitHubToolError

READ_TOOLS = frozenset({"get_project", "list_project_fields", "list_project_items"})
WRITE_TOOLS = frozenset(
    {
        "add_project_item",
        "update_project_item",
        "archive_project_item",
        "remove_project_item",
        "update_project_details",
    }
)
_LABELS = {
    "get_project": "Read project details",
    "list_project_fields": "Read project fields",
    "list_project_items": "Read project items",
    "add_project_item": "Add an issue or pull request to the project",
    "update_project_item": "Update a project field",
    "archive_project_item": "Archive or restore a project item",
    "remove_project_item": "Remove project membership",
    "update_project_details": "Update project details",
}
TOOL_CAPABILITIES = {
    name: {
        "label": label,
        "requires_approval": name in WRITE_TOOLS,
        "destructive": name == "remove_project_item",
    }
    for name, label in _LABELS.items()
}


def _schema(name, properties=None, required=None):
    return {
        "type": "function",
        "name": name,
        "description": _LABELS[name]
        + " in the configured GitHub Project only. "
        + (
            "Requires approval. Removing an item never deletes the repository issue."
            if name in WRITE_TOOLS
            else "Private project data must not be copied into public issues."
        ),
        "parameters": {
            "type": "object",
            "properties": properties or {},
            "required": required or [],
            "additionalProperties": False,
        },
    }


_ITEM_ID = {"type": "string", "minLength": 1, "maxLength": 256}
TOOL_SCHEMAS = [
    _schema("get_project"),
    _schema("list_project_fields"),
    _schema(
        "list_project_items",
        {"limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 30}},
    ),
    _schema(
        "add_project_item",
        {
            "url": {
                "type": "string",
                "description": "Existing vaishnavJa/Chatty issue or pull request URL.",
            }
        },
        ["url"],
    ),
    _schema(
        "update_project_item",
        {
            "item_id": _ITEM_ID,
            "field_name": {"type": "string", "minLength": 1, "maxLength": 256},
            "value": {
                "type": ["string", "number", "null"],
                "description": (
                    "Text, finite number, YYYY-MM-DD date, or exact single-select "
                    "option name (including Status). Null clears the field. "
                    "Read list_project_fields first; never invent option IDs."
                ),
            },
        },
        ["item_id", "field_name", "value"],
    ),
    _schema(
        "archive_project_item",
        {"item_id": _ITEM_ID, "archived": {"type": "boolean"}},
        ["item_id", "archived"],
    ),
    _schema("remove_project_item", {"item_id": _ITEM_ID}, ["item_id"]),
    _schema(
        "update_project_details",
        {
            "title": {"type": "string", "minLength": 1, "maxLength": 256},
            "description": {"type": "string", "maxLength": 1024},
            "readme": {"type": "string", "maxLength": 65536},
        },
    ),
]
_PARAMETERS = {schema["name"]: schema["parameters"] for schema in TOOL_SCHEMAS}
_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_=\-]{0,255}\Z")
_URL_PATTERN = re.compile(
    rf"https://github\.com/{re.escape(REPOSITORY)}/(?:issues|pull)/[1-9][0-9]*\Z",
    re.IGNORECASE,
)
_FIELDS_QUERY = """query($project: ID!, $after: String) {
  node(id: $project) { ... on ProjectV2 { id fields(first: 100, after: $after) {
    totalCount pageInfo { hasNextPage endCursor } nodes {
      __typename
      ... on ProjectV2Field { id name dataType }
      ... on ProjectV2SingleSelectField { id name dataType options { id name } }
      ... on ProjectV2IterationField { id name dataType }
    }
  } } }
}"""
_ITEM_QUERY = """query($item: ID!) {
  node(id: $item) { ... on ProjectV2Item { id isArchived project { id } } }
}"""
_DETAILS_MUTATION = """mutation($input: UpdateProjectV2Input!) {
  updateProjectV2(input: $input) { projectV2 { id title shortDescription readme url } }
}"""


def _failure(code, message):
    return {
        "ok": False,
        "error": {"code": code, "message": message, "uncertain": False},
    }


def _text(value, maximum, *, nonempty=False):
    if type(value) is not str or len(value) > maximum or "\x00" in value:
        return False
    if nonempty and not value.strip():
        return False
    try:
        value.encode("utf-8")
    except UnicodeError:
        return False
    return True


def validate(name, arguments):
    """Validate model arguments without network activity or choosing a project."""
    if type(name) is not str or name not in _PARAMETERS:
        return _failure("unknown_tool", "This project tool is not available.")
    if type(arguments) is not dict:
        return _failure("invalid_arguments", "Arguments must be a JSON object.")
    parameters = _PARAMETERS[name]
    if set(arguments) - parameters["properties"].keys() or not set(
        parameters["required"]
    ).issubset(arguments):
        return _failure("invalid_arguments", "Unexpected or missing project arguments.")
    if name == "list_project_items":
        limit = arguments.get("limit", 30)
        if type(limit) is not int or not 1 <= limit <= 100:
            return _failure(
                "invalid_arguments", "Limit must be an integer from 1 to 100."
            )
    if "item_id" in arguments and (
        type(arguments["item_id"]) is not str
        or not _ID_PATTERN.fullmatch(arguments["item_id"])
    ):
        return _failure("invalid_arguments", "Use an item ID returned by this project.")
    if name == "add_project_item" and (
        type(arguments["url"]) is not str
        or not _URL_PATTERN.fullmatch(arguments["url"])
    ):
        return _failure(
            "invalid_arguments", "Only existing Chatty issue or PR URLs are allowed."
        )
    if name == "archive_project_item" and type(arguments["archived"]) is not bool:
        return _failure("invalid_arguments", "Archived must be a boolean.")
    if name == "update_project_item":
        if not _text(arguments["field_name"], 256, nonempty=True):
            return _failure("invalid_arguments", "A nonempty field name is required.")
        value = arguments["value"]
        if value is not None and not (
            _text(value, 65536)
            or type(value) in (int, float)
            and -1e100 <= value <= 1e100
            and math.isfinite(value)
        ):
            return _failure(
                "invalid_arguments", "Value must be text, a finite number, or null."
            )
    if name == "update_project_details":
        if not arguments:
            return _failure(
                "invalid_arguments", "Provide at least one project detail to update."
            )
        for key, value in arguments.items():
            if not _text(
                value,
                parameters["properties"][key]["maxLength"],
                nonempty=key == "title",
            ):
                return _failure("invalid_arguments", "Invalid project detail value.")
    return None


def _configuration():
    owner = os.environ.get("CHATTY_PROJECT_OWNER", "")
    number = os.environ.get("CHATTY_PROJECT_NUMBER", "")
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\-]{0,38}", owner)
        or not re.fullmatch(r"[1-9][0-9]{0,9}", number)
        or int(number) > 2147483647
    ):
        raise GitHubToolError(
            "project_not_configured",
            "Configure CHATTY_PROJECT_OWNER and CHATTY_PROJECT_NUMBER on the server.",
        )
    return owner, number


def _command(operation, configuration):
    owner, number = configuration
    return ["project", operation, number, "--owner", owner, "--format", "json"]


def _invalid_response(*, uncertain=False):
    return GitHubToolError(
        "invalid_response",
        "GitHub did not return the expected project data.",
        uncertain=uncertain,
    )


def _get_project(configuration):
    project = transport.run_json(_command("view", configuration))
    owner, number = configuration
    if (
        type(project) is not dict
        or not _valid_id(project.get("id"))
        or type(project.get("number")) is not int
        or project["number"] != int(number)
        or type(project.get("owner")) is not dict
        or type(project["owner"].get("login")) is not str
        or project["owner"]["login"].casefold() != owner.casefold()
    ):
        raise _invalid_response()
    return project


def _valid_id(value):
    return type(value) is str and bool(_ID_PATTERN.fullmatch(value))


def _graphql(query, **variables):
    args = ["api", "graphql", "--method", "POST", "-f", "query=" + query]
    for key, value in variables.items():
        args.extend(["-f", key + "=" + value])
    return _graphql_data(transport.run_json(args))


def _graphql_data(result, *, uncertain=False):
    if type(result) is not dict or result.get("errors"):
        raise GitHubToolError(
            "project_access_error",
            "GitHub could not complete this project request. Check project access and token scopes.",
            uncertain=uncertain,
        )
    if type(result.get("data")) is not dict:
        raise _invalid_response(uncertain=uncertain)
    return result["data"]


def _fields(project):
    fields = []
    seen_cursors = set()
    variables = {"project": project["id"]}
    for _ in range(10):
        node = _graphql(_FIELDS_QUERY, **variables).get("node")
        if type(node) is not dict or node.get("id") != project["id"]:
            raise _invalid_response()
        connection = node.get("fields")
        if (
            type(connection) is not dict
            or type(connection.get("nodes")) is not list
            or type(connection.get("pageInfo")) is not dict
            or type(connection.get("totalCount")) is not int
        ):
            raise _invalid_response()
        for field in connection["nodes"]:
            if (
                type(field) is not dict
                or not _valid_id(field.get("id"))
                or not _text(field.get("name"), 256, nonempty=True)
                or type(field.get("dataType")) is not str
            ):
                raise _invalid_response()
            if field["dataType"] == "SINGLE_SELECT":
                options = field.get("options")
                if type(options) is not list or any(
                    type(option) is not dict
                    or not _valid_id(option.get("id"))
                    or not _text(option.get("name"), 256, nonempty=True)
                    for option in options
                ):
                    raise _invalid_response()
            fields.append(field)
        page = connection["pageInfo"]
        if page.get("hasNextPage") is False:
            return {"fields": fields, "totalCount": connection["totalCount"]}
        cursor = page.get("endCursor")
        if (
            page.get("hasNextPage") is not True
            or not _text(cursor, 4096, nonempty=True)
            or cursor in seen_cursors
        ):
            raise _invalid_response()
        seen_cursors.add(cursor)
        variables["after"] = cursor
    raise GitHubToolError(
        "project_limit", "The project has too many fields to inspect safely."
    )


def _item(project, item_id):
    item = _graphql(_ITEM_QUERY, item=item_id).get("node")
    if (
        type(item) is not dict
        or item.get("id") != item_id
        or type(item.get("project")) is not dict
        or item["project"].get("id") != project["id"]
    ):
        raise GitHubToolError(
            "item_not_in_project",
            "This item does not belong to the configured project.",
        )
    if type(item.get("isArchived")) is not bool:
        raise _invalid_response()
    return item


def _field_value(field, value):
    data_type = field["dataType"]
    if data_type not in {"TEXT", "NUMBER", "DATE", "SINGLE_SELECT"}:
        raise GitHubToolError(
            "unsupported_field",
            "This tool supports text, number, date, and single-select project fields.",
        )
    if value is None:
        return ["--clear"]
    if data_type == "TEXT" and value == "":
        raise GitHubToolError(
            "invalid_arguments", "Use null to clear an empty text field."
        )
    if data_type == "TEXT" and type(value) is str:
        return ["--text=" + value]
    if data_type == "NUMBER" and type(value) in (int, float):
        return ["--number=" + str(value)]
    if data_type == "DATE" and type(value) is str:
        try:
            if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                datetime.date.fromisoformat(value)
                return ["--date=" + value]
        except ValueError:
            pass
    if data_type == "SINGLE_SELECT" and type(value) is str:
        matches = [
            option
            for option in field["options"]
            if option["name"].casefold() == value.casefold()
        ]
        if len(matches) != 1:
            raise GitHubToolError(
                "invalid_option",
                "Use one unambiguous option name returned by list_project_fields.",
            )
        return ["--single-select-option-id=" + matches[0]["id"]]
    raise GitHubToolError(
        "invalid_arguments", "Value does not match the configured project's field type."
    )


def _write(args):
    try:
        return transport.run_json(args)
    except GitHubToolError as error:
        # Existing transport predates project tools. Preserve certain local startup
        # failures; once dispatched, never invite automatic retries of a write.
        uncertain = error.code not in {
            "gh_unavailable",
            "permission_denied",
            "invalid_arguments",
        }
        raise GitHubToolError(
            error.code, error.message, uncertain=error.uncertain or uncertain
        ) from None


def _write_item(args, item_id=None):
    result = _write(args)
    if type(result) is not dict or not _valid_id(result.get("id")):
        raise _invalid_response(uncertain=True)
    if item_id is not None and result["id"] != item_id:
        raise _invalid_response(uncertain=True)
    return result


def _update_details(project, arguments):
    changes = {
        "shortDescription" if key == "description" else key: value
        for key, value in arguments.items()
    }
    payload = {
        "query": _DETAILS_MUTATION,
        "variables": {"input": {"projectId": project["id"], **changes}},
    }
    # gh project edit 2.85 ignores empty strings. Use the documented GraphQL
    # mutation with a JSON input file to preserve explicit clears and literal text.
    dispatched = False
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+", encoding="utf-8", suffix=".json"
        ) as body:
            json.dump(payload, body, ensure_ascii=True)
            body.flush()
            dispatched = True
            data = _graphql_data(
                _write(["api", "graphql", "--method", "POST", "--input", body.name]),
                uncertain=True,
            )
    except OSError:
        raise GitHubToolError(
            "local_io_error",
            "Could not finish the local project update operation.",
            uncertain=dispatched,
        ) from None
    updated = data.get("updateProjectV2")
    updated = updated.get("projectV2") if type(updated) is dict else None
    if type(updated) is not dict or updated.get("id") != project["id"]:
        raise _invalid_response(uncertain=True)
    if any(updated.get(key) != value for key, value in changes.items()):
        raise _invalid_response(uncertain=True)
    return updated


def execute(name, arguments):
    """Return factual data or raise GitHubToolError; approval is the caller's job."""
    failure = validate(name, arguments)
    if failure:
        error = failure["error"]
        raise GitHubToolError(error["code"], error["message"])
    arguments = arguments.copy()
    configuration = _configuration()
    project = _get_project(configuration)
    if name == "get_project":
        return project
    if name == "list_project_fields":
        return _fields(project)
    if name == "list_project_items":
        result = transport.run_json(
            _command("item-list", configuration)
            + ["--limit", str(arguments.get("limit", 30))]
        )
        if (
            type(result) is not dict
            or type(result.get("items")) is not list
            or type(result.get("totalCount")) is not int
            or any(
                type(item) is not dict or not _valid_id(item.get("id"))
                for item in result["items"]
            )
        ):
            raise _invalid_response()
        result["truncated"] = result["totalCount"] > len(result["items"])
        return result
    if name == "add_project_item":
        return _write_item(
            _command("item-add", configuration) + ["--url=" + arguments["url"]]
        )
    if name == "update_project_details":
        return _update_details(project, arguments)
    item_id = arguments["item_id"]
    _item(project, item_id)
    if name == "update_project_item":
        fields = _fields(project)["fields"]
        matches = [
            field
            for field in fields
            if field["name"].casefold() == arguments["field_name"].casefold()
        ]
        if len(matches) != 1:
            raise GitHubToolError(
                "invalid_field",
                "Use one unambiguous field name returned by list_project_fields.",
            )
        field = matches[0]
        flags = _field_value(field, arguments["value"])
        result = _write_item(
            [
                "project",
                "item-edit",
                "--format",
                "json",
                "--id",
                item_id,
                "--project-id",
                project["id"],
                "--field-id",
                field["id"],
                *flags,
            ],
            item_id,
        )
        return {
            "item": result,
            "field_name": field["name"],
            "value": arguments["value"],
        }
    if name == "archive_project_item":
        args = _command("item-archive", configuration) + ["--id", item_id]
        if arguments["archived"] is False:
            args.append("--undo")
        result = _write_item(args, item_id)
        return {"item": result, "archived": arguments["archived"]}
    result = _write_item(
        _command("item-delete", configuration) + ["--id", item_id], item_id
    )
    return {
        "item_id": result["id"],
        "removed_from_project": True,
        "repository_issue_deleted": False,
    }

"""Command-line access to external information sources."""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from chatty.integrations.common import IntegrationError, require_text
from chatty.integrations.confluence import ConfluenceClient
from chatty.integrations.internet_search import InternetSearchClient
from chatty.integrations.teams import TeamsClient


def credential(name: str) -> str:
    return require_text(os.environ.get(name, ""), name)


def search(args, http):
    with InternetSearchClient(credential("BRAVE_SEARCH_API_KEY"), http=http) as client:
        return client.search(args.query, limit=args.limit)


def teams(args, http):
    with TeamsClient(credential("TEAMS_ACCESS_TOKEN"), http=http) as client:
        operations = {
            "list": lambda: client.teams(limit=args.limit),
            "channels": lambda: client.channels(args.team_id, limit=args.limit),
            "messages": lambda: client.messages(
                args.team_id, args.channel_id, limit=args.limit
            ),
            "replies": lambda: client.replies(
                args.team_id, args.channel_id, args.message_id, limit=args.limit
            ),
        }
        return operations[args.operation]()


def confluence(args, http):
    with ConfluenceClient(
        credential("CONFLUENCE_URL"),
        credential("CONFLUENCE_EMAIL"),
        credential("CONFLUENCE_API_TOKEN"),
        http=http,
    ) as client:
        if args.operation == "page":
            return client.page(args.page_id)
        if args.cql:
            return client.search_cql(args.query, limit=args.limit)
        return client.search(args.query, limit=args.limit)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Read Teams, Confluence, and internet search as JSON."
    )
    root.add_argument(
        "--env-file",
        type=Path,
        help="Explicit dotenv file; existing environment values take precedence",
    )
    commands = root.add_subparsers(dest="command")
    search_parser = commands.add_parser("search", help="Search the web with Brave")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=10)
    search_parser.set_defaults(handler=search)
    add_teams_parser(commands)
    add_confluence_parser(commands)
    return root


def add_teams_parser(commands):
    team_parser = commands.add_parser("teams", help="Read Microsoft Teams")
    team_parser.set_defaults(handler=teams)
    operations = team_parser.add_subparsers(dest="operation", required=True)
    arguments = {
        "list": (),
        "channels": ("team_id",),
        "messages": ("team_id", "channel_id"),
        "replies": ("team_id", "channel_id", "message_id"),
    }
    for name, positional in arguments.items():
        operation = operations.add_parser(name)
        operation.add_argument("--limit", type=int, default=100)
        for argument in positional:
            operation.add_argument(argument)


def add_confluence_parser(commands):
    confluence_parser = commands.add_parser(
        "confluence", help="Search and read Confluence Cloud"
    )
    confluence_parser.set_defaults(handler=confluence)
    operations = confluence_parser.add_subparsers(dest="operation", required=True)
    search_parser = operations.add_parser("search")
    search_parser.add_argument("query")
    search_parser.add_argument(
        "--cql",
        action="store_true",
        help="Interpret query as Confluence Query Language",
    )
    search_parser.add_argument("--limit", type=int, default=25)
    page_parser = operations.add_parser("page")
    page_parser.add_argument("page_id")


def run(argv: list[str] | None = None, *, http=None) -> int:
    root = parser()
    args = root.parse_args(argv)
    if args.command is None:
        root.print_help()
        return 0
    try:
        load_environment(args.env_file)
        result = args.handler(args, http)
    except IntegrationError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


def load_environment(path: Path | None) -> None:
    if path is None:
        return
    if not path.is_file():
        raise IntegrationError("The specified environment file does not exist.")
    try:
        load_dotenv(path, override=False, interpolate=False)
    except (OSError, UnicodeError):
        raise IntegrationError("Could not read the environment file.") from None


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()

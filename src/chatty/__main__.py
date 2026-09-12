"""Start the local Chatty backend with ``uv run chatty``."""

from chatty.server import create_server


def main() -> None:
    """Serve the UI and API without opening a microphone or Live session."""
    try:
        server = create_server()
    except (ValueError, OSError):
        raise SystemExit(
            "Cannot start Chatty. Check .env settings and whether the port is already in use."
        ) from None
    print(f"Chatty: http://localhost:{server.server_address[1]}", flush=True)
    if not server.app.settings.api_key:
        print(
            "Set OPENAI_API_KEY in .env and restart to enable Live sessions.",
            flush=True,
        )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

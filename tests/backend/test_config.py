import os

from chatty.config import Settings


def test_dotenv_loading_and_environment_precedence(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "environ", os.environ.copy())
    for key in (
        "OPENAI_API_KEY",
        "OPENAI_BACKEND_MODEL",
        "CHATTY_PORT",
        "GITHUB_REPOSITORY",
        "CHATTY_WEB_DIR",
    ):
        monkeypatch.delenv(key, raising=False)
    (tmp_path / ".env").write_text(
        "OPENAI_API_KEY=secret-from-dotenv\nOPENAI_BACKEND_MODEL=from-file\nCHATTY_PORT=4321\n"
    )
    monkeypatch.setenv("OPENAI_BACKEND_MODEL", "from-environment")
    settings = Settings.from_env(tmp_path)
    assert settings.api_key == "secret-from-dotenv"
    assert settings.backend_model == "from-environment"
    assert settings.port == 4321
    assert settings.repository == "vaishnavJa/Chatty"
    assert settings.web_dir == tmp_path / "web"
    assert settings.api_key not in repr(settings)

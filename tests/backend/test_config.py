import os

from chatty.config import Settings


def test_dotenv_loading_and_environment_precedence(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "environ", os.environ.copy())
    for key in (
        "OPENAI_API_KEY",
        "OPENAI_BACKEND_MODEL",
        "OPENAI_VISION_MODEL",
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
    assert settings.vision_model == "gpt-5.6-terra"
    assert settings.port == 4321
    assert settings.repository == "vaishnavJa/Chatty"
    assert settings.web_dir == tmp_path / "web"
    assert settings.api_key not in repr(settings)


def test_vision_model_can_be_configured_independently(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_BACKEND_MODEL", "delegation-model")
    monkeypatch.setenv("OPENAI_VISION_MODEL", "vision-model")
    settings = Settings.from_env(tmp_path)
    assert settings.backend_model == "delegation-model"
    assert settings.vision_model == "vision-model"

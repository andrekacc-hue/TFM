from __future__ import annotations

from shared.config import BaseServiceSettings, find_env_file


def test_find_env_file_walks_up(tmp_path):
    (tmp_path / ".env").write_text("X=1", encoding="utf-8")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert find_env_file(nested) == tmp_path / ".env"


def test_settings_normalization():
    settings = BaseServiceSettings(
        _env_file=None,
        supabase_url="https://demo.supabase.co/",
        supabase_service_role_key="sb_secret_x",
        internal_api_key="clave-interna-larga-123",
        redis_url="",
        supabase_jwt_secret="",
    )
    assert settings.supabase_url == "https://demo.supabase.co"
    assert settings.redis_url is None
    assert settings.supabase_jwt_secret is None
    assert settings.supabase_schema == "tfm"
    assert settings.embedding_dim == 384

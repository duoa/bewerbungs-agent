"""Unit tests for the credential + PII redaction layer.

User Story 3 (P3):
- FR-017: env-var secrets always redacted, regardless of mode/mask_pii.
- FR-019a: PII patterns redacted in full mode when mask_pii=True (default).
- mask_pii=False does NOT bypass env-var redaction.
"""

from __future__ import annotations

import pytest

from bewerbungs_agent.utils.redaction import redact, refresh_secret_snapshot


@pytest.fixture(autouse=True)
def _reset_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test sets its own secret env vars and refreshes the snapshot."""
    # Clear common secrets first
    for var in ("FAKE_API_KEY", "FAKE_TOKEN", "FAKE_SECRET", "FAKE_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    refresh_secret_snapshot()
    yield
    refresh_secret_snapshot()


class TestEnvVarRedaction:
    def test_strips_api_key_secret_token_password_values(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FAKE_API_KEY", "secret_apikey_123")
        monkeypatch.setenv("FAKE_TOKEN", "tok_xyz456")
        monkeypatch.setenv("FAKE_SECRET", "secret_word789")
        monkeypatch.setenv("FAKE_PASSWORD", "pw_pwd_000")
        refresh_secret_snapshot()

        text = (
            "user typed secret_apikey_123 and tok_xyz456, "
            "also secret_word789 and pw_pwd_000 in logs"
        )
        cleaned = redact(text, mode="summary", mask_pii=False)
        assert "secret_apikey_123" not in cleaned
        assert "tok_xyz456" not in cleaned
        assert "secret_word789" not in cleaned
        assert "pw_pwd_000" not in cleaned
        assert "<REDACTED:FAKE_API_KEY>" in cleaned
        assert "<REDACTED:FAKE_TOKEN>" in cleaned
        assert "<REDACTED:FAKE_SECRET>" in cleaned
        assert "<REDACTED:FAKE_PASSWORD>" in cleaned

    def test_full_mode_with_mask_pii_false_still_redacts_secrets(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FR-017: env-var secret redaction is unconditional. mask_pii=False
        only disables PII; it never disables secret redaction."""
        monkeypatch.setenv("FAKE_API_KEY", "topsecret999")
        refresh_secret_snapshot()

        text = "contains topsecret999 and alice@example.com"
        cleaned = redact(text, mode="full", mask_pii=False)
        assert "topsecret999" not in cleaned
        assert "<REDACTED:FAKE_API_KEY>" in cleaned
        # mask_pii=False → email is preserved
        assert "alice@example.com" in cleaned

    def test_summary_mode_does_not_apply_pii_pass(self) -> None:
        """Summary mode skips the PII regex pass entirely; only env-var pass runs."""
        text = "contact alice@example.com or call +49 30 12345678"
        cleaned = redact(text, mode="summary", mask_pii=True)
        # Email and phone preserved because we're in summary mode
        assert "alice@example.com" in cleaned
        assert "+49 30 12345678" in cleaned

    def test_recursive_walk_redacts_nested_structures(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FAKE_API_KEY", "deeply_nested_secret")
        refresh_secret_snapshot()

        nested = {
            "outer": ["item: deeply_nested_secret", {"k": "deeply_nested_secret"}],
            "scalar": 42,
            "bool": True,
        }
        cleaned = redact(nested, mode="summary", mask_pii=False)
        assert "deeply_nested_secret" not in str(cleaned)
        assert cleaned["scalar"] == 42
        assert cleaned["bool"] is True


class TestPIIRedaction:
    def test_full_mode_strips_email(self) -> None:
        text = "Email: alice.bob+work@example-corp.co.uk for inquiries"
        cleaned = redact(text, mode="full", mask_pii=True)
        assert "alice.bob+work@example-corp.co.uk" not in cleaned
        assert "<EMAIL>" in cleaned

    def test_full_mode_strips_phone(self) -> None:
        text = "Call +49 30 12345678 today"
        cleaned = redact(text, mode="full", mask_pii=True)
        assert "+49 30 12345678" not in cleaned
        assert "<PHONE>" in cleaned

    def test_full_mode_strips_iban(self) -> None:
        text = "IBAN DE89370400440532013000 for transfer"
        cleaned = redact(text, mode="full", mask_pii=True)
        assert "DE89370400440532013000" not in cleaned
        assert "<IBAN>" in cleaned

    def test_full_mode_strips_postal_block(self) -> None:
        text = "Lives at 10115 Berlin in the city"
        cleaned = redact(text, mode="full", mask_pii=True)
        assert "10115 Berlin" not in cleaned
        assert "<POSTAL>" in cleaned

    def test_full_mode_strips_all_pii_patterns_together(self) -> None:
        text = (
            "Alice Bob alice@example.com +49 30 12345678 "
            "DE89370400440532013000 10115 Berlin Germany"
        )
        cleaned = redact(text, mode="full", mask_pii=True)
        assert "alice@example.com" not in cleaned
        assert "+49 30 12345678" not in cleaned
        assert "DE89370400440532013000" not in cleaned
        assert "10115 Berlin" not in cleaned

    def test_returns_input_unchanged_for_non_string_scalars(self) -> None:
        assert redact(42, mode="full", mask_pii=True) == 42
        assert redact(None, mode="full", mask_pii=True) is None
        assert redact(True, mode="full", mask_pii=True) is True
        assert redact(3.14, mode="full", mask_pii=True) == 3.14

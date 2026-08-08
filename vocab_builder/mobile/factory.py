"""Composition root for the private mobile service."""

from __future__ import annotations

from pathlib import Path
from collections.abc import Sequence
from typing import Optional

from rich.console import Console

from vocab_builder.core.providers.manager import ProviderManager
from vocab_builder.core.vocab import VocabBuilder
from vocab_builder.languages import get_language_config
from vocab_builder.llm_client import ProviderFactory
from vocab_builder.ui_helper import UIHelper

from .catalog import MobileVocabCatalog
from .service import AIUnavailableError, MobileVocabService


def build_mobile_service(
    *,
    latex_file: Path,
    language: str = "fr",
    provider: str = "gemini",
    config_dir: Optional[Path] = None,
) -> MobileVocabService:
    """Build the service without ever launching the credential wizard."""
    runtime_dir = Path(config_dir) if config_dir else latex_file.parent
    api_key = _resolve_api_key(provider=provider, runtime_dir=runtime_dir)
    return _build_service(
        latex_file=latex_file,
        language=language,
        provider=provider,
        api_key=api_key,
    )


def build_mobile_catalog(
    *,
    languages: Sequence[str],
    provider: str = "gemini",
    config_dir: Path,
    default_language: Optional[str] = None,
) -> MobileVocabCatalog:
    """Build every configured collection from one credential resolution."""
    runtime_dir = Path(config_dir)
    api_key = _resolve_api_key(provider=provider, runtime_dir=runtime_dir)
    services: dict[str, MobileVocabService] = {}
    for requested_language in languages:
        config = get_language_config(requested_language)
        if config.code in services:
            raise ValueError(f"Duplicate mobile language: {config.code}")
        services[config.code] = _build_service(
            latex_file=runtime_dir / config.vocab_filename,
            language=config.code,
            provider=provider,
            api_key=api_key,
        )
    return MobileVocabCatalog(services, default_language=default_language)


def _resolve_api_key(*, provider: str, runtime_dir: Path) -> str:
    provider_manager = ProviderManager(
        UIHelper(Console(), interactive=False),
        runtime_dir,
    )
    metadata = provider_manager.get_metadata(provider)
    resolution = provider_manager.resolve_provider_silently(metadata)
    if resolution is None:
        raise AIUnavailableError(
            f"No valid {metadata.display_name} credential was found. "
            f"Set {metadata.env_var} in the server environment."
        )
    return resolution.api_key


def _build_service(
    *,
    latex_file: Path,
    language: str,
    provider: str,
    api_key: str,
) -> MobileVocabService:
    builder = VocabBuilder(
        latex_file=str(latex_file),
        provider=provider,
        language=language,
        client=ProviderFactory.create(provider, api_key),
        interactive=False,
    )
    return MobileVocabService(builder)


__all__ = ["build_mobile_catalog", "build_mobile_service"]

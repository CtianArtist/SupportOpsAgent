from app.config import Settings
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import LLMProvider
from app.providers.mock_provider import MockLLMProvider
from app.providers.openai_provider import OpenAIProvider
from app.services.errors import ProviderConfigurationError


def create_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "mock":
        return MockLLMProvider()
    if settings.llm_provider == "openai":
        return OpenAIProvider(settings)
    if settings.llm_provider == "anthropic":
        return AnthropicProvider(settings)
    raise ProviderConfigurationError(f"Unsupported LLM provider: {settings.llm_provider}")
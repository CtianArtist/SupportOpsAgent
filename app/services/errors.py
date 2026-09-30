class AgentError(Exception):
    """Base class for expected agent and tool failures."""


class AuthorizationDenied(AgentError):
    """Raised when a session attempts to access another customer's data."""


class RetryableToolError(AgentError):
    """A transient tool failure that can safely be retried."""


class RateLimitToolError(RetryableToolError):
    """A temporary downstream rate limit."""


class TemporaryServiceError(RetryableToolError):
    """A temporary downstream outage."""


class ToolExecutionFailed(AgentError):
    """Raised when a tool remains unavailable after safe retries."""


class ProviderError(AgentError):
    """Base class for provider configuration and response errors."""


class ProviderConfigurationError(ProviderError):
    """The selected provider is missing configuration."""


class MalformedProviderResponse(ProviderError):
    """The provider response did not match the expected structured contract."""
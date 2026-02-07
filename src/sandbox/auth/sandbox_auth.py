"""
Sandbox API Key Authentication.
Validates sandbox API keys by calling AI_Assistants_MVP REST API.
"""
import logging
from typing import Optional, Dict, Any
import httpx

logger = logging.getLogger(__name__)


class SandboxAuthenticator:
    """
    Authenticates sandbox requests using API keys from AI_Assistants_MVP.

    This class validates sandbox API keys (sb_*) by calling the MVP's
    validation endpoint via REST API.
    """

    def __init__(self, mvp_api_url: str, timeout: float = 5.0):
        """
        Initialize the authenticator with MVP API URL.

        Args:
            mvp_api_url: Base URL of AI_Assistants_MVP API
                        Example: http://localhost:8000 or https://api.yourdomain.com
            timeout: Request timeout in seconds (default: 5.0)
        """
        self.mvp_api_url = mvp_api_url.rstrip("/")
        self.validation_endpoint = f"{self.mvp_api_url}/api/v1/sandbox/validate-key"
        self.timeout = timeout
        self.client = httpx.AsyncClient(timeout=timeout)
        logger.info(f"Sandbox authenticator initialized with MVP API: {self.mvp_api_url}")

    async def verify_sandbox_key(self, api_key: str) -> Optional[Dict[str, Any]]:
        """
        Verify a sandbox API key by calling MVP validation endpoint.

        Args:
            api_key: The API key to verify (should start with 'sb_')

        Returns:
            Dict with workspace_id, workspace_name, user_id if valid, None otherwise
        """
        # Check prefix locally first
        if not api_key.startswith("sb_"):
            key_prefix = api_key[:10] if len(api_key) >= 10 else api_key
            logger.warning(f"Invalid API key prefix: {key_prefix}...")
            return None

        try:
            # Call MVP validation endpoint
            response = await self.client.post(
                self.validation_endpoint,
                json={"api_key": api_key},
                headers={"Content-Type": "application/json"}
            )

            if response.status_code != 200:
                logger.warning(
                    f"MVP API returned status {response.status_code} for key validation"
                )
                return None

            data = response.json()

            if not data.get("valid"):
                key_prefix = api_key[:10]
                logger.warning(f"Invalid or inactive sandbox API key: {key_prefix}...")
                return None

            logger.info(
                f"Sandbox API key validated via MVP API "
                f"(workspace_id={data.get('workspace_id')})"
            )

            return {
                "workspace_id": data.get("workspace_id"),
                "workspace_name": data.get("workspace_name"),
                "user_id": data.get("user_id"),
                "api_key_name": data.get("api_key_name"),
                "permissions": data.get("permissions", {}),
            }

        except httpx.TimeoutException:
            logger.error(f"Timeout calling MVP validation endpoint: {self.validation_endpoint}")
            return None
        except httpx.RequestError as e:
            logger.error(f"Error calling MVP validation endpoint: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Unexpected error verifying sandbox API key: {e}", exc_info=True)
            return None

    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()
        logger.info("Sandbox authenticator closed")


# Singleton instance
_authenticator: Optional[SandboxAuthenticator] = None


def initialize_authenticator(mvp_api_url: str, timeout: float = 5.0) -> SandboxAuthenticator:
    """
    Initialize the global authenticator instance.

    Args:
        mvp_api_url: Base URL of AI_Assistants_MVP API
        timeout: Request timeout in seconds

    Returns:
        The authenticator instance
    """
    global _authenticator
    _authenticator = SandboxAuthenticator(mvp_api_url, timeout)
    return _authenticator


def get_authenticator() -> Optional[SandboxAuthenticator]:
    """Get the global authenticator instance."""
    return _authenticator

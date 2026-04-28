import httpx
from typing import Dict, Optional
from app.core.config import settings

class UnipileException(Exception):
    """Exception raised for Unipile API errors"""
    pass

class Unipile:
    """
    Class to handle Unipile API interactions.
    """
    def __init__(self):
        """
        Initialize Unipile API client.
        """

        self.api_key = settings.UNIPILE_API_KEY
        
        # Get DSN and strip quotes
        dsn = settings.UNIPILE_DSN or "api11.unipile.com:14157"
        dsn = dsn.strip('"\'')
        self.base_url = f"https://{dsn}/api/v1"

        self.redirect_uri = settings.OAUTH_REDIRECT_URI or "http://localhost:8001/auth/callback"

        if not self.api_key:
            raise ValueError("UNIPILE_API_KEY environment variable not set")
         # Initialize httpx client with timeout and retry settings
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),  # 30s total timeout, 10s connect timeout
            transport=httpx.AsyncHTTPTransport(retries=3)  # Retry failed requests up to 3 times
        )

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for API requests"""
        return {
            "X-API-KEY": self.api_key,
            "Accept": "application/json"
        }
    
    async def get_email_attachment(self, email_id: str, attachment_id: str, account_id: Optional[str] = None) -> bytes:
        """
        Retrieve an attachment from an email.
        
        Args:
            email_id: ID of the email containing the attachment
            attachment_id: ID of the attachment to retrieve
            account_id: Optional account ID (uses default if not specified)
            
        Returns:
            bytes: The attachment file content
        """
        try:
            url = f"{self.base_url}/emails/{email_id}/attachments/{attachment_id}"
            
            params = {}
            if account_id:
                params["account_id"] = account_id
            
            response = await self.client.get(url, headers=self._get_headers(), params=params,timeout=120)
            
            if response.status_code != 200:
                raise UnipileException(f"Error retrieving attachment: {response.text}")
            
            return response.content
        except Exception as e:
            raise UnipileException(f"Failed to get attachment: {str(e)}")

import json
import httpx
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)

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
        self.client = httpx.Client(
            timeout=httpx.Timeout(30.0, connect=10.0),  # 30s total timeout, 10s connect timeout
            transport=httpx.HTTPTransport(retries=3)  # Retry failed requests up to 3 times
        )

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for API requests"""
        return {
            "X-API-KEY": self.api_key,
            "Accept": "application/json"
        }

    def get_email(self, email_id: str, account_id: Optional[str] = None) -> Dict:
        """
        Get a specific email by ID.
        
        Args:
            email_id: ID of the email to retrieve
            account_id: Optional account ID (uses default if not specified)
            
        Returns:
            Dict: Email details
        """
        try:
            url = f"{self.base_url}/emails/{email_id}"
            
            params = {}
            if account_id:
                params["account_id"] = account_id
            
            response = self.client.get(url, headers=self._get_headers(), params=params,timeout=120)
            
            if response.status_code != 200:
                raise UnipileException(f"Error getting email: {response.text}")
            
            result = response.json()
            return result
        except Exception as e:
            raise UnipileException(f"Failed to get email: {str(e)}")

    def get_account_email(self, account_id: str) -> str:
        """
        Get the email address (mailbox id) for a Unipile account_id.
        Uses GET /api/v1/accounts/{account_id}; email from connection_params.mail.id.
        Raises UnipileException if account not found or email not present.
        """
        if not account_id:
            raise UnipileException("account_id is required to get account email")
        try:
            url = f"{self.base_url}/accounts/{account_id}"
            response = self.client.get(url, headers=self._get_headers())
            if response.status_code != 200:
                raise UnipileException(f"Error getting account email: {response.text}")
            data = response.json()
            email = data.get("connection_params", {}).get("mail", {}).get("id")
            if not email or not isinstance(email, str) or "@" not in email:
                raise UnipileException(f"No email found for account_id: {account_id}")
            return email
        except Exception as e:
            raise UnipileException(f"Failed to get account email: {str(e)}")

    def get_email_attachment(self, email_id: str, attachment_id: str, account_id: Optional[str] = None) -> bytes:
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
            
            response = self.client.get(url, headers=self._get_headers(), params=params,timeout=120)
            
            if response.status_code != 200:
                raise UnipileException(f"Error retrieving attachment: {response.text}")
            
            return response.content
        except UnipileException:
            raise  
        except Exception as e:
            raise UnipileException(f"Failed to get attachment: {str(e)}")

    def list_emails(
        self, 
        account_id: Optional[str] = None,
        folder: Optional[str] = None,
        limit: int = 20,
        before: Optional[str] = None,
        after: Optional[str] = None,
        meta_only: bool = False,
        thread_id: Optional[str] = None,
        cursor: Optional[str] = None
    ) -> List[Dict]:
        """
        List emails from a mailbox with various filtering options.
        
        Args:
            account_id: Optional account ID (uses default if not specified)
            folder: Optional folder ID to filter emails by
            limit: Maximum number of emails to return (1-250)
            before: Filter to emails before this date (ISO 8601 format)
            after: Filter to emails after this date (ISO 8601 format)
            meta_only: If True, only return email metadata (no body)
            thread_id: Optional thread ID to filter emails by specific thread
            cursor: Cursor for pagination (alternative to before/after)
            
        Returns:
            List[Dict]: List of email objects
        """
        try:
            url = f"{self.base_url}/emails"
            
            params = {"limit": limit}
            
            # Use provided account_id or default
            if account_id:
                params["account_id"] = account_id
            else:
                raise ValueError("No account_id provided and no default account set")
            
            # Handle cursor-based pagination vs date-based pagination
            if cursor:
                # Use cursor-based pagination (only cursor and limit)
                params["cursor"] = cursor
            else:
                # Use date-based pagination with other filters
                if folder:
                    params["folder"] = folder
                    
                if before:
                    params["before"] = before
                    
                if after:
                    params["after"] = after
                    
                if thread_id:
                    params["thread_id"] = thread_id
                    
                if meta_only:
                    params["meta_only"] = "true"

            response = self.client.get(url, headers=self._get_headers(), params=params,timeout=120)

            if response.status_code != 200:
                raise UnipileException(f"Error listing emails: {response.text}")
            
            # Return the full result so we can access cursor information
            result = response.json()
            return result
        except Exception as e:
            raise UnipileException(f"Failed to list emails: {str(e)}")

    def send_email(
        self, 
        to: List[Dict], 
        subject: str, 
        body: str, 
        account_id: Optional[str] = None,
        cc: Optional[List[Dict]] = None, 
        bcc: Optional[List[Dict]] = None,
        reply_to: Optional[str] = None
    ) -> Dict:
        """
        Send an email using Unipile.
        
        Args:
            to: List of recipient dicts with display_name and identifier (email)
            subject: Email subject
            body: Email body content
            account_id: Optional account ID to send from
            cc: Optional list of CC recipients
            bcc: Optional list of BCC recipients
            reply_to: Optional provider_id of the email being replied to (Unipile API requirement)
            
        Returns:
            Dict: Response containing success status and tracking information
        """
        try:
            url = f"{self.base_url}/emails"
            
            if not account_id:
                raise ValueError("No account_id provided and no default account set")

            data = {
                'account_id': account_id,
                'subject': subject,
                'body': body,
                'to': json.dumps(to),
            }
            
            if cc:
                data['cc'] = json.dumps(cc)
            
            if bcc:
                data['bcc'] = json.dumps(bcc)
                
            if reply_to:
                data['reply_to'] = reply_to
            
            headers = self._get_headers()
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
            
            response = self.client.post(url, data=data, headers=headers,timeout=120)

            if response.status_code not in [200, 201]:
                error_msg = response.text
                error_details: Dict[str, Any] = {}
                try:
                    error_json = response.json()
                    # Extract error message, title, type, and status for better error reporting
                    error_msg = error_json.get('error') or error_json.get('title') or error_json.get('message') or error_msg
                    error_details = {
                        'status_code': response.status_code,
                        'error_type': error_json.get('type'),
                        'error_title': error_json.get('title'),
                        'raw_error': error_json
                    }
                except (ValueError, TypeError, KeyError):
                    error_details = {'status_code': response.status_code, 'raw_response': error_msg}
                
                # Format error message for better readability
                if response.status_code == 401:
                    formatted_error = f"Invalid credentials (401): {error_msg}. Please reconnect your email account."
                elif response.status_code == 403:
                    formatted_error = f"Access forbidden (403): {error_msg}. Check account permissions."
                elif response.status_code == 404:
                    formatted_error = f"Account not found (404): {error_msg}. The account_id may be invalid."
                else:
                    formatted_error = f"Email send failed ({response.status_code}): {error_msg}"
                
                logger.warning(
                    "Unipile POST /emails failed status=%s account_id=%s subject=%r reply_to=%r err=%s raw_len=%s",
                    response.status_code,
                    account_id,
                    subject[:200] if subject else "",
                    reply_to,
                    formatted_error,
                    len(response.text or ""),
                )
                logger.debug(
                    "Unipile POST /emails error_details=%s body_preview=%s",
                    error_details,
                    (response.text or "")[:2000],
                )
                return {"success": False, "error": formatted_error, "error_details": error_details}
            
            result = response.json()
            tracking_id = result.get("tracking_id")
            logger.info(
                "Unipile POST /emails ok status=%s account_id=%s subject=%r reply_to=%r tracking_id=%s",
                response.status_code,
                account_id,
                subject[:200] if subject else "",
                reply_to,
                tracking_id,
            )
            return {
                "success": True, 
                "message_id": tracking_id,
                "tracking_id": tracking_id,
                "response": result
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

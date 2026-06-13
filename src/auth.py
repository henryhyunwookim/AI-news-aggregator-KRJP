import os
import sys
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from src.config import SCOPES

def authenticate_gmail():
    """
    Authenticates with Gmail using credentials.json and token.json.
    Refreshes the token automatically if expired.
    """
    creds = None
    
    # Check if token.json exists in the current working directory
    if os.path.exists('token.json'):
        try:
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        except Exception as e:
            print(f"Error loading token.json: {e}")
            creds = None

    # If there are no (valid) credentials available, handle login or refresh
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                print("Attempting to refresh Gmail access token...")
                creds.refresh(Request())
            except Exception as e:
                print(f"Error refreshing token: {e}")
                creds = None
        
        if not creds:
            # Check if running in a cloud environment where browser isn't available
            is_cloud = os.getenv('K_SERVICE') is not None
            is_interactive = sys.stdin and sys.stdin.isatty()
            
            if is_cloud or not is_interactive:
                # Remove invalid token.json
                if os.path.exists('token.json'):
                    try:
                        os.remove('token.json')
                        print("Removed expired token.json.")
                    except Exception as rm_err:
                        print(f"Could not remove token.json: {rm_err}")
                
                raise RuntimeError(
                    "GMAIL AUTHENTICATION ERROR: token.json is expired and cannot be refreshed automatically "
                    "in a non-interactive/cloud environment. Please run the script locally in interactive mode "
                    "first (e.g. python src/main.py --auth) to re-authorize and generate a new token.json."
                )
            
            if not os.path.exists('credentials.json'):
                raise FileNotFoundError("credentials.json not found in the workspace root.")
            
            print("Starting local server for Gmail OAuth authorization...")
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
            
        # Save credentials for future runs
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
            print("Successfully authenticated and saved token.json!")

    return creds

if __name__ == "__main__":
    try:
        print("Re-authenticating Gmail...")
        authenticate_gmail()
        print("Gmail authenticated successfully!")
    except Exception as e:
        print(f"Authentication failed: {e}")

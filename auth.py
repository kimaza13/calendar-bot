from google_auth_oauthlib.flow import InstalledAppFlow
import json, os

SCOPES = ["https://www.googleapis.com/auth/calendar"]
CREDS_FILE = os.getenv("GOOGLE_CREDENTIALS_JSON", "credentials.json")
TOKEN_FILE = "token.json"

flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
creds = flow.run_local_server(port=0)

token_data = {
    "token": creds.token,
    "refresh_token": creds.refresh_token,
    "token_uri": creds.token_uri,
    "client_id": creds.client_id,
    "client_secret": creds.client_secret,
    "scopes": list(creds.scopes),
}
with open(TOKEN_FILE, "w") as f:
    json.dump(token_data, f, indent=2)

print(f"Saved {TOKEN_FILE}")
print(f"\nCopy this value to GOOGLE_TOKEN_JSON on Render:\n")
print(json.dumps(token_data))

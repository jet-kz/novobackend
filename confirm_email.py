"""
confirm_email.py - Force-confirms a user's email in Supabase and resets password.
Usage: .\\venv\\Scripts\\python.exe confirm_email.py
"""
import os, json, urllib.request, urllib.error
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

TARGET_EMAIL = "merchant@novo.ng"
TARGET_PASSWORD = "MerchantPass2026!"

from supabase import create_client  # type: ignore
c = create_client(SUPABASE_URL, KEY)

# Step 1: Find user ID
users = c.auth.admin.list_users()
user_id = None
for u in users:
    if u.email == TARGET_EMAIL:
        user_id = u.id
        break

if not user_id:
    # Create fresh
    res = c.auth.admin.create_user({
        "email": TARGET_EMAIL,
        "password": TARGET_PASSWORD,
        "email_confirm": True,
        "user_metadata": {"full_name": "Novo Merchant Partner", "role": "merchant"},
    })
    user_id = res.user.id if res.user else None
    print("Created new user: " + str(user_id))
else:
    print("Found user: " + user_id)

# Step 2: Force confirm via Admin REST API
url = SUPABASE_URL + "/auth/v1/admin/users/" + user_id
data = json.dumps({"email_confirm": True, "password": TARGET_PASSWORD}).encode("utf-8")
req = urllib.request.Request(url, data=data, method="PUT")
req.add_header("Content-Type", "application/json")
req.add_header("apikey", KEY)
req.add_header("Authorization", "Bearer " + KEY)

try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        d = json.loads(resp.read())
        print("Confirmed email_confirmed_at: " + str(d.get("email_confirmed_at", "?")))
except urllib.error.HTTPError as e:
    print("REST error: " + str(e.read()))

# Step 3: Verify login works
try:
    lr = c.auth.sign_in_with_password({"email": TARGET_EMAIL, "password": TARGET_PASSWORD})
    if lr.session and lr.session.access_token:
        print("LOGIN OK - " + TARGET_EMAIL)
    else:
        print("LOGIN FAIL - no session")
except Exception as ex:
    print("LOGIN FAIL - " + str(ex))

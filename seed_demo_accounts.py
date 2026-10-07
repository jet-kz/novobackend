"""
seed_demo_accounts.py - seeds admin@novo.ng and merchant@novo.ng
Uses service role key + direct REST to auto-confirm email.
Run: .\\venv\\Scripts\\python.exe seed_demo_accounts.py
"""
import os, json, urllib.request
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

if not SUPABASE_URL or not KEY:
    raise SystemExit("ERROR: SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY missing from .env")

from supabase import create_client  # type: ignore
c = create_client(SUPABASE_URL, KEY)

ACCOUNTS = [
    ("admin@novo.ng", "SuperAdminPass2026!", "Novo Super Admin", "super_admin"),
    ("merchant@novo.ng", "MerchantPass2026!", "Novo Merchant Partner", "merchant"),
]


def admin_rest_update(user_id, body):
    """Direct REST call to Supabase Admin Users endpoint to update a user."""
    url = SUPABASE_URL + "/auth/v1/admin/users/" + user_id
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "apikey": KEY,
            "Authorization": "Bearer " + KEY,
        },
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read()), None
    except urllib.error.HTTPError as e:
        return None, json.loads(e.read())
    except Exception as ex:
        return None, str(ex)


def main():
    print("=========================================")
    print("  SEEDING NOVO DEMO ACCOUNTS")
    print("=========================================")

    # Get existing users from Supabase
    try:
        users = c.auth.admin.list_users()
        uid_map = {u.email: u.id for u in users}
        print("[OK] Fetched existing users: " + str(list(uid_map.keys())))
    except Exception as ex:
        uid_map = {}
        print("[!!] Could not list users: " + str(ex))

    for email, password, full_name, role in ACCOUNTS:
        print("")
        print("-- Processing: " + email)

        user_id = uid_map.get(email)

        if user_id:
            print("[>>] Already exists, updating password + confirming email")
            resp, err = admin_rest_update(user_id, {
                "password": password,
                "email_confirm": True,
            })
            if err:
                print("[!!] Update error: " + str(err))
            else:
                confirmed_at = resp.get("email_confirmed_at", "unknown") if resp else "no_response"
                print("[OK] Updated. email_confirmed_at=" + str(confirmed_at))
        else:
            print("[>>] Creating new user")
            try:
                res = c.auth.admin.create_user({
                    "email": email,
                    "password": password,
                    "email_confirm": True,
                    "user_metadata": {
                        "full_name": full_name,
                        "role": role,
                    },
                })
                if res.user:
                    user_id = res.user.id
                    print("[OK] Created: " + str(user_id))
                    # Also confirm via REST to be safe
                    admin_rest_update(user_id, {"email_confirm": True})
            except Exception as ex:
                print("[FAIL] Could not create user: " + str(ex))
                continue

        # Final login check
        try:
            lr = c.auth.sign_in_with_password({"email": email, "password": password})
            if lr.session and lr.session.access_token:
                print("[LOGIN OK] " + email + " - token starts: " + lr.session.access_token[:30])
            else:
                print("[LOGIN FAIL] No session returned")
        except Exception as le:
            print("[LOGIN FAIL] " + str(le))

    print("")
    print("-----------------------------------------")
    print("  CREDENTIALS SUMMARY")
    print("-----------------------------------------")
    for email, password, _, role in ACCOUNTS:
        print("  " + role + " | " + email + " | " + password)
    print("-----------------------------------------")
    print("  Admin:    http://localhost:3000/auth")
    print("  Merchant: http://localhost:3000/merchant/login")
    print("-----------------------------------------")


if __name__ == "__main__":
    main()

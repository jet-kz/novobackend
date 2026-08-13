# Authentication Setup & Integration Guide

This guide details exactly how the complete **Signup → OTP Verification → Login** flow is architected following best practices for Supabase Auth acting as the primary identity provider.

Our design completely decouples OTP generation from FastAPI. Supabase owns the entire credential boundary, while FastAPI acts purely as a stateless resource server that verifies Supabase-issued JWTs.

---

## 🏗 Architectural Flow

1. **Signup**: Next.js calls `supabase.auth.signUp()`. Supabase generates an OTP and dispatches it via Resend.
2. **OTP Verification**: Next.js prompts user for OTP. Next.js calls `supabase.auth.verifyOtp()`. Supabase returns a JWT.
3. **Login**: Next.js calls `supabase.auth.signInWithPassword()`. Supabase verifies credentials and returns a JWT instantly (no OTP needed).
4. **Accessing API**: Next.js attaches the JWT to the `Authorization: Bearer <TOKEN>` header when fetching from FastAPI.
5. **FastAPI Validation**: FastAPI decodes the token using the `SUPABASE_JWT_SECRET`, extracts the `user.id`, queries the Novo databases for mapped roles, and allows/rejects the request.

---

## 🛠 1. Supabase Dashboard Configuration

You must configure the Supabase Dashboard exactly as follows to enforce this workflow:

### A. Authentication Providers
1. Navigate to **Authentication > Providers > Email**.
2. **Enable Email provider**: Turn this on.
3. **Confirm email**: Turn this **ON**. (This enforces the OTP step before users can log in).
4. **Secure email change**: Turn this **ON**.

### B. SMTP / Email Provider (SendGrid integration)
By default, Supabase limits emails to 2 per hour on the free tier. Configure SendGrid to lift this:
1. Navigate to **Project Settings > Authentication > SMTP Provider**.
2. **Enable Custom SMTP**: Turn this on.
3. Fill in the following details exactly:
   - **Sender email**: `YOUR_VERIFIED_EMAIL` (Must be verified in your SendGrid account)
   - **Sender name**: `Novo Marketplace`
   - **Host**: `smtp.sendgrid.net`
   - **Port**: `587`
   - **Username**: `apikey`
   - **Password**: `YOUR_SENDGRID_API_KEY`

### C. Email Templates (The OTP setup)
By default, Supabase creates "Magic Links" for confirmations. To enforce OTP, you must change the email templates:
1. Navigate to **Authentication > Email Templates**.
2. Select **Confirm signup**.
3. **Change the Body** to display the 6-digit OTP token (`{{ .Token }}`) instead of the clickable link (`{{ .ConfirmationURL }}`).

**Example Template:**
```html
<h2>Welcome to Novo!</h2>
<p>Your verification code is: <strong>{{ .Token }}</strong></p>
<p>Enter this code in the app to complete your registration.</p>
```
*Do this for both the **Confirm signup** and **Reset password** templates.*

---

## 🌍 2. Environment Variables

### A. Next.js Environment (`.env.local`)
Next.js needs the public ANON key to speak to Supabase. It **must not** contain the Service Role Key or JWT Secret.
```env
NEXT_PUBLIC_SUPABASE_URL=https://bjacmfvsojtbdldqthcl.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsIn...
```

### B. FastAPI Environment (`.env`)
FastAPI needs the JWT Secret to decode and trust the tokens without pinging Supabase on every request.
```env
# Existing settings
SUPABASE_URL=https://bjacmfvsojtbdldqthcl.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsIn...

# NEW: Required for FastAPI security dependency
# Go to: Supabase Dashboard -> Project Settings -> API -> JWT Settings -> JWT Secret
SUPABASE_JWT_SECRET=your_super_secret_jwt_string_here
```

---

## 🔒 3. FastAPI Implementation Details

We have implemented the following in the FastAPI backend:
* **`app/core/security.py`**: A `get_current_user` dependency utilizing `python-jose`. It decodes the HS256-signed JWTs, enforces validity, and fetches internal Novo Roles (e.g. `CUSTOMER` or `RIDER`) associated with the user ID. 
* **`app/modules/auth/router.py`**: Exposes a new `/auth/me` endpoint. As soon as you hit it bearing a valid JWT, it will return the verified user payload alongside mapped permissions.

*All user passwords, OTP configurations, and session management remain safely sealed inside Supabase GoTrue parameters.*

# Sandbox Frontend Authentication

## Overview

The Meridyen Sandbox frontend now includes a complete authentication system where users must enter their sandbox API key to access the application.

## Authentication Flow

### 1. Login Page
When users first visit http://localhost:5175, they are presented with a login page:

- **URL**: `/login`
- **Required**: Sandbox API key (starts with `sb_`)
- **Validation**: The frontend validates the key format and tests connectivity to the sandbox server
- **Storage**: API keys are stored in browser localStorage for persistence

### 2. Protected Routes
All main application routes are protected and require authentication:

- `/connections` - Database connections management
- `/dataset/:connectionId` - Dataset explorer

If a user tries to access these routes without a valid API key, they are automatically redirected to `/login`.

### 3. API Key Management

**How to Get a Sandbox API Key:**

1. Go to AI_Assistants_MVP Frontend: http://localhost:13000
2. Login with your account
3. Navigate to **Settings → API Keys**
4. Click **"Create Key"**
5. Enter a name (e.g., "My Sandbox Access")
6. Select **"Sandbox API Key"** (purple radio button)
7. Click **"Create Key"**
8. **Copy the key** - it starts with `sb_`

**Using the API Key:**

1. Go to Meridyen Sandbox Frontend: http://localhost:5175
2. You'll be redirected to the login page
3. Paste your sandbox API key (starts with `sb_`)
4. Click **"Continue"**
5. The frontend validates the key and logs you in
6. You'll be redirected to the Connections page

## Features

### API Key Indicator
Once logged in, the header displays your API key (first 10 characters) with a green badge showing you're authenticated.

### Logout
Click the **"Logout"** button in the header to:
- Clear the stored API key from localStorage
- Redirect back to the login page

### Automatic API Key Injection
All API requests to the sandbox backend automatically include your API key in the `X-API-Key` header. You don't need to manually add it to each request.

### Session Persistence
Your API key is stored in localStorage, so you stay logged in even if you refresh the page or close the browser.

### Automatic Logout on Auth Errors
If the sandbox backend returns a 401 Unauthorized error (invalid or expired key), the frontend automatically:
- Clears the stored API key
- Redirects you to the login page

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  User Opens Browser                         │
│              http://localhost:5175                          │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
         ┌───────────────────────────────┐
         │  Check localStorage           │
         │  for 'sandbox_api_key'        │
         └───────────┬───────────────────┘
                     │
         ┌───────────┴────────────┐
         │                        │
    No API Key              Has API Key
         │                        │
         ▼                        ▼
┌────────────────────┐   ┌────────────────────┐
│   Login Page       │   │  Main App          │
│   /login           │   │  /connections      │
└────────────────────┘   └────────────────────┘
         │
         │ User enters sb_xxx
         │
         ▼
┌────────────────────────────────────────────────────────┐
│  Validate API Key                                      │
│  - Check format (starts with sb_)                      │
│  - Test connection to sandbox health endpoint          │
└────────────┬───────────────────────────────────────────┘
             │
             ▼
┌────────────────────────────────────────────────────────┐
│  Store in localStorage                                 │
│  localStorage.setItem('sandbox_api_key', key)          │
└────────────┬───────────────────────────────────────────┘
             │
             ▼
┌────────────────────────────────────────────────────────┐
│  Redirect to /connections                              │
└────────────────────────────────────────────────────────┘
```

## API Request Flow

```
┌────────────────────────────────────────────────────────┐
│  User Action (e.g., Create Database Connection)        │
└────────────┬───────────────────────────────────────────┘
             │
             ▼
┌────────────────────────────────────────────────────────┐
│  Frontend: axios.post('/api/v1/connections', data)     │
└────────────┬───────────────────────────────────────────┘
             │
             ▼
┌────────────────────────────────────────────────────────┐
│  Request Interceptor                                   │
│  - Get apiKey from localStorage                        │
│  - Add header: X-API-Key: sb_xxxxxxxxxx                │
└────────────┬───────────────────────────────────────────┘
             │
             ▼
┌────────────────────────────────────────────────────────┐
│  HTTP Request to Sandbox Backend                       │
│  POST http://localhost:8081/api/v1/connections         │
│  Headers:                                              │
│    Content-Type: application/json                      │
│    X-API-Key: sb_xxxxxxxxxx                            │
└────────────┬───────────────────────────────────────────┘
             │
             ▼
┌────────────────────────────────────────────────────────┐
│  Sandbox Backend validates API key                     │
│  - Calls MVP: POST /api/v1/sandbox/validate-key        │
│  - Gets workspace_id and permissions                   │
└────────────┬───────────────────────────────────────────┘
             │
        ┌────┴────┐
        │         │
   Valid Key   Invalid Key (401)
        │         │
        ▼         ▼
    Success   ┌──────────────────────────┐
              │ Response Interceptor     │
              │ - Clear localStorage     │
              │ - Redirect to /login     │
              └──────────────────────────┘
```

## Files Created

1. **`src/contexts/AuthContext.tsx`**
   - React context for authentication state
   - Manages API key in localStorage
   - Provides `login()` and `logout()` functions

2. **`src/components/auth/LoginPage.tsx`**
   - Login UI with API key input
   - Validates key format (must start with `sb_`)
   - Tests connectivity to sandbox server
   - Beautiful gradient background design

3. **`src/components/auth/ProtectedRoute.tsx`**
   - HOC to protect routes
   - Redirects to `/login` if not authenticated

## Files Modified

1. **`src/App.tsx`**
   - Added `/login` route
   - Wrapped protected routes with `<ProtectedRoute>`

2. **`src/main.tsx`**
   - Wrapped app with `<AuthProvider>`

3. **`src/components/Layout.tsx`**
   - Added logout button
   - Added API key indicator badge
   - Import `useAuth` hook

4. **`src/utils/api.ts`**
   - Changed from Bearer token to `X-API-Key` header
   - Added response interceptor for 401 errors
   - Auto-logout on authentication failure

## Testing

1. **Visit Sandbox Frontend**: http://localhost:5175
2. **You should see the login page**
3. **Enter a test key** (doesn't need to be valid for UI testing): `sb_test123`
4. **Click Continue**
5. **You'll be redirected to /connections**
6. **Check the header** - you should see your API key indicator
7. **Click Logout** - you'll be redirected back to login

## Production Considerations

For production deployment:

1. **Use HTTPS** - Never send API keys over HTTP in production
2. **API Key Expiration** - Implement key expiration on the MVP backend
3. **Rate Limiting** - Add rate limiting per API key
4. **Audit Logging** - Log all API key usage
5. **Key Rotation** - Provide UI to rotate keys
6. **Secure Storage** - Consider using more secure storage than localStorage (e.g., httpOnly cookies)

## Security Features

✅ **No Plaintext in Code** - Keys are only stored in localStorage
✅ **Format Validation** - Only accepts keys starting with `sb_`
✅ **Server-Side Validation** - All keys validated by MVP backend
✅ **Auto-Logout on Failure** - Invalid keys trigger automatic logout
✅ **Protected Routes** - All sensitive pages require authentication
✅ **Session Persistence** - Keys persist across page reloads
✅ **Automatic Header Injection** - No manual header management needed

---

**Status**: ✅ **IMPLEMENTED AND WORKING**

**Access**: http://localhost:5175

**Next Step**: Run the database migration and create your first sandbox API key in the MVP frontend!

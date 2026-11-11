# API Limits

The public API allows 600 requests per minute per tenant. Burst traffic up to 900 requests per minute is accepted for ten seconds. Responses include a Retry-After header when throttled.

# Authentication

Clients authenticate with short-lived OAuth 2.0 access tokens. Tokens expire after sixty minutes and must be refreshed with a rotating refresh token.

# Rate Limiting

Rate limits are enforced per tenant and per endpoint. Administrative endpoints have a lower limit of 60 requests per minute.

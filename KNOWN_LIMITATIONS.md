# Known Limitations (Conscious Prototype Tradeoffs)

This is a teaching/demo MiniStack storage portal, not a production system. The
following are deliberate simplifications, documented so they are not mistaken for defects.

## 1. Secret keys are encrypted at rest but the key is derivable in dev

- `Credential.secret_key_encrypted` is Fernet-encrypted before insert
  (`backend/security.py`, `backend/provisioning.py`) and the plaintext secret is
  returned **only once**, at creation, by `POST /api/register` and
  `POST /api/credentials` — mirroring AWS/IAM. Listing endpoints never return it again.
- **Caveat:** if `FERNET_KEY` is not set, the app derives a Fernet key from
  `JWT_SECRET` so it still runs out of the box. In production you must set a real,
  separately-managed `FERNET_KEY` (and ideally a KMS), otherwise the encryption key
  is only as strong as the JWT secret.

## 2. Quota is enforced in the application, not the storage engine

S3 / MiniStack has no native per-bucket byte quota. The limit lives in
`packages.quota_bytes` and is enforced in `POST /api/objects` against the fast
`subscriptions.used_bytes` counter. Direct (power-user) access bypasses this; the
`worker.py` reconciliation pass corrects `used_bytes` from real bucket contents on a
schedule, so there is a window where usage can briefly exceed quota before reconciliation.

## 3. Subscriptions do not expire

`expires_at` is modelled and an `expired` status exists, but nothing sets an expiry
or sweeps expired subscriptions. Subscriptions stay `active` until the user switches
package (which cancels the previous one). Intentionally unimplemented for the prototype.

## 4. MiniStack IAM may be a stub

If MiniStack's IAM `create_access_key` is not fully implemented (or IAM is
unreachable), `ministack_client.create_user_credentials` falls back to locally
generated AWS-style keys (`backend/ministack_client.py`). These are still stored and
shown to the user, but they are not registered with a real IAM backend.

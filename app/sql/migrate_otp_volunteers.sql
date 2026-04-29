-- Run this against the existing database to add OTP support and caller expiry.

-- 1. Caller expiry
ALTER TABLE pb_authorized_volunteers
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;

-- 2. OTP challenges table
CREATE TABLE IF NOT EXISTS pb_otp_challenges (
    id          BIGSERIAL   PRIMARY KEY,
    service     TEXT        NOT NULL CHECK (service IN ('volunteer', 'admin')),
    email       TEXT        NOT NULL,
    code_hash   TEXT        NOT NULL,
    salt        TEXT        NOT NULL,
    ip_address  TEXT,
    attempts    INT         NOT NULL DEFAULT 0,
    used        BOOLEAN     NOT NULL DEFAULT FALSE,
    expires_at  TIMESTAMPTZ NOT NULL DEFAULT now() + INTERVAL '10 minutes',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS pb_otp_challenges_lookup
    ON pb_otp_challenges(service, email, created_at DESC);

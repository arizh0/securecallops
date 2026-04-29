import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def send_otp(to_email: str, code: str) -> None:
    if _env_bool("DEV_OTP_LOG"):
        logger.warning("Development OTP code: %s", code)
        return

    host = os.environ.get("SMTP_HOST", "")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASS", "")
    from_addr = os.environ.get("SMTP_FROM", user)

    if not host or not user or not password:
        raise RuntimeError("SMTP not configured (set SMTP_HOST, SMTP_USER, SMTP_PASS)")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Your sign-in code"
    msg["From"] = from_addr
    msg["To"] = to_email

    body = (
        f"Your SecureCallOps sign-in code is:\n\n"
        f"  {code}\n\n"
        f"It expires in 10 minutes and can only be used once.\n"
        f"If you did not request this, ignore this email."
    )
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(host, port, timeout=10) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(user, password)
        smtp.sendmail(from_addr, [to_email], msg.as_string())
    logger.info("OTP email sent")

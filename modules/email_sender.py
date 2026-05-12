from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Any


@dataclass(frozen=True)
class EmailSender:
    smtp_server: str
    smtp_port: int
    sender_name: str
    sender_email: str
    sender_password: str

    @staticmethod
    def from_config(cfg: dict[str, Any]) -> "EmailSender":
        email_cfg = cfg.get("email", {}) or {}
        pwd = ""
        env_var = email_cfg.get("password_env_var")
        if env_var:
            pwd = os.environ.get(str(env_var), "")
        pwd = pwd or str(email_cfg.get("password") or "")

        return EmailSender(
            smtp_server=str(email_cfg.get("smtp_server") or "smtp.gmail.com"),
            smtp_port=int(email_cfg.get("smtp_port") or 587),
            sender_name=str(email_cfg.get("sender_name") or ""),
            sender_email=str(email_cfg.get("sender_email") or ""),
            sender_password=pwd,
        )

    def send_email(self, *, to_email: str, subject: str, body: str) -> None:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = formataddr((self.sender_name, self.sender_email))
        msg["To"] = to_email

        with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
            server.starttls()
            server.login(self.sender_email, self.sender_password)
            server.sendmail(self.sender_email, [to_email], msg.as_string())


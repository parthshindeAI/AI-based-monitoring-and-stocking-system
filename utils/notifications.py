from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any


@dataclass(frozen=True)
class EmailSettings:
    host: str
    port: int
    username: str
    password: str
    sender: str
    recipient: str


def get_email_settings(secrets: Any) -> EmailSettings | None:
    config = secrets.get("email", {})
    required = ("smtp_host", "sender", "recipient")
    if not all(config.get(key) for key in required):
        return None

    username = str(config.get("smtp_username", ""))
    password = str(config.get("smtp_password", ""))
    if bool(username) != bool(password):
        raise ValueError("Configure both smtp_username and smtp_password, or leave both empty.")

    port = int(config.get("smtp_port", 465))
    if not 1 <= port <= 65535:
        raise ValueError("SMTP port must be between 1 and 65535.")

    return EmailSettings(
        host=str(config["smtp_host"]),
        port=port,
        username=username,
        password=password,
        sender=str(config["sender"]),
        recipient=str(config["recipient"]),
    )


def send_restock_alert(settings: EmailSettings, alerts: list[dict[str, object]]) -> None:
    if not alerts:
        raise ValueError("There are no restock alerts to send.")

    message = EmailMessage()
    message["Subject"] = f"Inventory restock alert: {len(alerts)} item(s) need attention"
    message["From"] = settings.sender
    message["To"] = settings.recipient
    lines = ["The following inventory items need attention:", ""]
    for alert in alerts:
        lines.append(
            f"- {alert['item_name']}: risk {alert['risk_level']}, "
            f"stock {alert['current_stock']}, recommended order "
            f"{alert['recommended_order_quantity']} units."
        )
    message.set_content("\n".join(lines))

    if settings.port == 465:
        with smtplib.SMTP_SSL(settings.host, settings.port, timeout=15) as server:
            _send_message(server, settings, message)
    else:
        with smtplib.SMTP(settings.host, settings.port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            _send_message(server, settings, message)


def _send_message(
    server: smtplib.SMTP | smtplib.SMTP_SSL,
    settings: EmailSettings,
    message: EmailMessage,
) -> None:
    if settings.username:
        server.login(settings.username, settings.password)
    server.send_message(message)

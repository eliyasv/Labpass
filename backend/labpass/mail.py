import smtplib
from email.message import EmailMessage

from labpass.delivery import SendError


class LocalSmtpSender:
    def __init__(self, settings):
        self.host, self.port = settings.smtp_host, settings.smtp_port

    def send(self, claim):
        confirmation = claim.confirmation
        message = EmailMessage()
        message["From"] = "LabPass <no-reply@labpass.test>"
        message["To"] = confirmation.recipient
        message["Subject"] = "Your LabPass reservation"
        message["Message-ID"] = f"<{claim.event_id}@labpass.test>"
        message.set_content(
            f"Your reservation was received for {confirmation.workshop_title}.\n\n"
            f"Booking reference: {confirmation.booking_id}\n"
            "Check My bookings in LabPass for its current status.\n"
        )
        try:
            with smtplib.SMTP(self.host, self.port, timeout=5) as smtp:
                smtp.send_message(message)
        except OSError, smtplib.SMTPException:
            raise SendError("smtp_acceptance_failed_or_unknown") from None

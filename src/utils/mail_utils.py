import os
import smtplib
import logging
import asyncio
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class EmailService:
    def __init__(self):
        self.smtp_host = os.getenv('SMTP_HOST') or os.getenv('MAIL_HOST')
        self.smtp_port = int(os.getenv('SMTP_PORT') or os.getenv('MAIL_PORT') or 587)
        self.smtp_user = os.getenv('SMTP_USER') or os.getenv('MAIL_USER') or os.getenv('MAIL_SENDER')
        self.smtp_password = os.getenv('SMTP_PASSWORD') or os.getenv('MAIL_PASSWORD')
        self.from_email = os.getenv('SMTP_FROM_EMAIL') or os.getenv('MAIL_SENDER') or self.smtp_user
        self.smtp_use_tls = (os.getenv('SMTP_USE_TLS', 'true').lower() == 'true')
        self.frontend_url = os.getenv('FRONTEND_URL')

    def _validate_smtp_settings(self) -> bool:
        missing = []
        if not self.smtp_host:
            missing.append('SMTP_HOST/MAIL_HOST')
        if not self.smtp_user:
            missing.append('SMTP_USER/MAIL_USER/MAIL_SENDER')
        if not self.smtp_password:
            missing.append('SMTP_PASSWORD/MAIL_PASSWORD')
        if not self.from_email:
            missing.append('SMTP_FROM_EMAIL/MAIL_SENDER')
        if missing:
            logger.error(f"Email is not configured. Missing: {', '.join(missing)}")
            return False
        return True

    def _send_email(self, to_email, subject, html_content):
        try:
            if not self._validate_smtp_settings():
                return False

            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.from_email
            msg['To'] = to_email

            html_part = MIMEText(html_content, 'html')
            msg.attach(html_part)

            use_ssl = (self.smtp_port == 465 or os.getenv('SMTP_USE_SSL', 'false').lower() == 'true')
            
            if use_ssl:
                with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port) as server:
                    server.login(self.smtp_user, self.smtp_password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                    if self.smtp_use_tls:
                        server.starttls()
                    server.login(self.smtp_user, self.smtp_password)
                    server.send_message(msg)

            logger.info(f"Email sent successfully to {to_email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False

    async def send_password_reset_email_async(self, to_email, reset_token):
        return await asyncio.to_thread(self.send_password_reset_email, to_email, reset_token)

    async def send_alert_email_async(self, to_email, alert_data):
        return await asyncio.to_thread(self.send_alert_email, to_email, alert_data)

    def send_password_reset_email(self, to_email, reset_token):
        reset_link = f"{self.frontend_url}/reset-password?token={reset_token}"
        
        subject = "Password Reset Request"
        html_content = f"""
        <html>
            <body>
                <h2>Password Reset Request</h2>
                <p>You requested to reset your password. Click the link below to reset it:</p>
                <p><a href="{reset_link}">Reset Password</a></p>
                <p>This link will expire in 1 hour.</p>
                <p>If you did not request this, please ignore this email.</p>
            </body>
        </html>
        """
        
        return self._send_email(to_email, subject, html_content)

    def send_alert_email(self, to_email, alert_data):
        alert_type = alert_data.get('alert_type', 'Alert')
        severity = alert_data.get('severity', 'info')
        barn_name = alert_data.get('barn_name', 'Unknown Barn')
        location_name = alert_data.get('location_name', '')
        message = alert_data.get('message', '')
        
        subject = f"Inokron Alert: {alert_type} - {barn_name}"
        
        severity_colors = {
            'critical': '#dc2626',
            'warning': '#f59e0b',
            'info': '#3b82f6'
        }
        color = severity_colors.get(severity, '#3b82f6')
        
        html_content = f"""
        <html>
            <body>
                <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                    <div style="background-color: {color}; color: white; padding: 20px; border-radius: 5px 5px 0 0;">
                        <h2 style="margin: 0;">{alert_type}</h2>
                    </div>
                    <div style="border: 1px solid #e5e7eb; padding: 20px; border-radius: 0 0 5px 5px;">
                        <p><strong>Severity:</strong> {severity.upper()}</p>
                        <p><strong>Barn:</strong> {barn_name}</p>
                        {f'<p><strong>Location:</strong> {location_name}</p>' if location_name else ''}
                        <p><strong>Message:</strong></p>
                        <p>{message}</p>
                        <p style="color: #6b7280; font-size: 12px; margin-top: 20px;">
                            This is an automated alert from Inokron monitoring system.
                        </p>
                    </div>
                </div>
            </body>
        </html>
        """
        
        return self._send_email(to_email, subject, html_content)


email_service = EmailService()

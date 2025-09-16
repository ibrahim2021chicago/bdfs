from email.mime.text import MIMEText
import smtplib
from utils.loggerGen import setup_logger
from utils.config import SMTP_CONFIG

logger = setup_logger()

def send_mail(subject, body, to_addr, from_addr='beladmin@belcan.com'):
    try:
        smtp_server = SMTP_CONFIG['server']
        smtp_port = SMTP_CONFIG['port']
        username = SMTP_CONFIG['username']
        password = SMTP_CONFIG['password']

        to_list = [to_addr] if isinstance(to_addr, str) else list(to_addr)

        msg = MIMEText(body, 'plain', 'utf-8')
        msg['From'] = from_addr
        msg['To'] = ", ".join(to_list)
        msg['Subject'] = subject

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.ehlo()
            if username and password:
                server.starttls()
                server.login(username, password)
            server.sendmail(from_addr, to_list, msg.as_string())
            logger.info(f"Email sent to {to_list} with subject '{subject}'")
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False

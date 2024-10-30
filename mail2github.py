import imaplib
import email
from email.header import decode_header
import os
import re
import datetime
import logging
from logging.handlers import RotatingFileHandler
from github import Github
from dotenv import load_dotenv
import dns.resolver
import spf
import dkim

# Load environment variables from the .env file
load_dotenv()

# Logging configuration
log_dir = os.path.join(os.path.dirname(__file__), 'log')
os.makedirs(log_dir, exist_ok=True)
log_file_path = os.path.join(log_dir, 'email_to_github.log')
handler = RotatingFileHandler(log_file_path, maxBytes=5*1024*1024, backupCount=5)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[
    handler,
    logging.StreamHandler()
])

# Define constants
IMAP_SERVER = os.getenv("IMAP_SERVER")
EMAIL_ACCOUNT = os.getenv("EMAIL_ACCOUNT")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
DEFAULT_GITHUB_REPO_NAME = os.getenv("DEFAULT_GITHUB_REPO_NAME")
DEFAULT_BRANCH = os.getenv("DEFAULT_BRANCH", "main")
WHITELIST = os.getenv("EMAIL_SENDER_WHITELIST").split(',')
REPO_WHITELIST = os.getenv("REPO_WHITELIST").split(',')

# Establish IMAP connection
def connect_to_email():
    mail = imaplib.IMAP4_SSL(IMAP_SERVER)
    mail.login(EMAIL_ACCOUNT, EMAIL_PASSWORD)
    return mail

# Check for unread emails
def check_unread_emails(mail):
    mail.select("inbox")
    status, messages = mail.search(None, '(UNSEEN)')
    if status != "OK":
        logging.info("No unread messages found.")
        return []
    return messages[0].split()

# Verify sender against whitelist
def is_sender_allowed(msg):
    sender = email.utils.parseaddr(msg["From"])[1]
    if sender in WHITELIST:
        return True
    else:
        logging.warning(f"Unauthorized email sender: {sender}. Ignoring email.")
        return False

# Verify SPF record
def verify_spf(sender_ip, domain):
    try:
        result, explanation = spf.check2(sender_ip, domain, EMAIL_ACCOUNT)
        if result == 'pass':
            return True
        elif result == 'softfail':
            logging.warning(f"SPF softfail for domain {domain}. Proceeding with caution: {explanation}")
            return True  # Optional: We can decide to proceed with caution
        else:
            logging.warning(f"SPF verification failed for domain {domain} with result: {result}. {explanation}")
            return False
    except Exception as e:
        logging.error(f"Error during SPF verification: {e}")
        return False

# Verify DKIM signature
def verify_dkim(raw_email):
    try:
        if dkim.verify(raw_email):
            return True
        else:
            logging.warning("DKIM verification failed.")
            return False
    except Exception as e:
        logging.error(f"Error during DKIM verification: {e}")
        return False

# Process email and extract content
def process_email(mail, email_id):
    status, data = mail.fetch(email_id, '(RFC822)')
    if status != "OK":
        logging.error("Error fetching the email.")
        return None, None, None, None, None, None, None

    msg = email.message_from_bytes(data[0][1])
    raw_email = data[0][1]

    # Check if the sender is allowed
    sender = email.utils.parseaddr(msg["From"])[1]
    if not is_sender_allowed(msg):
        return None, None, None, None, None, None, None

    # Get sender IP and domain for SPF verification
    received_headers = msg.get_all('Received')
    if received_headers:
        sender_ip = re.findall(r'\[([0-9\.]+)\]', received_headers[-1])
        sender_ip = sender_ip[0] if sender_ip else None
    else:
        sender_ip = None

    domain = email.utils.parseaddr(msg["From"])[1].split('@')[-1]

    # Robust SPF and DKIM verification
    spf_pass = False
    dkim_pass = False

    # SPF verification
    if sender_ip:
        spf_pass = verify_spf(sender_ip, domain)

    # DKIM verification
    dkim_pass = verify_dkim(raw_email)

    # Log results and determine if we proceed
    if not spf_pass and not dkim_pass:
        logging.error(f"Both SPF and DKIM verification failed for sender '{sender}'. Ignoring email.")
        return None, None, None, None, None, None, None
    elif spf_pass and not dkim_pass:
        logging.warning(f"SPF verification passed, but DKIM verification failed for sender '{sender}'. Proceeding with caution.")
    elif not spf_pass and dkim_pass:
        logging.warning(f"DKIM verification passed, but SPF verification failed for sender '{sender}'. Proceeding with caution.")
    else:
        logging.info(f"Both SPF and DKIM verification passed for sender '{sender}'.")

    subject, encoding = decode_header(msg["Subject"])[0]
    if isinstance(subject, bytes):
        subject = subject.decode(encoding if encoding else 'utf-8')

    # Extract control markers from the subject
    commit_msg = "Automatically generated change"
    branch = DEFAULT_BRANCH
    author = "Unknown"
    repo_name = DEFAULT_GITHUB_REPO_NAME
    tag_name = None

    # Updated regex to allow more flexible subjects and support tags
    match = re.match(r"(?:\[commit_msg:(?P<commit_msg>.*?)\])?\s*(?:\[branch:(?P<branch>.*?)\])?\s*(?:\[author:(?P<author>.*?)\])?\s*(?:\[repo:(?P<repo>.*?)\])?\s*(?:\[tag:(?P<tag>.*?)\])?\s*(?P<filename>.+\..+)$", subject)
    if not match:
        logging.error(f"Subject not in expected format for sender '{sender}'.")
        return None, None, None, None, None, None, None

    if match.group("commit_msg"):
        commit_msg = match.group("commit_msg").strip()
    if match.group("branch"):
        branch = match.group("branch").strip()
    if match.group("author"):
        author = match.group("author").strip()
    if match.group("repo"):
        repo_name = match.group("repo").strip()
    if match.group("tag"):
        tag_name = match.group("tag").strip()
    filename = match.group("filename").strip()

    # Verify if the repository is whitelisted
    if repo_name not in REPO_WHITELIST:
        logging.error(f"Repository '{repo_name}' is not whitelisted for sender '{sender}'. Ignoring email.")
        return None, None, None, None, None, None, None

    # Log the processing details
    logging.info(f"Processing email from '{sender}' for repository '{repo_name}', branch '{branch}', and filename '{filename}'.")

    # Extract message body
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))

            if content_type == "text/plain" and "attachment" not in content_disposition:
                body = part.get_payload(decode=True).decode()
                break
    else:
        body = msg.get_payload(decode=True).decode()

    return (sender, filename, body, commit_msg, branch, repo_name, tag_name)

# Create or update file in GitHub repository
def write_to_github_repo(sender, path, filename, content, commit_msg, branch, repo_name, tag_name):
    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(repo_name)

    # Ensure branch exists
    try:
        repo.get_branch(branch)
    except Exception:
        source = repo.get_branch(DEFAULT_BRANCH)
        repo.create_git_ref(ref=f"refs/heads/{branch}", sha=source.commit.sha)

    # Define full path for the file in GitHub
    full_path = filename if not path else f"{path}/{filename}"

    # Ensure path exists
    if path:
        try:
            repo.get_contents(path, ref=branch)
        except Exception as e:
            # Path does not exist, create it recursively
            parts = path.split('/')
            current_path = ""
            for part in parts:
                current_path = f"{current_path}/{part}" if current_path else part
                try:
                    repo.get_contents(current_path, ref=branch)
                except Exception:
                    repo.create_file(f"{current_path}/.gitkeep", f"Create directory {current_path}", "", branch=branch)

    try:
        # Check if the file already exists to create a new version
        contents = repo.get_contents(full_path, ref=branch)
        # Update the file to create a new version
        repo.update_file(contents.path, commit_msg, content, contents.sha, branch=branch)
        logging.info(f"File '{filename}' updated in repository '{repo_name}' on branch '{branch}' by sender '{sender}'. Commit message: '{commit_msg}'")
    except Exception as e:
        # File does not exist, create it
        repo.create_file(full_path, commit_msg, content, branch=branch)
        logging.info(f"File '{filename}' created in repository '{repo_name}' on branch '{branch}' by sender '{sender}'. Commit message: '{commit_msg}'")

    # Create a tag if specified
    if tag_name:
        try:
            repo.create_git_tag_and_release(tag=tag_name, tag_message=f"Tag {tag_name}", release_name=tag_name, release_message=commit_msg, object=repo.get_branch(branch).commit.sha, type="commit")
            logging.info(f"Tag '{tag_name}' created and added to the commit in repository '{repo_name}' by sender '{sender}'.")
        except Exception as e:
            logging.error(f"Error creating tag '{tag_name}' in repository '{repo_name}' by sender '{sender}': {e}")

# Main program
def main():
    mail = connect_to_email()
    email_ids = check_unread_emails(mail)

    for e_id in email_ids:
        sender, filename, body, commit_msg, branch, repo_name, tag_name = process_email(mail, e_id)
        if filename and body:
            write_to_github_repo(sender, None, filename, body, commit_msg, branch, repo_name, tag_name)

    mail.logout()

if __name__ == "__main__":
    main()

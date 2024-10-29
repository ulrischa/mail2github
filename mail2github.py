import imaplib
import email
from email.header import decode_header
import os
import re
import datetime
import logging
from github import Github
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()

# Logging configuration
log_file_path = os.path.join(os.path.dirname(__file__), 'email_to_github.log')
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[
    logging.FileHandler(log_file_path),
    logging.StreamHandler()
])

# Define constants
IMAP_SERVER = os.getenv("IMAP_SERVER")
EMAIL_ACCOUNT = os.getenv("EMAIL_ACCOUNT")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
DEFAULT_GITHUB_REPO_NAME = os.getenv("DEFAULT_GITHUB_REPO_NAME")
DEFAULT_BRANCH = os.getenv("DEFAULT_BRANCH", "main")

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

# Process email and extract content
def process_email(mail, email_id):
    status, data = mail.fetch(email_id, '(RFC822)')
    if status != "OK":
        logging.error("Error fetching the email.")
        return None, None, None, None, None, None, None

    msg = email.message_from_bytes(data[0][1])
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
        logging.error("Subject not in expected format.")
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

    return (None, filename, body, commit_msg, branch, repo_name, tag_name)

# Create or update file in GitHub repository
def write_to_github_repo(path, filename, content, commit_msg, branch, repo_name, tag_name):
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
    except Exception as e:
        # File does not exist, create it
        repo.create_file(full_path, commit_msg, content, branch=branch)

    # Ensure every change is committed
    logging.info(f"Change committed with message '{commit_msg}' in branch '{branch}' of repository '{repo_name}'.")

    # Create a tag if specified
    if tag_name:
        try:
            repo.create_git_tag_and_release(tag=tag_name, tag_message=f"Tag {tag_name}", release_name=tag_name, release_message=commit_msg, object=repo.get_branch(branch).commit.sha, type="commit")
            logging.info(f"Tag '{tag_name}' created and added to the commit.")
        except Exception as e:
            logging.error(f"Error creating tag '{tag_name}': {e}")

# Main program
def main():
    mail = connect_to_email()
    email_ids = check_unread_emails(mail)

    for e_id in email_ids:
        path, filename, body, commit_msg, branch, repo_name, tag_name = process_email(mail, e_id)
        if filename and body:
            write_to_github_repo(path, filename, body, commit_msg, branch, repo_name, tag_name)

    mail.logout()

if __name__ == "__main__":
    main()

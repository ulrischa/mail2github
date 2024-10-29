import imaplib
import email
from email.header import decode_header
import os
import re
import datetime
import logging
from github import Github
from dotenv import load_dotenv

# Lade Umgebungsvariablen aus der .env Datei
load_dotenv()

# Logging-Konfiguration
log_file_path = os.path.join(os.path.dirname(__file__), 'email_to_github.log')
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[
    logging.FileHandler(log_file_path),
    logging.StreamHandler()
])

# Konstanten definieren
IMAP_SERVER = os.getenv("IMAP_SERVER")
EMAIL_ACCOUNT = os.getenv("EMAIL_ACCOUNT")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
DEFAULT_GITHUB_REPO_NAME = os.getenv("DEFAULT_GITHUB_REPO_NAME")
DEFAULT_BRANCH = os.getenv("DEFAULT_BRANCH", "main")

# IMAP Verbindung herstellen
def connect_to_email():
    mail = imaplib.IMAP4_SSL(IMAP_SERVER)
    mail.login(EMAIL_ACCOUNT, EMAIL_PASSWORD)
    return mail

# Überprüft auf ungelesene E-Mails
def check_unread_emails(mail):
    mail.select("inbox")
    status, messages = mail.search(None, '(UNSEEN)')
    if status != "OK":
        logging.info("Keine ungelesenen Nachrichten gefunden.")
        return []
    return messages[0].split()

# E-Mail verarbeiten und Inhalt extrahieren
def process_email(mail, email_id):
    status, data = mail.fetch(email_id, '(RFC822)')
    if status != "OK":
        logging.error("Fehler beim Abrufen der E-Mail.")
        return None, None, None, None, None, None, None

    msg = email.message_from_bytes(data[0][1])
    subject, encoding = decode_header(msg["Subject"])[0]
    if isinstance(subject, bytes):
        subject = subject.decode(encoding if encoding else 'utf-8')

    # Steuerzeichen aus Betreff extrahieren
    commit_msg = "Automatisch generierte Änderung"
    branch = DEFAULT_BRANCH
    author = "Unbekannt"
    repo_name = DEFAULT_GITHUB_REPO_NAME
    tag_name = None

    # Überarbeiteter Regex, um flexiblere Betreffzeilen zuzulassen und Tags zu unterstützen
    match = re.match(r"(?:\[commit_msg:(?P<commit_msg>.*?)\])?\s*(?:\[branch:(?P<branch>.*?)\])?\s*(?:\[author:(?P<author>.*?)\])?\s*(?:\[repo:(?P<repo>.*?)\])?\s*(?:\[tag:(?P<tag>.*?)\])?\s*(?P<filename>.+\..+)$", subject)
    if not match:
        logging.error("Betreff nicht im erwarteten Format.")
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

    # Nachrichtentext extrahieren
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

# Datei im GitHub-Repository erstellen oder aktualisieren
def write_to_github_repo(path, filename, content, commit_msg, branch, repo_name, tag_name):
    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(repo_name)

    # Branch sicherstellen
    try:
        repo.get_branch(branch)
    except Exception:
        source = repo.get_branch(DEFAULT_BRANCH)
        repo.create_git_ref(ref=f"refs/heads/{branch}", sha=source.commit.sha)

    # Pfad und Datei auf GitHub erstellen oder aktualisieren
    full_path = filename if not path else f"{path}/{filename}"

    # Sicherstellen, dass der Pfad existiert
    if path:
        try:
            repo.get_contents(path, ref=branch)
        except Exception as e:
            # Ordner existiert nicht, also den Pfad rekursiv erstellen
            parts = path.split('/')
            current_path = ""
            for part in parts:
                current_path = f"{current_path}/{part}" if current_path else part
                try:
                    repo.get_contents(current_path, ref=branch)
                except Exception:
                    repo.create_file(f"{current_path}/.gitkeep", f"Create directory {current_path}", "", branch=branch)

    try:
        # Prüfen, ob die Datei bereits existiert, um eine neue Version zu erstellen
        contents = repo.get_contents(full_path, ref=branch)
        # Neue Version der Datei durch Update erzeugen
        repo.update_file(contents.path, commit_msg, content, contents.sha, branch=branch)
    except Exception as e:
        # Datei existiert nicht, neu erstellen
        repo.create_file(full_path, commit_msg, content, branch=branch)

    # Sicherstellen, dass jede Änderung als Commit erfasst wird
    logging.info(f"Änderung wurde mit der Commit-Nachricht '{commit_msg}' in den Branch '{branch}' des Repositories '{repo_name}' übernommen.")

    # Tag erstellen, falls angegeben
    if tag_name:
        try:
            repo.create_git_tag_and_release(tag=tag_name, tag_message=f"Tag {tag_name}", release_name=tag_name, release_message=commit_msg, object=repo.get_branch(branch).commit.sha, type="commit")
            logging.info(f"Tag '{tag_name}' wurde erstellt und dem Commit hinzugefügt.")
        except Exception as e:
            logging.error(f"Fehler beim Erstellen des Tags '{tag_name}': {e}")

# Hauptprogramm
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
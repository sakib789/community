#!/usr/bin/env python3
"""
Google Groups Gateway
Consumes Gmail Pub/Sub notifications and mirrors Google Groups posts/replies
to GitHub issues/comments and OpenSearch parent-child documents.
"""

import asyncio
import base64
import json
import os
import re
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import aiohttp
import requests
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.cloud import pubsub_v1
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Add parent directory to path
PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PARENT_DIR)

from indexer.opensearch_indexer import OpenSearchIndexer
from logging_config import setup_logger
from token_manager import TokenManager as CentralTokenManager


load_dotenv()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = os.path.dirname(SCRIPT_DIR)
LOG_FILE = os.path.join(SCRIPT_DIR, "google_group_gateway.log")

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
GOOGLE_CREDENTIALS_FILE = os.environ.get(
	"GOOGLE_CREDENTIALS_FILE",
	os.path.join(SCRIPT_DIR, "google-group-cred.json"),
)
GOOGLE_SERVICE_ACCOUNT_FILE = os.environ.get(
	"GOOGLE_SERVICE_ACCOUNT_FILE",
	os.path.join(SCRIPT_DIR, "google-group-cred-sa.json"),
)
GOOGLE_TOKEN_FILE = os.environ.get(
	"GOOGLE_TOKEN_FILE",
	os.path.join(SCRIPT_DIR, "token_google.json"),
)
GOOGLE_PROJECT_TOKEN_FILE = os.environ.get(
	"GOOGLE_PROJECT_TOKEN_FILE",
	os.path.join(TOOLS_DIR, ".token_google"),
)
GOOGLE_PUBSUB_TOKEN_FILE = os.environ.get(
	"GOOGLE_PUBSUB_TOKEN_FILE",
	os.path.join(TOOLS_DIR, ".token_google_pubsub_subscription"),
)


def _read_first_non_comment_line(file_path: str) -> str:
	if not file_path or not os.path.exists(file_path):
		return ""
	try:
		with open(file_path, "r", encoding="utf-8") as fh:
			for line in fh:
				line = line.strip()
				if line and not line.startswith("#"):
					return line
	except Exception:
		return ""
	return ""


def _read_project_id_from_json(file_path: str) -> str:
	if not file_path or not os.path.exists(file_path):
		return ""
	try:
		with open(file_path, "r", encoding="utf-8") as fh:
			data = json.load(fh)
		if isinstance(data, dict):
			if "project_id" in data:
				return str(data["project_id"])
			if "web" in data and isinstance(data["web"], dict) and "project_id" in data["web"]:
				return str(data["web"]["project_id"])
	except Exception:
		return ""
	return ""


PROJECT_ID = (
	os.environ.get("GOOGLE_PROJECT_ID", "")
	or _read_first_non_comment_line(GOOGLE_PROJECT_TOKEN_FILE)
	or _read_project_id_from_json(GOOGLE_SERVICE_ACCOUNT_FILE)
	or _read_project_id_from_json(GOOGLE_CREDENTIALS_FILE)
)
SUBSCRIPTION_ID = (
	os.environ.get("GOOGLE_PUBSUB_SUBSCRIPTION", "")
	or _read_first_non_comment_line(GOOGLE_PUBSUB_TOKEN_FILE)
)
TARGET_GROUP_EMAIL = os.environ.get("GOOGLE_GROUP_EMAIL", "")

GITHUB_API_BASE = "https://api.github.com"
GITHUB_REPO = os.environ.get("GITHUB_REPO", "sakib789/community")

logger = setup_logger("Collector.GoogleGroups", log_file=LOG_FILE)


@dataclass
class GoogleGroupMessage:
	gmail_id: str
	message_id: str
	sender: str
	subject: str
	to_header: str
	in_reply_to: Optional[str]
	references: List[str]
	text_body: str
	permalink: str

	@property
	def normalized_subject(self) -> str:
		return re.sub(r"^(re|fwd|fw):\s*", "", self.subject.strip(), flags=re.IGNORECASE)

	@property
	def is_target_group(self) -> bool:
		if not TARGET_GROUP_EMAIL:
			return True
		return TARGET_GROUP_EMAIL.lower() in (self.to_header or "").lower()


class GmailClient:
	def __init__(self):
		self.service = self._authenticate()

	def _authenticate(self):
		creds = None
		if os.path.exists(GOOGLE_TOKEN_FILE):
			creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_FILE, GMAIL_SCOPES)

		if not creds or not creds.valid:
			if creds and creds.expired and creds.refresh_token:
				creds.refresh(Request())
			else:
				if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
					raise FileNotFoundError(
						f"Google credentials file not found: {GOOGLE_CREDENTIALS_FILE}"
					)
				flow = InstalledAppFlow.from_client_secrets_file(
					GOOGLE_CREDENTIALS_FILE,
					GMAIL_SCOPES,
				)
				creds = flow.run_local_server(port=8081, open_browser=False)

			with open(GOOGLE_TOKEN_FILE, "w", encoding="utf-8") as token_file:
				token_file.write(creds.to_json())

		return build("gmail", "v1", credentials=creds)

	@staticmethod
	def _extract_body(payload: Dict) -> str:
		if "parts" in payload:
			for part in payload.get("parts", []):
				if part.get("mimeType") == "text/plain":
					data = part.get("body", {}).get("data")
					if data:
						return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
				nested = GmailClient._extract_body(part)
				if nested:
					return nested
		elif payload.get("mimeType") == "text/plain":
			data = payload.get("body", {}).get("data")
			if data:
				return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
		return ""

	@staticmethod
	def _clean_body(raw_body: str) -> str:
		body = raw_body or ""
		body = re.sub(
			r"(?s)--\s*\nYou received this message because you are subscribed to the Google Groups.*",
			"",
			body,
		)
		body = "\n".join(line for line in body.splitlines() if not line.strip().startswith(">"))
		return body.strip()

	@staticmethod
	def _extract_permalink(raw_body: str, gmail_id: str) -> str:
		match = re.search(r"(https://groups\.google\.com/d/msgid/\S+)", raw_body or "")
		if match:
			return match.group(1).rstrip(">").rstrip(".")
		return f"https://mail.google.com/mail/u/0/#all/{gmail_id}"

	def get_unread_messages(self) -> List[GoogleGroupMessage]:
		query = "is:unread"
		if TARGET_GROUP_EMAIL:
			query += f" to:{TARGET_GROUP_EMAIL}"

		response = self.service.users().messages().list(userId="me", q=query).execute()
		messages = response.get("messages", [])
		if not messages:
			return []

		parsed: List[GoogleGroupMessage] = []
		raw_items: List[Tuple[int, Dict]] = []
		for msg in messages:
			gmail_id = msg["id"]
			full = self.service.users().messages().get(userId="me", id=gmail_id, format="full").execute()
			raw_items.append((int(full.get("internalDate", 0)), full))

		raw_items.sort(key=lambda item: item[0])

		for _, full in raw_items:
			payload = full.get("payload", {})
			headers = payload.get("headers", [])

			def get_header(name: str) -> str:
				return next(
					(h.get("value", "") for h in headers if h.get("name", "").lower() == name.lower()),
					"",
				)

			gmail_id = full.get("id", "")
			raw_body = self._extract_body(payload)
			parsed.append(
				GoogleGroupMessage(
					gmail_id=gmail_id,
					message_id=get_header("Message-ID") or gmail_id,
					sender=get_header("X-Original-From") or get_header("From") or "Unknown Sender",
					subject=get_header("Subject") or "No Subject",
					to_header=get_header("To"),
					in_reply_to=get_header("In-Reply-To") or None,
					references=(get_header("References") or "").split(),
					text_body=self._clean_body(raw_body),
					permalink=self._extract_permalink(raw_body, gmail_id),
				)
			)

		return parsed

	def mark_as_read(self, gmail_id: str) -> None:
		self.service.users().messages().modify(
			userId="me",
			id=gmail_id,
			body={"removeLabelIds": ["UNREAD"]},
		).execute()


class GoogleGroupTicketCreator:
	def __init__(self, github_token: Optional[str], repo: str = GITHUB_REPO):
		self.github_token = "".join(github_token.split()) if github_token else None
		self.repo = repo
		self.enabled = bool(self.github_token)
		self.indexer = OpenSearchIndexer()

		if not self.enabled:
			logger.warning("GitHub integration disabled (no token found)")
		else:
			logger.info(f"GitHub integration enabled for repo: {self.repo}")

	@staticmethod
	def _safe_message_id(message_id: str) -> str:
		return message_id.strip("<>").replace("@", "%40")

	def _find_existing(self, message_id: str) -> bool:
		doc_id = f"googlegroups_{self._safe_message_id(message_id)}"
		return self.indexer.get_parent_document(doc_id) is not None

	async def _handle_reply(self, message: GoogleGroupMessage) -> Optional[Dict]:
		"""Find the parent issue via direct OpenSearch lookup and add a comment, same pattern as Slack."""
		refs = []
		if message.in_reply_to:
			refs.append(message.in_reply_to)
		refs.extend(message.references)

		parent_doc = None
		parent_ref = None
		for ref in refs:
			doc_id = f"googlegroups_{self._safe_message_id(ref)}"
			doc = self.indexer.get_parent_document(doc_id)
			if doc and doc.get("github_issue_number"):
				parent_doc = doc
				parent_ref = ref
				break

		if not parent_doc:
			logger.warning(f"No parent document found for reply {message.message_id}, skipping")
			return None

		return await self._add_comment(
			message,
			parent_message_id=parent_ref,
			issue_number=parent_doc["github_issue_number"],
			issue_url=parent_doc.get("github_issue_url", f"https://github.com/{self.repo}/issues/{parent_doc['github_issue_number']}"),
		)

	def _create_parent_doc(self, message: GoogleGroupMessage, issue_number: int, issue_url: str) -> Dict:
		return {
			"id": f"googlegroups_{self._safe_message_id(message.message_id)}",
			"platform": "googlegroups",
			"created_at": datetime.utcnow().isoformat() + "Z",
			"googlegroups_message_id": message.message_id,
			"googlegroups_subject": message.normalized_subject,
			"googlegroups_sender": message.sender,
			"googlegroups_permalink": message.permalink,
			"title": message.normalized_subject,
			"content": message.text_body,
			"record_type": "parent",
			"status": "open",
			"github_issue_number": issue_number,
			"github_issue_url": issue_url,
			"labels": ["platform/googlegroups"],
		}

	def _create_comment_doc(
		self,
		message: GoogleGroupMessage,
		parent_message_id: str,
		issue_number: int,
		issue_url: str,
		github_comment_id: Optional[int],
	) -> Dict:
		return {
			"id": f"googlegroups_{self._safe_message_id(message.message_id)}",
			"parent_id": f"googlegroups_{self._safe_message_id(parent_message_id)}",
			"platform": "googlegroups",
			"created_at": datetime.utcnow().isoformat() + "Z",
			"googlegroups_message_id": message.message_id,
			"googlegroups_parent_id": parent_message_id,
			"googlegroups_subject": message.normalized_subject,
			"googlegroups_sender": message.sender,
			"googlegroups_permalink": message.permalink,
			"content": message.text_body,
			"record_type": "comment",
			"github_comment_id": github_comment_id,
			"github_issue_number": issue_number,
			"github_issue_url": issue_url,
		}

	async def _create_issue(self, message: GoogleGroupMessage) -> Optional[Dict]:
		if not self.enabled:
			return None

		url = f"{GITHUB_API_BASE}/repos/{self.repo}/issues"
		headers = {
			"Authorization": f"token {self.github_token}",
			"Accept": "application/vnd.github.v3+json",
			"Content-Type": "application/json",
		}
		payload = {
			"title": message.normalized_subject[:100],
			"body": (
				"## Google Groups Post\n\n"
				f"**From:** {message.sender}\n"
				f"**Message-ID:** {message.message_id}\n"
				f"**Permalink:** {message.permalink}\n\n"
				f"{message.text_body or '(No content)'}\n"
			),
			"labels": ["platform/googlegroups"],
		}

		async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
			async with session.post(url, headers=headers, json=payload) as response:
				if response.status != 201:
					error_text = await response.text()
					logger.error(f"Failed creating Google Groups issue: {response.status} - {error_text}")
					return None

				issue_data = await response.json()
				parent_doc = self._create_parent_doc(
					message,
					issue_number=issue_data["number"],
					issue_url=issue_data["html_url"],
				)
				self.indexer.index_parent(parent_doc)
				logger.info(f"Created Google Groups issue #{issue_data['number']}")
				return issue_data

	async def _add_comment(
		self,
		message: GoogleGroupMessage,
		parent_message_id: str,
		issue_number: int,
		issue_url: str,
	) -> Optional[Dict]:
		if not self.enabled:
			return None

		url = f"{GITHUB_API_BASE}/repos/{self.repo}/issues/{issue_number}/comments"
		headers = {
			"Authorization": f"token {self.github_token}",
			"Accept": "application/vnd.github.v3+json",
			"Content-Type": "application/json",
		}
		payload = {
			"body": (
				"### Google Groups Reply\n\n"
				f"**From:** {message.sender}\n"
				f"**Message-ID:** {message.message_id}\n"
				f"**Permalink:** {message.permalink}\n\n"
				f"{message.text_body or '(No content)'}\n"
			)
		}

		async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
			async with session.post(url, headers=headers, json=payload) as response:
				if response.status != 201:
					error_text = await response.text()
					logger.error(f"Failed adding Google Groups comment: {response.status} - {error_text}")
					return None

				comment_data = await response.json()
				comment_doc = self._create_comment_doc(
					message,
					parent_message_id=parent_message_id,
					issue_number=issue_number,
					issue_url=issue_url,
					github_comment_id=comment_data.get("id"),
				)
				self.indexer.index_comment(
					comment_doc,
					parent_id=f"googlegroups_{self._safe_message_id(parent_message_id)}",
				)
				logger.info(f"Added Google Groups reply to issue #{issue_number}")
				return comment_data

	async def process_message(self, message: GoogleGroupMessage) -> str:
		if self._find_existing(message.message_id):
			return "duplicate"

		# Reply: has In-Reply-To or References → add as GitHub comment
		if message.in_reply_to or message.references:
			logger.info(f"Reply detected for message {message.message_id}")
			comment_data = await self._handle_reply(message)
			return "comment" if comment_data else "skipped"

		# New top-level post → create GitHub issue
		issue_data = await self._create_issue(message)
		return "issue" if issue_data else "error"


class GoogleGroupGateway:
	def __init__(self):
		if not PROJECT_ID:
			raise FileNotFoundError("GOOGLE_PROJECT_ID is required")
		if not SUBSCRIPTION_ID:
			raise FileNotFoundError("GOOGLE_PUBSUB_SUBSCRIPTION is required")

		token_manager = CentralTokenManager()
		self.gmail_client = GmailClient()
		self.ticket_creator = GoogleGroupTicketCreator(token_manager.get_token("github"))
		self.process_lock = threading.Lock()

	def _process_notification(self, pubsub_message) -> None:
		with self.process_lock:
			try:
				messages = self.gmail_client.get_unread_messages()
				for msg in messages:
					try:
						if not msg.is_target_group:
							self.gmail_client.mark_as_read(msg.gmail_id)
							continue
						asyncio.run(self.ticket_creator.process_message(msg))
						self.gmail_client.mark_as_read(msg.gmail_id)
					except Exception as exc:
						logger.error(f"Error processing message {msg.gmail_id}: {exc}", exc_info=True)
			except Exception as exc:
				logger.error(f"Pub/Sub callback error: {exc}", exc_info=True)
			finally:
				pubsub_message.ack()

	def _run_blocking(self) -> None:
		subscriber_kwargs = {}
		if os.path.exists(GOOGLE_SERVICE_ACCOUNT_FILE):
			try:
				subscriber_kwargs["credentials"] = service_account.Credentials.from_service_account_file(
					GOOGLE_SERVICE_ACCOUNT_FILE
				)
			except Exception as exc:
				logger.warning(f"Failed loading service account credentials: {exc}")

		subscriber = pubsub_v1.SubscriberClient(**subscriber_kwargs)
		subscription_path = subscriber.subscription_path(PROJECT_ID, SUBSCRIPTION_ID)

		logger.info("=" * 60)
		logger.info("Google Groups Gateway Starting")
		logger.info("=" * 60)
		logger.info(f"Project: {PROJECT_ID}")
		logger.info(f"Subscription: {SUBSCRIPTION_ID}")
		logger.info(f"Target group: {TARGET_GROUP_EMAIL or '(all unread)'}")
		logger.info(f"GitHub repo: {GITHUB_REPO}")
		logger.info("Press Ctrl+C to stop")
		logger.info("=" * 60)

		# Initial pass for unread messages.
		class DummyMessage:
			@staticmethod
			def ack():
				return None

		self._process_notification(DummyMessage())

		streaming_pull_future = subscriber.subscribe(subscription_path, callback=self._process_notification)
		streaming_pull_future.result()

	async def run(self) -> None:
		await asyncio.to_thread(self._run_blocking)


async def main() -> None:
	print("Google Groups Gateway with GitHub + OpenSearch Integration")
	print("Features:")
	print("  - Creates GitHub issues from Google Groups posts")
	print("  - Adds GitHub comments from Google Groups replies")
	print("  - Indexes parent/comment docs in OpenSearch")
	print("Press Ctrl+C to stop")
	print("-" * 50)

	gateway = GoogleGroupGateway()
	try:
		await gateway.run()
	except KeyboardInterrupt:
		logger.info("User requested shutdown")


if __name__ == "__main__":
	asyncio.run(main())



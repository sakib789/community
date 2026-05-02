#!/usr/bin/env python3
"""
Reddit RSS Collector
Collects new public subreddit posts from RSS and creates GitHub issues.
"""

import asyncio
import html
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional, Set
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import aiohttp

# Add parent directory to path so we can import shared tooling.
PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PARENT_DIR)

from logging_config import setup_logger
from token_manager import TokenManager as CentralTokenManager
from indexer.opensearch_indexer import OpenSearchIndexer


# ======================== Configuration ========================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(SCRIPT_DIR, "reddit_gateway.log")
DB_FILE = os.path.join(SCRIPT_DIR, "reddit_rss_mapping.db")

GITHUB_API_BASE = "https://api.github.com"
GITHUB_REPO = os.environ.get("GITHUB_REPO", "sakib789/community")


def normalize_subreddit_name(value: str) -> str:
    """Accept r/name, name, or a reddit URL and return the subreddit name."""
    cleaned_value = value.strip()
    if cleaned_value.startswith("http://") or cleaned_value.startswith("https://"):
        parsed_url = urlparse(cleaned_value)
        path_parts = [part for part in parsed_url.path.split("/") if part]
        if len(path_parts) >= 2 and path_parts[0].lower() == "r":
            return path_parts[1]
        return cleaned_value

    cleaned_value = cleaned_value.removeprefix("r/")
    return cleaned_value.strip("/")


REDDIT_SUBREDDIT = normalize_subreddit_name(os.environ.get("REDDIT_SUBREDDIT", "Wazuh"))
REDDIT_RSS_URL = os.environ.get(
    "REDDIT_RSS_URL",
    f"https://www.reddit.com/r/{REDDIT_SUBREDDIT}/new/.rss",
)
REDDIT_POLL_INTERVAL = int(os.environ.get("REDDIT_POLL_INTERVAL", "30"))
REDDIT_USER_AGENT = os.environ.get("REDDIT_USER_AGENT", "community-collector/1.0")
# Retry configuration for rate limiting
REDDIT_MAX_RETRIES = int(os.environ.get("REDDIT_MAX_RETRIES", "5"))
REDDIT_RETRY_BASE_DELAY = int(os.environ.get("REDDIT_RETRY_BASE_DELAY", "1"))
REDDIT_RETRY_MAX_DELAY = int(os.environ.get("REDDIT_RETRY_MAX_DELAY", "300"))

logger = setup_logger("Collector.Reddit", log_file=LOG_FILE)


# ======================== Data Classes ========================

@dataclass
class RedditRssPost:
    item_id: str
    title: str
    author: str
    permalink: str
    published_at: Optional[datetime]
    summary: str


@dataclass
class RedditRssComment:
    comment_id: str
    post_id: str
    author: str
    permalink: str
    published_at: Optional[datetime]
    body: str


class RedditRateLimitError(RuntimeError):
    """Raised when Reddit responds with 429 rate limit."""

    def __init__(self, message: str, retry_after: Optional[int] = None):
        super().__init__(message)
        self.retry_after = retry_after


# ======================== Token Manager Wrapper ========================

class RedditTokenManager:
    """Loads GitHub credential from the shared token manager."""

    def __init__(self):
        central_manager = CentralTokenManager()
        self.github_token = central_manager.get_token("github")


# ======================== SQLite Mapping Store ========================

class RedditRssStore:
    """Persistent local de-duplication/mapping store for RSS posts."""

    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS reddit_rss_mapping (
                    item_id TEXT PRIMARY KEY,
                    subreddit TEXT NOT NULL,
                    github_issue_number INTEGER NOT NULL,
                    github_issue_url TEXT NOT NULL,
                    title TEXT,
                    author TEXT,
                    permalink TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS reddit_rss_processed (
                    item_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS reddit_rss_comments_processed (
                    comment_id TEXT PRIMARY KEY,
                    post_item_id TEXT NOT NULL,
                    github_issue_number INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def save_issue_mapping(
        self,
        item_id: str,
        subreddit: str,
        github_issue_number: int,
        github_issue_url: str,
        title: str,
        author: str,
        permalink: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO reddit_rss_mapping (
                    item_id,
                    subreddit,
                    github_issue_number,
                    github_issue_url,
                    title,
                    author,
                    permalink,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    subreddit,
                    github_issue_number,
                    github_issue_url,
                    title,
                    author,
                    permalink,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def mark_processed(self, item_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO reddit_rss_processed (item_id, created_at)
                VALUES (?, ?)
                """,
                (item_id, datetime.now(timezone.utc).isoformat()),
            )

    def is_processed(self, item_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM reddit_rss_processed WHERE item_id = ?
                """,
                (item_id,),
            ).fetchone()
            return row is not None

    def get_issue_mappings(self) -> List[Dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT item_id, subreddit, github_issue_number, github_issue_url, title, author, permalink
                FROM reddit_rss_mapping
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def mark_comment_processed(self, comment_id: str, post_item_id: str, github_issue_number: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO reddit_rss_comments_processed (
                    comment_id,
                    post_item_id,
                    github_issue_number,
                    created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (comment_id, post_item_id, github_issue_number, datetime.now(timezone.utc).isoformat()),
            )

    def is_comment_processed(self, comment_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM reddit_rss_comments_processed WHERE comment_id = ?
                """,
                (comment_id,),
            ).fetchone()
            return row is not None

    def remove_closed_issue_mappings(self, open_issue_numbers: Set[int]) -> int:
        """Remove mapping rows that no longer point to open GitHub issues."""
        with self._connect() as connection:
            if not open_issue_numbers:
                cursor = connection.execute("DELETE FROM reddit_rss_mapping")
                return cursor.rowcount or 0

            sorted_numbers = sorted(open_issue_numbers)
            placeholders = ",".join(["?"] * len(sorted_numbers))
            cursor = connection.execute(
                f"DELETE FROM reddit_rss_mapping WHERE github_issue_number NOT IN ({placeholders})",
                tuple(sorted_numbers),
            )
            return cursor.rowcount or 0


# ======================== RSS Client ========================

class RedditRssClient:
    """Fetch and parse Reddit RSS feed entries."""

    ATOM_NS = "{http://www.w3.org/2005/Atom}"

    def __init__(self, rss_url: str, user_agent: str):
        self.rss_url = rss_url
        self.user_agent = user_agent

    @staticmethod
    def _parse_retry_after(value: Optional[str]) -> Optional[int]:
        if not value:
            return None

        try:
            seconds = int(value)
            return max(1, seconds)
        except (TypeError, ValueError):
            pass

        try:
            target = parsedate_to_datetime(value)
            delta = (target - datetime.now(timezone.utc)).total_seconds()
            return max(1, int(delta))
        except Exception:
            return None

    def _candidate_urls(self) -> List[str]:
        urls = [self.rss_url]
        if self.rss_url.endswith("/new/.rss"):
            urls.append(self.rss_url.replace("/new/.rss", "/.rss"))
        return urls

    @staticmethod
    def _comment_candidate_urls(post_permalink: str) -> List[str]:
        base = post_permalink.split("?", 1)[0].split("#", 1)[0].rstrip("/")
        return [f"{base}/.rss", f"{base}.rss"]

    @staticmethod
    def _extract_post_id_from_permalink(post_permalink: str, fallback_post_item_id: str) -> str:
        match = re.search(r"/comments/([a-z0-9]+)/", post_permalink, flags=re.IGNORECASE)
        if match:
            return match.group(1)
        return fallback_post_item_id

    @staticmethod
    def _strip_html(text: str) -> str:
        cleaned = re.sub(r"<[^>]+>", "", html.unescape(text or "")).strip()
        # Reddit RSS summaries often end with a footer like:
        # "submitted by /u/<user> [link] [comments]"
        cleaned = re.sub(
            r"\s*submitted by\s+/u/\S+\s*\[link\]\s*\[comments\]\s*$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        return cleaned.strip()

    @staticmethod
    def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            # RFC 2822 and related formats.
            dt = parsedate_to_datetime(value)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass

        try:
            # ISO-8601 formats such as 2026-04-23T11:00:00+00:00 or ...Z.
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            return None

    def _parse_feed(self, text: str) -> List[RedditRssPost]:
        root = ET.fromstring(text)
        entries = root.findall(f"{self.ATOM_NS}entry")

        posts: List[RedditRssPost] = []
        for entry in entries:
            item_id = (entry.findtext(f"{self.ATOM_NS}id") or "").strip()
            title = (entry.findtext(f"{self.ATOM_NS}title") or "").strip()
            updated = (entry.findtext(f"{self.ATOM_NS}updated") or "").strip()
            published = (entry.findtext(f"{self.ATOM_NS}published") or "").strip()

            author_elem = entry.find(f"{self.ATOM_NS}author")
            author = "unknown"
            if author_elem is not None:
                author = (author_elem.findtext(f"{self.ATOM_NS}name") or "unknown").strip()

            permalink = ""
            for link_elem in entry.findall(f"{self.ATOM_NS}link"):
                rel = (link_elem.attrib.get("rel") or "").strip().lower()
                href = (link_elem.attrib.get("href") or "").strip()
                if rel in ("alternate", "") and href:
                    permalink = href
                    break
            if not permalink:
                permalink = item_id

            content = entry.findtext(f"{self.ATOM_NS}content")
            if content is None:
                content = entry.findtext(f"{self.ATOM_NS}summary")

            posts.append(
                RedditRssPost(
                    item_id=item_id or permalink,
                    title=title or "(Untitled Reddit post)",
                    author=author,
                    permalink=permalink,
                    published_at=self._parse_datetime(published or updated),
                    summary=self._strip_html(content or ""),
                )
            )

        return posts

    def _parse_comment_feed(self, text: str, fallback_post_item_id: str) -> List[RedditRssComment]:
        root = ET.fromstring(text)
        entries = root.findall(f"{self.ATOM_NS}entry")

        comments: List[RedditRssComment] = []
        for entry in entries:
            updated = (entry.findtext(f"{self.ATOM_NS}updated") or "").strip()
            published = (entry.findtext(f"{self.ATOM_NS}published") or "").strip()

            author_elem = entry.find(f"{self.ATOM_NS}author")
            author = "unknown"
            if author_elem is not None:
                author = (author_elem.findtext(f"{self.ATOM_NS}name") or "unknown").strip()

            permalink = ""
            for link_elem in entry.findall(f"{self.ATOM_NS}link"):
                rel = (link_elem.attrib.get("rel") or "").strip().lower()
                href = (link_elem.attrib.get("href") or "").strip()
                if rel in ("alternate", "") and href:
                    permalink = href
                    break

            if not permalink:
                continue

            # Comment permalink format: .../comments/<post_id>/<slug>/<comment_id>/
            comment_match = re.search(
                r"/comments/([a-z0-9]+)/[^/]+/([a-z0-9]+)(?:/|$)",
                permalink,
                flags=re.IGNORECASE,
            )
            if not comment_match:
                # Skip the top-level post entry often present in the comments feed.
                continue

            post_id = comment_match.group(1)
            comment_id = comment_match.group(2)

            content = entry.findtext(f"{self.ATOM_NS}content")
            if content is None:
                content = entry.findtext(f"{self.ATOM_NS}summary")

            comments.append(
                RedditRssComment(
                    comment_id=comment_id,
                    post_id=post_id or fallback_post_item_id,
                    author=author,
                    permalink=permalink,
                    published_at=self._parse_datetime(published or updated),
                    body=self._strip_html(content or ""),
                )
            )

        return comments

    async def fetch_posts(self, session: aiohttp.ClientSession) -> List[RedditRssPost]:
        """Fetch posts from Reddit RSS with exponential backoff for rate limits"""
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/atom+xml, application/rss+xml, application/xml;q=0.9, */*;q=0.8",
        }
        
        last_error: Optional[str] = None
        
        for url in self._candidate_urls():
            # Retry loop with exponential backoff for this URL
            retry_delay = REDDIT_RETRY_BASE_DELAY
            
            for attempt in range(REDDIT_MAX_RETRIES):
                try:
                    async with session.get(url, headers=headers, timeout=30) as response:
                        text = await response.text()
                        
                        # Handle rate limiting (429)
                        if response.status == 429:
                            retry_after_seconds = self._parse_retry_after(response.headers.get("Retry-After"))
                            if retry_after_seconds is not None:
                                retry_delay = min(retry_after_seconds, REDDIT_RETRY_MAX_DELAY)
                                logger.warning(f"Rate limited (429) - Reddit suggests waiting {retry_delay}s")
                            
                            if attempt < REDDIT_MAX_RETRIES - 1:
                                logger.warning(f"Rate limited (429) on attempt {attempt + 1}/{REDDIT_MAX_RETRIES}. Waiting {retry_delay}s before retry...")
                                await asyncio.sleep(retry_delay)
                                # Exponential backoff for next attempt
                                retry_delay = min(retry_delay * 2, REDDIT_RETRY_MAX_DELAY)
                                continue
                            else:
                                raise RedditRateLimitError(
                                    f"Rate limited (429) from {url} after {REDDIT_MAX_RETRIES} attempts",
                                    retry_after=retry_after_seconds,
                                )
                        
                        # Try to parse the feed regardless of status
                        try:
                            posts = self._parse_feed(text)
                        except ET.ParseError:
                            posts = []
                        
                        # Reddit can return status 404 for some RSS endpoints while still returning a valid Atom feed
                        if response.status == 200 or posts:
                            if response.status != 200:
                                logger.warning(
                                    f"RSS endpoint returned HTTP {response.status} but provided a valid feed; continuing with parsed entries"
                                )
                            if url != self.rss_url:
                                logger.info(f"Using fallback Reddit RSS URL: {url}")
                            return posts
                        
                        last_error = f"RSS fetch failed from {url}: {response.status} - {text[:250]}"
                        break
                
                except asyncio.TimeoutError:
                    if attempt < REDDIT_MAX_RETRIES - 1:
                        logger.warning(f"Timeout on attempt {attempt + 1}/{REDDIT_MAX_RETRIES}. Waiting {retry_delay}s before retry...")
                        await asyncio.sleep(retry_delay)
                        retry_delay = min(retry_delay * 2, REDDIT_RETRY_MAX_DELAY)
                        continue
                    else:
                        last_error = f"Timeout from {url} after {REDDIT_MAX_RETRIES} attempts"
                        break
                except Exception as e:
                    if attempt < REDDIT_MAX_RETRIES - 1:
                        logger.warning(f"Error on attempt {attempt + 1}/{REDDIT_MAX_RETRIES}: {e}. Waiting {retry_delay}s before retry...")
                        await asyncio.sleep(retry_delay)
                        retry_delay = min(retry_delay * 2, REDDIT_RETRY_MAX_DELAY)
                        continue
                    else:
                        last_error = f"Error from {url} after {REDDIT_MAX_RETRIES} attempts: {e}"
                        break
        
        raise RuntimeError(last_error or "RSS fetch failed: unable to retrieve Reddit feed")

    async def fetch_comments_for_post(
        self,
        session: aiohttp.ClientSession,
        post_permalink: str,
        fallback_post_item_id: str,
    ) -> List[RedditRssComment]:
        """Fetch comments from Reddit RSS with exponential backoff for rate limits"""
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/atom+xml, application/rss+xml, application/xml;q=0.9, */*;q=0.8",
        }
        
        last_error: Optional[str] = None
        
        for url in self._comment_candidate_urls(post_permalink):
            # Retry loop with exponential backoff for this URL
            retry_delay = REDDIT_RETRY_BASE_DELAY
            
            for attempt in range(REDDIT_MAX_RETRIES):
                try:
                    async with session.get(url, headers=headers, timeout=30) as response:
                        text = await response.text()
                        
                        # Handle rate limiting (429)
                        if response.status == 429:
                            retry_after_seconds = self._parse_retry_after(response.headers.get("Retry-After"))
                            if retry_after_seconds is not None:
                                retry_delay = min(retry_after_seconds, REDDIT_RETRY_MAX_DELAY)
                                logger.warning(f"Rate limited (429) on comments - Reddit suggests waiting {retry_delay}s")
                            
                            if attempt < REDDIT_MAX_RETRIES - 1:
                                logger.warning(f"Rate limited (429) on comments attempt {attempt + 1}/{REDDIT_MAX_RETRIES}. Waiting {retry_delay}s before retry...")
                                await asyncio.sleep(retry_delay)
                                # Exponential backoff for next attempt
                                retry_delay = min(retry_delay * 2, REDDIT_RETRY_MAX_DELAY)
                                continue
                            else:
                                raise RedditRateLimitError(
                                    f"Rate limited (429) from {url} after {REDDIT_MAX_RETRIES} attempts",
                                    retry_after=retry_after_seconds,
                                )
                        
                        # Try to parse the comments feed
                        try:
                            comments = self._parse_comment_feed(text, fallback_post_item_id)
                        except ET.ParseError:
                            comments = []
                        
                        if response.status == 200 or comments:
                            if response.status != 200:
                                logger.warning(
                                    f"Reddit comment RSS endpoint returned HTTP {response.status} but provided valid entries"
                                )
                            return comments
                        
                        last_error = f"Comment RSS fetch failed from {url}: {response.status} - {text[:250]}"
                        break
                
                except asyncio.TimeoutError:
                    if attempt < REDDIT_MAX_RETRIES - 1:
                        logger.warning(f"Timeout on comments attempt {attempt + 1}/{REDDIT_MAX_RETRIES}. Waiting {retry_delay}s before retry...")
                        await asyncio.sleep(retry_delay)
                        retry_delay = min(retry_delay * 2, REDDIT_RETRY_MAX_DELAY)
                        continue
                    else:
                        last_error = f"Timeout from {url} after {REDDIT_MAX_RETRIES} attempts"
                        break
                except Exception as e:
                    if attempt < REDDIT_MAX_RETRIES - 1:
                        logger.warning(f"Error on comments attempt {attempt + 1}/{REDDIT_MAX_RETRIES}: {e}. Waiting {retry_delay}s before retry...")
                        await asyncio.sleep(retry_delay)
                        retry_delay = min(retry_delay * 2, REDDIT_RETRY_MAX_DELAY)
                        continue
                    else:
                        last_error = f"Error from {url} after {REDDIT_MAX_RETRIES} attempts: {e}"
                        break
        
        raise RuntimeError(last_error or "Comment RSS fetch failed")


# ======================== GitHub Issue Creator ========================

class GitHubIssueCreator:
    """Creates GitHub issues from Reddit RSS posts."""

    def __init__(self, github_token: Optional[str], repo: str = GITHUB_REPO):
        self.github_token = "".join(github_token.split()) if github_token else None
        self.repo = repo
        self.enabled = bool(self.github_token)
        self.indexer = OpenSearchIndexer()
        if not self.enabled:
            logger.warning("GitHub integration disabled (no token found)")
        else:
            logger.info(f"GitHub integration enabled for repo: {repo}")

    @staticmethod
    def _create_reddit_parent_document(
        post: RedditRssPost,
        issue_number: int,
        issue_url: str,
        labels: List[str],
    ) -> Dict:
        created_at = (
            post.published_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            if post.published_at is not None
            else datetime.utcnow().isoformat() + "Z"
        )
        return {
            "id": f"reddit_{post.item_id}",
            "platform": "reddit",
            "document_type": "parent",
            "created_at": created_at,
            "reddit_post_id": post.item_id,
            "reddit_subreddit": REDDIT_SUBREDDIT,
            "reddit_author": post.author,
            "reddit_permalink": post.permalink,
            "title": post.title,
            "content": post.summary or post.title,
            "record_type": "parent",
            "status": "open",
            "github_issue_number": issue_number,
            "github_issue_url": issue_url,
            "labels": labels,
        }

    @staticmethod
    def _create_reddit_comment_document(
        comment: RedditRssComment,
        post_item_id: str,
        issue_number: int,
        issue_url: str,
        github_comment_id: Optional[int],
    ) -> Dict:
        created_at = (
            comment.published_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            if comment.published_at is not None
            else datetime.utcnow().isoformat() + "Z"
        )
        return {
            "id": f"reddit_{comment.comment_id}",
            "parent_id": f"reddit_{post_item_id}",
            "platform": "reddit",
            "document_type": "comment",
            "created_at": created_at,
            "reddit_comment_id": comment.comment_id,
            "reddit_post_id": post_item_id,
            "reddit_subreddit": REDDIT_SUBREDDIT,
            "reddit_author": comment.author,
            "reddit_permalink": comment.permalink,
            "content": comment.body,
            "record_type": "comment",
            "github_comment_id": github_comment_id,
            "github_issue_number": issue_number,
            "github_issue_url": issue_url,
        }

    async def get_open_reddit_issue_numbers(self, session: aiohttp.ClientSession) -> Optional[Set[int]]:
        if not self.enabled:
            return set()

        headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github.v3+json",
        }

        open_issues: Set[int] = set()
        page = 1
        while True:
            url = (
                f"{GITHUB_API_BASE}/repos/{self.repo}/issues"
                f"?state=open&labels=platform/reddit&per_page=100&page={page}"
            )
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(
                        f"Failed to list open Reddit issues: {response.status} - {error_text[:250]}"
                    )
                    return None

                issues = await response.json()

            if not issues:
                break

            for issue in issues:
                if "pull_request" in issue:
                    continue
                number = issue.get("number")
                if isinstance(number, int):
                    open_issues.add(number)

            if len(issues) < 100:
                break

            page += 1

        return open_issues

    async def is_issue_open(self, session: aiohttp.ClientSession, issue_number: int) -> bool:
        """Return True only when the target issue currently exists and is open."""
        if not self.enabled:
            return False

        headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github.v3+json",
        }
        url = f"{GITHUB_API_BASE}/repos/{self.repo}/issues/{issue_number}"

        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                error_text = await response.text()
                logger.warning(
                    f"Unable to verify issue #{issue_number} state: {response.status} - {error_text[:200]}"
                )
                return False

            issue = await response.json()

        # Exclude pull requests from issue comment sync.
        if "pull_request" in issue:
            return False

        return issue.get("state") == "open"

    async def add_comment_to_issue(
        self,
        comment: RedditRssComment,
        post_item_id: str,
        issue_number: int,
        issue_url: str,
        session: aiohttp.ClientSession,
    ) -> Optional[Dict]:
        if not self.enabled:
            return None

        created_text = (
            comment.published_at.isoformat() if comment.published_at is not None else "unknown"
        )
        body = (
            f"### Reddit Comment from /u/{comment.author}\n\n"
            f"**Subreddit:** r/{REDDIT_SUBREDDIT}\n"
            f"**Published:** {created_text}\n"
            f"**Permalink:** {comment.permalink}\n\n"
            f"{comment.body or '(No comment content)'}\n"
        )

        headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
        }
        url = f"{GITHUB_API_BASE}/repos/{self.repo}/issues/{issue_number}/comments"
        payload = {"body": body}

        async with session.post(url, headers=headers, json=payload) as response:
            if response.status == 201:
                comment_data = await response.json()
                try:
                    comment_doc = self._create_reddit_comment_document(
                        comment=comment,
                        post_item_id=post_item_id,
                        issue_number=issue_number,
                        issue_url=issue_url,
                        github_comment_id=comment_data.get("id"),
                    )
                    self.indexer.index_comment(comment_doc, parent_id=f"reddit_{post_item_id}")
                except Exception as exc:
                    logger.error(f"Error indexing Reddit comment document: {exc}")

                logger.info(
                    f"Added Reddit comment {comment.comment_id} to GitHub issue #{issue_number}"
                )
                return comment_data

            error_text = await response.text()
            logger.error("Failed to create GitHub issue comment from Reddit")
            logger.error(f"Status: {response.status}")
            logger.error(f"URL: {url}")
            logger.error(f"Repository: {self.repo}")
            logger.error(f"Response: {error_text}")
            return None

    async def create_issue_for_post(self, post: RedditRssPost, session: aiohttp.ClientSession) -> Optional[Dict]:
        if not self.enabled:
            return None

        created_text = (
            post.published_at.isoformat() if post.published_at is not None else "unknown"
        )
        body = (
            "## Reddit Post\n\n"
            f"**Subreddit:** r/{REDDIT_SUBREDDIT}\n"
            f"**Author:** {post.author}\n"
            f"**Published:** {created_text}\n"
            f"**Permalink:** {post.permalink}\n\n"
            "### Summary\n\n"
            f"{post.summary or '(No summary provided in RSS)'}\n"
        )

        labels = ["platform/reddit", f"reddit/subreddit/{REDDIT_SUBREDDIT}"]
        payload = {
            "title": post.title[:100],
            "body": body,
            "labels": labels,
        }
        headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
        }
        url = f"{GITHUB_API_BASE}/repos/{self.repo}/issues"

        async with session.post(url, headers=headers, json=payload) as response:
            if response.status == 201:
                issue_data = await response.json()
                try:
                    parent_doc = self._create_reddit_parent_document(
                        post=post,
                        issue_number=issue_data["number"],
                        issue_url=issue_data["html_url"],
                        labels=labels,
                    )
                    self.indexer.index_parent(parent_doc)
                except Exception as exc:
                    logger.error(f"Error indexing Reddit parent document: {exc}")

                logger.info(f"Created GitHub issue #{issue_data['number']}: {post.title[:100]}")
                return issue_data

            error_text = await response.text()
            logger.error("Failed to create GitHub issue")
            logger.error(f"Status: {response.status}")
            logger.error(f"URL: {url}")
            logger.error(f"Repository: {self.repo}")
            logger.error(f"Response: {error_text}")
            return None


# ======================== Reddit RSS Gateway ========================

class RedditGateway:
    """Polls Reddit RSS feed for new posts and mirrors them to GitHub issues."""

    def __init__(self):
        self.token_manager = RedditTokenManager()
        self.rss_client = RedditRssClient(REDDIT_RSS_URL, REDDIT_USER_AGENT)
        self.issue_creator = GitHubIssueCreator(self.token_manager.github_token)
        self.store = RedditRssStore()
        self.start_timestamp = time.time()

    async def process_post(self, post: RedditRssPost, session: aiohttp.ClientSession) -> None:
        if not post.item_id:
            return

        if self.store.is_processed(post.item_id):
            return

        # First run: avoid creating issues for historical feed items.
        if post.published_at is not None and post.published_at.timestamp() <= self.start_timestamp:
            self.store.mark_processed(post.item_id)
            return

        logger.info(f"New Reddit RSS post detected: {post.title[:80]}")
        issue_data = await self.issue_creator.create_issue_for_post(post, session)
        if not issue_data:
            return

        self.store.save_issue_mapping(
            item_id=post.item_id,
            subreddit=REDDIT_SUBREDDIT,
            github_issue_number=issue_data["number"],
            github_issue_url=issue_data["html_url"],
            title=post.title,
            author=post.author,
            permalink=post.permalink,
        )
        self.store.mark_processed(post.item_id)

    async def process_comments(self, session: aiohttp.ClientSession) -> None:
        open_reddit_issues = await self.issue_creator.get_open_reddit_issue_numbers(session)
        if open_reddit_issues is None:
            logger.warning("Skipping comments sync and mapping cleanup due to GitHub issue-list fetch failure")
            return

        removed_count = self.store.remove_closed_issue_mappings(open_reddit_issues)
        if removed_count > 0:
            logger.info(f"Removed {removed_count} closed issue mapping(s) from local DB")

        if not open_reddit_issues:
            return

        for mapping in self.store.get_issue_mappings():
            raw_issue_number = mapping.get("github_issue_number")
            try:
                issue_number = int(raw_issue_number)
            except (TypeError, ValueError):
                logger.warning(f"Skipping mapping with invalid issue number: {raw_issue_number}")
                continue

            if issue_number not in open_reddit_issues:
                continue

            post_item_id = mapping.get("item_id")
            post_permalink = mapping.get("permalink")
            issue_url = mapping.get("github_issue_url")
            if not post_item_id or not post_permalink or not issue_url:
                continue

            # Double-check state in case issue was closed after list retrieval.
            if not await self.issue_creator.is_issue_open(session, issue_number):
                logger.info(
                    f"Skipping Reddit comments for closed/non-open issue #{issue_number}"
                )
                continue

            try:
                comments = await self.rss_client.fetch_comments_for_post(
                    session=session,
                    post_permalink=post_permalink,
                    fallback_post_item_id=post_item_id,
                )
            except RedditRateLimitError as exc:
                logger.warning(
                    f"Rate limited during comments sync (issue #{issue_number}, post {post_item_id}). "
                    f"Stopping current sync cycle: {exc}"
                )
                raise
            except Exception as exc:
                logger.warning(
                    f"Skipping comments fetch for issue #{issue_number}, post {post_item_id}: {exc}"
                )
                continue

            for comment in reversed(comments):
                if not comment.comment_id:
                    continue

                if self.store.is_comment_processed(comment.comment_id):
                    continue

                # First run: do not backfill old comments.
                if (
                    comment.published_at is not None
                    and comment.published_at.timestamp() <= self.start_timestamp
                ):
                    self.store.mark_comment_processed(comment.comment_id, post_item_id, issue_number)
                    continue

                comment_data = await self.issue_creator.add_comment_to_issue(
                    comment=comment,
                    post_item_id=post_item_id,
                    issue_number=issue_number,
                    issue_url=issue_url,
                    session=session,
                )
                if comment_data is not None:
                    self.store.mark_comment_processed(comment.comment_id, post_item_id, issue_number)

    async def poll_once(self, session: aiohttp.ClientSession) -> None:
        posts = await self.rss_client.fetch_posts(session)
        for post in reversed(posts):
            await self.process_post(post, session)
        await self.process_comments(session)

    async def run(self) -> None:
        logger.info("=" * 60)
        logger.info("Reddit RSS Gateway Starting")
        logger.info("=" * 60)
        logger.info(f"RSS URL: {REDDIT_RSS_URL}")
        logger.info(f"Poll interval: {REDDIT_POLL_INTERVAL}s")
        logger.info(f"GitHub repo: {GITHUB_REPO}")
        logger.info(f"Retry config: max_retries={REDDIT_MAX_RETRIES}, base_delay={REDDIT_RETRY_BASE_DELAY}s, max_delay={REDDIT_RETRY_MAX_DELAY}s")
        logger.info("Mode: posts only (RSS)")
        logger.info("Press Ctrl+C to stop")
        logger.info("=" * 60)

        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            consecutive_rate_limits = 0
            
            while True:
                try:
                    await self.poll_once(session)
                    consecutive_rate_limits = 0  # Reset on success
                    await asyncio.sleep(REDDIT_POLL_INTERVAL)
                except asyncio.CancelledError:
                    raise
                except RedditRateLimitError as exc:
                    consecutive_rate_limits += 1
                    default_backoff = min(60 * (2 ** (consecutive_rate_limits - 1)), 600)
                    backoff = max(exc.retry_after or 0, default_backoff)
                    logger.error(
                        f"Reddit RSS collector rate limited (attempt {consecutive_rate_limits}). "
                        f"Waiting {backoff}s before retry: {exc}"
                    )
                    await asyncio.sleep(backoff)
                except RuntimeError as exc:
                    error_msg = str(exc)
                    # Check if this is a rate limit error
                    is_rate_limit = "429" in error_msg or "Rate limited" in error_msg
                    
                    if is_rate_limit:
                        consecutive_rate_limits += 1
                        # Exponential backoff: 60s, 120s, 240s, 480s, 600s (max 10 min)
                        backoff = min(60 * (2 ** (consecutive_rate_limits - 1)), 600)
                        logger.error(
                            f"🔴 Reddit RSS collector rate limited (attempt {consecutive_rate_limits}). "
                            f"Waiting {backoff}s before retry: {error_msg}"
                        )
                        await asyncio.sleep(backoff)
                    else:
                        logger.error(f"Reddit RSS collector error: {exc}", exc_info=True)
                        await asyncio.sleep(min(REDDIT_POLL_INTERVAL, 30))
                except Exception as exc:
                    consecutive_rate_limits = 0
                    logger.error(f"Reddit RSS collector error: {exc}", exc_info=True)
                    await asyncio.sleep(min(REDDIT_POLL_INTERVAL, 30))


# ======================== Main ========================

async def main() -> None:
    print("Reddit RSS Gateway with GitHub Integration")
    print(f"RSS source: {REDDIT_RSS_URL}")
    print("Features:")
    print("  - Creates GitHub issues from new subreddit RSS posts")
    print("  - Adds GitHub comments from new Reddit comments for open Reddit issues")
    print(f"  - Uses labels: platform/reddit, reddit/subreddit/{REDDIT_SUBREDDIT}")
    print("  - Indexes Reddit parent/comment documents in OpenSearch")
    print("Press Ctrl+C to stop")
    print("-" * 50)

    gateway = RedditGateway()

    try:
        await gateway.run()
    except KeyboardInterrupt:
        print("\nShutting down...")
        logger.info("User requested shutdown")
    except Exception as exc:
        logger.error(f"Unexpected error: {exc}", exc_info=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass








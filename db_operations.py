"""Persistence for bulletins, mail, and the channel directory.

Pure: this module writes and reads SQLite and nothing else. Writers return a
record describing what happened; deciding whether that record is synced to
peer BBS Nodes or broadcast to the mesh belongs to Replication, not here.
"""

import logging
import sqlite3
import threading
import uuid
from datetime import datetime

from events import BulletinDeleted, BulletinPosted, ChannelAdded, MailDeleted, MailSent

thread_local = threading.local()


def get_db_connection():
    if not hasattr(thread_local, 'connection'):
        thread_local.connection = sqlite3.connect('bulletins.db')
    return thread_local.connection


def initialize_database():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS bulletins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    board TEXT NOT NULL,
                    sender_short_name TEXT NOT NULL,
                    date TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    content TEXT NOT NULL,
                    unique_id TEXT NOT NULL
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS mail (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender TEXT NOT NULL,
                    sender_short_name TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    date TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    content TEXT NOT NULL,
                    unique_id TEXT NOT NULL
                );''')
    c.execute('''CREATE TABLE IF NOT EXISTS channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL
                );''')
    conn.commit()
    print("Database schema initialized.")


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M')


# --- channels --------------------------------------------------------------

def insert_channel(name, url):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("INSERT INTO channels (name, url) VALUES (?, ?)", (name, url))
    conn.commit()
    return ChannelAdded(name=name, url=url)


def get_channels():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT name, url FROM channels")
    return c.fetchall()


# --- bulletins -------------------------------------------------------------

def insert_bulletin(board, sender_short_name, subject, content, unique_id=None):
    conn = get_db_connection()
    c = conn.cursor()
    if not unique_id:
        unique_id = str(uuid.uuid4())
    c.execute(
        "INSERT INTO bulletins (board, sender_short_name, date, subject, content, unique_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (board, sender_short_name, _now(), subject, content, unique_id))
    conn.commit()
    return BulletinPosted(board=board, sender_short_name=sender_short_name,
                          subject=subject, content=content, unique_id=unique_id)


def get_bulletins(board):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, subject, sender_short_name, date, unique_id "
              "FROM bulletins WHERE board = ? COLLATE NOCASE", (board,))
    return c.fetchall()


def get_bulletin_content(bulletin_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT sender_short_name, date, subject, content, unique_id "
              "FROM bulletins WHERE id = ?", (bulletin_id,))
    return c.fetchone()


def delete_bulletin(unique_id):
    """Delete by unique_id — the identity peers share. Returns None if absent.

    The previous implementation deleted by the local autoincrement `id` while
    its only caller (the sync path) passed a unique_id, so a replicated
    deletion silently matched nothing.
    """
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT unique_id FROM bulletins WHERE unique_id = ?", (unique_id,))
    if c.fetchone() is None:
        logging.error(f"No bulletin found with unique_id: {unique_id}")
        return None
    c.execute("DELETE FROM bulletins WHERE unique_id = ?", (unique_id,))
    conn.commit()
    return BulletinDeleted(unique_id=unique_id)


# --- mail ------------------------------------------------------------------

def insert_mail(sender_id, sender_short_name, recipient_id, subject, content, unique_id=None):
    conn = get_db_connection()
    c = conn.cursor()
    if not unique_id:
        unique_id = str(uuid.uuid4())
    c.execute("INSERT INTO mail (sender, sender_short_name, recipient, date, subject, content, unique_id) "
              "VALUES (?, ?, ?, ?, ?, ?, ?)",
              (sender_id, sender_short_name, recipient_id, _now(), subject, content, unique_id))
    conn.commit()
    return MailSent(sender_id=sender_id, sender_short_name=sender_short_name,
                    recipient_id=recipient_id, subject=subject,
                    content=content, unique_id=unique_id)


def get_mail(recipient_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, sender_short_name, subject, date, unique_id "
              "FROM mail WHERE recipient = ?", (recipient_id,))
    return c.fetchall()


def get_mail_content(mail_id, recipient_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT sender_short_name, date, subject, content, unique_id "
              "FROM mail WHERE id = ? and recipient = ?", (mail_id, recipient_id,))
    return c.fetchone()


def delete_mail(unique_id):
    """Delete by unique_id. Returns None if no such mail exists."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT recipient FROM mail WHERE unique_id = ?", (unique_id,))
    result = c.fetchone()
    if result is None:
        logging.error(f"No mail found with unique_id: {unique_id}")
        return None
    logging.info(f"Attempting to delete mail with unique_id: {unique_id} by {result[0]}")
    c.execute("DELETE FROM mail WHERE unique_id = ?", (unique_id,))
    conn.commit()
    return MailDeleted(unique_id=unique_id)


def get_sender_id_by_mail_id(mail_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT sender FROM mail WHERE id = ?", (mail_id,))
    result = c.fetchone()
    if result:
        return result[0]
    return None

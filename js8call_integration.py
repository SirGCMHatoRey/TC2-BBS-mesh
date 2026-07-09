"""The JS8Call bridge: listens to a JS8Call instance and stores what it hears.

Only the client lives here now — browsing what it stored is Js8Flow's job.
Writes go through the shared Js8Database, so the writer and the reader can no
longer point at different files.
"""

from socket import socket, AF_INET, SOCK_STREAM
import json
import time
import configparser
import logging

from meshtastic import BROADCAST_NUM

import settings
from utils import send_message

config_file = 'config.ini'


def from_message(content):
    try:
        return json.loads(content)
    except ValueError:
        return {}


def to_message(typ, value='', params=None):
    if params is None:
        params = {}
    return json.dumps({'type': typ, 'value': value, 'params': params})


class JS8CallClient:
    def __init__(self, interface, logger=None):
        self.logger = logger or logging.getLogger('js8call')
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False

        self.config = configparser.ConfigParser()
        self.config.read(config_file)

        self.server = (
            self.config.get('js8call', 'host', fallback=None),
            self.config.getint('js8call', 'port', fallback=None)
        )
        self.js8groups = [g.strip() for g in
                          self.config.get('js8call', 'js8groups', fallback='').split(',')]
        self.store_messages = self.config.getboolean('js8call', 'store_messages', fallback=True)
        self.js8urgent = [g.strip() for g in
                          self.config.get('js8call', 'js8urgent', fallback='').split(',')]

        self.connected = False
        self.sock = None
        self.interface = interface
        self.database = settings.js8_database()

        if self.database.configured:
            self.database.create_tables()
            self.logger.info("JS8Call database tables created or verified.")
        else:
            self.logger.info("JS8Call configuration not found. Skipping JS8Call integration.")

    def process(self, message):
        typ = message.get('type', '')
        value = message.get('value', '')

        if not typ:
            return

        rx_types = [
            'RX.ACTIVITY', 'RX.DIRECTED', 'RX.SPOT', 'RX.CALL_ACTIVITY',
            'RX.CALL_SELECTED', 'RX.DIRECTED_ME', 'RX.ECHO', 'RX.DIRECTED_GROUP',
            'RX.META', 'RX.MSG', 'RX.PING', 'RX.PONG', 'RX.STREAM'
        ]

        if typ not in rx_types:
            return

        if typ == 'RX.DIRECTED' and value:
            parts = value.split(' ')
            if len(parts) < 3:
                self.logger.warning(f"Unexpected message format: {value}")
                return

            sender = parts[0]
            receiver = parts[1]
            msg = ' '.join(parts[2:]).strip()

            self.logger.info(f"Received JS8Call message: {sender} to {receiver} - {msg}")

            if receiver in self.js8urgent:
                self.database.insert('urgent', sender, receiver, msg)
                notification_message = (f"💥 URGENT JS8Call Message Received 💥\n"
                                        f"From: {sender}\nCheck BBS for message")
                send_message(notification_message, BROADCAST_NUM, self.interface)
            elif receiver in self.js8groups:
                self.database.insert('groups', sender, receiver, msg)
            elif self.store_messages:
                self.database.insert('messages', sender, receiver, msg)

    def send(self, *args, **kwargs):
        params = kwargs.get('params', {})
        if '_ID' not in params:
            params['_ID'] = '{}'.format(int(time.time() * 1000))
            kwargs['params'] = params
        message = to_message(*args, **kwargs)
        self.sock.send((message + '\n').encode('utf-8'))  # Convert to bytes

    def connect(self):
        if not self.server[0] or not self.server[1]:
            self.logger.info("JS8Call server configuration not found. Skipping JS8Call connection.")
            return

        self.logger.info(f"Connecting to {self.server}")
        self.sock = socket(AF_INET, SOCK_STREAM)
        try:
            self.sock.connect(self.server)
            self.connected = True
            self.send("STATION.GET_STATUS")

            while self.connected:
                content = self.sock.recv(65500).decode('utf-8')  # Decode received bytes to string
                if not content:
                    continue  # Skip empty content

                try:
                    message = json.loads(content)
                except ValueError:
                    continue  # Skip invalid JSON content

                if not message:
                    continue  # Skip empty message

                self.process(message)
        except ConnectionRefusedError:
            self.logger.error(f"Connection to JS8Call server {self.server} refused.")
        finally:
            self.sock.close()

    def close(self):
        self.connected = False

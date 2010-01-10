#! /usr/bin/python

import logging
import re
import select
import signal
import socket
import subprocess
import sys
import time

from irc import Bot
from ircbot import SingleServerIRCBot, nm_to_n as get_nick, parse_channel_modes

# FIXME figure out async subprocess
# FIXME use optparse and/or configreader

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(message)s")

CHANNEL = '#foo'
PATTERN = '^[\!\?][^ ]+'

bot = Bot(('localhost', 6667), 'pycat', 'pycat', CHANNEL)

def listen_parser(line):
    if not line.strip() or not bot.ready:
        return
    elif line.startswith('/me '):
        bot.irc.ctcp_action(CHANNEL, line[len('/me '):])
    elif line.startswith('/notice '):
        bot.irc.notice(CHANNEL, line[len('/notice '):])
    else:
        bot.irc.privmsg(CHANNEL, line)

def msg_parser(nick=None, user=None, host=None, command=None, args=None):
    target, message = args

    if not re.match(PATTERN, message) or target != CHANNEL:
        return

    p = subprocess.Popen('./test.sh',
        shell=True,
        bufsize=1024,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE)

    # FIXME this will block
    response = p.communicate(input=message.encode('utf-8'))[0]

    if not response.strip():
        return

    try:
        response = response.decode('utf-8')
    except UnicodeDecodeError:
        response = response.decode('iso-8859-1')

    for line in response.split('\n'):
        if line.strip():
            bot.irc.privmsg(CHANNEL, line)

def reset_sigalarm(nick=None, user=None, host=None, command=None, args=None):
    signal.alarm(300)

def alarm_handler(signum, frame):
    bot.irc.version('')

signal.signal(signal.SIGALRM, alarm_handler)

bot.add_handler('PRIVMSG', msg_parser)
bot.add_handler('ALL', reset_sigalarm)

class PyCatBot(SingleServerIRCBot):
    def __init__(self, server_list, nick, real, channel):
        SingleServerIRCBot.__init__(self, server_list, nick, real)

        self.channel = channel

        self.sockets = []
        self.recivers = []
        self.listener = self.get_listener()

        self.ircobj.fn_to_add_socket = self.sockets.append
        self.ircobj.fn_to_remove_socket = self.sockets.remove

    def get_listener(self, addr=('', 12345)):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setblocking(0)
        listener.bind(addr)
        listener.listen(5)

        return listener

    def on_welcome(self, conn, event):
        conn.join(self.channel)

    def on_nicknameinuse(self, conn, event):
        conn.nick(conn.get_nickname() + '_')

    def on_invite(self, conn, event):
        if event.arguments()[0] == self.channel:
            conn.join(self.channel)

    def on_mode(self, conn, event):
        if event.target() != self.channel:
            return

        nick = conn.get_nickname()
        modes = parse_channel_modes(' '.join(event.arguments()))

        if ['+', 'o', nick] in modes:
            conn.mode(self.channel, '+v-o %s %s' % (nick, nick))

    def on_pubmsg(self, conn, event):
        sender = get_nick(event.source())
        message = event.arguments()[0]

        print sender, ':',  message

    def start(self):
        self._connect()

        while 1:
            self.process_once()

    def stop(self):
        if self.connection.is_connected():
            self.connection.disconnect('Bye :)')

    def process_once(self, timeout=0.2):
        sockets = self.sockets + [self.listener] + self.recivers

        for sock in select.select(sockets, [], [], timeout)[0]:
            if sock in self.recivers:
                self.handle_reciver(sock)
            elif sock is self.listener:
                self.handle_listener(sock)
            elif sock in self.sockets:
                self.handle_irc(sock)

        self.handle_timeout()

    def handle_reciver(self, sock):
        print sock.recv(1024)

    def handle_listener(self, sock):
        conn, addr = sock.accept()
        self.recivers.append(conn)

    def handle_irc(self, sock):
        self.ircobj.process_data([sock])

    def handle_timeout(self):
        self.ircobj.process_timeout()

pycat = PyCatBot([('localhost', 6667)], 'pycat', 'pycat', CHANNEL)

try:
    pycat.start()
except KeyboardInterrupt:
    pycat.stop()

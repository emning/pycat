#! /usr/bin/python

import logging
import select
import socket
import subprocess
import time

from ircbot import SingleServerIRCBot, nm_to_n as get_nick, parse_channel_modes

# FIXME use optparse and/or configreader

LOG_FORMAT = "[%(name)7s %(asctime)s] %(message)s"
logging.basicConfig(level=logging.DEBUG, format=LOG_FORMAT)

class PyCatBot(SingleServerIRCBot):
    def __init__(self, server_list, nick, real, channel, script):
        SingleServerIRCBot.__init__(self, server_list, nick, real)

        self.channel = channel
        self.script = script

        self.sockets = []
        self.recivers = []
        self.processes = []
        self.buffers = {}
        self.loggers = {}
        self.listener = self.get_listener()

        self.last_seen = time.time()
        self.ircobj.fn_to_add_socket = self.sockets.append
        self.ircobj.fn_to_remove_socket = self.sockets.remove

        self.setup_logging()

    def setup_logging(self):
        self.loggers['irc'] = logging.getLogger('irc')
        self.loggers['process'] = logging.getLogger('process')
        self.loggers['reciver'] = logging.getLogger('reciver')

        orignial_send_raw = self.connection.send_raw

        def send_raw(string):
            self.loggers['irc'].debug(string.decode('utf-8'))
            orignial_send_raw(string)

        def logger(conn, event):
            line = u' '.join(event.arguments())
            self.loggers['irc'].debug(line)

        self.connection.add_global_handler('all_raw_messages', logger)
        self.connection.send_raw = send_raw

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
        channel = event.target()
        nick = get_nick(event.source())
        message = self.decode(event.arguments()[0])

        p = subprocess.Popen([self.script, channel, nick, message],
            bufsize=1024, stdout=subprocess.PIPE)

        self.processes.append(p.stdout)

    def start(self):
        self._connect()

        while 1:
            sockets = self.sockets + self.recivers + \
                self.processes + [self.listener]
            self.process_sockets(sockets)

    def stop(self):
        if self.connection.is_connected():
            self.connection.disconnect('Bye :)')

        self.listener.close()

        for sock in self.recivers + self.processes:
            sock.close()

    def process_sockets(self, sockets):
        for sock in select.select(sockets, [], [], 0.2)[0]:
            if sock in self.recivers:
                self.handle_reciver(sock)
            elif sock is self.listener:
                self.handle_listener(sock)
            elif sock in self.sockets:
                self.handle_irc(sock)
            elif sock in self.processes:
                self.handle_process(sock)

        self.handle_timeout()

    def handle_process(self, sock):
        if sock not in self.buffers:
            self.buffers[sock] = u''

        data = sock.read(512)

        if len(data) == 0:
            self.processes.remove(sock)
            sock.close()
        else:
            self.buffers[sock] += self.decode(data)

        while '\n' in self.buffers[sock]:
            message, trailing = self.buffers[sock].split('\n', 1)
            self.buffers[sock] = trailing

            self.loggers['process'].debug(message)
            self.handle_reciver_message(message)

        if len(data) == 0:
            del self.buffers[sock]

    def handle_reciver(self, sock):
        if sock not in self.buffers:
            self.buffers[sock] = u''

        data = sock.recv(512)
        peer = sock.getpeername()[0]

        if len(data) == 0:
            self.recivers.remove(sock)
            self.loggers['reciver'].debug('%s disconnected', peer)
            sock.close()
        else:
            self.buffers[sock] += self.decode(data)

        while '\n' in self.buffers[sock]:
            message, trailing = self.buffers[sock].split('\n', 1)
            self.buffers[sock] = trailing

            self.loggers['reciver'].debug('%s %s', peer, message)
            self.handle_reciver_message(message)

        if len(data) == 0:
            del self.buffers[sock]

    def handle_reciver_message(self, message):
        message = message.encode('utf-8')

        if not message.strip() or not self.connection.is_connected():
            return
        elif message.startswith('/me '):
            self.connection.action(CHANNEL, message[len('/me '):])
        elif message.startswith('/notice '):
            self.connection.notice(CHANNEL, message[len('/notice '):])
        else:
            self.connection.privmsg(CHANNEL, message)

    def handle_listener(self, sock):
        conn, addr = sock.accept()
        self.loggers['reciver'].debug('%s connected', addr[0])
        self.recivers.append(conn)

    def handle_irc(self, sock):
        self.ircobj.process_data([sock])
        self.last_seen = time.time()

    def handle_timeout(self):
        self.ircobj.process_timeout()
        self.check_connection()

    def check_connection(self):
        # FIXME test if this is needed
        if time.time() - self.last_seen > 300:
            self.connection.version()

    def decode(self, data):
        try:
            data = data.decode('utf-8')
        except UnicodeDecodeError:
            data = data.decode('iso-8859-1')
        return data

pycat = PyCatBot([('localhost', 6667)], 'pycat', 'pycat', '#pycat', './test.sh')

try:
    pycat.start()
except KeyboardInterrupt:
    pycat.stop()

############################################################################
#                                                                          #
#                            REMOTE.PY                                     #
#                                                                          #
#           Copyright (C) 2008 - 2014 Ada Core, Inc.                       #
#                                                                          #
# This program is free software: you can redistribute it and/or modify     #
# it under the terms of the GNU General Public License as published by     #
# the Free Software Foundation, either version 3 of the License, or        #
# (at your option) any later version.                                      #
#                                                                          #
# This program is distributed in the hope that it will be useful,          #
# but WITHOUT ANY WARRANTY; without even the implied warranty of           #
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the            #
# GNU General Public License for more details.                             #
#                                                                          #
# You should have received a copy of the GNU General Public License        #
# along with this program.  If not, see <http://www.gnu.org/licenses/>     #
#                                                                          #
############################################################################

"""This module provides simple functions to perform ssh and scp.

If module paramiko is loaded then it offers paramiko-based functions which
allows better compatibility with unix and windows systems.
Otherwise it uses gnatpython.ex.Run implementation.
"""
from gnatpython.fileutils import unixpath
from gnatpython.ex import Run
import logging
import os


try:
    import paramiko
    import socket
    paramiko_logger = logging.getLogger('paramiko')
    paramiko_logger.setLevel(logging.ERROR)

    class SSHClient(paramiko.SSHClient):
        """Override exec_command to add a timeout."""
        def exec_command(self, command, bufsize=-1, timeout=None):
            chan = self._transport.open_session()
            chan.settimeout(timeout)
            chan.exec_command(command)
            stdout = chan.makefile('rb', bufsize)
            stderr = chan.makefile_stderr('rb', bufsize)
            status = chan.recv_exit_status()
            return (stdout, stderr, status)

    def ssh_exec(user, host, cmd, timeout=None):
        """Execute a command on the SSH server.

        :param user: user login to authenticate as
        :type user: str
        :param host: the server to connect to
        :type host: str
        :param cmd: the command to execute
        :type cmd: str
        :param timeout: seconds to wait before raising socket.timeout
        :type timeout: int | None

        :return: (output content, error content, exit status)
        :rtype: (str, str, int)
        """
        client = SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        if not socket.has_ipv6:
            # If python is configured without IPv6 then paramiko connect()
            # can fail with: getsockaddrarg: bad family
            host = socket.gethostbyname(host)

        client.connect(host, username=user)
        stdout, stderr, status = client.exec_command(cmd, timeout=timeout)
        response = (stdout.read().rstrip(), stderr.read().rstrip(), status)
        client.close()
        return response

    def scp(user, host, remotepath, localpath, method=None):
        """Copy a file on the remote server.

        :param user: user login to authenticate as
        :type user: str
        :param host: the server to connect to
        :type host: str
        :param remotepath: path on the remote server
        :type remotepath: str
        :param localpath: path on the local server
        :type localpath: str
        :param method: 'get' or 'put'
        :type method: str

        :return: (output content, error content, exit status)
        :rtype: (str, str, int)
        """
        if method not in ('get', 'put'):
            return ('', 'Method %s not implemented' % method, 1)

        client = SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        if not socket.has_ipv6:
            # If python is configured without IPv6 then paramiko connect()
            # can fail with: getsockaddrarg: bad family
            host = socket.gethostbyname(host)
        client.connect(host, username=user)
        sftp = client.open_sftp()

        remotepath = unixpath(remotepath)
        localpath = unixpath(localpath)
        err = ''
        status = 0
        out = localpath if method == 'get' else remotepath
        try:
            if method == 'get':
                sftp.get(remotepath, localpath)
            else:
                # method: put
                sftp.put(localpath, remotepath)
        except IOError as e:
            err = e
            status = 1
        finally:
            sftp.close()
            client.close()
        return (out, err, status)

    def scp_get(user, host, remotepath, localpath=None):
        """Copy a remote file from host to the local host as localpath.

        :param user: user login to authenticate as
        :type user: str
        :param host: the server to connect to
        :type host: str
        :param remotepath: path on the remote server
        :type remotepath: str
        :param localpath: path on the local server (if None use the remotepath
            basename)
        :type localpath: str | None

        :return: (output content, error content, exit status)
        :rtype: (str, str, int)
        """
        if localpath is None:
            localpath = os.path.basename(remotepath)
        return scp(user=user, host=host, remotepath=remotepath,
                   localpath=localpath, method='get')

    def scp_put(user, host,
                localpath, remotepath=None):
        """Copy a local file to the host as remotepath.

        :param user: user login to authenticate as
        :type user: str
        :param host: the server to connect to
        :type host: str
        :param localpath: path on the local server to copy to the host
        :type localpath: str
        :param remotepath: path on the remote serve (if None use the remotepath
            basename)
        :type remotepath: str | None

        :return: (output content, error content, exit status)
        :rtype: (str, str, int)
        """
        if remotepath is None:
            remotepath = os.path.basename(localpath)
        return scp(user=user, host=host, remotepath=remotepath,
                   localpath=localpath, method='put')

except ImportError:

    def ssh_exec(user, host, cmd, timeout=None):
        """Execute a command on the SSH server.

        :param user: user login to authenticate as
        :type user: str
        :param host: the server to connect to
        :type host: str
        :param cmd: the command to execute
        :type cmd: str
        :param timeout: seconds to wait before raising socket.timeout
        :type timeout: int | None

        :return: (output content, error content, exit status)
        :rtype: (str, str, int)
        """
        ssh = Run(['ssh', '-n', '-q',
                   '-o', 'StrictHostKeyChecking=no',
                   '-o', 'PasswordAuthentication=no',
                   '-l', user, host, cmd], set_sigpipe=False,
                  timeout=timeout)
        return (ssh.out, ssh.err, ssh.status)

    def scp_get(user, host, remotepath, localpath=None):
        """Copy a remote file from host to the local host as localpath.

        :param user: user login to authenticate as
        :type user: str
        :param host: the server to connect to
        :type host: str
        :param remotepath: path on the remote server
        :type remotepath: str
        :param localpath: path on the local server (if None use the remotepath
            basename)
        :type localpath: str | None

        :return: (output content, error content, exit status)
        :rtype: (str, str, int)
        """
        if localpath is None:
            localpath = os.path.basename(remotepath)
        localpath = unixpath(localpath)
        remotepath = unixpath(remotepath)
        p = Run(['scp', '-B', '%s@%s:%s' % (user, host, remotepath),
                 localpath])
        return (localpath, p.err, p.status)

    def scp_put(user, host, localpath, remotepath=None):
        """Copy a local file to the host as remotepath.

        :param user: user login to authenticate as
        :type user: str
        :param host: the server to connect to
        :type host: str
        :param localpath: path on the local server to copy to the host
        :type localpath: str
        :param remotepath: path on the remote serve (if None use the remotepath
            basename)
        :type remotepath: str | None

        :return: (output content, error content, exit status)
        :rtype: (str, str, int)
        """
        if remotepath is None:
            remotepath = os.path.basename(localpath)
        p = Run(['scp', '-B', unixpath(localpath),
                 '%s@%s:%s' % (user, host, unixpath(remotepath))])
        return (remotepath, p.err, p.status)


class ProxyServer(object):
    """Proxy server using PySocks module."""

    def __init__(self):
        self.is_set = False
        self.server_url = None

    def activate(self, server_url):
        """Set proxy server using PySocks module.

        :param server_url: the proxy server url, e.g. socks5://host:8080
        :type server_url: str

        :raise ValueError: when the URL scheme is not supported

        Note that this is not meant to be used in production
        """
        if self.is_set:
            return None
        self.server_url = server_url
        self.is_set = True

        import socks
        import socket
        import urlparse

        url = urlparse.urlparse(server_url)

        if url.scheme == 'socks5':
            scheme = socks.SOCKS5
        elif url.scheme == 'socks4':
            scheme = socks.SOCKS4
        elif url.scheme == 'http':
            scheme = socks.HTTP
        else:
            raise ValueError(
                "Unsupported proxy scheme '{}'".format(url.scheme))

        socks.set_default_proxy(scheme, url.hostname, url.port)
        socket.socket = socks.socksocket

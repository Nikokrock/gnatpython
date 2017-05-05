############################################################################
#                                                                          #
#                              EX.PY                                       #
#                                                                          #
#           Copyright (C) 2008 - 2014 Ada Core Technologies, Inc.          #
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

"""Subprocesses management.

This package provides a single class called run which ease spawn of
processes in blocking or non blocking mode and redirection of its
stdout, stderr and stdin
"""

from subprocess import Popen, STDOUT, PIPE
from gnatpython.stringutils import quote_arg

import errno
import logging
import os
import sys
import time
import re
import itertools

BUF_SIZE = 128

logger = logging.getLogger('gnatpython.ex')

# Special logger used for command line logging.
# This allow user to filter easily the command lines log from the rest
cmdlogger = logging.getLogger('gnatpython.ex.cmdline')


def subprocess_setup():
    """Reset SIGPIPE handler.

    Python installs a SIGPIPE handler by default. This is usually not
    what non-Python subprocesses expect.
    """
    # Set sigpipe only when set_sigpipe is True
    # This should fix HC16-020 and could be activated by default
    import signal
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)


def command_line_image(cmds):
    """Return a string image of the given command(s).

    :param cmds: Same as the cmds parameter in the Run.__init__ method.
    :type: list[str] | list[list[str]]

    :rtype: str

    This method also handles quoting as defined for POSIX shells.
    This means that arguments containing special characters
    (such as a simple space, or a backslash, for instance),
    are properly quoted.  This makes it possible to execute
    the same command by copy/pasting the image in a shell
    prompt.

    The result is expected to be a string that can be sent verbatim
    to a shell for execution.
    """
    if isinstance(cmds[0], basestring):
        # Turn the simple command into a special case of
        # the multiple-commands case.  This will allow us
        # to treat both cases the same way.
        cmds = (cmds, )
    return ' | '.join((' '.join((quote_arg(arg) for arg in cmd))
                       for cmd in cmds))


def enable_commands_handler(filename, mode='a'):
    """Add a handler that log all commands launched with Run in a file.

    :param filename: path to log the commands
    :type filename: str
    :param mode: mode used to open the file (default is 'a')
    :type mode: str
    """
    class CmdFilter(logging.Filter):
        """Keep only gnatpython.ex.cmdline records."""

        def filter(self, record):
            if record.name != 'gnatpython.ex.cmdline':
                return 0
            else:
                return 1

    # Here we don't attach the handler directly to the gnatpython.ex.cmdline
    # logger. Indeed in class like gnatpython.main.Main we do attach handlers
    # to the root logger. In that case only the handlers attached to root
    # logger are called.
    rootlog = logging.getLogger()
    fh = logging.FileHandler(filename, mode=mode)
    fh.addFilter(CmdFilter())
    fh.setLevel(logging.DEBUG)
    rootlog.addHandler(fh)


class Run(object):
    """Class to handle processes.

    ATTRIBUTES
      cmds: The ``cmds`` argument passed to the __init__ method
        (a command line passed in a list, or a list of command lines passed as
        a list of list).
      status: The exit status.  As the exit status is only meaningful after
        the process has exited, its initial value is None.  When a problem
        running the command is detected and a process does not get
        created, its value gets set to the special value 127.
      out: process standard output  (if instanciated with output = PIPE)
      err: same as out but for standard error
      pid: PID.  Set to -1 if the command failed to run.
    """

    def __init__(self, cmds, cwd=None, output=PIPE,
                 error=STDOUT, input=None, bg=False, timeout=None, env=None,
                 set_sigpipe=True, parse_shebang=False, ignore_environ=True,
                 python_executable=sys.executable):
        """Spawn a process.

        :param cmds: two possibilities:
            1) a command line: a tool name and its arguments, passed
            in a list. e.g. ['ls', '-a', '.']
            2) a list of command lines (as defined in (1)): the
            different commands will be piped. This means that
            [['ps', '-a'], ['grep', 'vxsim']] will be equivalent to
            the system command line 'ps -a | grep vxsim'.
        :type cmds: list[str] | list[list[str]]
        :param cwd: directory in which the process should be executed (string
            or None). If None then current directory is used
        :type cwd: str | None
        :param output: can be PIPE (default), a filename string, a fd on an
            already opened file, a python file object or None (for stdout).
        :type output: int | str | file | None
        :param error: same as output or STDOUT, which indicates that the
            stderr data from the applications should be captured into the same
            file handle as for stdout.
        :type error: int | str | file | None
        :param input: same as output
        :type input: int | str | file | None
        :param bg: if True then run in background
        :type bg: bool
        :param timeout: limit execution time (in seconds), None means
            unlimited
        :type timeout: int | None
        :param env: dictionary for environment variables (e.g. os.environ)
        :type env: dict
        :param set_sigpipe: reset SIGPIPE handler to default value
        :type set_sigpipe: bool
        :param parse_shebang: take the #! interpreter line into account
        :type parse_shebang: bool
        :param ignore_environ: Applies only when env parameter is not None.
            When set to True (the default), the only environment variables
            passed to the program are the ones provided by the env parameter.
            Otherwise, the environment passed to the program consists of the
            environment variables currently defined (os.environ) augmented by
            the ones provided in env.
        :type ignore_environ: bool
        :param python_executable: name or path to the python executable
        :type python_executable: str

        :raise OSError: when trying to execute a non-existent file.

        If you specify a filename for output or stderr then file content is
        reseted (equiv. to > in shell). If you prepend the filename with '+'
        then the file will be opened in append mode (equiv. to >> in shell)
        If you prepend the input with '|', then the content of input string
        will be used for process stdin.
        """
        def add_interpreter_command(cmd_line):
            """Add the interpreter defined in the #! line to cmd_line.

            If the #! line cannot be parsed, just return the cmd_line
            unchanged

            If the interpreter command line contains /usr/bin/env python it
            will be replaced by the value of python_executable

            On windows, /usr/bin/env will be ignored to avoid a dependency on
            cygwin
            """
            if not parse_shebang:
                # nothing to do
                return cmd_line
            prog = which(cmd_line[0], default=None)
            if prog is None:
                # Not found. Do not modify the command line
                return cmd_line

            with open(prog) as f:
                header = f.read()[0:2]
                if header != "#!":
                    # Unknown header
                    return cmd_line
                # Header found, get the interpreter command in the first line
                f.seek(0)
                line = f.readline()
                interpreter_cmds = [l.strip() for l in
                                    line[line.find('!') + 1:].split()]
                # Pass the program path to the interpreter
                if len(cmd_line) > 1:
                    cmd_line = [prog] + list(cmd_line[1:])
                else:
                    cmd_line = [prog]

                # If the interpreter is '/usr/bin/env python', use
                # python_executable instead to keep the same python executable
                if interpreter_cmds[0:2] == ['/usr/bin/env', 'python']:
                    if len(interpreter_cmds) > 2:
                        return [python_executable] + interpreter_cmds[
                            2:] + cmd_line
                    else:
                        return [python_executable] + cmd_line
                elif sys.platform == 'win32':
                    if interpreter_cmds[0] == '/usr/bin/env':
                        return interpreter_cmds[1:] + cmd_line
                    elif interpreter_cmds[0] in ('/bin/bash', '/bin/sh') and \
                            'SHELL' in os.environ:
                        return [os.environ['SHELL']] + cmd_line
                return interpreter_cmds + cmd_line

        # First resolve output, error and input
        self.input_file = File(input, 'r')
        self.output_file = File(output, 'w')
        self.error_file = File(error, 'w')

        self.status = None
        self.out = ''
        self.err = ''
        self.cmds = []

        if env is not None and not ignore_environ:
            # ignore_environ is False, so get a copy of the current
            # environment and update it with the env dictionnary.
            tmp = os.environ.copy()
            tmp.update(env)
            env = tmp

        rlimit_args = []
        if timeout is not None:
            # Import gnatpython.fileutils just now to avoid a circular
            # dependency
            from gnatpython.fileutils import get_rlimit
            rlimit = get_rlimit()
            assert rlimit, 'rlimit not found'
            rlimit_args = [rlimit, '%d' % timeout]

        try:
            if isinstance(cmds[0], basestring):
                self.cmds = rlimit_args + list(add_interpreter_command(cmds))
            else:
                self.cmds = [add_interpreter_command(c) for c in cmds]
                self.cmds[0] = rlimit_args + list(self.cmds[0])

            cmdlogger.debug('Run: cd %s; %s' % (
                cwd if cwd is not None else os.getcwd(),
                self.command_line_image()))

            if isinstance(cmds[0], basestring):
                popen_args = {
                    'stdin': self.input_file.fd,
                    'stdout': self.output_file.fd,
                    'stderr': self.error_file.fd,
                    'cwd': cwd,
                    'env': env,
                    'universal_newlines': True}

                if sys.platform != 'win32' and set_sigpipe:
                    # preexec_fn is no supported on windows
                    popen_args['preexec_fn'] = subprocess_setup

                self.internal = Popen(self.cmds, **popen_args)

            else:
                runs = []
                for index, cmd in enumerate(self.cmds):
                    if index == 0:
                        stdin = self.input_file.fd
                    else:
                        stdin = runs[index - 1].stdout

                    # When connecting two processes using a Pipe don't use
                    # universal_newlines mode. Indeed commands transmitting
                    # binary data between them will crash
                    # (ex: gzip -dc toto.txt | tar -xf -)
                    if index == len(self.cmds) - 1:
                        stdout = self.output_file.fd
                        txt_mode = True
                    else:
                        stdout = PIPE
                        txt_mode = False

                    popen_args = {
                        'stdin': stdin,
                        'stdout': stdout,
                        'stderr': self.error_file.fd,
                        'cwd': cwd,
                        'env': env,
                        'universal_newlines': txt_mode}

                    if sys.platform != 'win32' and set_sigpipe:
                        # preexec_fn is no supported on windows
                        popen_args['preexec_fn'] = subprocess_setup

                    runs.append(Popen(cmd, **popen_args))
                    self.internal = runs[-1]

        except Exception as e:
            self.__error(e, self.cmds)
            raise

        self.pid = self.internal.pid

        if not bg:
            self.wait()

    def command_line_image(self):
        """Get shell command line image of the spawned command(s).

        :rtype: str

        This just a convenient wrapper around the function of the same
        name.
        """
        return command_line_image(self.cmds)

    def _close_files(self):
        """Internal procedure."""
        self.output_file.close()
        self.error_file.close()
        self.input_file.close()

    def __error(self, error, cmds):
        """Set pid to -1 and status to 127 before closing files."""
        self.pid = -1
        self.status = 127
        self._close_files()
        logger.error(error)

        def not_found(path):
            """Raise OSError."""
            logger.error("%s not found" % path)
            raise OSError(errno.ENOENT,
                          'No such file or directory, %s not found' % path)

        # Try to send an helpful message if one of the executable has not
        # been found.
        if isinstance(cmds[0], basestring):
            if which(cmds[0], default=None) is None:
                not_found(cmds[0])
        else:
            for cmd in cmds:
                if which(cmd[0], default=None) is None:
                    not_found(cmd[0])

    def wait(self):
        """Wait until process ends and return its status."""
        if self.status == 127:
            return self.status

        self.status = None

        # If there is no pipe in the loop then just do a wait. Otherwise
        # in order to avoid blocked processes due to full pipes, use
        # communicate.
        if self.output_file.fd != PIPE and self.error_file.fd != PIPE and \
                self.input_file.fd != PIPE:
            self.status = self.internal.wait()
        else:
            tmp_input = None
            if self.input_file.fd == PIPE:
                tmp_input = self.input_file.get_command()

            (self.out, self.err) = self.internal.communicate(tmp_input)
            self.status = self.internal.returncode

        self._close_files()
        return self.status

    def poll(self):
        """Check the process status and set self.status if available.

        This method checks whether the underlying process has exited
        or not. If it hasn't, then it just returns None immediately.
        Otherwise, it stores the process' exit code in self.status
        and then returns it.

        :return: None if the process is still alive; otherwise, returns
          the process exit status.
        :rtype: int | None
        """
        if self.status == 127:
            # Special value indicating that we failed to run the command,
            # so there is nothing to poll.  Just return that as the exit
            # code.
            return self.status

        result = self.internal.poll()
        if result is not None:
            self.status = result
        return result

    def kill(self):
        """Kill the process."""
        self.internal.kill()

    def interrupt(self):
        """Send a Ctrl-C signal to the process. """
        import signal
        # On windows CTRL_C_EVENT is available and SIGINT is not;
        # and the other way around on other platforms.
        if 'CTRL_C_EVENT' in dir(signal):
            self.internal.send_signal(signal.CTRL_C_EVENT)
        else:
            self.internal.send_signal(signal.SIGINT)


class File(object):
    """Can be a PIPE, a file object."""

    def __init__(self, name, mode='r'):
        """Create a new File.

        PARAMETERS
          name: can be PIPE, STDOUT, a filename string, an opened fd, a python
            file object, or a command to pipe (if starts with |)
          mode: can be 'r' or 'w' if name starts with + the mode will be a+
        """
        assert mode in 'rw', 'Mode should be r or w'

        self.name = name
        self.to_close = False
        if isinstance(name, str) or isinstance(name, unicode):
            # can be a pipe or a filename
            if mode == 'r' and name.startswith('|'):
                self.fd = PIPE
            else:
                if mode == 'w':
                    if name.startswith('+'):
                        open_mode = 'a+'
                        name = name[1:]
                    else:
                        open_mode = 'w+'
                else:
                    open_mode = 'r'

                self.fd = open(name, open_mode)
                if open_mode == 'a+':
                    self.fd.seek(0, 2)
                self.to_close = True

        else:
            # this is a file descriptor
            self.fd = name

    def get_command(self):
        """Return the command to run to create the pipe."""
        if self.fd == PIPE:
            return self.name[1:]

    def close(self):
        """Close the file if needed."""
        if self.to_close:
            self.fd.close()


class WaitError(Exception):
    pass


def wait_for_processes(process_list, timeout):
    """Wait for several processes spawned with Run.

    :param process_list: a list of Run objects
    :type process_list: list[Run]
    :param timeout: a timeout in seconds. If 0 block until a process ends.
    :type timeout: int

    :return: None in case of timeout or the index in process Run corresponding
        to the first process that end
    :rtype: None | int
    """
    if len(process_list) == 0:
        return None

    if sys.platform == 'win32':
        import ctypes
        from ctypes.wintypes import HANDLE, DWORD
        from ctypes import byref

        plen = len(process_list)
        WAIT_OBJECT = 0x0
        WAIT_ABANDONED = 0x80
        WAIT_TIMEOUT = 0x102
        WAIT_FAILED = 0xFFFFFFFF
        INFINITE = DWORD(0xFFFFFFFF)

        # Compute timeout
        if timeout == 0:
            win_timeout = INFINITE
        else:
            win_timeout = DWORD(int(timeout * 1000))

        start = time.time()
        # Build the handler array c structure
        handle_arr = HANDLE * len(process_list)
        handles = handle_arr(*[int(p.internal._handle) for p in process_list])

        while True:
            result = ctypes.windll.kernel32.WaitForMultipleObjects(
                DWORD(plen),
                handles, 0,
                win_timeout)
            if (WAIT_OBJECT <= result < WAIT_OBJECT + plen) or \
                    (WAIT_ABANDONED <= result < WAIT_ABANDONED + plen):
                # One process has been signaled. Check we have an exit code
                if result >= WAIT_ABANDONED:
                    result -= WAIT_ABANDONED
                exit_code = DWORD()
                ctypes.windll.kernel32.GetExitCodeProcess(handles[result],
                                                          byref(exit_code))
                if exit_code == DWORD(259):
                    # Process is still active so loop
                    # Update windows timeout
                    if timeout == 0:
                        win_timeout = INFINITE
                    else:
                        remain_seconds = timeout - time.time() + start
                        if remain_seconds <= 0:
                            return None
                        else:
                            win_timeout = DWORD(int(remain_seconds * 1000))
                else:
                    # At the stage we need to set the process status and close
                    # related handles. Indeed we will not be able to use the
                    # wait method afterwards and retrieve it.
                    # status has type c_ulong, we need to return its int value
                    process_list[result].status = int(exit_code.value)
                    process_list[result]._close_files()
                    return result
            elif result == WAIT_TIMEOUT:
                return None
            elif result == WAIT_FAILED:
                raise WaitError
    else:
        start = time.time()
        remain_seconds = timeout
        result = None

        wait3_option = os.WNOHANG
        if timeout == 0:
            wait3_option = 0

        while remain_seconds >= 0.0 or timeout == 0:

            pid, exit_status, resource_usage = os.wait3(wait3_option)
            if (pid, exit_status) != (0, 0):
                # We have a result
                result = [(index, p) for index, p in
                          enumerate(process_list) if p.pid == pid]
                if len(result) > 0:
                    # At the stage we need to set the process status and close
                    # related handles. Indeed we will not be able to use the
                    # wait method afterwards and retrieve it.
                    process_list[result[0][0]].status = exit_status
                    process_list[result[0][0]]._close_files()
                    return result[0][0]
            time.sleep(1.0)
            remain_seconds = timeout - time.time() + start
        return None


def is_running(pid):
    """Check whether a process with the given pid is running.

    :param pid: an integer (e.g the value of Run().pid)
    :type pid: int

    :rtype: bool
    """
    if sys.platform == 'win32':
        import ctypes
        import ctypes.wintypes
        h = ctypes.windll.kernel32.OpenProcess(1, 0, pid)
        try:
            if h == 0:
                return False

            # Pid exists for the handle, now check whether we can retrieve
            # the exit code
            exit_code = ctypes.wintypes.DWORD()
            if ctypes.windll.kernel32.GetExitCodeProcess(
                    h, ctypes.byref(exit_code)) == 0:
                # GetExitCodeProcess returns 0 when it could not get the value
                # of the exit code
                return True
            if exit_code.value == 259:
                # GetExitCodeProcess returns 259 is the process is still
                # running
                return True

            # Process not running
            return False
        finally:
            ctypes.windll.kernel32.CloseHandle(h)

    else:
        try:
            # We send a null signal to check the validity of pid
            os.kill(pid, 0)
        except OSError as e:
            # If the process is not found, errno will be set to ESRCH
            return e.errno != errno.ESRCH
        return True


def which(prog, paths=None, default=''):
    """Locate executable.

    :param prog: program to find
    :type prog: str
    :param paths: if not None then we use this value instead of PATH to look
        for the executable.
    :type paths: str | None
    :param default: default value to return if not found
    :type default: str | None | T

    :return: absolute path to the program on success, found by searching for an
      executable in the directories listed in the environment variable PATH
      or default value if not found
    :rtype: str | None | T
    """
    def is_exe(fpath):
        return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

    def possible_names(fpath):
        names = [fpath]
        if sys.platform == 'win32':
            names.extend([fpath + ext for ext in
                          os.environ.get('PATHEXT', '').split(';')])
        return names

    fpath, fname = os.path.split(prog)
    if fpath:
        # Full path given, check if executable
        for progname in possible_names(prog):
            if is_exe(progname):
                return progname
    else:
        # Check for all directories listed in $PATH
        if paths is None:
            paths = os.environ["PATH"]

        for pathdir in paths.split(os.pathsep):
            exe_file = os.path.join(pathdir, prog)
            for progname in possible_names(exe_file):
                if is_exe(progname):
                    return progname

    # Not found.
    return default


def get_rlimit():
    """Return rlimit path."""
    def get_path(relative_path):
        """Search for binary in directory parent.

        :param relative_path: the binary relative path
        :type relative_path: str

        :return: the path or empty string if not found
        :rtype: str
        """
        start_dir = os.path.join(os.path.dirname(__file__))

        # if current file equals to the already tested one, we stop
        previous_dir = ''
        while os.path.realpath(start_dir) != os.path.realpath(previous_dir):
            previous_dir = start_dir
            start_dir = os.path.join(start_dir, os.pardir)
            if not os.path.exists(start_dir):
                return ""
            if os.path.exists(os.path.join(start_dir, relative_path)):
                return os.path.join(start_dir, relative_path)

        return which(os.path.basename(relative_path), default='')

    if sys.platform == 'win32':
        return get_path(os.path.join(
            'Scripts', 'rlimit.exe'))
    else:
        return get_path(os.path.join('bin', 'rlimit'))


def kill_processes_with_handle(path):
    """Kill processes with a handle on the selected directory.

    Note: this works only on windows

    :param path: path
    :type path: str
    :return: the output of launched commands (can be used for logging
        purposes)
    :rtype: str
    """
    if sys.platform == 'win32':
        path = re.sub('^[a-zA-Z]:(.*)', r'\1', path).replace('/', '\\')
        mod_dir = os.path.dirname(__file__)
        handle_path = os.path.abspath(
            os.path.join(mod_dir, 'internal', 'data', 'libexec',
                         'x86-windows', 'handle.exe'))
        handle_p = Run([handle_path, '/AcceptEULA', '-a', '-u', path])
        msg = "handle_output:\n%s" % handle_p.out
        logger.debug(msg)
        process_list = set(re.findall(r'pid: *([0-9]+) *', handle_p.out))
        if process_list:
            taskkill_p = Run(['taskkill.exe', '/F'] +
                             list(itertools.chain.from_iterable(
                                 [['/PID', '%s' % k] for k in process_list])),
                             error=STDOUT)
            logger.debug("taskkill output:\n%s", taskkill_p.out)
            msg += "taskkill output:\n%s" % taskkill_p.out
        return msg
    else:
        return ''

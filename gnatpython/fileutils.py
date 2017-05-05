############################################################################
#                                                                          #
#                            FILEUTILS.PY                                  #
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

"""Operations on files and directories.

All this features are already present in python but they are available
in different modules with different interfaces. Here the interface of each
function tries to be as close as possible to the Unix shell commands.

This module also avoid common pitfalls on Windows (new rm implementation,
unixpath function...)
"""

from gnatpython.ex import Run, PIPE, which, get_rlimit
from gnatpython.env import Env
from gnatpython.logging_util import highlight
from gnatpython.logging_util import COLOR_GREEN, COLOR_RED, COLOR_CYAN

from difflib import SequenceMatcher, unified_diff
from collections import namedtuple

import hashlib
import collections
import fnmatch
import glob
import logging
import os
import stat
import re
import shutil
import socket
import sys
import tempfile
import itertools

logger = logging.getLogger('gnatpython.fileutils')

# Check whether ln is supported on this platform
# If ln is not supported, use shutil.copy2 instead
HAS_LN = hasattr(os, "link")

# When diff find a difference between two lines, we'll try to highlight
# the differences if diff_within_line is True. This is currently disabled
# because the output is not always more readable (the diff is too fine
# grained, we should probably do it at the word level)
diff_within_line = False


class FileUtilsError(Exception):
    """Exception raised by functions defined in this module."""

    def __init__(self, cmd, msg):
        Exception.__init__(self, cmd, msg)
        self.cmd = cmd
        self.msg = msg

    def __str__(self):
        return "%s: %s\n" % (self.cmd, self.msg)


def __compute_hash(path, kind):
    if not os.path.isfile(path):
        raise FileUtilsError(kind, 'cannot find %s' % path)

    with open(path, 'rb') as f:
        result = getattr(hashlib, kind)()
        while True:
            data = f.read(1024 * 1024)
            if not data:
                break
            result.update(data)
    return result.hexdigest()


def md5(path):
    """Compute md5 hexadecimal digest of a file.

    :param str path: path to a file

    :return: the hash of the file content
    :rtype: str
    :raise FileUtilsError: in case of error
    """
    return __compute_hash(path, 'md5')


def sha1(path):
    """Compute sha1 hexadecimal digest of a file.

    :param str path: path to a file

    :return: the hash of the file content
    :rtype: str
    :raise FileUtilsError: in case of error
    """
    return __compute_hash(path, 'sha1')


def cd(path):
    """Change current directory.

    :param str path: directory name

    :raise FileUtilsError: in case of error
    """
    try:
        os.chdir(path)
    except Exception as e:
        logger.error(e)
        raise FileUtilsError('cd', "can't chdir to %s\n" % path), None, \
            sys.exc_traceback


def cp(source, target, copy_attrs=True, recursive=False,
       preserve_symlinks=False):
    """Copy files.

    :param str source: a glob pattern
    :param str target: target file or directory. If the source resolves as
        several files then target should be a directory
    :param bool copy_attrs: If True, also copy all the file attributes such as
        mode, timestamps, ownership, etc.
    :param bool recursive: If True, recursive copy. This also preserves
        attributes; if copy_attrs is False, a warning is emitted.
    :param bool preserve_symlinks: if True symlinks are recreated in the
        destination folder
    :raise FileUtilsError: if an error occurs
    """
    switches = ''
    if copy_attrs:
        switches += ' -p'
    if recursive:
        switches += ' -r'
    logger.debug('cp %s %s->%s' % (switches, source, target))

    if recursive and not copy_attrs:
        logger.warning('recursive copy always preserves file attributes')

    # Compute file list and number of file to copy
    file_list = ls(source, enable_logging=False)
    file_number = len(file_list)

    if file_number == 0:
        # If there is no source files raise an error
        raise FileUtilsError('cp', "can't find files matching '%s'" % source)
    elif file_number > 1:
        # If we have more than one file to copy then check that target is a
        # directory
        if not os.path.isdir(target):
            raise FileUtilsError('cp', 'target should be a directory')

    for f in file_list:
        try:
            if os.path.isdir(target):
                f_dest = os.path.join(target, os.path.basename(f))
            else:
                f_dest = target

            if recursive and os.path.isdir(f):
                shutil.copytree(f, f_dest, symlinks=preserve_symlinks)
            elif preserve_symlinks and os.path.islink(f):
                linkto = os.readlink(f)
                os.symlink(linkto, f_dest)
            elif copy_attrs:
                shutil.copy2(f, f_dest)
            else:
                shutil.copy(f, f_dest)
        except Exception as e:
            logger.error(e)
            raise FileUtilsError(
                'cp', 'error occurred while copying %s' % f), \
                None, sys.exc_traceback


def unixpath(path):
    r"""Convert path to Unix/Cygwin format.

    :param str path: path string to convert

    :return: the converted path
    :rtype: str
    :raise FileUtilsError: in case of error

    On Unix systems this function is identity. On Win32 systems it removes
    drive letter information and replace \\ by /.
    """
    if path and sys.platform == 'win32':
        # Cygpath is not available so just replace \ by / and remove drive
        # information. This should work in most cases
        result = path.replace('\\', '/')
        m = re.match('[a-zA-Z]:(.*)', result)
        if m is not None:
            result = m.group(1)
        return result
    else:
        return path


def ln(source, target):
    """Create a hard link.

    :param str source: a filename
    :param str target: the target filename
    :raise FileUtilsError: in case of error
    """
    try:
        if HAS_LN:
            os.link(source, target)
        else:
            shutil.copy2(source, target)
    except Exception as e:
        logger.error(e)
        raise FileUtilsError(
            'ln', 'can not link %s to %s' % (source, target)), \
            None, sys.exc_traceback


def df(path, full=False):
    """Disk space available on the filesystem containing the given path.

    :param str path: a path
    :param bool full: if True return full disk information otherwise only
        space left.

    :rtype: int | collections.namedtuple
    :return: either space left in Mo or a :py:func:`collections.namedtuple`
        with ``total``, ``used`` and ``free`` attributes. Each attribute is
        an int representing Mo.
    """
    _ntuple_diskusage = collections.namedtuple(
        'usage', 'total used free')
    if Env().host.os.name.lower() == 'windows':
        import ctypes
        path = ctypes.c_wchar_p(path)
        GetDiskFreeSpaceEx = ctypes.WINFUNCTYPE(
            ctypes.c_int, ctypes.c_wchar_p,
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint64))
        GetDiskFreeSpaceEx = GetDiskFreeSpaceEx(
            ('GetDiskFreeSpaceExW', ctypes.windll.kernel32), (
                (1, 'path'),
                (2, 'freeuserspace'),
                (2, 'totalspace'),
                (2, 'freespace'),))

        def GetDiskFreeSpaceEx_errcheck(result, func, args):
            if not result:
                raise ctypes.WinError()
            return (args[1].value, args[2].value, args[3].value)
        GetDiskFreeSpaceEx.errcheck = GetDiskFreeSpaceEx_errcheck
        _, total, free = GetDiskFreeSpaceEx(path)
        used = total - free
    else:
        # f_frsize = fundamental filesystem block size
        # f_bsize = preferred file system block size
        # The use of f_frsize seems to give more accurate results.
        st = os.statvfs(path)
        free = (st.f_bavail * st.f_frsize)
        total = (st.f_blocks * st.f_frsize)
        used = ((st.f_blocks - st.f_bfree) * st.f_frsize)
    if full:
        return _ntuple_diskusage(
            total / (1024 * 1024),
            used / (1024 * 1024),
            free / (1024 * 1024))
    return free / (1024 * 1024)


def colored_unified_diff(a, b, fromfile='', tofile='',
                         fromfiledate='', tofiledate='', n=3, lineterm='\n',
                         onequal=None, onreplaceA=None, onreplaceB=None):
    """Colored diff.

    :param a: see :py:func:`difflib.unified_diff`
    :param b: see :py:func:`difflib.unified_diff`
    :param fromfile: see :py:func:`difflib.unified_diff`
    :param tofile: see :py:func:`difflib.unified_diff`
    :param fromfiledate: see :py:func:`difflib.unified_diff`
    :param tofiledate: see :py:func:`difflib.unified_diff`
    :param n: see :py:func:`difflib.unified_diff`
    :param lineterm: see :py:func:`difflib.unified_diff`
    :param onequal: callback called whenever a substring of a match a
        subtring of b. The callback should return the string to be
        displayed. If None no change is performed on the substring.
    :type onequal: (str) -> str
    :param onreplaceA: when a substring in a is replaced by a substring in b,
        onreplaceA is called with the substring from a and should return
        the replacement for that string.
    :type onreplaceA: (str) -> str
    :param onreplaceB: same as onreplaceb except the callback is called with
        the substring from b.
    :type onreplaceB: (str) -> str

    :return: the delta between a and b
    :rtype: generator
    """
    if not Env().main_options or not Env().main_options.enable_color:
        for line in unified_diff(
                a, b, fromfile, tofile,
                fromfiledate, tofiledate, n, lineterm):
            yield line
    else:
        # Code inspired from difflib.py
        minus = highlight('-', fg=COLOR_CYAN)
        plus = highlight('+', fg=COLOR_CYAN)

        def id_f(x):
            return x

        if not onequal:
            onequal = id_f
        if not onreplaceA:
            onreplaceA = id_f
        if not onreplaceB:
            onreplaceB = id_f

        started = False
        for group in SequenceMatcher(None, a, b).get_grouped_opcodes(n):
            if not started:
                yield highlight('--- %s %s%s', fg=COLOR_CYAN) \
                    % (fromfile, fromfiledate, lineterm)
                yield highlight('+++ %s %s%s', fg=COLOR_CYAN) \
                    % (tofile, tofiledate, lineterm)
                started = True

            i1, i2, j1, j2 = (group[0][1], group[-1][2],
                              group[0][3], group[-1][4])
            yield highlight(
                "@@ -%d,%d +%d,%d @@%s" % (i1 + 1, i2 - i1,
                                           j1 + 1, j2 - j1, lineterm),
                fg=COLOR_CYAN)

            for tag, i1, i2, j1, j2 in group:
                if tag == 'equal':
                    for line in a[i1:i2]:
                        yield ' ' + onequal(line)
                    continue

                elif tag == 'replace':
                    line1 = onreplaceA(("\n" + minus).join(a[i1:i2]))
                    line2 = onreplaceB(("\n" + plus).join(b[j1:j2]))

                    if diff_within_line:
                        # Do a diff within the lines to highlight the difs

                        d = list(SequenceMatcher(
                            None, line1, line2).get_grouped_opcodes(
                            len(line1) + len(line2)))
                        result1 = ""
                        result2 = ""
                        for c in d:
                            for t, e1, e2, f1, f2 in c:
                                if t == 'equal':
                                    result1 += "".join(onequal(line1[e1:e2]))
                                    result2 += "".join(onequal(line2[f1:f2]))
                                elif t == 'replace':
                                    result1 += highlight(
                                        "".join(line1[e1:e2]), COLOR_RED)
                                    result2 += highlight(
                                        "".join(line2[f1:f2]), COLOR_GREEN)
                                elif t == 'delete':
                                    result1 += highlight(
                                        "".join(line1[e1:e2]), COLOR_RED)
                                elif t == 'insert':
                                    result2 += highlight(
                                        "".join(line2[f1:f2]), COLOR_GREEN)
                        yield minus + result1
                        yield plus + result2
                    else:
                        yield minus + highlight(line1, COLOR_RED)
                        yield plus + highlight(line2, COLOR_GREEN)

                elif tag == 'delete':
                    for line in a[i1:i2]:
                        if diff_within_line:
                            yield minus + line
                        else:
                            yield minus + highlight(line, COLOR_RED)
                elif tag == 'insert':
                    for line in b[j1:j2]:
                        if diff_within_line:
                            yield plus + line
                        else:
                            yield plus + highlight(line, COLOR_GREEN)


def diff(item1, item2, ignore=None, item1name="expected", item2name="output",
         ignore_white_chars=True):
    """Compute diff between two files or list of strings.

    :param item1: a filename or a list of strings
    :type item1: str | list[str]
    :param item2: a filename or a list of strings
    :type item2: str | list[str]
    :param ignore: all lines matching this pattern in both files are
        ignored during comparison. If set to None, all lines are considered.
    :type ignore: str | None
    :param str item1name: name to display for item1 in the diff
    :param str item2name: name to display for item2 in the diff
    :param bool ignore_white_chars: if True (default) then empty lines,
        trailing and leading white chars on each line are ignored

    :return: A diff string. If the string is equal to '' it means that there
        is no difference
    :rtype: str
    :raise FileUtilsError: if an error occurs
    """
    tmp = [[], []]
    """:type: list[list[str]]"""

    # Read first item
    if isinstance(item1, list):
        tmp[0] = item1
    else:
        try:
            with open(item1, 'r') as f:
                tmp[0] = f.readlines()
        except IOError:
            tmp[0] = []

    # Do same thing for the second one
    if isinstance(item2, list):
        tmp[1] = item2
    else:
        try:
            with open(item2, 'r') as f:
                tmp[1] = f.readlines()
        except IOError:
            tmp[1] = []

    # Filter empty lines in both items and ignore white chars at beginning
    # and ending of lines
    for k in (0, 1):
        if ignore_white_chars:
            tmp[k] = ["%s\n" % line.strip() for line in tmp[k]
                      if line.strip()]
        else:
            # Even if white spaces are not ignored we should ensure at
            # that we don't depend on platform specific newline
            tmp[k] = ["%s\n" % line.rstrip('\r\n') for line in tmp[k]]

        # If we have a filter apply it now
        if ignore is not None:
            tmp[k] = [line for line in tmp[k]
                      if re.search(ignore, line) is None]

    diff_content = colored_unified_diff(
        tmp[0], tmp[1], n=1, fromfile=item1name, tofile=item2name)
    return ''.join(diff_content)


def ls(path, enable_logging=True):
    """List files.

    :param path: glob pattern or glob pattern list
    :type path: list[string] | string
    :param enable_logging: if set to False calls to logging functions
        are disabled
    :type enable_logging: bool

    :return: a list of filenames (sorted alphabetically).
    :rtype: list[string]

    This function do not raise an error if no file matching the glob pattern
    is encountered. The only consequence is that an empty list is returned.
    """
    if isinstance(path, basestring):
        path = (path, )

    if enable_logging:
        logger.debug('ls %s' % str(path))

    return list(sorted(itertools.chain.from_iterable(
        (glob.glob(p) for p in path))))


def mkdir(path, mode=0755):
    """Create a directory.

    :param str path: path to create. If intermediate directories do not exist
        the procedure create them
    :param int mode: default is 0755

    :raise FileUtilsError: if an error occurs

    This function behaves quite like mkdir -p command shell. So if the
    directory already exist no error is raised.
    """
    if os.path.isdir(path):
        return
    else:
        logger.debug('mkdir %s (mode=%s)', path, oct(mode))
        try:
            os.makedirs(path, mode)
        except Exception as e:
            if os.path.isdir(path):
                # Take care of cases where in parallel execution environment
                # the directory is created after the initial test on its
                # existence and the call to makedirs
                return
            logger.error(e)
            raise FileUtilsError('mkdir', "can't create %s" % path), \
                None, sys.exc_traceback


def mv(source, target):
    """Move files.

    :param source: a glob pattern
    :type source: str | list[str]
    :param target: target file or directory. If the source resolves as
        several files then target should be a directory
    :type target: str

    :raise FileUtilsError: if an error occurs
    """
    logger.debug('mv %s->%s' % (source, target))

    try:
        # Compute file list and number of file to copy
        file_list = ls(source)
        assert file_list, "can't find files matching '%s'" % source

        if len(file_list) == 1:
            f = file_list[0]
            if os.path.isdir(f) and os.path.isdir(target):
                shutil.move(f, os.path.join(target, os.path.basename(f)))
            else:
                shutil.move(f, target)
        else:
            # If we have more than one file to move then check that target is a
            # directory
            assert os.path.isdir(target), 'target should be a directory'

            for f in file_list:
                shutil.move(f, os.path.join(target, os.path.basename(f)))
    except Exception as e:
        logger.error(e)
        raise FileUtilsError('mv', e), None, sys.exc_traceback


def __safe_unlink_func():
    """Provide a safe unlink function on windows.

    Note that all this is done to ensure that rm is working fine on Windows 7
    and 2008R2. Indeed very often, deletion will fail with access denied
    error. The typical scenario is when you spawn an executable and try to
    delete it just afterward.
    """
    if Env().build.os.name == 'windows':
        from gnatpython._winlow import safe_unlink

        def py_safe_unlink(f):
            # We need to pass to the C function an absolute path in Unicode and
            # with the "Native" convention (i.e: the leading \??\)
            if safe_unlink(u"\\??\\%s" % os.path.abspath(f)) != 0:
                raise OSError

        return (py_safe_unlink, py_safe_unlink)
    else:
        return (os.remove, os.rmdir)


safe_remove, safe_rmdir = __safe_unlink_func()


def force_remove_file(path):
    """Force file removing, changing permissions if first attempt failed.

    :param str path: path of the file to remove
    """
    try:
        safe_remove(path)
    except OSError:
        # The permission of the parent directory does not allow us to remove
        # the file, temporary get write permission in the directory
        dir_path = os.path.dirname(path)
        orig_mode = os.stat(dir_path).st_mode
        chmod('u+w', dir_path)

        # ??? It seems that this might be needed on windows
        os.chmod(path, 0777)
        safe_remove(path)
        os.chmod(dir_path, orig_mode)


def rm(path, recursive=False, glob=True):
    """Remove files.

    :param path: a glob pattern, or a list of glob patterns
    :type path: str | list[str]
    :param bool recursive: if True do a recursive deletion. Default is False
    :param bool glob: if True globbing pattern expansion is used

    :raise FileUtilsError: if an error occurs

    Note that the function will not raise an error is there are no file to
    delete.
    """
    logger.debug('rm %s' % str(path))

    # We transform the list into a set in order to remove duplicate files in
    # the list
    if glob:
        file_list = set(ls(path))
    else:
        if isinstance(path, basestring):
            file_list = {path}
        else:
            file_list = set(path)

    def onerror(func, path, exc_info):
        """When shutil.rmtree fail, try again to delete the file."""
        if func == os.remove:
            # Cannot remove path, call chmod and redo an attempt

            # This function is only called when deleting a file inside a
            # directory to remove, it is safe to change the parent directory
            # permission since the parent directory will also be removed.
            os.chmod(os.path.dirname(path), 0777)

            # ??? It seems that this might be needed on windows
            os.chmod(path, 0777)
            safe_remove(path)
        elif func == os.rmdir:
            # Cannot remove path, call chmod and redo an attempt
            os.chmod(path, 0777)

            # Also change the parent directory permission if it will also
            # be removed.
            if recursive and path not in file_list:
                # If path not in the list of directories to remove it means
                # that we are already in a subdirectory.
                os.chmod(os.path.dirname(path), 0777)
            safe_rmdir(path)

    for f in file_list:
        try:
            # When calling rmtree or remove, ensure that the string that is
            # passed to this function is unicode on Windows. Otherwise,
            # the non-Unicode API will be used and so we won't be
            # able to remove these files. On Unix don't do that as
            # we got some strange unicode "ascii codec" errors
            # (need some further investigation at some point)
            if Env().build.os.name == 'windows':
                f = unicode(f)

            # Note: shutil.rmtree requires its argument to be an actual
            # directory, not a symbolic link to a directory.

            if recursive and os.path.isdir(f) and not os.path.islink(f):
                shutil.rmtree(f, onerror=onerror)
            else:
                force_remove_file(f)

        except Exception as e:
            logger.error(e)
            raise FileUtilsError(
                'rm', 'error occurred while removing %s' % f), None, \
                sys.exc_traceback


VCS_IGNORE_LIST = ('RCS', 'SCCS', 'CVS', 'CVS.adm', 'RCSLOG',
                   '.svn', '.git', '.hg', '.bzr', '.cvsignore',
                   '.gitignore', '.gitattributes', '.gitmodules',
                   '.gitreview', '.mailmap', '.idea')


def sync_tree(source, target, ignore=None,
              file_list=None,
              delete=True,
              preserve_timestamps=True,
              delete_ignore=False):
    """Synchronize the files and directories between two directories.

    :param str source: the directory from where the files and directories
        need to be copied
    :param str target: the target directory
    :param ignore: glob pattern or list of files or directories to ignore,
        if the name starts with `/` then only the path is taken into
        account from the root of the source (or target) directory.
        If the ignore value contains a glob pattern, it is taken in account
        only if it doesn't contain a /, since for now the filtering
        is not segmented by '/'.
    :type ignore: None | str | iterable[str]
    :param file_list: list of files to synchronize, if empty synchronize all
        files. Note that if file in the list is a directory then the complete
        content of that directory is included. Note also that ignore list
        takes precedence other file_list.
    :type file_list: None | list[str]
    :param bool delete: if True, remove files from target if they do not exist
        in source
    :param bool preserve_timestamps: if True preserve original timestamps.
        If False updated files get their timestamps set to current time.
    :param bool delete_ignore: if True files that are explicitely ignored
        are deleted. Note delete should be set to True in that case.
    """
    # Some structure used when walking the trees to be synched
    FilesInfo = namedtuple('FilesInfo', ['rel_path', 'source', 'target'])
    FileInfo = namedtuple('FileInfo', ['path', 'stat'])

    # normalize the list of file to synchronize
    norm_file_list = None
    if file_list is not None:
        norm_file_list = [f.replace('\\', '/').rstrip('/') for f in file_list]

    # normalize ignore patterns
    if ignore is not None:
        norm_ignore_list = [p.replace('\\', '/') for p in ignore]
        abs_ignore_patterns = [p for p in norm_ignore_list
                               if p.startswith('/')]
        rel_ignore_patterns = [p for p in norm_ignore_list
                               if not p.startswith('/')]

    def is_in_ignore_list(p):
        """Check if a file should be ignored.

        :param p: path relative to source directory (note it starts with a /)
        :type p: str

        :return: True if in the list of file to include
        :rtype: bool
        """
        if ignore is None:
            return False

        return any((f for f in abs_ignore_patterns if
                    p == f or p.startswith(f + '/'))) or \
            any((f for f in rel_ignore_patterns if
                 p[1:] == f or p.endswith('/' + f))) or \
            any((f for f in norm_ignore_list if
                 '/' not in f and fnmatch.fnmatch(os.path.basename(p), f)))

    def is_in_file_list(p):
        """Check if a file should be included.

        :param p: path relative to source directory (note it starts with a /)
        :type p: str

        :return: True if in the list of file to include
        :rtype: bool
        """
        return file_list is None or \
            any([f for f in norm_file_list if
                 f == p[1:] or
                 p.startswith('/' + f + '/') or
                 f.startswith(p[1:] + '/')])

    def isdir(fi):
        """Check if a file is a directory.

        :param fi: a FileInfo namedtuple
        :type fi: FileInfo

        :return: True if fi is a directory
        :rtype: bool
        """
        return fi.stat is not None and stat.S_ISDIR(fi.stat.st_mode)

    def islink(fi):
        """Check if a file is a link.

        :param fi: a FileInfo namedtuple
        :type fi: FileInfo

        :return: True if fi is a symbolic link
        :rtype: bool
        """
        return fi.stat is not None and stat.S_ISLNK(fi.stat.st_mode)

    def isfile(fi):
        """Check if a file is a regular file.

        :param fi: a FileInfo namedtuple
        :type fi: FileInfo

        :return: True if fi is a regular file
        :rtype: bool
        """
        return fi.stat is not None and stat.S_ISREG(fi.stat.st_mode)

    def cmp_files(src, dst):
        """Fast compare two files.

        :type src: FileInfo
        :type dst: FileInfo
        """
        bufsize = 8 * 1024
        with open(src.path, 'rb') as fp1, open(dst.path, 'rb') as fp2:
            while True:
                b1 = fp1.read(bufsize)
                b2 = fp2.read(bufsize)
                if b1 != b2:
                    return False

                if len(b1) < bufsize:
                    return True

    def need_update(src, dst):
        """Check if dst file should updated.

        :param src: the source FileInfo object
        :type src: FileInfo
        :param dst: the target FileInfo object
        :type dst: FileInfo

        :return: True if we should update dst
        :rtype: bool
        """
        # when not preserving timestamps we cannot rely on the timestamps to
        # check if a file is up-to-date. In that case do a full content
        # comparison as last check.
        return dst.stat is None or \
            stat.S_IFMT(src.stat.st_mode) != stat.S_IFMT(dst.stat.st_mode) or \
            (preserve_timestamps and
             abs(src.stat.st_mtime - dst.stat.st_mtime) > 0.001) or \
            src.stat.st_size != dst.stat.st_size or \
            (not preserve_timestamps and
             isfile(src) and not cmp_files(src, dst))

    def copystat(src, dst):
        """Update attribute of dst file with src attributes.

        :param src: the source FileInfo object
        :type src: FileInfo
        :param dst: the target FileInfo object
        :type dst: FileInfo
        """
        if islink(src):
            mode = stat.S_IMODE(src.stat.st_mode)
            if hasattr(os, 'lchmod'):
                os.lchmod(dst.path, mode)

            if hasattr(os, 'lchflags') and hasattr(src.stat, 'st_flags'):
                try:
                    os.lchflags(dst.path, src.stat.st_flags)
                except OSError as why:
                    import errno
                    if (not hasattr(errno, 'EOPNOTSUPP') or
                            why.errno != errno.EOPNOTSUPP):
                        raise
        else:
            mode = stat.S_IMODE(src.stat.st_mode)
            if hasattr(os, 'utime'):
                if preserve_timestamps:
                    os.utime(dst.path, (src.stat.st_atime, src.stat.st_mtime))
                else:
                    os.utime(dst.path, None)
            if hasattr(os, 'chmod'):
                os.chmod(dst.path, mode)
            if hasattr(os, 'chflags') and hasattr(src.stat, 'st_flags'):
                try:
                    os.chflags(dst.path, src.stat.st_flags)
                except OSError as why:
                    import errno
                    if (not hasattr(errno, 'EOPNOTSUPP') or
                            why.errno != errno.EOPNOTSUPP):
                        raise

    def safe_copy(src, dst):
        """Copy src file into dst preserving all attributes.

        :param src: the source FileInfo object
        :type src: FileInfo
        :param dst: the target FileInfo object
        :type dst: FileInfo
        """
        if islink(src):
            linkto = os.readlink(src.path)
            if not islink(dst) or os.readlink(dst.path) != linkto:
                if dst.stat is not None:
                    rm(dst.path, recursive=True, glob=False)
                os.symlink(linkto, dst.path)
            copystat(src, dst)
        else:
            if isdir(dst):
                rm(dst.path, recursive=True, glob=False)
            elif islink(dst):
                rm(dst.path, recursive=False, glob=False)
            try:
                with open(src.path, 'rb') as fsrc:
                    with open(dst.path, 'wb') as fdst:
                        shutil.copyfileobj(fsrc, fdst)
            except IOError:
                rm(dst.path, glob=False)
                with open(src.path, 'rb') as fsrc:
                    with open(dst.path, 'wb') as fdst:
                        shutil.copyfileobj(fsrc, fdst)
            copystat(src, dst)

    def safe_mkdir(dst):
        """Create a directory modifying parent directory permissions if needed.

        :param dst: directory to create
        :type dst: FileInfo
        """
        try:
            os.makedirs(dst.path)
        except OSError:
            # in case of error to change parent directory
            # permissions. The permissions will be then
            # set correctly at the end of rsync.
            chmod('a+wx', os.path.dirname(dst.path))
            os.makedirs(dst.path)

    def walk(source_top, target_top, entry=None):
        """Walk through source and target file trees.

        :param source_top: path to source tree
        :type source_top: str
        :param target_top: path to target tree
        :type target_top: str
        :param entry: a FilesInfo object (used internally for the recursion)
        :type entry: FilesInfo

        :return: an iterator that iterate other the relevant FilesInfo object
        :rtype: collections.iterable(FilesInfo)
        """
        if entry is None:
            target_stat = None
            if os.path.exists(target_top):
                target_stat = os.lstat(target_top)

            entry = FilesInfo('',
                              FileInfo(source_top, os.lstat(source_top)),
                              FileInfo(target_top, target_stat))
            yield entry
        try:
            source_names = set(os.listdir(entry.source.path))
        except Exception:
            # Don't crash in case a source directory cannot be read
            return

        target_names = set()
        if isdir(entry.target):
            try:
                target_names = set(os.listdir(entry.target.path))
            except Exception:
                target_names = set()

        all_names = source_names | target_names

        result = []
        for name in all_names:
            rel_path = "%s/%s" % (entry.rel_path, name)

            source_full_path = os.path.join(entry.source.path, name)
            target_full_path = os.path.join(entry.target.path, name)
            source_stat = None
            target_stat = None

            if name in source_names:
                source_stat = os.lstat(source_full_path)

            source_file = FileInfo(source_full_path, source_stat)

            if name in target_names:
                target_stat = os.lstat(target_full_path)

            target_file = FileInfo(target_full_path, target_stat)
            result.append(FilesInfo(rel_path, source_file, target_file))

        for el in result:
            if is_in_ignore_list(el.rel_path):
                logger.debug('ignore %s' % el.rel_path)
                if delete_ignore:
                    yield FilesInfo(el.rel_path,
                                    FileInfo(el.source.path, None),
                                    el.target)
            elif is_in_file_list(el.rel_path):
                yield el
                if isdir(el.source):
                    for x in walk(source_top, target_top, el):
                        yield x
            else:
                yield FilesInfo(el.rel_path,
                                FileInfo(el.source.path, None),
                                el.target)

    source_top = os.path.normpath(source).rstrip(os.path.sep)
    target_top = os.path.normpath(target).rstrip(os.path.sep)
    copystat_dir_list = []

    logger.debug('sync_tree %s -> %s [delete=%s, preserve_stmp=%s]' %
                 (source, target, delete, preserve_timestamps))

    if not os.path.exists(source):
        raise FileUtilsError('sync_tree', '%s does not exist' % source)

    # Keep track of deleted and updated files
    deleted_list = []
    updated_list = []

    for f in walk(source_top, target_top):
        if f.source.stat is None and f.target.stat is not None:
            # Entry that exist only in the target file tree. Check if we
            # should delete it
            if delete:
                rm(f.target.path, recursive=True, glob=False)
                deleted_list.append(f.target.path)
        else:
            # At this stage we have an element to synchronize in
            # the source tree.
            if need_update(f.source, f.target):
                if isfile(f.source) or islink(f.source):
                    safe_copy(f.source, f.target)
                    updated_list.append(f.target.path)
                elif isdir(f.source):
                    if isfile(f.target) or islink(f.target):
                        rm(f.target.path, glob=False)
                    if not isdir(f.target):
                        safe_mkdir(f.target)
                        updated_list.append(f.target.path)
                    copystat_dir_list.append((f.source, f.target))
                else:
                    continue

    # Adjust directory permissions once all files have been copied
    for d in copystat_dir_list:
        copystat(d[0], d[1])

    return (updated_list, deleted_list)


def rsync(source, target, files=None,
          protected_files=None, delete=False, options=None):
    """Wrapper around rsync utility.

    :param source: source directory to sync. Note that it will be always
        considered as the 'content' of source (i.e source is passed with a
        trailing '/')
    :type source: str
    :param target: target destination directory
    :type target: str
    :param files: if None all files from source are synchronized. Otherwise it
        should be a list of string that are patterns (rsync format) to select
        which files should be transferred.
    :type files: None | list[str]
    :param protected_files: type is the same as files parameters. Files that
        are matching these pattern will be protected in the destination
        directory
    :type protected_files: None | list[str]
      delete: If true, files that don't exist in source will deleted in target.

    :raise FileUtilsError: in case of error
    """
    rsync_args = ['rsync', '-a']
    rsync_filename = ''

    if delete:
        rsync_args.append('--delete-excluded')

    if files is not None or protected_files is not None:
        rsync_filename = os.path.join(Env().tmp_dir,
                                      'rsync.list.%d' % os.getpid())

        f = open(rsync_filename, 'w')

        if files is not None:
            for filename in files:
                # add filename to the list
                f.write('+ /' + filename + '\n')

                # add also all its parent directories
                while filename != '':
                    (filename, _) = os.path.split(filename)
                    if filename != '':
                        f.write('+ /' + filename + '/\n')

        if protected_files is not None:
            for filename in protected_files:
                f.write('P /' + filename + '\n')

        # exclude files that did not match the patterns
        f.write('- *\n')
        f.close()

        # Update rsync arguments
        rsync_args.append('--filter=. ' + rsync_filename)

    if options is not None:
        for opt in options:
            rsync_args.append(opt)

    # Note: source and target must be in Unix format. Windows style for path
    # will not work.
    rsync_args.append(unixpath(source) + '/')
    rsync_args.append(unixpath(target))
    p = Run(rsync_args)

    # Clean temp file if necessary
    if files is not None or protected_files is not None:
        rm(rsync_filename)

    if p.status != 0:
        raise FileUtilsError(
            'rsync', 'rsync failed with status %d\n%s\n%s' %
            (p.status, " ".join(rsync_args), p.out)), \
            None, sys.exc_traceback


def touch(filename):
    """Update file access and modification times.

    :param str filename: file to update

    If the file does not exist it is created.
    """
    if os.path.exists(filename):
        os.utime(filename, None)
    else:
        with open(filename, 'w+'):
            pass


def split_file(filename, split_line=None, keys=None, ignore_errors=False,
               host=None):
    """Split a file into a list or a dictionary.

    :param filename: file to read
    :type filename: str
    :param split_line: if None then the file is split by line. Otherwise lines
        are also subdivided using split_line as separator
    :type split_line: None | str
    :param keys: this is a list of string. If split_line is None then this
        parameter is ignored. Otherwise, each line is subdivided using
        split_line parameter and each field associated with a key to compose a
        dictionary. If the number of keys is not sufficient additional fields
        are ignored. If the number of keys is superior to the number of fields
        then last keys will have '' as value.
    :type keys: None | list[str]
    :param host: if not None, this is a remote file
    :type host: None | str

    :return: If split_line if None then each element is a string (i.e a line
      of the file), otherwise each element is list of string (i.e a list split
      using split_line separator) or a dictionary (if keys are passed). If
      an I/O error occurs and ignore_errors is set to True then an empty list
      is returned.
    :rtype: list[str] | list[list[str]] | list[dict]
    """
    result = []
    try:
        if host is None:
            fd = open(filename, 'r')
        else:
            fd = Run(['ssh', host, 'cat', filename]).out.splitlines()

        for line in fd:
            line = line.rstrip()
            if split_line is not None and line != '':
                tmp = line.split(split_line)
                if keys is None:
                    line = tmp
                else:
                    line = {}
                    tmp_last = len(tmp) - 1
                    for index, k in enumerate(keys):
                        if tmp_last < index:
                            line[k] = ''
                        else:
                            line[k] = tmp[index]
                result.append(line)
            elif split_line is None:
                result.append(line)
        if host is None:
            fd.close()
    except IOError as e:
        if not ignore_errors:
            logger.error(e)
            raise FileUtilsError(
                'split_file', 'cannot open file %s' % filename), \
                None, sys.exc_traceback
        else:
            result = []

    return result


def echo_to_file(filename, content, append=False):
    """Output content into a file.

    This function is useful when writing few content to a file for which we
    don't want to keep a file descriptor opened . In other cases, it's more
    efficient to open a file and use the regular python I/O functions.

    :param filename: file to write into
    :type filename: str
    :param content: string to be written
    :type content: str | list[str]
    :param append: if True append to the file, otherwise overwrite.
    :type append: bool
    """
    with open(filename, 'a+' if append else 'w+') as fd:
        if append:
            fd.seek(0, 2)

        if isinstance(content, list):
            for l in content:
                fd.write(l + '\n')
        else:
            fd.write(content)


def __select_archiving_tool(filename, unpack=True,
                            tar='tar',
                            force_extension=None,
                            require_wilcard=False):
    """Internal function used by create_archive and unpack_archive.

    :param filename: the name of the archive to extract the extension
    :type filename: str
    :param unpack: to know if we are called by unpack_archive or create_archive
    :type unpack: bool
    :param tar: path to the tar binary to use ('tar' by default)
    :type tar: str
    :param force_extension: specify the archive extension if not in the
        filename
    :type force_extension: str | None
    :param require_wilcard: whether wildcard will be used, in that case we try
        to use the python libraries directly to avoid portability issues
    :type require_wilcard: bool

    :return: a tuple (ext, True if we should use python libraries else False)
    :rtype: (str, bool)
    """
    def has_python_lib_support(ext):
        """Return True if python library can be used.

        :type ext: str
        :rtype: bool
        """
        try:
            if ext == 'zip':
                # We need to check for zlib presence to be sure that we can
                # compress otherwise zipfile will be used a an archiver
                # (no compression)
                import zlib
                return bool(zlib.__name__)  # Avoid unused warning
            else:
                import tarfile
                return bool(tarfile.__name__)  # Avoid unused warning
        except ImportError:
            return False

    def has_binary_tools(ext):
        """Return True if binary tools ar found else False.

        :type ext: str
        :rtype: bool
        """
        if not which(tar):
            return False
        elif ext == 'tar.gz' and not which('gzip'):
            return False
        elif ext == 'tar.bz2' and not which(
                'bunzip' if unpack else 'bzip2'):
            return False
        elif ext == 'zip' and not which(
                'unzip' if unpack else 'zip'):
            return False
        return True

    # Check extension
    if filename.endswith('.tar.gz') or filename.endswith('.tgz') or (
            force_extension is not None and
            force_extension in ['.tar.gz', '.tgz']):
        ext = 'tar.gz'
    elif filename.endswith('.tar.bz2') or (
            force_extension is not None and
            force_extension == '.tar.bz2'):
        ext = 'tar.bz2'
    elif filename.endswith('.tar') or (
            force_extension is not None and
            force_extension == '.tar'):
        ext = 'tar'
    elif filename.endswith('.zip') or (
            force_extension is not None and
            force_extension == '.zip'):
        ext = 'zip'
    else:
        raise FileUtilsError('unpack_archive',
                             'unknown format "%s"' % filename)

    if Env().host.os.name == 'windows' or require_wilcard:
        # On windows, do not spawn tar/zip often provided by cygwin but calls
        # tarfile/zipfile python implementation.  If wildcards (* or ?) are
        # used in selected_files, to avoid portability issue, use directly the
        # python library if possible
        impls = (has_python_lib_support, has_binary_tools)
    else:
        impls = (has_binary_tools, has_python_lib_support)

    for imp in impls:
        if imp(ext):
            return (ext, imp == has_python_lib_support)

    raise FileUtilsError(
        'unpack_archive',
        'no python module and no binary tools found'), \
        None, sys.exc_traceback


def unpack_archive(filename,
                   dest,
                   selected_files=None,
                   remove_root_dir=False,
                   tar='tar',
                   unpack_cmd=None,
                   force_extension=None,
                   delete=False,
                   ignore=None,
                   preserve_timestamps=True):
    """Unpack an archive file (.tgz, .tar.gz, .tar or .zip).

    :param filename: archive to unpack
    :type filename: str
    :param dest: destination directory (should exist)
    :type dest: str
    :param selected_files: list of files to unpack (partial extraction). If
        None all files are unpacked
    :type selected_files: collections.iterable[str] | None
    :param remove_root_dir: if True then the root dir of the archive is
        suppressed.
        if set to 'auto' then the root dir of the archive is suppressed only
        if it is possible. If not do not raise an exception in that case and
        fallback on the other method.
    :type remove_root_dir: bool
    :param tar: path/to/tar binary (else use 'tar')
    :type tar: str
    :param unpack_cmd: command to run to unpack the archive, if None use
        default methods or raise FileUtilsError if archive format is not
        supported. If unpack_cmd is not None, then remove_root_dir is ignored.
        The unpack_cmd must raise FileUtilsError in case of failure.
    :type unpack_cmd: callable | None
    :param force_extension: specify the archive extension if not in the
        filename. If filename has no extension and force_extension is None
        unpack_archive will fail.
    :type force_extension: str | None
    :param delete: if True and remove_root_dir is also True, remove files
        from dest if they do not exist in the archive
    :type delete: bool
    :param ignore: a list of files/folders to keep when synchronizing with
        the final destination directory.
    :type ignore: list[str] | None
    :param preserve_timestamps: if False and remove_root_dir is True, and the
        target directory exists, ensure that updated files get their timestamp
        updated to current time.
    :type preserve_timestamps: bool

    :raise FileUtilsError: in case of error

    cygpath (win32) utilities might be needed when using remove_root_dir option
    """
    logger.debug('unpack %s in %s' % (filename, dest))
    # First do some checks such as archive existence or destination directory
    # existence.
    if not os.path.isfile(filename):
        raise FileUtilsError('unpack_archive', 'cannot find %s' % filename)

    if not os.path.isdir(dest):
        raise FileUtilsError('unpack_archive',
                             'dest dir %s does not exist' % dest)

    if selected_files is None:
        selected_files = []

    # We need to resolve to an absolute path as the extraction related
    # processes will be run in the destination directory
    filename = os.path.abspath(filename)

    if unpack_cmd is not None:
        # Use user defined unpack command
        if not selected_files:
            return unpack_cmd(filename, dest)
        else:
            return unpack_cmd(filename, dest,
                              selected_files=selected_files)

    if [f for f in selected_files if '*' in f or '?' in f]:
        require_wilcard = True
    else:
        require_wilcard = False

    ext, use_python_lib = __select_archiving_tool(
        filename,
        unpack=True,
        tar=tar,
        force_extension=force_extension,
        require_wilcard=require_wilcard)

    # If remove_root_dir is set then extract to a temp directory first.
    # Otherwise extract directly to the final destination
    if remove_root_dir:
        tmp_dest = tempfile.mkdtemp(prefix='',
                                    dir=os.path.dirname(os.path.abspath(dest)))
    else:
        tmp_dest = dest

    try:
        if use_python_lib:
            if ext in ('tar', 'tar.bz2', 'tar.gz'):
                import tarfile
                try:
                    fd = tarfile.open(filename, mode='r')
                    # selected_files must be converted to tarfile members
                    if selected_files:
                        members = fd.getmembers()

                        def is_matched(members, pattern):
                            """Return a list of matched tarfile members.

                            :param members: TarInfo list
                            :type members: list[TarInfo]
                            :param pattern: string or regexp
                            :type pattern: str

                            :raise FileutilsError: if no member match the
                                pattern.

                            :return: a list of tarfile members
                            :rtype: list[TarInfo]
                            """
                            r = [mem for mem in members
                                 if fnmatch.fnmatch(mem.name, pattern)]
                            if not r:
                                raise FileUtilsError(
                                    'unpack_archive',
                                    'Cannot untar %s ' % pattern)
                            return r

                        selected_files = [f for l in selected_files
                                          for f in is_matched(members, l)]

                    # detect directories. This is not done by default
                    # For each directory, select all the tree
                    selected_dirnames = [
                        d.name for d in selected_files if d.isdir()]
                    for dname in selected_dirnames:
                        selected_files += [
                            fd.getmember(n) for n in fd.getnames()
                            if n.startswith(dname + '/')]

                except tarfile.TarError as e:
                    raise FileUtilsError(
                        'unpack_archive',
                        'Cannot untar %s (%s)' % (filename, e)), \
                        None, sys.exc_traceback

            else:
                import zipfile
                try:
                    fd = zipfile.ZipFile(filename, mode='r')
                except zipfile.BadZipfile as e:
                    raise FileUtilsError(
                        'unpack_archive',
                        'Cannot unzip %s (%s)' % (filename, e)), \
                        None, sys.exc_traceback

            fd.extractall(tmp_dest,
                          selected_files if selected_files else None)
            fd.close()

        else:
            # Spawn tar, gzip, bunzip2 or zip

            if ext == 'tar.gz':
                p = Run([['gzip', '-dc', filename],
                         [tar, '-xf', '-'] + list(selected_files)],
                        cwd=tmp_dest)
            elif ext == 'tar.bz2':
                p = Run([['bunzip2', '-dc', filename],
                         [tar, '-xf', '-'] + list(selected_files)],
                        cwd=tmp_dest)
            elif ext == 'tar':
                p = Run([tar, '-xf', filename] + list(selected_files),
                        cwd=tmp_dest)
            else:
                p = Run(['unzip', '-o', filename] + list(selected_files),
                        cwd=tmp_dest)

            if p.status != 0:
                # The extract command failed
                raise FileUtilsError('unpack_archive',
                                     'extraction of %s failed:\n%s' % (
                                         filename, p.out))

        if remove_root_dir:
            # First check that we have only one dir in our temp destination. If
            # not raise an error.
            file_list = ls(os.path.join(tmp_dest, '*'))
            if len(file_list) == 0:
                # Nothing to do...
                return
            if len(file_list) != 1:
                if remove_root_dir != 'auto':
                    raise FileUtilsError(
                        'unpack_archive',
                        'archive does not have a unique root dir')

                # We cannot remove root dir but remove_root_dir is set to
                # 'auto' so fallback on non remove_root_dir method
                if not os.listdir(dest):
                    mv(os.path.join(tmp_dest, '*'),
                       dest)
                else:
                    sync_tree(tmp_dest, dest, delete=delete,
                              ignore=ignore,
                              preserve_timestamps=preserve_timestamps)
            else:
                root_dir = file_list[0]

                # Now check if the destination directory is empty. If this is
                # the case a simple move will work, otherwise we need to do a
                # sync_tree (which cost more)

                if not os.listdir(dest):
                    mv([os.path.join(root_dir, f)
                        for f in os.listdir(root_dir)], dest)
                else:
                    sync_tree(root_dir, dest, delete=delete,
                              ignore=ignore,
                              preserve_timestamps=preserve_timestamps)

    finally:
        # Always remove the temp directory before exiting
        if remove_root_dir:
            rm(tmp_dest, True)


def create_archive(filename, from_dir, dest, tar='tar', force_extension=None,
                   from_dir_rename=None, no_root_dir=False):
    """Create an archive file (.tgz, .tar.gz, .tar or .zip).

    On Windows, if the python tarfile and zipfile modules are available, the
    python implementation is used to create the archive.  On others system,
    create_archive spawn tar, gzip or zip as it is twice faster that the python
    implementation. If the tar, gzip or zip binary is not found, the python
    implementation is used.

    :param filename: archive to create
    :type filename: str
    :param from_dir: directory to pack (full path)
    :type from_dir: str
    :param dest: destination directory (should exist)
    :type dest: str
    :param tar: path/to/tar binary (else use 'tar')
    :type tar: str
    :param force_extension: specify the archive extension if not in the
        filename. If filename has no extension and force_extension is None
        create_archive will fail.
    :type force_extension: str | None
    :param from_dir_rename: name of root directory in the archive.
    :type from_dir_rename: str | None
    :param no_root_dir: create archive without the root dir (zip only)
    :type no_root_dir: bool

    :raise FileUtilsError: if an error occurs
    """
    # Check extension
    from_dir = from_dir.rstrip('/')
    filepath = os.path.abspath(os.path.join(dest, filename))

    ext, use_python_lib = __select_archiving_tool(
        filename,
        unpack=False,
        force_extension=force_extension)

    if use_python_lib:
        if from_dir_rename is None:
            from_dir_rename = os.path.basename(from_dir)

        if ext == 'zip':
            import zipfile
            archive = zipfile.ZipFile(filepath, 'w', zipfile.ZIP_DEFLATED)
            for root, _, files in os.walk(from_dir):
                relative_root = os.path.relpath(os.path.abspath(root),
                                                os.path.abspath(from_dir))
                for f in files:
                    zip_file_path = os.path.join(
                        from_dir_rename, relative_root, f)
                    if no_root_dir:
                        zip_file_path = os.path.join(relative_root, f)
                    archive.write(os.path.join(root, f),
                                  zip_file_path)
            archive.close()
            return
        else:
            import tarfile
            if ext == 'tar':
                tar_format = 'w'
            elif ext == 'tar.gz':
                tar_format = 'w:gz'
            else:
                raise FileUtilsError('create_archive',
                                     'unsupported ext %s' % ext)
            archive = tarfile.open(filepath, tar_format)
            archive.add(from_dir, from_dir_rename, recursive=True)
            archive.close()
    else:
        command_dir = os.path.dirname(from_dir)
        base_archive_dir = os.path.basename(from_dir)
        abs_archive_dir = from_dir

        if from_dir_rename is not None:
            base_archive_dir = from_dir_rename
            abs_archive_dir = os.path.join(command_dir, base_archive_dir)

            if os.path.isdir(abs_archive_dir):
                raise FileUtilsError('create_archive',
                                     '%s should not exist' % abs_archive_dir)
            mv(from_dir, abs_archive_dir)

        try:
            if ext == 'tar.gz':
                p = Run([[tar, 'cf', '-', base_archive_dir],
                        ['gzip', '-9']],
                        output=filepath, error=PIPE, cwd=command_dir)
            elif ext == 'tar':
                p = Run([tar, 'cf', '-', base_archive_dir],
                        output=filepath,
                        error=PIPE,
                        cwd=command_dir)
            elif ext == 'zip':
                if no_root_dir:
                    p = Run(['zip', '-r9', '-q', filepath,
                             '.', '-i', '*'],
                            cwd=os.path.join(command_dir, base_archive_dir))
                else:
                    p = Run(['zip', '-r9', '-q', filepath, base_archive_dir],
                            cwd=command_dir)
            else:
                raise FileUtilsError('create_archive',
                                     'unsupported ext %s' % ext)
            if p.status != 0:
                raise FileUtilsError('create_archive',
                                     'creation of %s failed:\n%s' % (
                                         filename, p.out))
        finally:
            if from_dir_rename is not None:
                mv(abs_archive_dir, from_dir)


def find(root, pattern=None, include_dirs=False,
         include_files=True, follow_symlinks=False):
    """Find files or directory recursively.

    :param root: directory from which the research start
    :type root: str
    :param pattern: glob pattern that files or directories should match in
        order to be included in the final result
    :type pattern: str | None
    :param include_dirs: if True include directories
    :type include_dirs: bool
    :param include_files: if True include regular files
    :type include_files: bool
    :param follow_symlinks: if True include symbolic links
    :type follow_symlinks: bool

    :return: a list of files
    :rtype: list[str]
    """
    result = []
    for root, dirs, files in os.walk(root, followlinks=follow_symlinks):
        root = root.replace('\\', '/')
        if include_files:
            for f in files:
                if pattern is None or fnmatch.fnmatch(f, pattern):
                    result.append(root + '/' + f)
        if include_dirs:
            for d in dirs:
                if pattern is None or fnmatch.fnmatch(d, pattern):
                    result.append(root + '/' + d)
    return result


def split_mountpoint(path):
    """Split a given path between it's mount point and the remaining part.

    :param path: a filesystem path
    :type path: str

    :return: two elements: the first one is the mount point and second one
        is the remaining part of the path or None
    :rtype: (str, str | None)

    :raise FileUtilsError: if the path does not exist
    """
    # If the path is invalid raise an exception
    if not os.path.exists(path):
        raise FileUtilsError('split_mountpoint',
                             "path does not exist: %s" % path)

    # First get the absolute path
    path = os.path.realpath(os.path.abspath(path))
    queue = []

    # Iterate through the path until we found the mount point
    while not os.path.ismount(path):
        queue = [os.path.basename(path)] + queue
        path = os.path.dirname(path)
    if queue:
        return (path, os.path.join(*queue))
    else:
        return (path, None)


def get_path_nfs_export(path):
    """Guess NFS related information for a given path.

    :param path: a string containing a valid path
    :type path: str

    :rtype: None | (str, str, str, str)
    :return: a length four tuple containing:
        (machine IP, machine name, export, path relative to the export). Note
        that the function is just making a guess. We cannot really ensure that
        the return export really exist. If the function canot guess the NFS
        export then None is returned.
    """
    def add_ip_info(machine, export, path):
        """Add ip information."""
        domain = '.' + e.host.domain if e.host.domain else ''

        try:
            result = (socket.gethostbyname(machine),
                      machine + domain,
                      export,
                      path)
        except socket.gaierror:
            # if gethostbyname fails assume that the ip
            # address is localhost
            result = ('127.0.0.1',
                      machine + domain,
                      export,
                      path)
        return result

    # First find the mount point
    e = Env()
    mountfiles = []
    if e.host.os.name.lower() != 'windows':
        # Don't try to look into unix specific files or to use 'mount' command
        # on Windows platform (if the later exists it will be a cygwin tool
        # that is not useful in our case).
        mountfiles = ['/etc/mtab', '/etc/mnttab', '/proc/mounts', 'mount']

    mount_point, path = split_mountpoint(path)

    # Then read system imports
    for fname in mountfiles:

        # Extract necessary fields
        if fname == 'mount':
            # Either by parsing the output of the mount command
            mount_bin = which('mount')
            if not mount_bin:
                # /sbin is not always in the PATH
                if os.path.exists('/sbin/mount'):
                    mount_bin = '/sbin/mount'
                else:
                    # No mount program found !
                    raise FileUtilsError(
                        'get_path_nfs_export', 'Cannot find mount')
            p = Run([mount_bin])
            if p.status != 0:
                raise FileUtilsError(
                    'get_path_nfs_export', 'Error when calling mount')
            lines = p.out.splitlines()
            mount_index = 2

        elif os.path.exists(fname):
            # Or by reading a system file
            with open(fname, 'r') as f:
                lines = f.readlines()
            mount_index = 1
        else:
            continue

        for line in lines:
            fields = line.rstrip().split()
            if fields[mount_index] == mount_point:
                # We found a file system. It can either be a local
                # filesystem or on a remote machine.
                tmp = fields[0].split(':')
                if len(tmp) == 1:
                    # This is a local fs. Here the heuristic is to
                    # consider the export
                    return add_ip_info(e.host.machine, mount_point, path)
                elif len(tmp) == 2:
                    # Looks like 'nfs' import
                    return add_ip_info(tmp[0], tmp[1], path)
                else:
                    # What's that ?
                    return add_ip_info(e.host.machine, mount_point, path)

    if e.host.os.name.lower() == 'windows':
        tmp = path.split('\\')
        if len(tmp) > 1:
            return add_ip_info(e.host.machine, '/' + tmp[0], '/'.join(tmp[1:]))


def substitute_template(template, target, variables):
    """Create a file using a template and and a dictionnary.

    :param str template: path to the template
    :param str target: path in which to dump the result
    :param dict variables: dictionary that will be applied to the template
        content using the '%' Python operator
    """
    if not os.path.isfile(template):
        raise FileUtilsError('process_template',
                             'cannot find template %s' % template)
    with open(template) as f_template:
        with open(target, 'wb') as fd:
            fd.write(f_template.read() % variables)


def file_sub(pattern, repl, filename, count=0, flags=0):
    """Do substitution in a file.

    :param pattern: search pattern (see :py:func:`re.sub`)
    :type pattern: str
    :param repl: substitution pattern (see :py:func:`re.sub`)
    :type repl: str
    :param filename: file in which substitution should be done
    :type filename: str
    :param count: see :py:func:`re.sub`
    :type count: int
    :param flags: see :py:func:`re.sub`
    :type flags: int
    """
    with open(filename, 'rb') as fd:
        content = fd.read()
    content = re.sub(pattern, repl, content, count, flags)
    with open(filename, 'wb') as fd:
        fd.write(content)


def chmod(mode, path):
    """Chmod with interface similar to Unix tool.

    :param mode: should conform with posix specification for
        chmod utility (ex: +wx). See chmod man page for more information
    :type mode: str
    :param path: a filename, a glob or a list of glob patterns
    :type path: str | list[str]
    """
    # Developer note: for local variable names in this function
    # we try to use the words used in the opengroup specification
    # this way we can map easily between the implementation and
    # what is defined in the standard.
    filelist = set(ls(path))

    whos = {'u': stat.S_IRWXU,
            'g': stat.S_IRWXG,
            'o': stat.S_IRWXO}
    perms = {'r': stat.S_IROTH,
             'w': stat.S_IWOTH,
             'x': stat.S_IXOTH}

    for filename in filelist:

        current_mode = os.stat(filename).st_mode

        # Retrieve umask
        umask = os.umask(0)
        os.umask(umask)

        clauses = mode.split(',')

        for clause in clauses:
            match = re.search(r'([ugoa]+)([-\+=].*)', clause)
            if match is not None:
                wholist = match.group(1)
                actionlist = match.group(2)
            else:
                wholist = ''
                actionlist = clause

            actions = re.findall(r'(?:([-\+=])([ugo]|[rwx]*))',
                                 actionlist)
            assert ''.join(list(itertools.chain.from_iterable(actions))) == \
                actionlist

            for (op, permlist) in actions:
                if permlist == '' and op != '=':
                    continue
                else:
                    if permlist in ('u', 'g', 'o'):
                        action_mask = current_mode & whos[permlist]
                        if permlist == 'u':
                            action_mask >>= 6
                        elif permlist == 'g':
                            action_mask >>= 3
                    else:
                        action_mask = 0
                        for perm in permlist:
                            action_mask |= perms[perm]

                    if wholist == '':
                        action_mask = action_mask | \
                            action_mask << 3 | \
                            action_mask << 6
                        action_mask &= ~umask
                        apply_mask = stat.S_IRWXO | stat.S_IRWXU | stat.S_IRWXG
                    else:
                        if 'a' in wholist:
                            action_mask = action_mask | \
                                action_mask << 3 | \
                                action_mask << 6
                            apply_mask = stat.S_IRWXO | stat.S_IRWXU | \
                                stat.S_IRWXG
                        else:
                            final_action_mask = 0
                            apply_mask = 0
                            for who in wholist:
                                if who == 'u':
                                    final_action_mask |= action_mask << 6
                                    apply_mask |= stat.S_IRWXU
                                elif who == 'g':
                                    final_action_mask |= action_mask << 3
                                    apply_mask |= stat.S_IRWXG
                                else:
                                    final_action_mask |= action_mask
                                    apply_mask |= stat.S_IRWXO

                            action_mask = final_action_mask
                    if op == '-':
                        current_mode &= ~action_mask
                    elif op == '=':
                        current_mode = (current_mode & ~apply_mask) | \
                            action_mask
                    else:
                        current_mode = current_mode | action_mask

        logger.debug("chmod %s %s (new perm: %s)" %
                     (mode, filename, oct(current_mode)))
        os.chmod(filename, current_mode)


def patch(patch_file, working_dir, discarded_files=None, filtered_patch=None):
    """Apply a patch, ignoring changes in files matching discarded_files.

    :param patch_file: the file containing the patch to apply
    :type patch_file: str
    :param working_dir: the directory where to apply the patch
    :type working_dir: str
    :param discarded_files: list of files or glob patterns (or function taking
        a filename and returning a boolean - True if the file should be
        discarded)
    :type discarded_files: list[str] | (str) -> bool | None
    :param filtered_patch: name of the filtered patch. By default append
        '.filtered' to the patch_file name
    :type filtered_patch: str | None
    """
    def apply_patch(fname):
        """Run the patch command.

        :type fname: str
        :raise FileUtilsError: when the patch command fails
        """
        cmd = ['patch', '-p0', '-f']
        p = Run(cmd, cwd=working_dir, input=fname)
        if p.status != 0:
            raise FileUtilsError(
                'patch',
                'running %s < %s in %s failed with %s' % (
                    ' '.join(cmd), fname, working_dir, p.out))
        logger.debug(p.out)

    if discarded_files is None:
        apply_patch(patch_file)
        return

    if filtered_patch is None:
        filtered_patch = patch_file + '.filtered'

    files_to_patch = 0

    with open(patch_file, 'rb') as f, open(filtered_patch, 'wb') as fdout:

        line_buffer = ()
        # Can contains the previous line with its matched result

        discard = False  # whether the current patch line should be discarded

        for line in f:
            if line_buffer:
                # We got a patch start. Now check the next line
                m2 = re.search(r'^[\+-]{3} ([^ \n\t]+)', line)
                if m2 is not None:
                    discard = False
                    if callable(discarded_files):
                        for fn in (line_buffer[1].group(1), m2.group(1)):
                            if fn != '/dev/null' and discarded_files(fn):
                                logger.debug(
                                    'patch %s discarding %s' % (
                                        patch_file, fn))
                                discard = True
                                break
                    else:
                        for pattern in discarded_files:
                            for fn in (line_buffer[1].group(1), m2.group(1)):
                                if fn != '/dev/null' and fnmatch.fnmatch(
                                        fn, pattern):
                                    logger.debug(
                                        'patch %s discarding %s' % (
                                            patch_file, fn))
                                    discard = True
                                    break
                            if discard:
                                break
                    if not discard:
                        files_to_patch += 1
            else:
                # Find lines starting with '*** filename' (contextual diff) or
                # with '--- filename' (unified diff)
                m = re.search(r'^[\*-]{3} ([^ \t\n]+)', line)
                if m is not None:
                    # Ensure this is not a hunk start of the form
                    # '*** n,m ****' or '--- n,m ----'
                    if not re.search(r'[\*-]{4}$', line):
                        # We have a patch start. Get the next line that
                        # contains other possibility for the filename
                        line_buffer = (line, m)
                        continue

            # Empty the buffer
            if not discard:
                if line_buffer:
                    fdout.write(line_buffer[0])
                fdout.write(line)
            line_buffer = ()

    if files_to_patch:
        apply_patch(filtered_patch)
    else:
        logger.debug("All %s content has been discarded" % patch_file)


def max_path():
    """Return the maximum length for a path.

    :return: the maximum length
    :rtype: int
    """
    if sys.platform == 'win32':
        from ctypes.wintypes import MAX_PATH
        return MAX_PATH
    else:
        return os.pathconf('/', 'PC_PATH_MAX')


def get_filetree_state(path, ignore_hidden=True):
    """Compute a hash on a filetree to reflect its current state.

    :param path: root path of the file tree to be checked
    :type path: str
    :param ignore_hidden: if True (default) then files and directories
        tarting with a dot are ignored.
    :type ignore_hidden: bool
    :return: a hash as a string
    :rtype: str

    The function will not report changes in the hash if a file is modified
    and its attributes (size, modification time and mode) are not changed.
    This case is quite uncommon. By ignoring it we can compute efficiently a
    hash representing the state of the file tree without having to read the
    content of all files.
    """
    path = os.path.abspath(path)
    result = hashlib.sha1()
    if os.path.isdir(path):
        for root, dirs, files in os.walk(path):
            if ignore_hidden:
                ignore_dirs = []
                for index, name in enumerate(dirs):
                    if name.startswith('.'):
                        ignore_dirs.append(index)
                ignore_dirs.reverse()
                for index in ignore_dirs:
                    del dirs[index]

            for path in files:
                if ignore_hidden and path.startswith('.'):
                    continue

                full_path = os.path.join(root, path)
                path_stat = os.lstat(full_path)
                result.update('%s:%s:%s:%s' % (full_path,
                                               path_stat.st_mode,
                                               path_stat.st_size,
                                               path_stat.st_mtime))
    else:
        path_stat = os.lstat(path)
        result.update('%s:%s:%s:%s' % (path,
                                       path_stat.st_mode,
                                       path_stat.st_size,
                                       path_stat.st_mtime))
    return result.hexdigest()


if __name__ == "__main__":
    # Make pyflakes happy and display some information when executed directly
    print 'Python path:', which(os.path.basename(sys.executable))
    print 'rlimit path:', get_rlimit()

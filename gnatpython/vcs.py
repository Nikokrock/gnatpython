############################################################################
#                                                                          #
#                              VCS.PY                                      #
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

"""Version control management systems interface.

Currently this module provide a two classes called SVN and Git to
interact respectively with Subversion and Git repositories.
"""

from gnatpython.ex import Run, STDOUT, PIPE
from gnatpython.env import Env
from gnatpython.fileutils import which, rm, unixpath
from xml.dom import minidom

import logging
import os
import re
import sys

# Set the logger for this module
vcslogger = logging.getLogger('gnatpython.vcs')


# Exceptions used by Git and SVN classes.


class VCS_Error(Exception):
    pass


class SVN_Error(VCS_Error):
    pass


class Git_Error(VCS_Error):
    pass


class SVNBase(object):
    """Base implementation for Subversion support.

    Note that you should not use that class directly. use SVN class instead.
    Depending on your Python distribution, the class will use rather an
    implementation based on the pysvn library or an implementation that spawns
    the svn command.

    ATTRIBUTES
      url: root url of your checkout
      dest: root directory that contains the checkout
      use_externals: True if external links should be taken into account,
                     False if they should be ignored.
      force: if True then in case dest contains already things non related to
             the given url then cleanup of this directory will be performed.
             Otherwise a SVN_Error exception is raised in case of conflict
      rev: revision number. If not set head is assumed.
    """

    def __init__(self, url, dest, rev=None, use_externals=False, force=False):
        """SVNBase constructor.

        :type url: str
        :type dest: str
        :type rev: str | None
        :type use_externals: bool
        :type force: bool
        """
        self.url = url.rstrip('/')
        self.dest = dest
        self.use_externals = use_externals
        self.force = force
        self.rev = rev

        is_valid = self.is_valid()
        if not is_valid:
            if is_valid is not None:
                if not force:
                    # Directory is a svn working directory
                    self.error("destination is already a svn working dir on"
                               " different url")

                try:
                    # First try a subversion switch command
                    vcslogger.debug('switch %s to %s' % (self.dest, self.url))
                    self.switch()
                    # If successful then return.
                    return
                except SVN_Error:
                    pass

            if force:
                vcslogger.debug('cleanup dest directory: %s' % self.dest)
                rm(self.dest, recursive=True)

            vcslogger.debug('checkout %s@%s in %s' %
                            (self.url, self.rev, self.dest))
            self.checkout()
            self.update()

    @classmethod
    def error(cls, msg, traceback=None):
        """Log an error message and raise SVN_Error.

        :param msg: the message to be logged and passed to the exception
        :type msg: str
        """
        vcslogger.error(msg)
        if traceback is None:
            raise SVN_Error(msg)
        else:
            raise SVN_Error(msg), None, traceback

    def update(self, files=None):
        """Update a list of files or the repository.

        :param files: if None the complete repository is considered. Otherwise
            should be a list of path relative to the dest
        :type files: list[str] | None
        """
        vcslogger.debug('update of %s in %s' % (self.url, self.dest))
        if files is None:
            files = [self.dest]
        else:
            files = [self.dest + '/' + k for k in files]

        for f in files:
            self.update_file(f)

    def last_changed_rev(self):
        """Get the last change revision of the local checkout.

        :return: None if the information cannot be retrieved, an integer
            otherwise
        :rtype: int | None
        """
        result = self.log(limit=1)
        if len(result) > 0:
            return int(result[0]['revision'])
        return None

try:
    import pysvn

    class SVN(SVNBase):
        """Implementation of the SVN class using pysvn.

        See SVNBase for attributes documentation
        """

        def __init__(self, url, dest, rev=None, use_externals=False,
                     force=False):
            """See SVNBase.__init__.

            :type url: str
            :type dest: str
            :type rev: str | None
            :type use_externals: bool
            :type force: bool
            """
            self.client = pysvn.Client()
            self.client.exception_style = 1
            self.client.set_interactive(False)

            if rev is None:
                rev = pysvn.Revision(pysvn.opt_revision_kind.head)
            else:
                rev = pysvn.Revision(pysvn.opt_revision_kind.number, int(rev))

            SVNBase.__init__(self, url, dest, rev, use_externals, force)

        def switch(self):
            """Perform svn switch to the selected url."""
            try:
                self.client.switch(self.dest, self.url,
                                   revision=self.rev,
                                   depth=pysvn.depth.infinity,
                                   depth_is_sticky=True)
            except pysvn.ClientError as e:
                raise SVN_Error("error during switch: %s" % e.args[0]), \
                    None, sys.exc_traceback

        def checkout(self):
            """Perform svn checkout."""
            try:
                self.client.checkout(self.url, self.dest,
                                     revision=self.rev,
                                     depth=pysvn.depth.empty)
            except pysvn.ClientError as e:
                self.error("error during checkout: %s" % e.args[0],
                           traceback=sys.exc_traceback)

        def update_file(self, filename):
            """Update a file in the local checkout.

            :param filename: path relative to the root url that should be
                updated
            :type filename: str
            """
            try:
                self.client.update(filename, revision=self.rev,
                                   ignore_externals=not self.use_externals,
                                   depth=pysvn.depth.infinity,
                                   depth_is_sticky=True)
            except pysvn.ClientError as e:
                self.error("subversion update failure: %s" % e.args[0],
                           traceback=sys.exc_traceback)

        def is_valid(self):
            """Check if our current checkout is valid.

            :return: True if the current checkout is the expected directory,
              False if the current checkout is a subversion checkout with a
              different URL and None when the directory is not svn checkout
            :rtype: bool | None
            """
            try:
                if self.client.info(self.dest).url == self.url:
                    return True
                else:
                    return False
            except pysvn.ClientError:
                return None

        def log(self, limit=32):
            """Retrieve log entries.

            Only use the 'local' history.

            :param limit: maximum number of entries we want to retrieve
            :type limit: int

            :return: a list of dictionaries
            :rtype: list[dict]

            :raise SVN_Error: if case of unexpected failure
            """
            try:
                result = self.client.log(
                    self.dest,
                    revision_start=self.client.info(self.dest)['revision'],
                    limit=limit)
                for item in result:
                    item['revision'] = item['revision'].number

                return result
            except pysvn.ClientError as e:
                self.error("subversion log failure: %s" % e.args[0],
                           traceback=sys.exc_traceback)

        def diff(self, rev1=None, rev2=None):
            """Return the local changes in the checkout.

            :param rev1: start diff from this revision
            :type rev1: int
            :param rev2: stop diff at this revision
            :type rev1: int

            :return: the diff content
            :rtype: str
            """
            try:
                if rev1 and rev2:
                    result = self.client.diff(
                        Env().tmp_dir, self.dest,
                        pysvn.Revision(rev1), pysvn.Revision(rev2))
                else:
                    result = self.client.diff(Env().tmp_dir, self.dest)
                return result
            except pysvn.ClientError as e:
                self.error("subversion diff failure: %s" % e.args[0],
                           traceback=sys.exc_traceback)

except ImportError:

    class SVN(SVNBase):
        """Implementation of the SVN class using pysvn.

        See SVNBase for attributes documentation
        """

        def __init__(self, url, dest, rev=None, use_externals=False,
                     force=False):
            """See SVNBase.__init__."""
            self.ext_args = \
                ['--config-option=config:miscellany:use-commit-times=yes']

            if not use_externals:
                self.ext_args.append('--ignore-externals')

            self.rev_args = []
            if rev is not None:
                self.rev_args = ['-r', rev]

            SVNBase.__init__(self, url, unixpath(dest),
                             rev, use_externals, force)

        def is_valid(self):
            """Check if our current checkout is valid.

            :return: True if the current checkout is the expected directory,
              False if the current checkout is a subversion checkout with a
              different URL and None when the directory is not svn checkout
            :rtype: bool | None
            """
            svninfo = Run(['svn', '--non-interactive', 'info', self.dest])
            if svninfo.status != 0:
                return None
            m = re.search(r'^URL: *(.*)\n', svninfo.out, flags=re.M)
            if m is not None:
                return m.group(1).strip() == self.url
            return False

        def checkout(self):
            """Perform svn checkout.

            :raise SVN_Error: if case of unexpected failure
            """
            svncheckout = Run(['svn', '--non-interactive', 'checkout'] +
                              self.ext_args + self.rev_args +
                              [self.url, self.dest],
                              error=STDOUT)
            if svncheckout.status != 0:
                self.error("error during checkout: %s" % svncheckout.out)

        def switch(self):
            """Perform svn switch to the selected url.

            :raise SVN_Error: if case of unexpected failure
            """
            svnswitch = Run(['svn', '--non-interactive', 'switch'] +
                            self.ext_args +
                            [self.url, self.dest], error=STDOUT)
            if svnswitch.status != 0:
                raise SVN_Error("error during switch: %s" % svnswitch.out)

        def update_file(self, filename):
            """Update a file in the local checkout.

            :param filename: path relative to the root url that should be
                updated
            :type filename: str

            :raise SVN_Error: if case of unexpected failure
            """
            svnupdate = Run(['svn', '--non-interactive', 'update'] +
                            self.ext_args + self.rev_args + [filename],
                            error=STDOUT)
            if svnupdate.status != 0:
                self.error('svn update error:\n' + svnupdate.out)

        def log(self, rev1=None, rev2=None, limit=32):
            """Retrieve log entries.

            :param limit: maximum number of entries we want to retrieve
            :type limit: int

            :param rev1: start log from this revision
            :type rev1: int
            :param rev2: stop log at this revision
            :type rev1: int

            :return: a list of dictionaries
            :rtype: list[dict]

            :raise SVN_Error: if case of unexpected failure
            """
            if rev1 and rev2:
                cmd = ['svn', '--non-interactive', 'log',
                       '--xml', '--limit', str(limit),
                       '-r%s:%s' % (str(rev1), str(rev2))] + self.rev_args
            else:
                cmd = ['svn', '--non-interactive', 'log',
                       '--xml', '--limit', str(limit)] + self.rev_args

            svnlog = Run(cmd + [self.dest], error=PIPE)
            if svnlog.status != 0:
                self.error('svn log error:\n' + svnlog.out)

            # parse log
            xml_log = minidom.parseString(svnlog.out)
            logs = []
            for node in xml_log.getElementsByTagName("logentry"):
                entry = {}
                if node.getAttribute('revision'):
                    entry['revision'] = node.getAttribute('revision')
                if node.getElementsByTagName('author'):
                    entry['author'] = node.getElementsByTagName(
                        'author')[0].firstChild.data
                if node.getElementsByTagName('date'):
                    entry['date'] = node.getElementsByTagName(
                        'date')[0].firstChild.data
                if node.getElementsByTagName('msg'):
                    entry['message'] = node.getElementsByTagName(
                        'msg')[0].firstChild.data
                logs.append(entry)
            return logs

        def diff(self, rev1=None, rev2=None):
            """Return the local changes in the checkout.

            :param rev1: start diff from this revision
            :type rev1: int
            :param rev2: stop diff at this revision
            :type rev1: int

            :return: the diff content
            :rtype: str
            """
            if rev1 and rev2:
                cmd = ['svn', 'diff', '-r',
                       '%s:%s' % (str(rev1), str(rev2))]
            else:
                cmd = ['svn', 'diff']
            svndiff = Run(cmd, error=STDOUT, cwd=self.dest)
            if svndiff.status != 0:
                self.error('svn diff error:\n' + svndiff.out)
            return svndiff.out


class Git(object):
    """Interface to Git.

    ATTRIBUTES
       url:    the git url
       dest:   the local git repository path
       branch: the branch
       rev:    the revision used
       remote: the current remote name
    """

    def __init__(self, url, dest,
                 branch='master', rev=None,
                 force_checkout=True):
        """Initialize a Git working environment.

        :param url: the remote git url
        :type url: str
        :param dest: the local git repository path
        :type dest: str
        :param branch: the branch
        :type branch: str
        :param rev: the revision used
        :type rev: str | None
        :param force_checkout: do a checkout of the given `rev` or `branch`
            even if the repository already exists, it overwrite existing files
        :type force_checkout: bool
        :raise: Git_Error
        """
        self.url = unixpath(url)
        self.dest = unixpath(dest)
        self.branch = branch
        self.rev = rev
        self.remote = None
        self.git = which('git', default=None)

        if not self.git:
            raise Git_Error('git not found')

        try:
            # If the dest directory does not exist or is empty, do a git clone
            if not os.path.exists(self.dest) or not os.listdir(self.dest):
                self.clone()
                return
            remotes = self.remote_info()
        except Git_Error:
            if force_checkout:
                self.init()
                remotes = self.remote_info()
            else:
                self.__error("%s not empty and force_checkout is not True"
                             % self.dest,
                             traceback=sys.exc_traceback)

        configured_remote = [r[0] for r in remotes if r[1] == self.url]
        if configured_remote:
            self.remote = configured_remote[0]
        elif not configured_remote:
            error_msg = "Remote for %s not found. " % self.url
            if not remotes:
                error_msg += "No configured remotes"
            else:
                error_msg += "Configured remotes are:\n"
                error_msg += '\n'.join(set((r[1] for r in remotes)))
            if force_checkout:
                vcslogger.debug(error_msg)
                self.init()
            else:
                self.__error(error_msg)

        if force_checkout:
            try:
                if rev is not None:
                    self.checkout(rev, force=True)
                else:
                    self.checkout("%s/%s" % (self.remote, branch), force=True)
            except Git_Error:
                # ??? the ref to checkout is maybe not already fetched
                # force an update in that case
                self.update(rev)

    def update(self, ref=None, ignore_diff=False, picks=None):
        """Update the repository.

        :param ref: the ref to checkout, by default
            current_remote/current_branch
        :type ref: str | None
        :param ignore_diff: If True do not compute any diff
        :type ignore_diff: bool
        :param picks: list of additional git references to cherry-pick
        :type picks: list[str] | None
        :return: (last revision, log since last update)
        :rtype: (str, str)
        """
        if ref is None:
            ref = "%s/%s" % (self.remote, self.branch)
        last_rev = self.get_rev('HEAD')

        # Clean stale / deleted remote branches
        Run([self.git, 'remote', 'prune', self.remote], cwd=self.dest)

        self.fetch()
        self.checkout(ref)

        # Cherry pick additional changes
        if picks is not None:
            for p in picks:
                self.fetch(p, pick=True)

        return (self.rev, self.log("%s..%s" % (last_rev, self.rev),
                                   ignore_diff=ignore_diff))

    def init(self):
        """Initialize a new Git repository and configure the remote."""
        self.remote = 'origin'
        p = Run([self.git, 'init'], cwd=self.dest)
        if p.status != 0:
            self.__error('git init failed\n%s' % p.out)
        p = Run([self.git, 'remote', 'add', self.remote, self.url],
                cwd=self.dest)
        if p.status != 0:
            self.__error('git remote add failed\n%s' % p.out)
        self.fetch()

    def get_rev(self, ref='HEAD'):
        """Get the sha associated to a given reference.

        :param ref: the git ref, by default HEAD
        :type ref: str

        :return: the sha1 string
        :rtype: str
        """
        p = Run([self.git, 'rev-parse', ref], cwd=self.dest)
        if p.status != 0:
            self.__error("git rev-parse %s error:\n%s" % (ref, p.out))
        return p.out.strip()

    def describe(self, ref='HEAD'):
        """Get a human friendly revision.

        Returns the most recent tag name with the number of additional commits
        on top of the tagged object and the abbreviated object name of the most
        recent commit.

        :param ref: the git ref, by default HEAD
        :type ref: str

        :return: a string (see `git help describe`)
        :rtype: str
        """
        p = Run([self.git, 'describe', '--always', ref], cwd=self.dest)
        if p.status != 0:
            self.__error("git describe --always %s error:\n%s" % (ref, p.out))
        return p.out.strip()

    def fetch(self, ref=None, pick=False):
        """Fetch remote changes.

        :param ref: a git reference. If None fetch default remote
        :type ref: str | None
        :param pick: if True cherry-pick the fetched reference
        :type pick: bool
        """
        cmd = [self.git, 'fetch']
        if ref is not None:
            cmd.append(self.url)
            cmd.append(ref)

        p = Run(cmd, cwd=self.dest)
        if p.status != 0:
            self.__error('git fetch error:\n%s' % p.out)
        if ref and pick:
            # Pick the last fetched ref
            p = Run([self.git, 'cherry-pick', 'FETCH_HEAD'],
                    cwd=self.dest)
            if p.status != 0:
                self.__error('git cherry-pick error:\n%s' % p.out)
            # Update current revision
            self.rev = self.get_rev('HEAD')

    def clone(self):
        """Clone the git repository."""
        p = Run([self.git, 'clone', self.url, self.dest])
        if p.status != 0:
            self.__error('git clone %s error:\n%s' % (self.url, p.out))

        # New remote origin is created
        self.remote = 'origin'

        if self.rev is not None:
            self.checkout(self.rev)
        else:
            self.checkout("%s/%s" % (self.remote, self.branch))

    def remote_info(self):
        """Get info on remote repositories."""
        if not os.path.exists(self.dest):
            self.__error(self.dest + " does not exist")
        p = Run([self.git, 'remote', '-v'], cwd=self.dest)
        if p.status != 0:
            self.__error('git remote -v error:\n' + p.out)
        else:
            return [l.split() for l in p.out.splitlines()]

    def checkout(self, rev, force=False):
        """Checkout a revision.

        :param rev: the revision to checkout
        :type rev: str
        :param force: throw away local changes if needed
        :type force: bool
        """
        cmd = [self.git, 'checkout']
        if force:
            cmd.append('-f')
        cmd.append(rev)
        p = Run(cmd, cwd=self.dest)
        if p.status != 0:
            self.__error("git checkout %s error:\n%s" % (rev, p.out))
        self.rev = self.get_rev('HEAD')

    def log(self, rev=None, path=None, ignore_diff=False):
        """Run logs messages.

        :param rev: the revision range. If not set, gets all logs from the
            beginning
        :type rev: str | None
        :param path: the file or directory to get logs from. If not set, gets
            the overall working dir's logs.
        :type path: str | None
        :param ignore_diff: If True do not compute any diff
        :type ignore_diff: bool

        :return: a list of dictionaries containing: revision, author, date, msg
        :rtype: list[dict[str][str]]
        """
        cmd = [self.git, '--no-pager', 'log', '--pretty=medium']
        if not ignore_diff:
            cmd.append('-p')
        if rev is not None:
            cmd.append(rev)
        p = Run(cmd, cwd=self.dest)
        if p.status != 0:
            self.__error("git log %s error:\n%s" % (rev, p.out))

        logs = []
        entry = {}

        def get_entry_value(line):
            return line.split()[1].strip()

        def get_author_value(line):
            """Return author last name.

            :param line: line like "Author: name lastname <email>"
            :rtype str
            """
            return line.split(':')[1].strip().split()[1]

        def get_author_email(line):
            """Return author email

            :param line: line like "Author: name lastname <email>"
            :rtype str
            """
            return line.split('<')[1].strip()[:-1]

        is_diff = False
        for l in p.out.splitlines():
            if l.startswith('commit'):
                # End of an entry
                if entry:
                    logs.append(entry)
                # Beginning of a new entry
                entry = {'revision': get_entry_value(l),
                         'message': '',
                         'diff': ''}
                is_diff = False
            elif l.startswith('Author'):
                entry['author'] = get_author_value(l)
                entry['email'] = get_author_email(l)
            elif l.startswith('Date'):
                entry['date'] = l.replace('Date:', '').strip()
            else:
                if l.startswith('diff --git'):
                    is_diff = True
                if not is_diff:
                    entry['message'] += '%s\n' % l[4:]
                else:
                    entry['diff'] += '%s\n' % l

        if entry:
            logs.append(entry)

        return logs

    def diff(self):
        """Return local changes in the working tree.

        :rtype: str
        """
        cmd = [self.git, '--no-pager', 'diff', 'HEAD']
        p = Run(cmd, cwd=self.dest, error=PIPE)
        if p.status != 0:
            self.__error("git diff error:\n" + p.err)
        return p.out

    @classmethod
    def __error(cls, msg, traceback=None):
        """Log the message and raise Git_Error."""
        vcslogger.error(msg)
        if traceback is None:
            raise Git_Error(msg)
        else:
            raise Git_Error(msg), None, traceback

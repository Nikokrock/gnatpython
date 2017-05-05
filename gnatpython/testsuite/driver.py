from gnatpython.testsuite.result import Result
from gnatpython.fileutils import unixpath, diff
import logging
import re
import os


class TestDriver(object):
    """Testsuite Driver.

    All drivers declared in a testsuite should inherit from this class
    """

    def __init__(self, global_env, test_env):
        """Create a TestDriver instance.

        :param global_env: the testsuite env
        :type global_env: dict
        :param test_env: the test env (usually parsed content of the
            tests.yaml)
        :type test_env: dict
        """
        self.result = Result(test_env)
        self.global_env = global_env
        self.test_env = test_env

        # Used by analyze_diff to do some automatic substitution
        self.subst = []

    def tear_up(self):
        """Execute operations before executing a test."""
        pass

    def tear_down(self):
        """Execute operations once a test is finished."""
        pass

    def run(self):
        """Execute a test."""
        pass

    def analyze(self):
        """Compute the test result."""
        self.result.set_status("PROBLEM",
                               "you should not used directly this class")

    def register_path_subst(self, path, subst=''):
        """Register a path to be substituted in actual and expected output.

        Note that that substitution are only applied when using helper
        functions such as analyze_diff

        :param path: a path
        :type path: str
        :param subst: substitution string
        :type subst: str
        """
        self.subst.append((os.path.abspath(path).replace('\\', '\\\\'), subst))
        self.subst.append((unixpath(path).replace('\\', '\\\\'), subst))
        self.subst.append((path.replace('\\', '\\\\'), subst))

    def register_subst(self, pattern, replace):
        """Register a substitution.

        Note that that substitution are only applied when using helper
        functions such as analyze_diff

        :param pattern: a regexp
        :type pattern: str
        :param replace: a substitution string (see re.sub)
        :type replace: str
        """
        self.subst.append((pattern, replace))

    def analyze_diff(self, expected=None, actual=None,
                     strip_cr=True, replace_backslashes=True):
        """Set status based on diff analysis.

        If there is no difference test status is set to PASSED, otherwise
        it is set to FAILED. diff string is stored in self.result.diff.

        :param expected: if None then self.result.expected_output is taken
          otherwise parameter expected is used
        :type expected: str | None
        :param actual: if None then self.result.actual_output is taken
          otherwise parameter actual is used
        :type expected: str | None
        :param strip_cr: if True, strip cr from both expected and actual
        :type strip_cr: bool
        :param replace_backslashes: if True, replace backslashes by slashes
            in expected and actual
        :type replace_backslashes: bool
        """
        if expected is None:
            expected = self.result.expected_output

        if actual is None:
            actual = self.result.actual_output

        if strip_cr:
            actual = actual.replace('\r', '')
            expected = expected.replace('\r', '')

        for d in self.subst:
            logging.debug('%s -> %s' % (d[0], d[1]))
            expected = re.sub(d[0], d[1], expected)
            actual = re.sub(d[0], d[1], actual)

        if replace_backslashes:
            actual = actual.replace('\\', '/')
            expected = expected.replace('\\', '/')

        self.result.diff = diff(expected.splitlines(),
                                actual.splitlines())

        if self.result.diff:
            self.result.set_status('FAILED', 'output diff')
        else:
            self.result.set_status('PASSED')

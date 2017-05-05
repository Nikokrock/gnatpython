import os

from gnatpython.fileutils import echo_to_file


class Result(object):
    """Class used to hold test results.

    :var description: test description
    :var status: test status (should a key from Result.STATUS)
    :var msg: a short message
    :var expected_output: expected test output (not mandatory)
    :var actual_output: test output
    :var filtered_output: filtered test output (not mandatory)
    :var diff: diff between expected and actual output
    :var hash: hash that identify the test result
    """

    # Declare the avalaible status
    # to each status a boolean is associated indicating if the status
    # correspond to a failure
    STATUS = {'PASSED': False,
              'XFAIL': False,
              'UOK': False,
              'FAILED': True,
              'PROBLEM': True,
              'UNKNOWN': True,
              'CRASH': True,
              'INVALID_TEST': True,
              'DEAD': False}

    def __init__(self, test_env=None):
        """Create a new test result.

        :param test_env: the test environment info
        :type test_env: dict | None
        """
        self.test_env = test_env
        self.status = 'UNKNOWN'
        self.msg = ''
        self.expected_output = ''
        self.actual_output = ''
        self.filtered_output = ''
        self.diff = ''
        self.hash = ''

    def set_status(self, status, msg=""):
        """Update status.

        :param status: a valid status string
        :type status: str
        :param msg: a one-line description associated with the status
        :type msg: str
        """
        assert status in self.STATUS, 'invalid status %s' % status
        self.status = status
        self.msg = msg

    def dump_result(self, output_dir):
        """Dump the result as separated files.

        :param path_prefix: the path_prefix to be used as prefix for
           the several files
        :type path_prefix: str
        """

        path_prefix = os.path.join(output_dir,
                                   self.test_env['test_name'])

        echo_to_file(path_prefix + '.result',
                     '%s: %s' % (self.status, self.msg))

        if 'PASSED' not in self.status:
            echo_to_file(path_prefix + '.out',
                         '%s' % self.actual_output)
            echo_to_file(path_prefix + '.diff',
                         '%s' % self.diff)
            echo_to_file(path_prefix + '.expected',
                         '%s' % self.expected_output)
            echo_to_file(path_prefix + '.filtered',
                         '%s' % self.filtered_output)

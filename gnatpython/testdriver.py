############################################################################
#                                                                          #
#                           TESTDRIVER.PY                                  #
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

"""Run a bugs test located in test_dir.

Define a default test driver: TestRunner
"""

from gnatpython.env import Env
from gnatpython.fileutils import (
    split_file, echo_to_file, diff, rm, mkdir, cp, get_rlimit, mv)
from gnatpython.optfileparser import OptFileParse
from gnatpython.stringutils import Filter

import logging
import os
import re
import shutil
import subprocess
import sys
import time

IS_STATUS_FAILURE = {
    'DEAD': False,
    'CRASH': True,
    'INVALID_TEST': True,
    'INVALID_TEST_OPT': True,
    'UNKNOWN': True,
    'OK': False,
    'PROBLEM': True,
    'FAILED': True,
    'DIFF': True,
    'XFAIL': False,
    'UOK': False}
# Dictionary for which keys are the available test status. Associated value
# is a boolean that is True if status should be considered as a failure, False
# otherwise. Note that XFAIL and UOK are handled separately by the script.


class TestRunner(object):
    """Default test driver.

    ATTRIBUTES
      test: full path to test location
      discs: a list of discriminants (list of strings)
      cmd_line: the command line to be spawned (list of strings)
      test_name: name of the test
      result_prefix: prefix of files that are written in the result directory
      work_dir: the working directory in which the test will be executed
      output: name of the temporary file that hold the test output
      result: current state of the test. This is a dictionary with 3 keys:
        'result' that contains the test status, 'msg' the associated short
        message and 'is_failure' a boolean that is True if the test should
        be considered as a failure
      opt_results: context dependent variable (dictionnary)
      bareboard_mode: True if in bareboard mode. Default is False

    For code readability, methods are ordered following the invocation order
    used by the execute 'method'
    """

    keep_test_dir_on_failure = False

    def __init__(self,
                 test,
                 discs,
                 result_dir,
                 temp_dir=Env().tmp_dir,
                 enable_cleanup=True,
                 restricted_discs=None,
                 test_args=None,
                 failed_only=False,
                 default_timeout=780,
                 use_basename=True):
        """TestRunner constructor.

        :param test: location of the test
        :type test: str
        :param discs: list of discriminants
        :type discs: list[str]
        :param result_dir: directory in which results will be stored
        :type result_dir: str
        :param temp_dir: temporary directory used during test run
        :type temp_dir: str
        :param enable_cleanup: whether the temporary files needs to be removed
        :type enable_cleanup: bool
        :param restricted_discs: None or a list of discriminants
        :type restricted_discs:  list[str] | None
        :param test_args: ???
        :param failed_only: run failed only
        :type failed_only: bool
        :param default_timeout: timeout when executing a test
        :type default_timeout: int
        :param use_basename: if True use the test basename to get the test name
            else use the relative path
        :type use_basename: bool
        """
        self.test = test.rstrip('/')
        self.discs = discs
        self.cmd_line = None
        self.test_args = test_args
        self.enable_cleanup = enable_cleanup
        self.restricted_discs = restricted_discs
        self.skip = False  # if True, do not run execute()

        # Test name
        if use_basename:
            self.test_name = os.path.basename(self.test)
        else:
            self.test_name = os.path.relpath(self.test, os.getcwd())

        # Prefix of files holding the test result
        self.result_prefix = result_dir + '/' + self.test_name

        mkdir(os.path.dirname(self.result_prefix))

        # Temp directory in which the test will be run
        self.work_dir = os.path.realpath(
            os.path.join(temp_dir,
                         'tmp-test-%s-%d' % (self.test_name, os.getpid())))
        self.output = self.work_dir + '/tmpout'
        self.output_filtered = self.work_dir + '/tmpout.filtered'
        self.diff_output = self.work_dir + '/diff'
        self.cmdlog = self.work_dir + '/' + self.test_name + '.log'

        # Initial test status
        self.result = {'result': 'UNKNOWN', 'msg': '', 'is_failure': True}

        # Some tests save the pids of spawned background processes in
        # work_dir/.pids. The TEST_WORK_DIR environment variable is used to
        # pass the working directory location.
        os.environ['TEST_WORK_DIR'] = self.work_dir

        if failed_only:
            # Read old result now
            previous_result = self.read_result()
            if previous_result in IS_STATUS_FAILURE \
                    and not IS_STATUS_FAILURE[previous_result]:
                # We don't need to run this test. Return now
                self.skip = True
                return

        # Be sure to be a sane environment
        rm(self.result_prefix + '.result')
        rm(self.result_prefix + '.out')
        rm(self.result_prefix + '.expected')
        rm(self.result_prefix + '.diff')
        rm(self.result_prefix + '.log')
        rm(self.result_prefix + '.out.filtered')

        # Initialize options defaults (can be modified with test.opt).
        # By default a test is not DEAD, SKIP nor XFAIL. Its maximum execution
        # time is 780s. Test script is test.cmd and output is compared against
        # test.out.
        self.opt_results = {'RLIMIT': str(default_timeout),
                            'DEAD': None,
                            'XFAIL': False,
                            'SKIP': None,
                            'OUT': 'test.out',
                            'CMD': 'test.cmd',
                            'FILESIZE_LIMIT': None,
                            'TIMING': None,
                            'NOTE': None}
        self.opt_file = 'test.opt'

        # test.cmd have priority, if not found use test.py
        if not os.path.isfile(
            self.test + '/test.cmd') and os.path.isfile(
                self.test + '/test.py'):
            self.opt_results['CMD'] = 'test.py'

    def cleanup(self, force=False):
        """Remove generated files."""
        rm(self.result_prefix + '.result')
        rm(self.result_prefix + '.out')
        rm(self.result_prefix + '.expected')
        rm(self.result_prefix + '.diff')
        rm(self.result_prefix + '.log')

    def execute(self):
        """Complete test execution.

        Calls all the steps that are needed to run the test.
        """
        if self.skip:
            logging.debug("SKIP %s - failed only mode" % self.test)
            return

        # Adjust test context
        self.adjust_to_context()

        for key in ('CMD', 'OUT'):
            # Read command file and expected output from working directory
            self.opt_results[key] = self.work_dir + '/src/' + \
                self.opt_results[key]

        # Keep track of the discriminants that activate the test
        if self.opt_results['NOTE']:
            echo_to_file(self.result_prefix + '.note',
                         '(' + self.opt_results['NOTE'] + ')\n')

        # If a test is either DEAD or SKIP then do not execute it. The only
        # difference is that a SKIP test will appear in the report whereas a
        # DEAD test won't.

        for opt_cmd in ('DEAD', 'SKIP'):
            if self.opt_results[opt_cmd] is not None:
                echo_to_file(self.result_prefix + '.result',
                             opt_cmd + ':%s\n' % self.opt_results[opt_cmd])
                return

        if self.result['result'] != 'UNKNOWN':
            self.write_results()
            return

        # Run the test
        self.prepare_working_space()
        self.compute_cmd_line()

        if self.opt_results['TIMING'] is not None:
            start_time = time.time()

        try:
            self.run()
        except KeyboardInterrupt:
            self.result['result'] = 'CRASH'
            self.result['msg'] = 'User interrupt'
            self.write_results()
            raise

        if self.opt_results['TIMING'] is not None:
            self.opt_results['TIMING'] = time.time() - start_time

        # Analyze the results and write them into result_dir
        self.set_output_filter()
        self.analyze()
        self.write_results()

        # Clean the working space
        if self.enable_cleanup:
            self.clean()

    def adjust_to_context(self):
        """Adjust test environment to context.

        At this stage we parse the test.opt and adjust the opt_results
        attribute value. The driver will check if the test should be run
        (i.e is DEAD) right after this step.
        """
        opt_file_path = os.path.join(self.test, self.opt_file)

        if self.restricted_discs is not None:
            opt_file_content = ['ALL DEAD disabled by default']
            if os.path.isfile(opt_file_path):
                opt_file_content += split_file(opt_file_path)

            opt = OptFileParse(self.discs, opt_file_content)
            self.opt_results = opt.get_values(self.opt_results)
            if not self.opt_results['DEAD']:
                activating_tags = opt.get_note(sep='')
                for d in self.restricted_discs:
                    if d not in activating_tags:
                        self.opt_results['DEAD'] = \
                            '%s not in activating tags' % d
        else:
            opt = OptFileParse(self.discs, opt_file_path)
            self.opt_results = opt.get_values(self.opt_results)

        self.opt_results['NOTE'] = opt.get_note()

        if not os.path.isfile(self.test + '/' + self.opt_results['CMD']):
            self.result = {
                'result': 'INVALID_TEST',
                'msg': 'cannot find script file %s' % (
                    self.opt_results['CMD']),
                'is_failure': True}
            return

        if self.opt_results['OUT'][-8:] != 'test.out' and \
                not os.path.isfile(self.test + '/' + self.opt_results['OUT']):
            tmp = os.path.basename(self.opt_results['OUT'])
            self.result = {
                'result': 'INVALID_TEST',
                'msg': 'cannot find output file %s' % (tmp),
                'is_failure': True}
            return

    def prepare_working_space(self):
        """Prepare working space.

        Set the working space in self.work_dir. This resets the working
        directory and copies the test into <work_dir>/src. This
        directory can be used to hold temp files as it will be
        automatically deleted at the end of the test by the clean method
        """
        # At this stage the test should be executed so start copying test
        # sources in a temporary location.
        rm(self.work_dir, True)
        mkdir(self.work_dir)
        try:
            shutil.copytree(self.test, self.work_dir + '/src')
        except shutil.Error:
            print >> sys.stderr, "Error when copying %s in %s" % (
                self.test, self.work_dir + '/src')

    def compute_cmd_line_py(self, filesize_limit):
        """Compute self.cmd_line and preprocess the test script.

        This function is called by compute_cmd_line
        """
        self.cmd_line += [sys.executable, self.opt_results['CMD']]
        if self.test_args:
            self.cmd_line += self.test_args

    def compute_cmd_line_cmd(self, filesize_limit):
        """Compute self.cmd_line and preprocess the test script.

        This function is called by compute_cmd_line
        """
        cmd = self.opt_results['CMD']
        if Env().host.os.name != 'windows':
            script = split_file(cmd)

            # The test is run on a Unix system but has a 'cmd' syntax.
            # Convert it to Bourne shell syntax.
            cmdfilter = Filter()
            cmdfilter.append([r'-o(.*).exe', r'-o \1'])
            cmdfilter.append([r'%([^ ]*)%', r'"$\1"'])
            cmdfilter.append([r'(\032|\015)', r''])
            cmdfilter.append([r'set *([^ =]+) *= *([^ ]*)',
                              r'\1="\2"; export \1'])
            script = cmdfilter.process(script)

            cmd = self.work_dir + '/__test.sh'
            echo_to_file(cmd, 'PATH=.:$PATH; export PATH\n')

            # Compute effective file size limit on Unix system.
            if filesize_limit > 0:
                # File size limit can be specified either by a default or by
                # mean of FILESIZE_LIMIT command in the test test.opt. When
                # both are specified use the upper limit (note that 0 means
                # unlimited).
                opt_limit = self.opt_results['FILESIZE_LIMIT']
                if opt_limit is not None:
                    try:
                        opt_limit = int(opt_limit)
                    except TypeError:
                        opt_limit = filesize_limit
                else:
                    opt_limit = filesize_limit

                if opt_limit != 0:
                    if filesize_limit < opt_limit:
                        filesize_limit = opt_limit

                    # Limit filesize. Argument to ulimit is a number of blocks
                    # (512 bytes) so multiply by two the argument given by the
                    # user. Filesize limit is not supported on Windows.
                    echo_to_file(cmd,
                                 'ulimit -f %s\n' % (filesize_limit * 2),
                                 True)

            # Source support.sh in TEST_SUPPORT_DIR if set
            if 'TEST_SUPPORT_DIR' in os.environ and os.path.isfile(
                    os.environ['TEST_SUPPORT_DIR'] + '/support.sh'):
                echo_to_file(cmd, '. $TEST_SUPPORT_DIR/support.sh\n', True)

            echo_to_file(cmd, script, True)

            self.cmd_line += ['bash', cmd]
        else:
            # On windows system, use cmd to run the script.
            if cmd[-4:] != '.cmd':
                # We are about to use cmd.exe to run a test. In this case,
                # ensure that the file extension is .cmd otherwise a dialog box
                # will popup asking to choose the program that should be used
                # to run the script.
                cp(cmd, self.work_dir + '/test__.cmd')
                cmd = self.work_dir + '/test__.cmd'

            self.cmd_line += ['cmd.exe', '/q', '/c', cmd]

    def compute_cmd_line(self, filesize_limit=36000):
        """Compute command line.

        :param filesize_limit: if set to something greater than 0 then a
            "ulimit -f" is inserted in the scripts. The unit of filesize_limit
             is Kb.
        :type filesize_limit: int

        When this step is called we assume that we have all the context set and
        that the working space is in place. The main goal of this step is to
        compute self.cmd_line and do any processing on the test script file.

        If the script is in Windows CMD format, convert it to Bourne shell
        syntax on UNIX system and source TEST_SUPPORT_DIR/support.sh if exist
        """
        # Find which script language is used. The default is to consider it
        # in Windows CMD format.
        _, ext = os.path.splitext(self.opt_results['CMD'])
        if ext in ['.cmd', '.py']:
            cmd_type = ext[1:]
        else:
            cmd_type = 'cmd'

        rlimit = get_rlimit()
        assert rlimit, 'rlimit not found'
        self.cmd_line = [rlimit, self.opt_results['RLIMIT']]
        if cmd_type == 'py':
            self.compute_cmd_line_py(filesize_limit)
        elif cmd_type == 'cmd':
            self.compute_cmd_line_cmd(filesize_limit)

    def run(self):
        """Run the test.

        This step should spawn the test using self.cmd_line and save its
        output in self.output.
        """
        # Run the test

        logging.debug("RUN: %s" % " ".join(self.cmd_line))

        # Open output in append (not write) mode, so that output from multiple
        # concurrent subprocesses are concatenated (instead of overwriting
        # each other).

        with open(self.output, 'a') as fd:
            # Here we are calling directly subprocess function as it is a bit
            # faster than using gnatpython.ex.Run
            subprocess.call(self.cmd_line,
                            cwd=self.work_dir + '/src',
                            stdout=fd,
                            bufsize=-1,
                            stderr=subprocess.STDOUT)

    def apply_output_filter(self, str_list):
        """Apply the output filters.

        :param str_list: a list of strings
        :type str_list: list[str]

        :return: a list of string
        :rtype: list[str]
        """
        return self.output_filter.process(str_list)

    def set_output_filter(self):
        """Set output filters.

        output filters are applied both to expected output and test
        output before comparing them.
        """
        self.output_filter = Filter()
        # General filters. Filter out CR and '.exe' and work_dir and replace
        # \ by /
        self.output_filter.append([r'\\', r'/'])
        self.output_filter.append([r'(\.exe|\015)', r''])
        self.output_filter.append([r'[^ \'"]*%s/src/' %
                                   os.path.basename(self.work_dir), r''])

    def get_status_filter(self):
        """Get the status filters.

        :return: a list. Each element is a list containing two items.
            The first is a regexp, the second a dictionary used to update
            self.result.
        :rtype: list[list]

        The return value will be used the following way. For each entry, if the
        test output match the regexp then we update self.result with its
        dictionnary. Only the first match is taken into account.
        """
        result = [['Segmentation fault',
                   {'result': 'CRASH', 'msg': 'Segmentation fault'}],
                  ['Bus error',
                   {'result': 'CRASH', 'msg': 'Bus error'}],
                  ['Cputime limit exceeded',
                   {'result': 'CRASH', 'msg': 'Cputime limit exceeded'}],
                  ['Filesize limit exceeded',
                   {'result': 'CRASH', 'msg': 'Filesize limit exceeded'}]]
        return result

    def analyze(self, ignore_white_chars=True):
        """Compute test status.

        :param ignore_white_chars: in the default driver difference in white
            chars are ignored. This parameter allow the user to change that
            behavior. In that case the user should override the analyze method
            in its own driver and call this method with ignore_white_chars set
            to False.
        :type ignore_white_chars: bool

        This method should set the final value of 'result' attribute
        """
        # Retrieve the outputs and see if we match some of the CRASH or DEAD
        # patterns
        output = split_file(self.output, ignore_errors=True)
        if output:
            tmp = "\n".join(output)
            for pattern in self.get_status_filter():
                if re.search(pattern[0], tmp):
                    self.result.update(pattern[1])
                    break

        # If the test status has not been updated compare output with the
        # baseline
        if self.result['result'] == 'UNKNOWN':
            # Retrieve expected output
            expected = split_file(self.opt_results['OUT'], ignore_errors=True)

            # Process output and expected output with registered filters
            expected = self.apply_output_filter(expected)
            output = self.apply_output_filter(output)

            # Save the filtered output (might be needed by some developpers to
            # create more easily baselines).
            echo_to_file(self.output_filtered, output)

            d = diff(expected, output, ignore_white_chars=ignore_white_chars)
            if d:
                logging.debug(d)
                self.result['result'] = 'DIFF'
                if len(expected) == 0:
                    self.result['msg'] = 'unexpected output'
                else:
                    self.result['msg'] = 'output'
                diff_file = open(self.diff_output, 'w')
                diff_file.write(d)
                diff_file.close()
            else:
                self.result = {'result': 'OK',
                               'msg': '',
                               'is_failure': False}

        self.result['is_failure'] = IS_STATUS_FAILURE[self.result['result']]

        # self.opt_results['XFAIL'] contains the XFAIL comment or False
        # The status should be set to XFAIL even if the comment is empty
        if not isinstance(self.opt_results['XFAIL'], bool) or \
                self.opt_results['XFAIL']:
            if self.result['result'] in ['DIFF', 'CRASH']:
                self.result.update({'result': 'XFAIL',
                                    'msg': self.opt_results['XFAIL']})
            elif self.result['result'] == 'OK':
                self.result.update({'result': 'UOK',
                                    'msg': self.opt_results['XFAIL']})

    def write_results(self):
        """Write results on disk.

        Write at least .result and maybe .out and .expected files in the
        result directory.
        """
        echo_to_file(self.result_prefix + '.result',
                     self.result['result'] + ':' + self.result['msg'] + '\n')

        # The command line logs are always saved in the result directory
        # because all of them are needed to generate the aggregation file
        # (testsuite_support.log) in the collect_result function.

        if os.path.isfile(self.cmdlog):
            cp(self.cmdlog, self.result_prefix + '.log')

        if self.result['is_failure']:
            if os.path.isfile(self.opt_results['OUT']):
                cp(self.opt_results['OUT'], self.result_prefix + '.expected')

            if os.path.isfile(self.output):
                cp(self.output, self.result_prefix + '.out')

            if os.path.isfile(self.output_filtered):
                cp(self.output_filtered, self.result_prefix + '.out.filtered')

            if os.path.isfile(self.diff_output):
                cp(self.diff_output, self.result_prefix + '.diff')

            if self.keep_test_dir_on_failure:
                with open(self.result_prefix + '.info', 'a') as f:
                    f.write('binary_path:%s\n' % self.failed_bin_path)

        if self.opt_results['TIMING']:
            echo_to_file(self.result_prefix + '.time',
                         str(self.opt_results['TIMING']) + '\n')

    def read_result(self):
        """Read last result."""
        if os.path.exists(self.result_prefix + '.result'):
            with open(self.result_prefix + '.result') as f_res:
                return f_res.read().strip().split(':')[0]

    @property
    def failed_bin_path(self):
        return os.path.join(
            os.path.dirname(self.result_prefix), 'failed_bin', self.test_name)

    def clean(self):
        """Clean up working space.

        Clean any temporary files
        """
        # Clean up before exiting
        if self.keep_test_dir_on_failure:
            mv(self.work_dir, self.failed_bin_path)
        else:
            rm(self.work_dir, True)


def add_run_test_options(m):
    """Add standard test driver options."""
    run_test_opts = m.create_option_group("Test driver options")
    run_test_opts.add_option(
        "-o", "--output-dir",
        dest="output_dir",
        metavar="DIR",
        default="./out",
        help="select output dir")
    run_test_opts.add_option(
        "--timeout",
        default='780',
        metavar="SECONDS",
        help="Default timeout")
    run_test_opts.add_option(
        "-d", "--discriminants",
        dest="discs",
        metavar="DISCS",
        default="ALL",
        help="set discriminants")
    run_test_opts.add_option(
        "-t", "--temp-dir",
        dest="tmp",
        metavar="DIR",
        default=Env().tmp_dir)
    run_test_opts.add_option(
        "-e", "--env-file",
        dest="env_file",
        metavar="FILE",
        default="load env file")
    run_test_opts.add_option(
        "--disable-cleanup",
        dest="enable_cleanup",
        action="store_false",
        default=True,
        help="disable cleanup of working space")
    run_test_opts.add_option(
        "--dump-environ",
        dest="dump_environ",
        action="store_true",
        default=False,
        help="Dump all environment variables in a file named environ.sh,"
        " located in the output directory (see --output-dir). This"
        " file can then be sourced from a Bourne shell to recreate"
        " the environement that existed when this testsuite was run"
        " to produce a given testsuite report.")
    run_test_opts.add_option(
        "-r", "--restricted-mode",
        dest="restricted_discs",
        metavar="DISCS",
        default=None,
        help="enable restricted mode")
    run_test_opts.add_option(
        '-f', '--failed-only',
        action="store_true",
        help="run failed only - skip the test is last result is OK")
    run_test_opts.add_option(
        '--use-basename',
        action='store_true',
        help="Use os.path.basename to get the real name of a test. "
        "Note that this will only work if you don't have two tests with "
        "the same name in your test directories")
    m.add_option_group(run_test_opts)

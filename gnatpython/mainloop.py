############################################################################
#                                                                          #
#                          MAINLOOP.PY                                     #
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

"""Generic loop for testsuites.

This package provides a class called MainLoop that provides a generic
implementation of a testsuite main loop. Parallelism, abortion and time
control are the key features.

Each MainLoop instance controls a set of Workers whose number is set
by the user. The list of tasks/tests to be achieved by the workers,
is provided by a list. The mainloop distribute the elements to the
the workers when they have nothing to do. Usually, an element is a
string identifying the test to be run. An element can also be a list
in that case the worker will execute sequentially each "subelement".
This case is used to address dependency between tests (occurs for
example with the ACATS).

When a worker is asked to run a test, the command is executed by
calling run_testcase (testid). Once a test is finished the function
collect_result will be called with test id, and process (a
gnatpython.ex.Run object) and the job_info as parameters. Both
run_testcase and collect_result are user defined functions.

Note also that from the user point view there is no parallelism to handle.
The two user defined function run_testcase and collect_result are called
sequentially.
"""

from time import sleep, strftime

import itertools
import logging
import os
import re
import sys

from gnatpython import testsuite_logging
from gnatpython.arch import UNKNOWN
from gnatpython.env import Env
from gnatpython.ex import Run
from gnatpython.dag import DAG
from gnatpython.fileutils import (
    echo_to_file, FileUtilsError, mkdir, mv, rm, split_file)
from gnatpython.stringutils import quote_arg

logger = logging.getLogger('gnatpython.mainloop')


SKIP_EXECUTION = -1
# Ask the mainloop to stop execution for this test
# See MainLoop documentation

# Define some default status
DIFF_STATUS = ('DIFF', 'FAILED', 'PROBLEM')
CRASH_STATUS = ('CRASH', )
XFAIL_STATUS = ('XFAIL', )

FAIL_STATUS = list(itertools.chain(
    DIFF_STATUS, CRASH_STATUS, XFAIL_STATUS))
SKIP_STATUS = ('DEAD', 'SKIP')


class NeedRequeue(Exception):
    """Raised by collect_result if a test need to be requeued."""
    pass


class TooManyErrors(Exception):
    """Raised by collect_result if there ase too many errors.

    This exception is raised when the number of consecutive errors
    is higher than the value defined by --max-consecutive-failures
    """
    pass


class Worker(object):
    """Run run_testcase and collect_result."""

    def __init__(self, items, run_testcase, collect_result, slot):
        """Worker constructor.

        :param items: item or list of items to be run by the worker
        :param run_testcase: command builder function (see MainLoop doc)
        :param collect_result: result processing function (see MailLoop doc)
        """
        self.run_testcase = run_testcase
        self.collect_result = collect_result
        self.slot = slot

        # Count the number of retry for the current test
        self.nb_retry = 0

        if isinstance(items, list):
            items.reverse()
            self.jobs = items
        else:
            self.jobs = [items]

        logger.debug('Init worker %d with %r' % (self.slot, self.jobs))
        self.current_process = None
        self.current_job = None
        self.execute_next()

    def execute_next(self):
        """Execute next worker item/test.

        :return: False if the worker has nothing to do. True if a test is
          launched.
        :rtype: bool
        """
        if len(self.jobs) == 0:
            return False
        else:
            self.current_job = self.jobs.pop()

            job_info = (self.slot, self.nb_retry)
            self.current_process = self.run_testcase(self.current_job,
                                                     job_info)
            return True

    def poll(self):
        """Test if a test/item is still executing.

        :return: True if busy, False otherwise.
        :rtype: bool
        """
        if self.current_process == SKIP_EXECUTION:
            # Test not run by run_testcase
            # Call directly wait()
            self.wait()
            return False
        else:
            if self.current_process.poll() is not None:
                # Current process has finished
                self.wait()
                return False
            else:
                return True

    def wait(self):
        """Wait for a test/item to finish.

        The collect_result function is called upon test/item termination
        """
        if self.current_process != SKIP_EXECUTION:
            self.current_process.wait()

        try:
            job_info = (self.slot, self.nb_retry)
            self.collect_result(self.current_job,
                                self.current_process,
                                job_info)
            self.current_job = None
            self.current_process = None

        except NeedRequeue:
            # Reinsert the current job in the job list
            self.nb_retry += 1
            self.jobs.append(self.current_job)


class MainLoop (object):
    """Run a list of jobs."""

    def __init__(self,
                 item_list,
                 run_testcase,
                 collect_result,
                 parallelism=None,
                 abort_file=None,
                 dyn_poll_interval=True):
        """Launch loop.

        :param item_list: a list of jobs or a dag
        :param run_testcase: a function that takes a job for argument and
            return the spawned process (ex.Run object). Its prototype should be
            func (name, job_info) with name the job identifier and job_info the
            related information, passed in a tuple (slot_number, job_retry)
            Note that if you want to take advantage of the parallelism the
            spawned process should be launched in background (ie with bg=True
            when using ex.Run).
            If run_testcase returns SKIP_EXECUTION instead of an ex.Run object
            the mainloop will directly call collect_result without waiting.
        :param collect_result: a function called when a job is finished. The
            prototype should be func (name, process, job_info). If
            collect_result raise NeedRequeue then the test will be requeued.
            job_info is a tuple: (slot_number, job_nb_retry)
        :param parallelism: number of workers
        :type parallelism: int | None
        :param abort_file: If specified, the loop will abort if the file is
            present
        :type abort_file: str | None
        :param dyn_poll_interval: If True the interval between each polling
            iteration is automatically updated. Otherwise it's set to 0.1
            seconds.
        :type dyn_poll_interval: bool
        """
        e = Env()
        self.parallelism = e.get_attr("main_options.mainloop_jobs",
                                      default_value=1,
                                      forced_value=parallelism)
        self.abort_file = e.get_attr("main_options.mainloop_abort_file",
                                     default_value=None,
                                     forced_value=abort_file)

        if self.parallelism == 0:
            if e.build.cpu.cores != UNKNOWN:
                self.parallelism = e.build.cpu.cores
            else:
                self.parallelism = 1

        logger.debug("start main loop with %d workers (abort on %s)"
                     % (self.parallelism, self.abort_file))
        self.workers = [None] * self.parallelism
        self.locked_items = [None] * self.parallelism

        if not isinstance(item_list, DAG):
            self.item_list = DAG(item_list)
        else:
            self.item_list = item_list

        self.iterator = self.item_list.__iter__()
        self.collect_result = collect_result
        active_workers = 0
        max_active_workers = self.parallelism
        poll_sleep = 0.1
        no_free_item = False

        try:
            while True:
                # Check for abortion
                if self.abort_file is not None and \
                        os.path.isfile(self.abort_file):
                    logger.info('Aborting: file %s has been found'
                                % self.abort_file)
                    self.abort()
                    return      # Exit the loop

                # Find free workers
                for slot, worker in enumerate(self.workers):
                    if worker is None:
                        # a worker slot is free so use it for next job
                        next_id, next_job = self.iterator.next()
                        if next_job is None:
                            no_free_item = True
                            break
                        else:
                            self.locked_items[slot] = next_id
                            self.workers[slot] = Worker(next_job,
                                                        run_testcase,
                                                        collect_result,
                                                        slot)
                            active_workers += 1

                poll_counter = 0
                logger.debug('Wait for free worker')
                while active_workers >= max_active_workers or no_free_item:
                    # All worker are occupied so wait for one to finish
                    poll_counter += 1
                    for slot, worker in enumerate(self.workers):
                        if worker is None:
                            continue

                        # Test if the worker is still active and have more
                        # job pending
                        if not (worker.poll() or worker.execute_next()):
                            # If not the case free the worker slot
                            active_workers -= 1
                            self.workers[slot] = None
                            self.item_list.release(self.locked_items[slot])
                            no_free_item = False
                            self.locked_items[slot] = None

                    sleep(poll_sleep)

                if dyn_poll_interval:
                    poll_sleep = compute_next_dyn_poll(poll_counter,
                                                       poll_sleep)

        except (StopIteration, KeyboardInterrupt) as e:
            if e.__class__ == KeyboardInterrupt:
                # Got ^C, abort the mainloop
                logger.error("User interrupt")

            # All the tests are finished
            while active_workers > 0:
                for slot, worker in enumerate(self.workers):
                    if worker is None:
                        continue

                    # Test if the worker is still active and ignore any
                    # job pending
                    try:
                        still_running = worker.poll()
                    except TooManyErrors:
                        still_running = False
                        # We're not spawing more tests so we can safely
                        # ignore all TooManyErrors exceptions.
                    if not still_running:
                        active_workers -= 1
                        self.workers[slot] = None
                    sleep(0.1)

            if e.__class__ == KeyboardInterrupt:
                self.abort()
                raise

        except TooManyErrors:
            # too many tests failure, abort the testsuite
            logger.error("Too many errors, aborting")
            self.abort()

    def abort(self):
        """Abort the loop."""
        # First force release of all elements to ensure that iteration
        # on the remaining DAG elements won't be blocked
        for job_id in self.locked_items:
            if job_id is not None:
                self.item_list.release(job_id)

        # Wait for worker still active if necessary
        if self.abort_file is not None and os.path.isfile(self.abort_file):
            for worker in self.workers:
                if worker is not None:
                    worker.wait()

        # Mark remaining tests as skipped
        for job_id, job_list in self.iterator:
            self.item_list.release(job_id)
            if not isinstance(job_list, list):
                job_list = [job_list]
            for job in job_list:
                self.collect_result(job, SKIP_EXECUTION, None)


def generate_collect_result(
        result_dir=None, results_file=None, output_diff=False,
        use_basename=True, metrics=None, options=None):
    """Generate a collect result function.

    The generated collect_result function is known to work with gnatpython
    default test driver: gnatpython.testdriver.TestRunner

    If you use the default options, the call to generate_collect_result
    should be:

    .. code-block:: python

        metrics = {'total': NUMBER_OF_TESTS}
        generate_collect_result(metrics=metrics, options=options)

    :param result_dir: [deprecated] directory containing test results,
        if None use options.output_dir
    :type result_dir: str | None
    :param results_file: [deprecated] file containing the list of test status,
        if None use options.results_file
    :type results_file: str | None
    :param output_diff: if True, output the .diff in case of failure (useful
        when debugging)
    :type output_diff: bool
    :param use_basename: if True use the test basename to get the test name
        else use the relative path
    :type use_basename: bool
    :param metrics: to collect metrics, just pass an empty dictionary or
        a dictionary containing a key named 'total' with an integer
        value equal to the number of test to run
    :type metrics: dict | None
    :param options: test driver and Main options

    When collecting metrics, a file named status will be created in
    result_dir and will contain some metrics

    If options.max_consecutive_failures is set to N, the test will be aborted
    when more than N tests are failing consecutively (ignoring tests
    expecting to fail and tests skipped).
    """
    # Set result_dir and results_file if needed
    if options is not None and result_dir is None:
        result_dir = options.output_dir
    if results_file is None:
        results_file = options.results_file

    # Save the startup time
    start_time_str = strftime('%Y-%m-%d %H:%M:%S')

    max_consecutive_failures = int(
        options.max_consecutive_failures) if hasattr(
        options, 'max_consecutive_failures') else 0
    if max_consecutive_failures:
        if metrics is None:
            metrics = {}
        metrics['max_consecutive_failures'] = 0

    if metrics is not None:
        for m in ('run', 'failed', 'crashed', 'new_failed', 'new_crashed'):
            metrics[m] = 0
        for m in ('old_diffs', 'old_crashes'):
            if m not in metrics:
                metrics[m] = []
        if 'total' not in metrics:
            metrics['total'] = 0

        # Compute old metrics if needed
        if hasattr(options, 'old_output_dir') \
                and options.old_output_dir is not None:
            old_results = [k.split(':') for k in split_file(
                os.path.join(options.old_output_dir, 'results'),
                ignore_errors=True)]
            if 'old_diffs' not in metrics:
                metrics['old_diffs'] = [
                    k[0] for k in old_results if k[1] in DIFF_STATUS]
            if 'old_crashes' not in metrics:
                metrics['old_crashes'] = [
                    k[0] for k in old_results if k[1] in CRASH_STATUS]

    def collect_result(name, process, _job_info):
        """Default collect result function.

        Read .result and .note file in {result_dir}/{test_name} dir
        Then append result to {result_file}

        If output_diff is True, print the content of .diff files

        Name should be the path to the test directory
        """
        # Unused parameter
        del _job_info
        if metrics is not None:
            # Increment number of run tests
            metrics['run'] += 1

        if use_basename:
            test_name = os.path.basename(name)
        else:
            test_name = os.path.relpath(name, os.getcwd())

        test_result = split_file(
            result_dir + '/' + test_name + '.result',
            ignore_errors=True)
        if not test_result:
            if process == SKIP_EXECUTION:
                test_result = 'CRASH:test skipped'
            else:
                test_result = 'CRASH:cannot read result file'
        else:
            test_result = test_result[0]
            if not test_result:
                test_result = 'CRASH: invalid result file'

        test_note = split_file(result_dir + '/' + test_name + '.note',
                               ignore_errors=True)

        if not test_note:
            test_note = ""
        else:
            test_note = test_note[0]

        # Append result to results file
        echo_to_file(results_file,
                     "%s:%s %s\n" % (test_name, test_result, test_note),
                     append=True)

        testsuite_logging.append_to_logfile(test_name, result_dir)

        test_status = test_result.split(':')[0]
        if test_status not in (DIFF_STATUS + CRASH_STATUS):
            # The command line log is not useful in these cases so it is
            # removed.
            cmdlog = result_dir + '/' + test_name + '.log'
            if os.path.isfile(cmdlog):
                rm(cmdlog)

        if metrics is not None:
            diffs_format = options.diffs_format if hasattr(
                options, 'diffs_format') else None

            # Set last test name
            metrics['last'] = test_name

            # Update metrics and diffs or xfail_diffs file
            diffs_file = os.path.join(result_dir, 'diffs')
            xfail_diffs_file = os.path.join(result_dir, 'xfail_diffs')

            if test_status in DIFF_STATUS:
                metrics['failed'] += 1
                if test_name not in metrics['old_diffs']:
                    metrics['new_failed'] += 1
                get_test_diff(result_dir, test_name, test_note,
                              test_result, diffs_file, diffs_format)
            elif test_status in CRASH_STATUS:
                metrics['crashed'] += 1
                if test_name not in metrics['old_crashes']:
                    metrics['new_crashed'] += 1
                get_test_diff(result_dir, test_name, test_note,
                              test_result, diffs_file, diffs_format)
            elif test_status in XFAIL_STATUS:
                get_test_diff(result_dir, test_name, test_note,
                              test_result, xfail_diffs_file, diffs_format)

            if max_consecutive_failures and process != SKIP_EXECUTION:
                # Count number of consecutive failures
                if test_status in FAIL_STATUS:
                    # ignore XFAIL
                    if test_status not in XFAIL_STATUS:
                        metrics['max_consecutive_failures'] += 1
                elif test_status in SKIP_STATUS:
                    # ignore DEAD or SKIP tests
                    pass
                else:
                    metrics['max_consecutive_failures'] = 0

            # Update global status
            s = []
            if "JOB_ID" in os.environ:
                s.append("%s running tests since %s\n" % (
                    os.environ['JOB_ID'], start_time_str))

            s.append("%(run)s out of %(total)s processed (now at %(last)s)"
                     % metrics)
            s.append("%(new_failed)s new potential regression(s)"
                     " among %(failed)s" % metrics)
            s.append("%(new_crashed)s new crash(es) among %(crashed)s"
                     % metrics)
            echo_to_file(os.path.join(result_dir, 'status'),
                         '\n'.join(s) + '\n')

        if process != SKIP_EXECUTION:
            # else the test has been skipped. No need to print its status.
            if test_status in (DIFF_STATUS + CRASH_STATUS):
                logging_func = logging.error
            else:
                logging_func = logging.info

            logging_func("%-30s %s %s" % (test_name, test_result, test_note))

            if output_diff:
                diff_filename = result_dir + '/' + test_name + '.diff'
                if os.path.exists(diff_filename):
                    with open(diff_filename) as diff_file:
                        logging_func(diff_file.read().strip())

        # Exit the mainloop if too many errors (more than
        # max_consecutive_failures)
        if metrics and max_consecutive_failures \
                and process != SKIP_EXECUTION and metrics[
                    'max_consecutive_failures'] >= max_consecutive_failures:
            raise TooManyErrors

    return collect_result


def generate_run_testcase(driver, discs, options, use_basename=True):
    """Generate a basic run_test command.

    :param driver: test script to run
    :type driver: str
    :param discs: A list of discriminants, or None for no discriminant.
    :type discs: list[str] | None
    :param options: test driver and Main options
    :param use_basename: if True, use the test directory's basename to
        compute the test name; otherwise, use its relative path.
    :type use_basename: bool
    """
    def run_testcase(test, job_info):
        """Run the given test.

        See mainloop documentation
        """
        skip_if_ok = hasattr(options, 'skip_if_ok') and options.skip_if_ok
        skip_if_run = hasattr(
            options, 'skip_if_already_run') and options.skip_if_already_run
        skip_if_dead = hasattr(
            options, 'skip_if_dead') and options.skip_if_dead

        result_dir = options.output_dir

        if skip_if_ok or skip_if_run or skip_if_dead:
            try:
                if use_basename:
                    test_name = os.path.basename(test)
                else:
                    test_name = os.path.relpath(test, os.getcwd())

                old_result_file = os.path.join(
                    result_dir, test_name + '.result')
                if os.path.exists(old_result_file):
                    if skip_if_run:
                        return SKIP_EXECUTION
                    old_result = split_file(old_result_file)[0].split(':')[0]
                    if skip_if_ok and old_result in ('OK', 'UOK', 'PASSED'):
                        return SKIP_EXECUTION
                    if skip_if_dead and old_result == 'DEAD':
                        return SKIP_EXECUTION
            except FileUtilsError:
                logging.debug("Cannot get old result for %s" % test)
                pass

        # VxWorks tests needs WORKER_ID to be set in order to have an id for
        # vxsim that will not collide with other instances.
        os.environ['WORKER_ID'] = str(job_info[0])

        cmd = [sys.executable, driver,
               '-d', ",".join(discs or []),
               '-o', result_dir,
               '-t', options.tmp,
               test]
        if options.verbose:
            cmd.append('-v')
        if hasattr(options, 'host'):
            if options.host:
                cmd.append('--host=' + options.host)
            if options.build:
                cmd.append('--build=' + options.build)
            if options.target:
                cmd.append('--target=' + options.target)
        if not options.enable_cleanup:
            cmd.append('--disable-cleanup')
        if hasattr(options,
                   'restricted_discs') and options.restricted_discs:
            cmd.extend(('-r', options.restricted_discs))
        if options.failed_only:
            cmd.append('--failed-only')
        if options.timeout:
            cmd.append('--timeout=' + options.timeout)
        if options.use_basename:
            cmd.append('--use-basename')
        return Run(cmd, bg=True, output=None)
    return run_testcase


def setup_result_dir(options):
    """Save old results and create new result dir.

    :param options: test driver and Main options. This dictionary will be
        modified in place to set: `results_file`, the path to the results file,
        `report_file`, the path to the report file. Note that
        `output_dir` and `old_output_dir` might be modified if
        keep_old_output_dir is True

    Required options are `output_dir`, `keep_old_output_dir`,
    `old_output_dir`, `skip_if_ok` and `skip_if_already_run`.
    Where:

    - output_dir: directory containing test result
    - keep_old_output_dir: if True, move last results in
      old_output_dir
    - old_output_dir:directory where the last results are kept.
      Note that if old_output_dir is None, and keep_old_output_dir
      is True, the last tests results will be moved in
      output_dir/old and the new ones in output_dir/new
    - skip_if_ok, skip_if_already_run: if one of these options is set to
      True, then just remove the results file.
    """
    output_dir = options.output_dir

    if options.keep_old_output_dir and options.old_output_dir is None:
        options.old_output_dir = os.path.join(output_dir, 'old')
        options.output_dir = os.path.join(output_dir, 'new')

    options.results_file = os.path.join(options.output_dir, 'results')
    options.report_file = os.path.join(options.output_dir, 'report')

    if options.skip_if_ok or options.skip_if_already_run:
        # Remove only the results file
        rm(options.results_file)
    else:
        if not options.keep_old_output_dir:
            # We don't want to keep old results. Just clean the new output_dir
            if os.path.exists(options.output_dir):
                rm(options.output_dir, True)
        else:
            # Move output_dir to old_output_dir
            if os.path.exists(options.old_output_dir):
                rm(options.old_output_dir, True)
            if os.path.exists(options.output_dir):
                mv(options.output_dir, options.old_output_dir)
            else:
                mkdir(options.old_output_dir)

    mkdir(options.output_dir)

    # For the testsuites that used gnatpython.testdriver.add_run_test_options,
    # the user has the option of requesting that the environment be dumped
    # in the form of a shell script inside the output_dir.  If requested,
    # do it now.
    if hasattr(options, 'dump_environ') and options.dump_environ:
        with open(os.path.join(options.output_dir, 'environ.sh'), 'w') as f:
            for var_name in sorted(os.environ):
                f.write('export %s=%s\n'
                        % (var_name, quote_arg(os.environ[var_name])))


def compute_next_dyn_poll(poll_counter, poll_sleep):
    """Adjust the polling delay."""
    # if two much polling is done, the loop might consume too
    # much resources. In the opposite case, we might wait too
    # much to launch new jobs. Adjust accordingly.
    if poll_counter > 8 and poll_sleep < 1.0:
        poll_sleep *= 1.25
        logger.debug('Increase poll interval to %f' % poll_sleep)
    elif poll_sleep > 0.0001:
        poll_sleep *= 0.75
        logger.debug('Decrease poll interval to %f' % poll_sleep)
    return poll_sleep


def get_test_diff(
        result_dir, name, note, result_str, filename, diffs_format):
    """Update diffs and xfail_diffs files.

    :param result_str: content of the test .result file
    :type result_dir: str
    :param name: test name
    :type name: str
    :param note: annotation
    :type note: str
    :param filename: file to update
    :type filename: str
    :param diffs_format: if 'diff' show diff content else show the expected /
        actual output
    :type diffs_format: str | None
    """
    result = ["================ Bug %s %s" % (name, note)]
    if diffs_format == 'diff':
        result += split_file(result_dir + '/' + name + '.diff',
                             ignore_errors=True)[0:2000]
    else:
        if re.match("DIFF:unexpected", result_str):
            result.append("---------------- unexpected output")
            result += split_file(result_dir + '/' + name + '.out',
                                 ignore_errors=True)[0:100]

        elif re.match("CRASH:", result_str):
            result.append("---------------- unexpected output")
            result += split_file(result_dir + '/' + name + '.out',
                                 ignore_errors=True)[0:30]

        elif re.match("DIFF:output|XFAIL:|FAILED:|PROBLEM:", result_str):
            result.append("---------------- expected output")
            result += split_file(result_dir + '/' + name + '.expected',
                                 ignore_errors=True)[0:2000]
            result.append("---------------- actual output")
            result += split_file(result_dir + '/' + name + '.out',
                                 ignore_errors=True)

    echo_to_file(filename, result, append=True)


def add_mainloop_options(main, extended_options=False):
    """Add command line options to control mainloop default.

    :param main: a gnatpython.main.Main instance
    :type main: `class`:gnatpython.main.Main`
    :param extended_options: if True, add additional options that require
        using the gnatpython testdriver and the generate_run_testcase,
        generate_collect_result functions.
    :type extended_options: bool
    """
    mainloop_opts = main.create_option_group("Mainloop control""")

    mainloop_opts.add_option(
        "-j", "--jobs",
        dest="mainloop_jobs",
        type="int",
        metavar="N",
        default=1,
        help="Specify the number of jobs to run simultaneously")
    mainloop_opts.add_option(
        "--abort-file",
        dest="mainloop_abort_file",
        metavar="FILE",
        default="",
        help="Specify a file whose presence cause loop abortion")

    if extended_options:
        mainloop_opts.add_option(
            "--skip-if-ok",
            action="store_true",
            default=False,
            help="If the test result is found and is OK skip the test")
        mainloop_opts.add_option(
            "--skip-if-dead",
            action="store_true",
            default=False,
            help="If the test result is found and is DEAD skip the test")
        mainloop_opts.add_option(
            "--skip-if-already-run",
            action="store_true",
            default=False,
            help="If the test result is found skip the test")
        mainloop_opts.add_option(
            "--old-output-dir",
            dest="old_output_dir",
            metavar="DIR",
            default=None,
            help="Select old output dir")
        mainloop_opts.add_option(
            "--keep-old-output-dir",
            dest="keep_old_output_dir",
            action="store_true",
            help="Keep old output dir. Note that if --old-output-dir is not"
            " set, the old output dir will be stored in OUTPUT_DIR/old and"
            " the new test outputs in OUTPUT_DIR/new")
        mainloop_opts.add_option(
            "--max-consecutive-failures",
            default=0,
            help="If there are more than N consecutive failures, the testsuite"
            " is aborted. If set to 0 (default) then the testsuite will never"
            " be stopped")

    main.add_option_group(mainloop_opts)

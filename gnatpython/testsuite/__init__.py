from gnatpython.env import Env
from gnatpython.ex import Run
from gnatpython.fileutils import find, rm, mkdir, mv, echo_to_file, touch
from gnatpython.yaml_utils import load_with_config
from gnatpython.logging_util import RAW, add_handlers
from gnatpython.main import Main
from gnatpython.mainloop import MainLoop, add_mainloop_options, TooManyErrors
from gnatpython.reports import ReportDiff
from gnatpython.stringutils import quote_arg
from gnatpython.testsuite.driver import TestDriver
from gnatpython.testsuite.result import Result

import collections
import traceback
import logging
import os
import yaml
import sys
import re
import tempfile

logger = logging.getLogger('testsuite')


class TestsuiteCore(object):
    """Testsuite Core driver.

    This class is the base of Testsuite class and should not be instanciated.
    It's not recommended to override any of the functions declared in it.

    See documentation of Testsuite class for overridable methods and
    variables.
    """

    def __init__(self, root_dir):
        """Testsuite constructor.

        :param root_dir: root dir of the testsuite. Usually the directory in
            which testsuite.py and runtest.py are located
        :type root_dir: str | unicode
        """
        self.root_dir = os.path.abspath(root_dir)
        self.test_dir = os.path.join(self.root_dir, self.TEST_SUBDIR)
        self.global_env = {}
        self.test_env = {}
        self.global_env['root_dir'] = self.root_dir
        self.global_env['test_dir'] = self.test_dir
        self.consecutive_failures = 0

    def split_variant(self, name):
        """Split test scenario from the variant.

        :param name: the combination of test scenario and the variant
        :type name: str
        :return: a tuple with the test scnerio file and the variant
        :rtype: (str, str) | (str, None)
        """
        if '|' in name:
            test_scenario, test_variant_str = name.split('|', 1)
            test_variant = yaml.load(test_variant_str)
            return (test_scenario, test_variant)
        else:
            return [name, None]

    def test_result_filename(self, test_case_file, variant):
        """Return the name of the file in which the result are stored.

        :param test_case_file: path to a test case scenario relative to the
            test directory
        :type test_case_file: str | unicode
        :param variant: the test variant
        :type variant: str
        :return: the test name. Note that test names should not contain path
            separators
        :rtype: str | unicode
        """
        return os.path.join(self.output_dir,
                            self.test_name(test_case_file, variant)) + '.yaml'

    def dump_test_result(self, result=None, status=None, msg=None):
        """Dump a result into the test result file in the output directory.

        :param result: the result object to be dump. If None a new Result
            object is created on the fly
        :type result: Result | None
        :param status: override the status of the result object
        :type status: str
        :param msg: override the short message associated with the result
        :type msg: str | unicode
        """
        if result is None:
            result = Result(self.test_env)

        if status is not None:
            result.set_status(status, msg)

        with open(self.test_result_filename(self.test_case_file,
                                            self.test_variant),
                  'wb') as fd:
            yaml.dump(result, fd)

    def test_main(self):
        """Main function for the script in charge of running a single test.

        The script expect two parameters on the command line:

        * the output dir in which the results of the tests are saved
        * the path to the test.yaml file relative to the tests directory
        """
        self.output_dir = sys.argv[1]
        self.test_case_file, self.test_variant = \
            self.split_variant(sys.argv[2])

        logging.getLogger('').setLevel(RAW)
        add_handlers(level=RAW,
                     format='%(asctime)s: %(name)-24s: '
                     '%(levelname)-8s %(message)s',
                     filename=os.path.join(
                         self.output_dir,
                         self.test_name(self.test_case_file,
                                        self.test_variant) + '.log'))

        with open(os.path.join(self.output_dir, 'global_env.yaml'),
                  'rb') as fd:
            self.global_env = yaml.load(fd.read())

        # Set target information
        Env().build = self.global_env['build']
        Env().host = self.global_env['host']
        Env().target = self.global_env['target']

        # Load testcase file
        self.test_env = load_with_config(
            os.path.join(self.test_dir, self.test_case_file),
            Env().to_dict())

        # Ensure that the test_env act like a dictionary
        if not isinstance(self.test_env, collections.Mapping):
            self.test_env = {'test_name': self.test_name(self.test_case_file,
                                                         self.test_variant),
                             'test_yaml_wrong_content': self.test_env}
            logger.error("abort test because of invalid test.yaml")
            self.dump_test_result(status="PROBLEM", msg="invalid test.yaml")
            return

        # Add to the test environment the directory in which the test.yaml is
        # stored
        self.test_env['test_dir'] = os.path.join(
            self.global_env['test_dir'],
            os.path.dirname(self.test_case_file))
        self.test_env['test_case_file'] = self.test_case_file
        self.test_env['test_variant'] = self.test_variant
        self.test_env['test_name'] = self.test_name(self.test_case_file,
                                                    self.test_variant)

        if 'driver' in self.test_env:
            driver = self.test_env['driver']
        else:
            driver = self.default_driver

        logger.debug('set driver to %s' % driver)
        if driver not in self.DRIVERS or \
                not issubclass(self.DRIVERS[driver], TestDriver):
            self.dump_test_result(status="PROBLEM", msg="cannot set driver")
            return

        try:
            instance = self.DRIVERS[driver](self.global_env, self.test_env)
        except Exception as e:
            error_msg = str(e)
            error_msg += "Traceback:\n"
            error_msg += "\n".join(traceback.format_tb(sys.exc_traceback))
            logger.error(error_msg)
            self.dump_test_result(status="PROBLEM",
                                  msg="exception during driver loading: %s"
                                  % str(e).split('\n')[0])
            return

        try:
            instance.tear_up()
            if instance.result.status == 'UNKNOWN':
                instance.run()
            if instance.result.status == 'UNKNOWN':
                instance.analyze()
        except Exception as e:
            error_msg = str(e)
            error_msg += "Traceback:\n"
            error_msg += "\n".join(traceback.format_tb(sys.exc_traceback))
            logger.error(error_msg)
            instance.result.set_status("PROBLEM",
                                       "exception: %s" % str(e).split('\n')[0])

        instance.tear_down()

        self.dump_test_result(instance.result)

    def dump_testsuite_result(self):
        """Dump testsuite result files.

        Dump the content of all <test>.yaml files and create report,
        result and comment files.
        """
        testsuite_results = os.path.join(self.output_dir, 'results')
        testsuite_report = os.path.join(self.output_dir, 'report')
        testsuite_comment = os.path.join(self.output_dir, 'comment')

        with open(testsuite_comment, 'w') as f:
            self.write_comment_file(f)

        touch(testsuite_results)

        # Mapping: test status -> hits. Computed to display the testsuite run
        # summary.
        summary = collections.defaultdict(lambda: 0)

        for test_result in find(self.output_dir, '*.yaml'):

            if os.path.basename(test_result) != 'global_env.yaml':
                with open(test_result, "rb") as fd:
                    tr_yaml = yaml.load(fd)

                if tr_yaml:
                    # result in results file
                    echo_to_file(testsuite_results,
                                 '%s:%s: %s\n' %
                                 (tr_yaml.test_env['test_name'],
                                  tr_yaml.status,
                                  tr_yaml.msg),
                                 append=True)

                    tr_yaml.dump_result(self.output_dir)
                    summary[tr_yaml.status] += 1

        try:
            report = ReportDiff(self.output_dir,
                                self.old_output_dir,
                                use_diff=True)
        except:
            report = ReportDiff(self.output_dir,
                                self.old_output_dir)

        report.txt_image(testsuite_report)

        summary_msg = ['Summary:']
        for status in sorted(summary):
            hits = summary[status]
            summary_msg.append('  {}: {} test{}'.format(
                status, summary[status],
                's' if hits > 1 else ''
            ))
        logging.info('\n'.join(summary_msg))

    def testsuite_main(self):
        """Main for the main testsuite script."""
        self.main = Main(add_targets_options=self.CROSS_SUPPORT)

        # Add common options
        add_mainloop_options(self.main)
        self.main.add_option(
            "-o", "--output-dir",
            metavar="DIR",
            default="./out",
            help="select output dir")
        self.main.add_option(
            "-t", "--temp-dir",
            metavar="DIR",
            default=Env().tmp_dir)
        self.main.add_option(
            "--max-consecutive-failures",
            default=0,
            help="If there are more than N consecutive failures, the testsuite"
            " is aborted. If set to 0 (default) then the testsuite will never"
            " be stopped")
        self.main.add_option(
            "--keep-old-output-dir",
            default=False,
            action="store_true",
            help="This is default with this testsuite framework. The option"
            " is kept only to keep backward compatibility of invocation with"
            " former framework (gnatpython.testdriver)")
        self.main.add_option(
            "--disable-cleanup",
            dest="enable_cleanup",
            action="store_false",
            default=True,
            help="disable cleanup of working space")
        self.main.add_option(
            "--show-error-output",
            action="store_true",
            help="When testcases fail, display their output. This is for"
                 " convenience for interactive use."
        )
        self.main.add_option(
            "--dump-environ",
            dest="dump_environ",
            action="store_true",
            default=False,
            help="Dump all environment variables in a file named environ.sh,"
            " located in the output directory (see --output-dir). This"
            " file can then be sourced from a Bourne shell to recreate"
            " the environement that existed when this testsuite was run"
            " to produce a given testsuite report."
        )

        # Add user defined options
        self.add_options()

        # parse options
        self.main.parse_args()

        # At this stage compute commonly used paths
        # Keep the working dir as short as possible, to avoid the risk
        # of having a path that's too long (a problem often seen on
        # Windows, or when using WRS tools that have their own max path
        # limitations).
        # Note that we do make sure that working_dir is an absolute
        # path, as we are likely to be changing directories when
        # running each test. A relative path would no longer work
        # under those circumstances.
        d = os.path.abspath(self.main.options.output_dir)
        self.output_dir = os.path.join(d, 'new')
        self.old_output_dir = os.path.join(d, 'old')

        if not os.path.isdir(self.main.options.temp_dir):
            logging.critical("temp dir '%s' does not exist",
                             self.main.options.temp_dir)
            sys.exit(1)

        self.working_dir = tempfile.mkdtemp(
            '', 'tmp', os.path.abspath(self.main.options.temp_dir))

        # Create the new output directory that will hold the results
        self.setup_result_dir()

        # Store in global env: target information and common paths
        self.global_env['build'] = Env().build
        self.global_env['host'] = Env().host
        self.global_env['target'] = Env().target
        self.global_env['output_dir'] = self.output_dir
        self.global_env['working_dir'] = self.working_dir
        self.global_env['options'] = self.main.options

        # User specific startup
        self.tear_up()

        # Retrieve the list of test
        self.test_list = self.get_test_list(self.main.args)

        # Dump global_env so that it can be used by test runners
        with open(os.path.join(self.output_dir, 'global_env.yaml'),
                  'wb') as fd:
            fd.write(yaml.dump(self.global_env))

        # Launch the mainloop
        self.total_test = len(self.test_list)
        self.run_test = 0

        MainLoop(self.test_list, self.launch_test, self.collect_result)

        self.dump_testsuite_result()

        # Clean everything
        self.tear_down()

    def launch_test(self, name, job_info):
        """Launch a test (mainloop callback)

        :param name: path to a test case file relative to the test directory
        :type name: str | unicode
        :param job_info: additional information associated with the worker
        :type job_info: (int, int)
        :return: a Run object
        :rtype: gnatpython.ex.Run
        """
        os.environ['WORKER_ID'] = str(job_info[0])
        return Run([sys.executable,
                    os.path.join(self.root_dir, self.TEST_RUNNER),
                    self.output_dir, name],
                   bg=True,
                   output=None)

    def collect_result(self, name, process, _job_info):
        """Collect test results.

        See gnatpython.mainloop documentation
        """
        del process, _job_info
        test_name, test_variant = self.split_variant(name)
        result_file = self.test_result_filename(test_name, test_variant)
        if not os.path.isfile(result_file):
            result = Result()
            result.set_status("CRASH", "cannot find result file")
            with open(result_file, "wb") as fd:
                yaml.dump(result, fd)
        else:
            with open(result_file, "rb") as fd:
                result = yaml.load(fd)

        self.run_test += 1
        msg = "(%s/%s): %-32s: %s %s" % \
            (self.run_test, self.total_test,
             self.test_name(test_name, test_variant),
             result.status, result.msg)

        if Result.STATUS[result.status]:
            logger.error(msg)
            self.consecutive_failures += 1
            if self.main.options.show_error_output:
                logger.error('Testcase output was:\n' + result.actual_output)
        else:
            logger.info(msg)
            self.consecutive_failures = 0

        if 0 < self.main.options.max_consecutive_failures < \
                self.consecutive_failures:
            raise TooManyErrors

    def setup_result_dir(self):
        """Create the output directory in which the results are stored."""
        if os.path.isdir(self.old_output_dir):
            rm(self.old_output_dir, True)
        if os.path.isdir(self.output_dir):
            mv(self.output_dir, self.old_output_dir)
        mkdir(self.output_dir)

        if self.main.options.dump_environ:
            with open(os.path.join(self.output_dir, 'environ.sh'), 'w') as f:
                for var_name in sorted(os.environ):
                    f.write('export %s=%s\n'
                            % (var_name, quote_arg(os.environ[var_name])))


class Testsuite(TestsuiteCore):
    """Testsuite class.

    When implementing a new testsuite you should create a class that
    inherit from this class.
    """
    CROSS_SUPPORT = False
    # set CROSS_SUPPORT to true if the driver should accept --target, --build
    # --host switches

    TEST_SUBDIR = '.'
    # Subdir in which the tests are actually stored

    TEST_RUNNER = 'run-test'
    # Name of the script that should be launched to run a given test

    DRIVERS = {}
    # Dictionary that map a name to a class that inherit from TestDriver

    @property
    def default_driver(self):
        """Return the default driver to be used.

        The return value is used only if the test.yaml file does not contain
        any ``driver`` key. Note that you have access to the current test.yaml
        location using the attribute ``self.test_case_file``.

        :return: the driver to be used by default
        :rtype: str
        """
        return None

    def test_name(self, test_case_file, variant):
        """Compute the test name given a testcase spec.

        This function can be overriden. By default it uses the name of the
        directory in which the test.yaml is stored

        Note that the test name should be valid filename (not dir seprators,
        or special characters such as ``:``, ...).

        :param test_case_file: path to test.yaml file (relative to test subdir
        :type test_case_file: str | unicode
        :param variant: the test variant or None
        :type variant: str | None
        :return: the test name
        :rtype: basestring
        """
        result = os.path.dirname(
            test_case_file).replace('\\', '/').rstrip('/').replace('/', '__')
        if variant is not None:
            result += '.' + \
                str(variant).translate(None, ',:/\\[]\'"{}').replace(' ', '_')
        return result

    def get_test_list(self, sublist):
        """Retrieve the list of tests.

        The default method looks for all test.yaml files in the test
        directory. If a test.yaml has a variants field, the test is expanded
        in several test, each test being associated with a given variant.

        This function may be overriden.
        At this stage the self.global_env (after update by the tear_up
        procedure) is available.

        :param sublist: a list of tests scenarios or patterns
        :type sublist: list[str]
        :return: the list of selected test
        :rtype: list[str]
        """
        # First retrive the list of test.yaml files
        result = [os.path.relpath(p, self.test_dir).replace('\\', '/')
                  for p in find(self.test_dir, 'test.yaml')]
        if sublist:
            filtered_result = []
            path_selectors = [os.path.relpath(os.path.abspath(s),
                                              self.test_dir).replace('\\', '/')
                              for s in sublist]
            for p in result:
                for s in path_selectors:
                    if re.match(s, p):
                        filtered_result.append(p)
                        continue

            result = filtered_result

        # For each of them look for a variants field
        expanded_result = []
        for test in result:
            test_env = load_with_config(
                os.path.join(self.test_dir, test),
                Env().to_dict())

            if test_env and 'variants' in test_env:
                for variant in test_env['variants']:
                    expanded_result.append("%s|%s" % (test,
                                                      yaml.dump(variant)))
            else:
                expanded_result.append(test)

        return expanded_result

    def tear_up(self):
        """Execute operations before launching the testsuite.

        At this stage arguments have been read. The next step will be
        get_test_list.

        A few things can be done at this stage:

        * set some environment variables
        * adjust self.global_env (dictionary passed to all tests)
        * take into account testsuite specific options
        """
        pass

    def tear_down(self):
        """Execute operation when finalizing the testsuite.

        By default clean the working directory in which the tests
        were run
        """
        if self.main.options.enable_cleanup:
            rm(self.working_dir, True)

    def add_options(self):
        """Used to add testsuite specific switches.

        We can add your own switches by calling self.main.add_option
        function
        """
        pass

    def write_comment_file(self, comment_file):
        """Write the comment file's content.

        :param comment_file: File descriptor for the comment file.
            Overriding methods should only call its "write" method
            (or print to it).
        :type comment_file: file
        """
        pass

############################################################################
#                                                                          #
#                         TESTSUITE_LOGGING.PY                             #
#                                                                          #
#            Copyright (C) 2013-2014 Ada Core Technologies, Inc.           #
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

r"""The testsuite_logging module.

This module offers a standard way to log command lines spawned by an
ex.Run object. It is also useful for gathering target specific options
on the compiler toolchain.

A testsuite logging can be set up in 3 steps :
----------------------------------------------

# 1) Import the module :
from gnatpython import testsuite_logging

# 2) Activate the logging before the testcase is launched :
testsuite_logging.setup_logging(test_name, temp_dir)

# 3) Aggregate the logged command lines, in a collect_result function :
testsuite_logging.append_to_logfile(test_name, result_dir)

/!\ Warning :
-------------

The second step should be done where the actual test scenario is run
(e.g. where ex.Run actually spawns the tested tools).

According to the testsuite, it could be either in :
- a TestRunner instance
  (The testsuite and the testcase are run in the same process)
- a module imported on the script containing the testcase scenario (test.py)
  (The testcase is run in another process than the testsuite one)

"""

import re
import os
from gnatpython import ex
from gnatpython.fileutils import rm


TRACKED_TOOLS = ('gnatmake', 'gcc', 'gprbuild', 'gnatbind', 'gnatlink')


class CommandCollector:
    """Command line aggregator.

    Aggregator that computes an ordered intersection between options for a
    specific tool. The order is kept because, for example, linker options
    (--largs) should not be lost.

    ATTRIBUTES
      options_for_tool: dict containing all common options gathered
        for a specific tool
    """

    def __init__(self):
        """CommandCollector constructor."""
        self.options_for_tool = {}

    def list_intersection(self, list1, list2):
        """Compute an ordered list intersection.

        A set intersection is not used because one list order should be at
        least kept. The list from which the order is kept does not matter
        as both lists contain command line options in the right order.

        For example, the intersection of the following lists
        (after splitting) :
        * i586-wrs-vxworks-gnatmake p --RTS=rtp -g -largs -vxsim
        * i586-wrs-vxworks-gnatmake test1 --RTS=rtp -g -largs -vxsim
        should be :
        i586-wrs-vxworks-gnatmake --RTS=rtp -g -largs -vxsim

        It is necessary that '-vxsim' comes after '-largs'.
        (if a set had been used, it would not have been always the case).

        :type list1: list
        :type list2: list

        :return: a list whose elements appear in both list, preserving the
            order of one of them.
        :rtype: list
        """
        if len(list2) > len(list1):
            tmp = list2
            list2 = list1
            list1 = tmp
        return [item for item in list2 if item in list1]

    def add_cmd(self, command_line_image):
        """Add and process a command line image.

        If the command line tool was not used before, its options are
        straightforwardly added to the options_for_tool database.

        Otherwise, the intersection between the command line given's options,
        and the previous options used for the same tool is computed.

        At the end of the testsuite execution, the database will contains
        the common options used by all testcases.

        :param command_line_image: a string containing a command line
        :type command_line_image: str
        """
        cmd_tokens = command_line_image.split(' ')
        tool = cmd_tokens.pop(0)
        if tool not in self.options_for_tool:
            self.options_for_tool[tool] = cmd_tokens
        else:
            self.options_for_tool[tool] = \
                self.list_intersection(self.options_for_tool[tool], cmd_tokens)

    def load_log(self, filename):
        """Populate the options_for_tool database.

        :param filename: a log path (usually testsuite_support.log)
        :type filename: str
        """
        if os.path.isfile(filename):
            with open(filename) as f:
                for line in f:
                    line = line.rstrip()
                    self.add_cmd(line)

    def write_log(self, filename):
        """Serialize the options_for_tool database to a text file.

        :param filename: a log path (usually testsuite_support.log)
        :type filename: str
        """
        rm(filename)
        with open(filename, 'w') as cmdlog:
            for tool in self.options_for_tool:
                line = tool + ' ' + ' '.join(self.options_for_tool[tool])
                cmdlog.write(line + '\n')


def filter_command_line_image(cmdline_image):
    """Detect the tracked_tools and if so, filter the command line image.

    :param cmdline_image: a string containing a command line image
    :type cmdline_image: str

    :return: a string containing a filtered command line image (without a full
        path) or an empty string if no tracked tool is found
    :rtype: str
    """
    pattern = '[^/\s]*(' + '|'.join(TRACKED_TOOLS) + ')\s.*'
    match = re.search(pattern, cmdline_image)
    if match is not None:
        return str(match.group(0))
    # An empty string is returned when cmdline_image does not contains any tool
    return ''


def append_to_logfile(test_name, result_dir):
    """Aggregate a command line log file with the testsuite_support.log file.

    Usually this function is called in a collect_result function body

    :param test_name: a testcase name
    :type test_name: str
    :param result_dir: the testsuite result dir
    :type result_dir: str
    """
    cmdlog = result_dir + '/' + test_name + '.log'
    if os.path.isfile(cmdlog):
        command_collector = CommandCollector()
        command_collector.load_log(result_dir + '/testsuite_support.log')
        with open(cmdlog) as f:
            for line in f:
                command_line_image = line.split('; ')[1]
                filtered_cmd = filter_command_line_image(command_line_image)
                if filtered_cmd != '':
                    command_collector.add_cmd(filtered_cmd)
        command_collector.write_log(result_dir + '/testsuite_support.log')


def write_comment(result_dir):
    """Write the content of testsuite_support.log into the comment file.

    :param result_dir: the testsuite result dir
    :type result_dir: str
    """
    if not os.path.isfile(result_dir + '/testsuite_support.log'):
        return
    with open(result_dir + '/testsuite_support.log') as to_readfile:
        reading_file = to_readfile.read()
    with open(result_dir + '/comment', 'a') as writefile:
        writefile.write("tools options : ")
        writefile.write(reading_file)


def setup_logging(test_name, temp_dir):
    """General function to setup a testsuite logging.

    The call is done before the testcase launch, either in a TestRunner
    instance (for testcases running in the same process than the testsuite)
    or a module imported in all testcases python script (eg. test.py) for
    testcases running on separate process.

    :param test_name: a testcase name
    :type test_name: str
    :param temp_dir: temporary directory / working directory
    :type temp_dir: str

    :return: the command line log file corresponding to the testcase
    :rtype: str
    """
    cmdlog = temp_dir + '/' + test_name + '.log'
    ex.enable_commands_handler(cmdlog)
    return cmdlog

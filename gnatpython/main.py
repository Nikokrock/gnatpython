############################################################################
#                                                                          #
#                              MAIN.PY                                     #
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

"""Main program initialization.

This package provides a class called Main used to initialize a python script
invoked from command line. The main goal is to ensure consistency in term of
interface, documentation and logging activities for all scripts using
gnatpython.

When a script uses this module, it should contain a docstring formatted in
the following way. Everything before the first empty line will be part of the
usage. Everything after will be considered as part of the description.

The script will support by default the following switches::

    -v|--verbose to enable verbose mode (a console logger is added)
    -h|--help    display information parsed in the docstring
    --log-file FILE
                 to redirect logs to a given file (this is independent from
                 verbose option

In addition, if the add_targets_options parameter is set to True
when instantiating an object of class Main, the following switches
will also be provided::

    --target     to set the target
    --host       to set the host
    --build      to set the build

Note that the Main class now support the use of two classes that
perform the parsing of the command line:

* optparse.OptionParser,
* and argparse.ArgumentParser.

Which parser gets used is determined by the value of the ``option_parser_kind``
parameter during __init__. For compatibility reasons, the default is to use
optparse, but we recommend that you use argparse because the former is now
deprecated and supported only up to Python 2.7.


*EXAMPLES*

If you have the following script test.py::

    import logging
    from gnatpython.main import *

    m = Main(add_targets_options=True,
             option_parser_kind=MAIN_USE_ARGPARSE)
    m.option_parser.add_option("-t",
                               "--test",
                               dest="test",
                               metavar="STRING",
                               default="default",
                               help="option example")
    m.parse_args()
    logging.info('Test begin')
    logging.debug('test option value: ' + m.options.test)
    logging.debug('target option value: ' + m.options.target)
    logging.debug('host option value: ' + m.options.host)
    logging.info('Test end')

Here are some invocation examples::

    $ gnatpython test.py --help
    usage: test

    optional arguments:
      -h, --help            show this help message and exit
      -v, --verbose         add some verbosity for debugging purposes
      --target=TARGET       set target
      --host=HOST           set host
      --build=HOST          set build
      -t STRING, --test=STRING
                            option example

    $ gnatpython test.py -v
    root        : INFO     Test begin
    root        : DEBUG    test option value: default
    root        : DEBUG    target option value:
    root        : DEBUG    host option value:
    root        : INFO     Test end

    $ gnatpython test.py
    root        : INFO     Test begin
    root        : INFO     Test end
"""
from optparse import OptionGroup, OptionParser, TitledHelpFormatter

import logging
import os
import re
import sys
import signal

import gnatpython.logging_util
from gnatpython.logging_util import (highlight, COLOR_RED, COLOR_YELLOW,
                                     COLOR_GREEN, COLOR_CYAN)
from gnatpython.env import Env


class MainError (Exception):
    """MainError exception."""
    pass


class MainHelpFormatter(TitledHelpFormatter):
    """Format help with underlined section headers.

    Do not modify description formatting.
    """

    def format_description(self, description):
        """Do not modify description."""
        return description

color_table = {
    ' (FAILED|DIFF)': COLOR_RED,
    ' (UOK)': COLOR_YELLOW,
    ' (OK|PASSED)': COLOR_GREEN,
    ' (XFAIL)': COLOR_CYAN,
    ' (DEAD)': COLOR_CYAN}


class ConsoleColorFormatter(logging.Formatter):
    """Formatter with color support.

    If level is ERROR or CRITICAL then the output color is set to red.
    Furthermore if some keyword such as PASSED,FAILED are detected then
    they are highlighted with an adequate color
    """

    def __init__(self, fmt=None, datefmt=None):
        logging.Formatter.__init__(self, fmt, datefmt)

    def format(self, record):
        output = logging.Formatter.format(self, record)
        if record.levelno >= logging.ERROR:
            output = highlight(output, fg=COLOR_RED)
        else:
            for k in color_table:
                output = re.sub(
                    k, ' ' + highlight("\\1", fg=color_table[k]), output)
        return output

# The different types of option parsers that the Main class supports:
#   - MAIN_USE_OPTPARSE: Use optparse.OptionParser.
#   - MAIN_USE_ARGPARSE: Use argparse.ArgumentParser.
(MAIN_USE_OPTPARSE, MAIN_USE_ARGPARSE) = range(2)


class Main(object):
    """Class that implement argument parsing.

    ATTRIBUTES
      name: name of the program (default is the filename with the extension)
      usage: contains the usage retrived from the main docstring
      description: contains the description retrieved from the main docstring
      option_parser_kind: The type of option parser to use. This must be one
        of the MAIN_USE_* constants above.
      option_parser: The object that will be used to parse the command-line
        options and arguments.
      options: object containing the result of option parsing (see python
        optparse module). Note that this object is made global by putting its
        value in Env.main_options.
      args: list of positional parameters after processing options
      add_option: this is in fact a method that can be used to add other
        options (see documentation of the Python module optparse)
    """

    def __init__(self, name=None, formatter=None,
                 require_docstring=True, add_targets_options=False,
                 option_parser_kind=MAIN_USE_OPTPARSE):
        """Init Main object.

        :param name: name of the program (if not specified the filename without
            extension is taken)
        :type name: str | None
        :param formatter: override the default formatter for console output
        :type formatter: str | None
        :param require_docstring: if True, raise MainError when the toplevel
            docstring is not found
        :type require_docstring: bool
        :param add_targets_options: add --target and --host options
        :type add_targets_options: bool
        :param option_parser_kind: The kind of option parser that should be
            be used.  For compatibility reasons, the default is
            to use optparse.OptionParser.
        :type option_parser_kind: int
        """
        # Set a signal handler for SIGTERM that will raise SystemExit
        # This is to let a gnatpython application enough time to perform
        # cleanup steps when killed by rlimit. rlimit first send a SIGTERM
        # then a SIGKILL 5 seconds later

        main = sys.modules['__main__']

        if name is not None:
            self.name = name
        else:
            self.name = os.path.splitext(os.path.basename(main.__file__))[0]

        docstring = main.__doc__
        if require_docstring and docstring is None:
            raise MainError('Doc string not found')

        if docstring is not None:
            usage_end = docstring.find('\n\n')
            if usage_end == -1 and require_docstring:
                raise MainError('Doc string must start with a usage, '
                                'followed by an empty line')

            self.usage = docstring[0:usage_end]
            self.description = docstring[usage_end + 2:]
        else:
            self.usage = None
            self.description = None

        # The "add_targets_options" attribute is no longer used
        # in this class' code. But, although it is not a documented
        # attribute of the class, we are keeping it nonetheless
        # for compatibility reason, in case someone actually uses it.
        self.add_targets_options = add_targets_options

        self.option_parser_kind = option_parser_kind
        if self.option_parser_kind == MAIN_USE_OPTPARSE:
            self.__parse_proxy = OptParseProxy()
        elif self.option_parser_kind == MAIN_USE_ARGPARSE:
            self.__parse_proxy = ArgParseProxy()
        else:
            raise MainError('Usupported option_parser_kind: %d'
                            % self.option_parser_kind)

        self.option_parser = self.__parse_proxy.new_option_parser(
            usage=self.usage, description=self.description)

        # Create the logging options in a specific option group.
        log_options = self.__parse_proxy.new_option_group(
            self.option_parser,
            "Various logging options")

        self.__parse_proxy.add_option(
            log_options,
            "-v", "--verbose",
            dest="verbose",
            action="store_true",
            default=False,
            help="add some verbosity for debugging purposes. "
            "Overrides --loglevel")
        self.__parse_proxy.add_option(
            log_options,
            "--log-file",
            dest="logfile",
            metavar="FILE",
            default="",
            help="add some logs into the specified file")
        self.__parse_proxy.add_option(
            log_options,
            "--enable-color",
            dest="enable_color",
            action="store_true",
            default=False,
            help="enable colors in log outputs")
        self.__parse_proxy.add_option(
            log_options,
            "--loglevel", default="INFO",
            action="store",
            help="defines a loglevel (RAW,DEBUG,INFO,ERROR) for"
            " stdout")

        if add_targets_options:
            self.add_target_options_handling(self.option_parser)

        self.options = None
        self.args = None
        self.formatter = formatter
        self.__log_handlers_set = False

        # By default do not filter anything. What is effectively logged will
        # be defined by setting/unsetting handlers
        logging.getLogger('').setLevel(gnatpython.logging_util.RAW)

        # Make the add_option function directly available to Main objects.
        # This method is deprecated, so we only make it available when
        # using optparse, where we want to preserve upward compatibility.
        if self.option_parser_kind == MAIN_USE_OPTPARSE:
            self.add_option = self.option_parser.add_option

        def sigterm_handler(signal, frame):
            """Automatically convert SIGTERM to SystemExit exception.

            This is done to give enough time to an application killed by
            rlimit to perform the needed cleanup steps
            """
            logging.critical('SIGTERM received')
            raise SystemExit('SIGTERM received')

        signal.signal(signal.SIGTERM, sigterm_handler)

    def add_target_options_handling(self, parser):
        """Add the --target, --host and --build options to the given parser.

        :param parser: A parser. This can be either self.option_parser, or
            a sub-command parser (if the option parser supports it).
        """
        self.__parse_proxy.add_option(
            parser,
            "--target",
            dest="target",
            metavar="TARGET[,TARGET_VERSION[,TARGET_MACHINE[,TARGET_MODE]]]",
            default="",
            help="set target")
        self.__parse_proxy.add_option(
            parser,
            "--host",
            dest="host",
            metavar="HOST[,HOST_VERSION]",
            default="",
            help="set host")
        self.__parse_proxy.add_option(
            parser,
            "--build",
            dest="build",
            metavar="BUILD[,BUILD_VERSION]",
            default="",
            help="set build")
        # We add a default to a fake option as a way to encode
        # the fact that this parser supports the standard
        # --host/target options.  That way, after the parser
        # is used to evaluate the command-line arguments, we can
        # determine from the result whether the parser was supporting
        # the standard --host/target options or not, and then process
        # them if we did.
        #
        # To avoid clashes with user-defined options, we use a dest
        # name that is improbable in practice.
        parser.set_defaults(gnatpython_main_target_options_supported=True)

    def parse_args(self, args=None):
        """Parse options and set console logger.

        :param args: the list of positional parameters. If None then
            ``sys.argv[1:]`` is used
        :type: list[str] | None
        """
        levels = {'RAW': gnatpython.logging_util.RAW,
                  'DEBUG': logging.DEBUG,
                  'INFO': logging.INFO,
                  'ERROR': logging.ERROR,
                  'CRITICAL': logging.CRITICAL}

        (self.options, self.args) = self.__parse_proxy.parse_args(
            self.option_parser, args)

        if not self.__log_handlers_set:
            # First set level of verbosity
            if self.options.verbose:
                level = gnatpython.logging_util.RAW
            else:
                level = levels.get(self.options.loglevel, logging.INFO)

            # Set logging handlers
            default_format = '%(levelname)-8s %(message)s'
            handler = gnatpython.logging_util.add_handlers(
                level=level,
                format=default_format)[0]

            if self.formatter is not None:
                default_format = self.formatter

            if self.options.enable_color:
                handler.setFormatter(ConsoleColorFormatter(default_format))
            else:
                if self.formatter is not None:
                    handler.setFormatter(logging.Formatter(self.formatter))

            # Log to a file if necessary
            if self.options.logfile != "":
                handler = gnatpython.logging_util.add_handlers(
                    level=gnatpython.logging_util.RAW,
                    format='%(asctime)s: %(name)-24s: '
                    '%(levelname)-8s %(message)s',
                    filename=self.options.logfile)

            self.__log_handlers_set = True

        # Export options to env
        e = Env()
        e.main_options = self.options

        if hasattr(self.options, "gnatpython_main_target_options_supported"):
            # Handle --target, --host and --build options
            e.set_env(self.options.build,
                      self.options.host,
                      self.options.target)

    def disable_interspersed_args(self):
        """See optparse.disable_interspersed_args in standard python library.

        This function is now deprecated and is only supported
        if self.option_parser_kind == MAIN_USE_OPTPARSE.
        Use self.option_parser.disable_interspersed_args instead.
        """
        assert self.option_parser_kind == MAIN_USE_OPTPARSE
        self.option_parser.disable_interspersed_args()

    def error(self, msg):
        """Print a usage message incorporating 'msg' to stderr and exit.

        This function is now deprecated and is only supported
        if self.option_parser_kind == MAIN_USE_OPTPARSE.
        Use self.option_parser.error instead.

        :param msg: Error message to display
        :type msg: str
        """
        assert self.option_parser_kind == MAIN_USE_OPTPARSE
        self.option_parser.error(msg)

    def create_option_group(self, txt):
        """Create a new option group.

        You need to call add_option_group after having added the options

        This function is now deprecated and is only supported
        if self.option_parser_kind == MAIN_USE_OPTPARSE.
        Create the OptionGroup object directly, using
        self.option_parser as the option parser.
        """
        assert self.option_parser_kind == MAIN_USE_OPTPARSE
        return OptionGroup(self.option_parser, txt)

    def add_option_group(self, group):
        """Add groups to parsers.

        This function is now deprecated and is only supported
        if self.option_parser_kind == MAIN_USE_OPTPARSE.
        Use self.option_parser.add_option_group instead.
        """
        assert self.option_parser_kind == MAIN_USE_OPTPARSE
        self.option_parser.add_option_group(group)


class AbstractParseProxy(object):
    """An abstract API providing limited access to an option parser.

    This API is meant to be used by the Main class as a proxy
    for some of the operations it needs to perform on the underlying
    option parser. The API only provides enough features to support
    the needs of the Main class, and nothing more. The goal is only
    to avoid littering the code of class Main with with code like::

        if parser_kind = ...
            self.option_parser.use_this_method (...)
        elif parser_kind = ...
            self.option_parser.user_that_method (...)
        else
            raise MainError ("the same message over and over")

    This class should be derived and all methods should be overriden
    for each option parser being supported.

    This class is an abstract class and should not be instantiated.
    Use the child classes that are relevant to the actual option
    parser in use.
    """
    def new_option_parser(self, usage, description):
        """Return a new option parser.

        :raise MainError: not implemented
        """
        del usage, description
        raise MainError("Not implemented: "
                        "__AbstractParserProxy.new_option_parser")

    def new_option_group(self, parser, title, description=None):
        """Create a new option group attached to the given parser.

        :raise MainError: not implemented
        """
        del parser, title, description
        raise MainError("Not implemented: "
                        "__AbstractParserProxy.new_option_group")

    def add_option(self, parser, *args, **kwargs):
        """Add a new option to the given parser.

        The parser can be an option parser, or a group parser.
        :raise MainError: not implemented
        """
        del parser, args, kwargs
        raise MainError("Not implemented: "
                        "__AbstractParserProxy.add_option")

    def parse_args(self, parser, args):
        """Parse the arguments.

        Return a tuple containing two elements (see OptParse.parse_args).

        :param parser: an argument parser
        :param args: the arguments to be parsed

        :raise MainError: not implemented
        """
        del parser, args
        raise MainError("Not implemented: "
                        "__AbstractParserProxy.parse_args")


class OptParseProxy(AbstractParseProxy):
    """The parse-proxy class for optparse.OptionParser option parsers."""
    def new_option_parser(self, usage, description):
        return OptionParser(usage=usage, description=description,
                            formatter=MainHelpFormatter())

    def new_option_group(self, parser, title, description=None):
        group = OptionGroup(parser, title, description)
        parser.add_option_group(group)
        return group

    def add_option(self, parser, *args, **kwargs):
        parser.add_option(*args, **kwargs)

    def parse_args(self, parser, args):
        return parser.parse_args(args)


class ArgParseProxy(AbstractParseProxy):
    """The parse-proxy class for argparse.ArgumentParser option parsers."""
    def new_option_parser(self, usage, description):
        # We import argparse.ArgumentParser here to make sure we import
        # it only when actually used.
        #
        # There is no equivalent of optparse's TitledHelpFormatter
        # with argparse. So just use the RawDescriptionHelpFormatter,
        # which is very close.
        from argparse import ArgumentParser, RawDescriptionHelpFormatter
        return ArgumentParser(usage=usage, description=description,
                              formatter_class=RawDescriptionHelpFormatter)

    def new_option_group(self, parser, title, description=None):
        return parser.add_argument_group(title, description)

    def add_option(self, parser, *args, **kwargs):
        parser.add_argument(*args, **kwargs)

    def parse_args(self, parser, args):
        # With ArgumentParser, all positional arguments are treated
        # as options.  So the second half of the tuple being returned
        # is always the empty list.
        return (parser.parse_args(args), [])

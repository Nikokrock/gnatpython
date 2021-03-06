###########################################################################
#                                                                          #
#                           LOGGING_UTIL.PY                                #
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

"""Extensions to the standard python logging system."""

from logging import (addLevelName, StreamHandler, FileHandler,
                     Filter, Formatter, getLogger, DEBUG, codecs)
from gnatpython.env import Env

import os
import types

# Define a new log level for which level number is lower then DEBUG
RAW = 5
# Register the new level name
addLevelName(RAW, 'RAW')

COLOR_UNCHANGED = -1
COLOR_BLACK = 0
COLOR_RED = 1
COLOR_GREEN = 2
COLOR_YELLOW = 3
COLOR_BLUE = 4
COLOR_MAGENTA = 5
COLOR_CYAN = 6
COLOR_WHITE = 7


def highlight(string, fg=COLOR_UNCHANGED, bg=COLOR_UNCHANGED):
    """Return a version of string with color highlighting applied to it.

    This is suitable for display on a console. Nothing is done if color
    has been disabled
    """
    if not Env().main_options.enable_color:
        return string
    else:
        if bg == COLOR_UNCHANGED:
            colors = "%d" % (30 + fg,)
        elif fg == COLOR_UNCHANGED:
            colors = "%d" % (40 + fg,)
        else:
            colors = "%d;%d" % (40 + bg, 30 + fg)
        return "\033[%sm%s\033[m" % (colors, string)


class RawFilter(Filter):
    """Filters in/out RAW level records."""

    def __init__(self, include_raw=True):
        """RawFilter constructor.

        :param include_raw: if True then keep only RAW level records. If False
            discard RAW level record
        :type include_raw: bool
        """
        Filter.__init__(self)
        if include_raw:
            self.include_raw = 1
        else:
            self.include_raw = 0

    def filter(self, record):
        """Filter implementation (internal).

        :param record: a record to be filtered

        :return: 1 if we keep the record, 0 otherwise
        :rtype: int

        This function should not be called directly by the user
        """
        if record.levelno <= RAW:
            return self.include_raw
        else:
            return 1 - self.include_raw


class RawStreamHandler(StreamHandler):
    """Logging system handler for 'raw' logging on streams."""

    def flush(self):
        """Flush the stream."""
        # In some cases instances of RawStreamHandler might share the same fd
        # as other StreamHandler. As we don't control the order in which these
        # objects will be finalized, we might try to flush an already closed
        # stream. That's why we protect the flush call with a try/except
        # statement
        try:
            self.stream.flush()
        except ValueError:
            return

    def emit(self, record):
        """Emit a record.

        If a formatter is specified, it is used to format the record.
        The record is then written to the stream with a trailing newline
        [N.B. this may be removed depending on feedback]. If exception
        information is present, it is formatted using
        traceback.print_exception and appended to the stream.
        """
        try:
            msg = self.format(record)
            fs = "%s"
            if not hasattr(types, "UnicodeType"):  # if no unicode support...
                self.stream.write(fs % msg)
            else:
                try:
                    self.stream.write(fs % msg)
                except UnicodeError:
                    self.stream.write(fs % msg.encode("UTF-8"))
            self.flush()
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            self.handleError(record)


class RawFileHandler(RawStreamHandler):
    """Logging system handler for 'raw' logging on files.

    Same as logging.FileHandler except that it inherits from
    RawStreamHandler instead of StreamHandler
    """

    def __init__(self, filename, mode='a', encoding=None):
        """Handler constructor."""
        if codecs is None:
            encoding = None
        if encoding is None:
            stream = open(filename, mode)
        else:
            stream = codecs.open(filename, mode, encoding)
        RawStreamHandler.__init__(self, stream)
        # keep the absolute path, otherwise derived classes which use this
        # may come a cropper when the current directory changes
        self.baseFilename = os.path.abspath(filename)
        self.mode = mode

    def close(self):
        """Close the file."""
        self.flush()
        self.stream.close()
        StreamHandler.close(self)


def add_handlers(level, format=None, filename=None):
    """Add handlers with support for 'RAW' logging."""
    # Case in which we add handler to the console
    handler = None
    raw_handler = None

    if filename is None:
        handler = StreamHandler()
    else:
        handler = FileHandler(filename)

    if format is not None:
        formatter = Formatter(format)
        handler.setFormatter(formatter)

    if level <= RAW:
        handler.setLevel(DEBUG)
        if filename is None:
            raw_handler = RawStreamHandler()
        else:
            raw_handler = RawStreamHandler(handler.stream)
        raw_handler.setLevel(RAW)
        raw_handler.addFilter(RawFilter())
        getLogger('').addHandler(raw_handler)
    else:
        handler.setLevel(level)

    getLogger('').addHandler(handler)

    return (handler, raw_handler)


def remove_handlers(handlers):
    """Remove handlers."""
    if handlers[1] is not None:
        getLogger('').removeHandler(handlers[1])

    if handlers[0] is not None:
        getLogger('').removeHandler(handlers[0])
        if hasattr(handlers[0], 'close'):
            handlers[0].close()

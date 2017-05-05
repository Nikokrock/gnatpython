############################################################################
#                                                                          #
#                         STRINGUTILS.PY                                   #
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

"""This module provides various function to process/handle strings."""

import re


class Filter(object):
    """Apply several filters at the same time on a string or a list of strings.

    ??? we should use tuple instead of list

    ATTRIBUTES
      filters: list of filters to apply. each element of filters is either a
        function or a list of the form [ pattern, sub ] where pattern and sub
        string representing regexp
    """

    def __init__(self):
        """Filter constructor."""
        self.filters = []

    def process(self, item):
        """Apply the filters on the item.

        :param item: this is either a string or a list of strings
        :type item: str | list[str]

        :return: the filtered string or a list of filtered strings
        :rtype: str | list[str]
        """
        def run_aux(line):
            """Apply the filters on a string."""
            result = line
            for p in self.filters:
                if isinstance(p, (list, tuple)):
                    result = re.sub(p[0], p[1], result)
                else:
                    result = p(result)
            return result

        if isinstance(item, list):
            return [run_aux(k) for k in item]
        else:
            return run_aux(item)

    def append(self, pattern):
        """Add a filter.

        :param pattern: either a function or a list containing the matching
            pattern and the sub pattern.
        """
        self.filters.append(pattern)


def format_with_dict(pattern, values):
    """Safely format a python string using % and a dictionary for values.

    This method is safer than using directly percent as it will escape
    automatically % in the pattern that cannot be replaced.

    :param pattern: a string that should be formatted
    :type pattern: str | unicode
    :param values: a dictionary containing the values of the keys that can be
        replaced
    :type values: dict

    :rtype: str
    """
    key_regexp = r"|".join([r'\(%s\)' % k for k in values])
    return re.sub(r'%(?!' + key_regexp + ')', r'%%', pattern) % values


def quote_arg(arg):
    """Return the quoted version of the given argument.

    Returns a human-friendly representation of the given argument, but with all
    extra quoting done if necessary.  The intent is to produce an argument
    image that can be copy/pasted on a POSIX shell command (at a shell prompt).
    """
    # The empty argument is a bit of a special case, as it does not
    # contain any character that might need quoting, and yet still
    # needs to be quoted.
    if arg == '':
        return "''"

    need_quoting = ('|', '&', ';', '<', '>', '(', ')', '$',
                    '`', '\\', '"', "'", ' ', '\t', '\n',
                    # The POSIX spec says that the following
                    # characters might need some extra quoting
                    # depending on the circumstances.  We just
                    # always quote them, to be safe (and to avoid
                    # things like file globbing which are sometimes
                    # performed by the shell). We do leave '%' and
                    # '=' alone, as I don't see how they could
                    # cause problems.
                    '*', '?', '[', '#', '~')
    for char in need_quoting:
        if char in arg:
            # The way we do this is by simply enclosing the argument
            # inside single quotes.  However, we have to be careful
            # of single-quotes inside the argument, as they need
            # to be escaped (which we cannot do while still inside.
            # a single-quote string).
            arg = arg.replace("'", r"'\''")
            # Also, it seems to be nicer to print new-line characters
            # as '\n' rather than as a new-line...
            arg = arg.replace('\n', r"'\n'")
            return "'%s'" % arg
    # No quoting needed.  Return the argument as is.
    return arg

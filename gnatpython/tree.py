############################################################################
#                                                                          #
#                              TREE.PY                                     #
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

"""list contents of directories in a tree-like format.

Produces a depth indented  listing  of  files.
"""

import os
from os.path import walk


def tree(directory, stdout=False):
    """Return a depth indented listing of files.

    If stdout is true, print directly on stdout else return the list of
    indented lines
    """
    def print_line(output, line):
        """Print line to stdout or append in output."""
        if output is None:
            print line
        else:
            output.append(line)

    if not stdout:
        output = []
    else:
        # Do not return a list but print all lines to stdout
        output = None

    print_line(output, directory)

    def print_files(output, dirname, fnames):
        """Add filename to the output."""
        dir_relative_path = os.path.normpath(dirname[len(directory):])
        indent = '|   '
        nb_indent = 0
        _, tail = os.path.split(dir_relative_path)

        # Count number of / in the path to compute the indent
        nb_indent = dir_relative_path.count(os.path.sep)

        if tail and tail != ".":
            # If not the root directory, output the directory name
            print_line(output, "%s|-- %s" % (indent * nb_indent, tail))
        else:
            # Else no indent
            nb_indent = -1

        # Print all file names in the current directory
        fnames.sort()
        for fname in fnames:
            if not os.path.isdir(os.path.join(dirname, fname)):
                if fname == fnames[-1] and nb_indent != -1:
                    # Pretty print the last file
                    sep = '`'
                else:
                    sep = '|'
                print_line(output, "%s%s-- %s" % (indent * (nb_indent + 1),
                                                  sep, fname))

    walk(directory, print_files, output)
    return output

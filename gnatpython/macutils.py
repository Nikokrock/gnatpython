############################################################################
#                                                                          #
#                           MACUTILS.PY                                    #
#                                                                          #
#           Copyright (C) 2013 - 2014 Ada Core Technologies, Inc.          #
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

from gnatpython.fileutils import find
from gnatpython.ex import Run, PIPE, STDOUT

import re
import os


def get_dylib_deps(filename):
    """Retrieve the list of shared libraries a given binary depends on.

    Note that we depends on an external tool called :file:`otool`

    :param filename: path to the Mac OS binary file
    :type filename: str
    :return: a list of shared libraries
    :rtype: list[str]
    """
    p = Run(['otool', '-L', filename], output=PIPE, error=STDOUT)
    result = p.out.splitlines()[1:]
    result = [re.sub(r' \(.*\)', r'', k).replace('\t', '') for k in result]
    result = [k for k in result if '/System/Library/Frameworks/' not in k]
    return result


def localize_distrib(distrib_dir, executables):
    """Localize a Mac OS distribution by making adjusting library paths.

    Paths to libraries are made relative so that the distribution can be
    moved easily from one place to another. The change is done in place

    Note that we depends on an external tool called :file:`install_name_tool`

    :param distrib_dir: root directory of the distribution
    :type distrib_dir: str
    :param executables: list of relative path to the executables present
        in the distribution
    :type executables: list[str]
    """
    # First we need to find the shared libraries present in our distribution
    dylib_list = find(distrib_dir, pattern="*.dylib") + \
        find(distrib_dir, pattern="*.so")
    dylib_dict = {os.path.basename(k): k for k in dylib_list}

    # List of files to adjust (executables + shared libraries)
    for bin_file in dylib_list + \
            [os.path.join(distrib_dir, e) for e in executables]:
        # Retrieve the list of dependencies for that file
        file_dylibs = get_dylib_deps(bin_file)

        for d in file_dylibs:
            base_d = os.path.basename(d)
            if base_d in dylib_dict:
                if base_d == 'libgcc_s.1.dylib':
                    # On darwin, we absolutely want to pick the libgcc_s from
                    # the system. shared libgcc_s from our compilers are
                    # broken.
                    Run(['install_name_tool',
                         '-change', d,
                         '/usr/lib/libgcc_s.1.dylib', bin_file])
                else:
                    Run(['install_name_tool',
                         '-change', d,
                         '@loader_path/' +
                         os.path.relpath(dylib_dict[base_d],
                                         os.path.dirname(bin_file)),
                         bin_file])

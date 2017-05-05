############################################################################
#                                                                          #
#                          PYTHON.PY                                       #
#                                                                          #
#           Copyright (C) 2015 - 2015 Ada Core Technologies, Inc.          #
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

"""Helper functions to compute python command lines.

This package provides a few portable functions to compute python interpreter
location, scripts locations, env setting, ...
"""

from gnatpython.env import Env
import sys
import os


def set_python_env(prefix):
    """Set environment for a Python distribution.

    :param prefix: root directory of the python distribution
    :type prefix: str
    """
    env = Env()
    if sys.platform == 'win32':
        env.add_path(prefix)
        env.add_path(os.path.join(prefix, 'Scripts'))
    else:
        env.add_path(os.path.join(prefix, 'bin'))
        env.add_dll_path(os.path.join(prefix, 'lib'))


def interpreter(prefix=None, version='2.7.10'):
    """Return location of the Python interpreter.

    :param prefix: root directory of the python distribution. if None location
        of the current interpreter is returned
    :type prefix: None | str
    :param version: specify python version to return the correct binary name
    :type version: str
    :return: python executable path
    :rtype: str
    """
    python_bin = 'python'
    if version.startswith('3'):
        python_bin = 'python3'
    if prefix is None:
        return sys.executable
    if sys.platform == 'win32':
        return os.path.join(prefix, python_bin + '.exe')
    else:
        return os.path.join(prefix, 'bin', python_bin)


def python_script(name, prefix=None, version='2.7.10'):
    """Return command line prefix to spawn a script part of Python distribution

    :param name: the script name
    :type name: str
    :param prefix: root directory of the Python distribution. if None the
        distribution currently used by this script will be used
    :type prefix: None | str
    :param version: specify the python version to use the correct binary name
    :type version: str
    :return: a list that will be the prefix of your command line
    :rtype: list[str]
    """
    if prefix is None:
        if sys.platform == 'win32':
            prefix = os.path.dirname(sys.executable)
        else:
            prefix = os.path.dirname(os.path.dirname(sys.executable))

    if sys.platform == 'win32':
        script = os.path.join(prefix, 'Scripts', name)
        if os.path.isfile(script + '.exe'):
            return [script + '.exe']
        else:
            return [interpreter(prefix, version), script]
    else:
        return [interpreter(prefix, version),
                os.path.join(prefix, 'bin', name)]

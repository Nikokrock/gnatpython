
from setuptools.command.build_ext import build_ext
from distutils.command.build_scripts import build_scripts
from setuptools import Extension
from distutils.sysconfig import get_python_inc, get_python_lib

import glob
import platform
import os
import sys


class BuildError(Exception):
    pass

# Distutils does not have support for compiled programs. So override the
# build_scripts command with ours. We first compile our program and copy
# it along with the Python scripts. Then we call the regular build_scripts
# command.


def build_scripts_gnatpython(root_dir=''):

    class BuildScriptsGnatpython(build_scripts):

        def run(self):
            if 'Windows' in platform.system() or 'CYGWIN' in platform.system():
                os.system('gcc -o %sscripts/rlimit %ssrc/rlimit/rlimit-NT.c' %
                          (root_dir, root_dir))
            else:
                os.system('gcc -o %sscripts/rlimit %ssrc/rlimit/rlimit.c' %
                          (root_dir, root_dir))

            # Update the scripts list
            self.scripts += glob.glob(root_dir + 'scripts/rlimit*')

            build_scripts.run(self)
    return BuildScriptsGnatpython


# Our C module requires a mingw compiler. On windows python will use by
# default the Microsoft one and even if we use the --compiler=mingw option
# it does not seem to work all the time. So override the build_ext command.
# If the the platform is windows use out manual procedure. Otherwise use
# the regular build_ext implementation.


def build_ext_gnatpython(root_dir=''):

    class BuildExtGnatpython(build_ext):
        def build_extension(self, ext):
            if 'Windows' not in platform.system() and \
                    'CYGWIN' not in platform.system():
                return build_ext.build_extension(self, ext)
            else:
                # Get the python installation prefix
                python_prefix = sys.prefix

                # The Python version
                python_version = "%d.%d" % (
                    sys.version_info[0], sys.version_info[1])

                # The location of the static library (in fact an import
                # library)
                python_lib = "%s/libs/libpython%s%s.a" % (
                    sys.prefix, sys.version_info[0], sys.version_info[1])

                # Find the location of Python includes in various locations.
                python_stdlib_dir = get_python_lib(True, False)
                python_include_dir = None
                for p in (
                    get_python_inc(False),
                    python_stdlib_dir + '/config',
                        python_prefix + '/include/python/%s' % python_version):
                    if os.path.isfile(p + '/Python.h'):
                        python_include_dir = p
                        break

                # Build our module with mingw GCC
                ddk_dir = ''
                for path in os.environ["PATH"].split(os.pathsep):
                    exe_file = os.path.join(path, 'gcc.exe')
                    if os.path.isfile(exe_file):
                        ddk_dir = os.path.join(os.path.dirname(path),
                                               'i686-pc-mingw32',
                                               'include',
                                               'ddk')
                        break

                status = os.system(
                    'gcc -shared -static-libgcc -o '
                    '%s/gnatpython/%s.pyd %s -I%s -I%s %s -lntdll' % (
                        self.build_lib,
                        ext.name.split('.')[-1],
                        ' '.join(ext.sources),
                        python_include_dir,
                        ddk_dir,
                        python_lib))
                if status != 0:
                    raise BuildError(
                        "%s C module compilation error" % ext.name)
    return BuildExtGnatpython


def get_extension_list(root_dir=''):
    extension_list = [Extension('gnatpython._term',
                                [root_dir + 'src/mod_term/terminals.c'])]

    if 'Windows' in platform.system() or \
            'CYGWIN' in platform.system():
        extension_list.append(Extension('gnatpython._winlow',
                                        [root_dir + 'src/mod_win/winlow.c']))
    return extension_list

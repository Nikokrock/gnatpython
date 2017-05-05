#!/usr/bin/env python

from gnatpython import __version__
from setup_helpers import (
    build_scripts_gnatpython, build_ext_gnatpython, get_extension_list)

from distutils.core import setup
import distutils.file_util

import glob
import os

old_copy_file = distutils.file_util.copy_file


def my_copy_file(src, dst, preserve_mode=1,
                 preserve_times=1, update=0, link=None,
                 verbose=0, dry_run=0):
    old_copy_file(src, dst, 1, preserve_times,
                  update, link, verbose, dry_run)

distutils.file_util.copy_file = my_copy_file

# Compute the list of data files
data_file_list = []
for root, _, _ in os.walk('gnatpython/internal/data'):
    data_file_list.append(
        os.path.relpath(os.path.join(root, '*'), 'gnatpython/internal'))

setup(name='gnatpython',
      version=__version__,
      author="AdaCore",
      author_email="report@adacore.com",
      packages=['gnatpython',
                'gnatpython.binarydata',
                'gnatpython.testsuite'],
      package_data={'gnatpython.internal': data_file_list},
      cmdclass={'build_scripts': build_scripts_gnatpython(),
                'build_ext': build_ext_gnatpython()},
      ext_modules=get_extension_list(),
      scripts=[f for f in glob.glob('scripts/*') +
               glob.glob('scripts/internal/*')
               if os.path.isfile(f)],
      requires=['requests', 'pep8', 'pyflakes'])

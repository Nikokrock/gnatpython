#!/usr/bin/env python
from __future__ import absolute_import

from gnatpython import __version__
from setup_helpers import (
    build_scripts_gnatpython, build_ext_gnatpython, get_extension_list)

from setuptools import setup, find_packages
import distutils.file_util

import glob
import os

setup(name='gnatpython',
      version=__version__,
      author="AdaCore",
      author_email="report@adacore.com",
      packages=find_packages(),
      ext_modules=get_extension_list(),
      cmdclass={'build_ext': build_ext_gnatpython(),
                'build_scripts': build_scripts_gnatpython()},
      install_requires = ['colorama', 'pyyaml', 'python-dateutil'],
      extras_require = {":sys_platform=='win32'": ['pypiwin32']},
      scripts=[f for f in glob.glob('scripts/*') if os.path.isfile(f)])

############################################################################
#                                                                          #
#                              ENV.PY                                      #
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

"""Global environment handling.

This package provide a class called Env used to store global information. Env
is a singleton so there is in fact only one instance.

Here is a description of the functionalities provided by the class:

* host, target information retrieval/setting:
    >>> from gnatpython.env import Env
    >>> e = Env()

    Then e.target contains something like::

        platform: x86-linux
        machine:  barcelona
        is_hie:   False
        is_host:  True
        triplet:  i686-pc-linux-gnu
        OS
            name:          linux
            version:       suse10.3
            is_bareboard:  False
        CPU
            name:   x86
            bits:   32
            endian: little

    >>> e.set_target('ppc-vxw')
    >>> print e.target.os.name
    vxworks
    >>> print e.target.os.version
    5.5

* make some info global
    >>> e = Env()
    >>> d = Env()
    >>> e.example_of_global_info = 'hello'
    >>> print d.example_of_global_info
    hello

* restoring/saving complete environment, including environment variables and
  current dir

    >>> e = Env()
    >>> e.example = 'hello'
    >>> e.store('./saved_env')

    Quit and restart gnatpython

    >>> from gnatpython.env import Env
    >>> e = Env()
    >>> e.restore('./saved_env')
    >>> print e.example
    hello
"""
from gnatpython.arch import Arch

import logging
import pickle
import os
import sys


logger = logging.getLogger('gnatpython.env')


def putenv(key, value):
    """Portable version of os.putenv.

    :param key: variable naem
    :type key: str
    :param value: variable name
    :type value: str
    """
    # When a variable is set by os.putenv, os.environ is not updated;
    # this is a problem, as Env and ex.Run use os.environ to store the
    # current environment or to spawn a process. This limitation is
    # documented in the Python Library Reference:

    # environ
    #       A mapping object representing the string environment. For
    #       example, environ['HOME'] is the pathname of your home directory
    #       (on some platforms), and is equivalent to getenv("HOME") in C.
    #
    #       This mapping is captured the first time the os module is
    #       imported, typically during Python startup as part of
    #       processing site.py. Changes to the environment made after
    #       this time are not reflected in os.environ, except for
    #       changes made by modifying os.environ directly.
    #
    #       If the platform supports the putenv() function, this
    #       mapping may be used to modify the environment as well as
    #       query the environment. putenv() will be called
    #       automatically when the mapping is modified. Note: Calling
    #       putenv() directly does not change os.environ, so it's
    #       better to modify os.environ.

    # ...For this reason, os.environ is preferred to os.putenv here.
    logger.debug("export {key}={value}".format(key=key, value=value))
    os.environ[key] = value


def getenv(key, default=None):
    """Portable version of os.getenv.

    :param key: variable name
    :type key: str
    :param default: value returned if variable does not exist
    :type default: str | None

    :return: variable value or default
    :rtype: str | None
    """
    # For the reason documented in putenv, and for consistency, it is better
    # to use os.environ instead of os.getenv here.
    if key in os.environ:
        return os.environ[key]
    else:
        return default

# This global variable contains a list of tuples
# (build platform, host platform) that should not be considered as canadian
# configurations.
CANADIAN_EXCEPTIONS = (('x86-windows', 'x86_64-windows'),
                       ('sparc-solaris', 'sparc64-solaris'))


class BaseEnv(object):
    """Environment Handling.

    :ivar build: default system (autodetected)
    :ivar host: host system
    :ivar target: target system
    :ivar is_cross: true if we are in a cross environment
    :ivar is_canadian: true if we are in a canadian environment
    :ivar platform: platform name based on host and target
    :ivar main_options: The command-line switches, after parsing by
        the gnatpython.main.Main class (see the documentation
        of that class).

    build, host and target attributes are instances of gnatpython.arch.Arch.

    The only difference between Env and BaseEnv class is that Env is a
    singleton. This is not the case for BaseEnv.
    """

    def __init__(self, build=None, host=None, target=None):
        """BaseEnv constructor.

        On first instantiation, build attribute will be computed and host
        and target set to the build attribute.

        :param build: build architecture. If None then it is set to default
            build
        :type build: Arch | None
        :param host: host architecture. If None then it is set to build
        :type host: Arch | None
        :param target: target architecture. If None then it is set to target
        :type target: Arch | None
        """
        # class variable that holds the current environment
        self._instance = {}

        # class variable that holds the stack of saved environments state
        self._context = []

        if build is None:
            self.build = Arch()
        else:
            self.build = build

        if host is None:
            self.host = self.build
        else:
            self.host = host

        if target is None:
            self.target = self.host
        else:
            self.target = target

        self.environ = None
        self.cwd = None
        self.main_options = None  # Command line switches

    @property
    def platform(self):
        """Compute the platform name based on the host and the target.

        For example for target ppc-elf hosted on linux, platform will
        be ppc-elf-linux. So the concept of platform embed both target
        and host concept.

        :rtype: str
        """
        if self.is_cross:
            # In cross we need to append host information. For backward
            # compatibility we don't append 64 to darwin host (which is
            # always 64bits).
            suffix = self.host.os.name
            if self.host.cpu.bits == 64 and self.host.os.name != 'darwin':
                suffix += '64'
            return self.target.platform + '-' + suffix
        else:
            # In native concept the platform is equivalent to target.platform
            return self.target.platform

    def __getattr__(self, name):
        try:
            if name in ('_instance', '_context'):
                return self.__dict__[name]
            else:
                return self._instance[name]
        except KeyError as e:
            raise AttributeError(e), None, sys.exc_traceback

    def __setattr__(self, name, value):
        if name in ('_instance', '_context'):
            object.__setattr__(self, name, value)
        else:
            self._instance[name] = value

    @property
    def is_canadian(self):
        """Return true if this is a canadian configuration.

        :rtype: bool
        """
        if self.build != self.host:
            if (self.build.platform,
                    self.host.platform) in CANADIAN_EXCEPTIONS:
                return False
            return True
        else:
            return False

    @property
    def is_cross(self):
        """Return true if this is a cross configuration.

        :rtype: bool
        """
        if self.target != self.host:
            return True
        else:
            return False

    def set_build(self, build_name=None, build_version=None):
        """Set build platform.

        :param build_name: a string that identify the system to be considered
            as the build. If None then build is unchanged. Note that passing
            an empty value will force the autodetection and possibly reset to
            the default value.
        :type build_name: str | None
        :param build_version: a string containing the system version. If set
            to None the version is either a default or autodetected when
            possible
        :type build_version: str | None

        When calling set_build, the target and host systems are reset to the
        build one. Thus you should call set_build before calling either
        set_host or set_target.
        """
        if build_name is not None:
            self.build = Arch(platform_name=build_name,
                              is_host=True,
                              version=build_version)
        self.host = self.build
        self.target = self.build

    def set_host(self, host_name=None, host_version=None):
        """Set host platform.

        :param host_name: a string that identify the system to be considered
            as the host. If None then host is set to the build one (the
            autodetected platform). If set to 'build' or 'target' then host
            is set respectively to current 'build' or 'target' value
        :type host_name: str | None
        :param host_version: a string containing the system version. If set to
            None the version is either a default or autodetected when possible
        :type host_version: str | None

        When calling set_host, the target system is reset to the host one.
        Thus you should call set_host before set_target otherwise your call
        to set_target will be ignored. Note also that is the host_name is
        equal to the build platform, host_version will be ignored.
        """
        # Handle special parameters 'target' and 'build'
        if host_name is not None:
            if host_name == 'target':
                host_name = self.target.platform
                host_version = self.target.os.version
            elif host_name == 'build':
                host_name = self.build.platform
                host_version = self.target.os.version

        if host_name is not None and host_name != self.build.platform:
            is_host = False
            if (self.build.platform, host_name) in CANADIAN_EXCEPTIONS:
                # We are not in a canadian configuration, so we can invoke
                # our methods to guess some information such as os version,...
                is_host = True

            self.host = Arch(platform_name=host_name,
                             is_host=is_host,
                             version=host_version,
                             machine=self.build.machine)
        else:
            self.host = self.build

        self.target = self.host

    def set_target(self,
                   target_name=None,
                   target_version=None,
                   target_machine=None,
                   target_mode=None):
        """Set target platform.

        :param target_name: a string that identify the system to be considered
            as the host. If None then host is set to the host one. If set to
            'build' or 'host' then target is set respectively to current
            'build' or 'host' value. In that case target_version and
            target_machine are ignored.
        :type target_name: str | None
        :param target_version: a string containing the system version. If set
            to None the version is either a default or autodetected when
            possible.
        :type target_version: str | None
        :param target_machine: a string containing the name of the target
            machine.
        :type target_machine: str | None
        :param target_mode: a string containing the name of the mode. This
            notion is needed on some targets such as VxWorks to switch between
            kernel mode and other modes such as rtp

        The target parameters are ignored if the target_name is equal to the
        host platform.
        """
        # Handle special values
        if target_name is not None:
            if target_name == 'host':
                target_name = self.host.platform
                target_version = self.host.os.version
                target_machine = self.host.machine
            elif target_name == 'build':
                target_name = self.build.platform
                target_version = self.build.os.version
                target_machine = self.build.machine

        if target_name is not None and target_name != self.host.platform:
            self.target = Arch(platform_name=target_name,
                               version=target_version,
                               machine=target_machine,
                               mode=target_mode)
        else:
            self.target = self.host

    def set_env(self, build='', host='', target=''):
        """Set build/host/target.

        :param build: string as passed to --build option
        :type build: str
        :param host: string as passed to --host
        :type host: str
        :param target: string as passed to --target
        :type target: str
        """
        # We expect 2 fields for build and host and 4 for target
        build_opts = [k if k else None for k in build.split(',')][0:2]
        host_opts = [k if k else None for k in host.split(',')][0:2]
        target_opts = [k if k else None for k in target.split(',')][0:4]

        self.set_build(*build_opts)
        self.set_host(*host_opts)
        self.set_target(*target_opts)

    def cmd_triplet(self):
        """Return command line parameters corresponding to current env.

        :return: a list of command line parameters
        :rtype: list(str)
        """
        result = []
        if not self.build.is_default:
            result.append('--build=%s' %
                          ','.join([self.build.platform,
                                    self.build.os.version]))

        if self.host != self.build:
            result.append('--host=%s' %
                          ','.join([self.host.platform,
                                    self.host.os.version]))

        if self.target != self.host:
            result.append('--target=%s' %
                          ','.join([self.target.platform,
                                    self.target.os.version,
                                    self.target.machine,
                                    self.target.os.mode]))
        return result

    def get_attr(self, name, default_value=None, forced_value=None):
        """Return an attribute value.

        :param name: name of the attribute to check. Name can contain '.'
        :type name: str
        :param default_value: returned value if forced_value not set and the
            attribute does not exist
        :type default_value: object | None
        :param forced_value: if not None, this is the return value
        :type forced_value: object | None

        :return: the attribute value

        This function is useful to get the value of optional functions
        parameters whose default value might depend on the environment.
        """
        if forced_value is not None:
            return forced_value

        attributes = name.split('.')
        result = self
        for a in attributes:
            if not hasattr(result, a):
                return default_value
            else:
                result = getattr(result, a)

        if result is None or result == "":
            return default_value

        return result

    def store(self, filename=None):
        """Save environment into memory or file.

        :param filename: a string containing the path of the filename in which
            the environment will be saved. If set to None the environment is
            saved into memory in a stack like structure.
        :type filename: str | None
        """
        # Store environment variables
        self.environ = os.environ.copy()

        # Store cwd
        self.cwd = os.getcwd()

        if filename is None:
            self._context.append(pickle.dumps(self._instance))
        else:
            with open(filename, 'w+') as fd:
                pickle.dump(self._instance, fd)

    def restore(self, filename=None):
        """Restore environment from memory or a file.

        :param filename: a string containing the path of the filename from
            which the environment will be restored. If set to None the
            environment is pop the last saved one
        :type filename: str | None
        """
        if filename is None:
            # We are restoring from memory.  In that case, just double-check
            # that we did store the Env object in memory beforehand (using
            # the store method).
            assert self.environ is not None

        if filename is None and self._context:
            self._instance = pickle.loads(self._context[-1])
            self._context = self._context[:-1]
        elif filename is not None:
            with open(filename, 'r') as fd:
                self._instance = pickle.load(fd)
        else:
            return

        # Restore environment variables value
        # Do not use os.environ = self.environ.copy()
        # or it will break the os.environ object and child process
        # will get the old environment.
        for k in os.environ.keys():
            if os.environ[k] != self.environ.get(k, None):
                del os.environ[k]
        for k in self.environ:
            if os.environ.get(k, None) != self.environ[k]:
                os.environ[k] = self.environ[k]

        # Restore current directory
        os.chdir(self.cwd)

    @classmethod
    def add_path(cls, path, append=False):
        """Set a path to PATH environment variable.

        :param path: path to add
        :type path: str
        :param append: if True append, otherwise prepend. Default is prepend
        :type append: bool
        """
        if append:
            new_path = os.path.pathsep + path
            logger.debug('export PATH=$PATH{new_path}'.format(
                new_path=new_path))
            os.environ['PATH'] += new_path
        else:
            new_path = path + os.path.pathsep + os.environ['PATH']
            logger.debug('export PATH={new_path}'.format(new_path=new_path))
            os.environ['PATH'] = new_path

    @classmethod
    def add_search_path(cls, env_var, path, append=False):
        """Add a path to the env_var search paths.

        :param env_var: the environment variable name (e.g. PYTHONPATH,
            LD_LIBRARY_PATH, ...)
        :type env_var: str
        :param path: path to add
        :type path: str
        :param append: if True append, otherwise prepend. Default is prepend
        :type append: bool
        """
        if env_var not in os.environ or not os.environ[env_var]:
            logger.debug('export {env_var}={path}'.format(
                env_var=env_var,
                path=path))
            os.environ[env_var] = path
        else:
            if append:
                new_path = os.path.pathsep + path
                logger.debug('export {env_var}=${env_var}{new_path}'.format(
                    env_var=env_var,
                    new_path=new_path))
                os.environ[env_var] += new_path
            else:
                new_path = path + os.path.pathsep + os.environ[env_var]
                logger.debug('export {env_var}={new_path}'.format(
                    env_var=env_var,
                    new_path=new_path))
                os.environ[env_var] = new_path

    def add_dll_path(self, path, append=False):
        """Add a path to the dynamic libraries search paths.

        :param path: path to add
        :type path: str
        :param append: if True append, otherwise prepend. Default is prepend
        :type append: bool
        """
        # On most platforms LD_LIBRARY_PATH is used. For others use:
        env_var_name = {'windows': 'PATH',
                        'hp-ux': 'SHLIB_PATH',
                        'darwin': 'DYLD_FALLBACK_LIBRARY_PATH'}
        env_var = env_var_name.get(
            self.host.os.name.lower(),
            'LD_LIBRARY_PATH')
        self.add_search_path(env_var, path, append)

    @property
    def discriminants(self):
        """Compute discriminants.

        :return: the list of discriminants associated with the current context
            (target, host, ...). This is mainly used for testsuites to ensure a
            coherent set of base discriminants.
        :rtype: list[str]
        """
        discs = [self.target.platform, self.target.triplet,
                 self.target.cpu.endian + '-endian',
                 self.target.cpu.name,
                 self.host.os.name + '-host']

        if self.target.os.is_bareboard:
            discs.append('bareboard')
        else:
            discs.extend((
                self.target.os.name,
                self.target.os.name + '-' + self.target.os.version))
        if self.target.os.name.startswith('vxworks'):
            discs.append('vxworks')
        if self.target.os.name == 'vxworks6' and \
           self.target.os.version.startswith('653-3.'):
            discs.append('vxworks653mc')
        if not self.is_cross:
            discs.append('native')
        discs.append("%dbits" % self.target.cpu.bits)
        if self.target.os.name.lower() == 'windows':
            discs.append('NT')

        if (not self.is_cross and not self.is_canadian) and \
                self.build.is_virtual:
            discs.append('virtual_machine')

        return discs

    @property
    def tmp_dir(self):
        """Return current temporary directory.

        :return: a path
        :rtype: str

        The function looks for several variables ``TMPDIR``, ``TMP``
        and in case none of these variables are defined fallback on
        on ``/tmp``.
        """
        return os.environ.get(
            'TMPDIR', os.environ.get('TMP', '/tmp'))

    def to_dict(self):
        """Get current env as a dictionary.

        :return: the dictionary entries are all strings and thus the result
            can be used to format string. For example ``Env().target.os.name``
            will appear with the key ``target_os_name``, ...
        :rtype: dict
        """
        result = {k: v for k, v in self._instance.iteritems()}
        result['is_canadian'] = self.is_canadian
        result['is_cross'] = self.is_cross

        for c in ('host', 'target', 'build'):
            result.update({'%s_%s' % (c, k): v
                           for k, v in result[c].to_dict().iteritems()})
            del result[c]
        return result


class Env(BaseEnv):
    """Environment Handling.

    ATTRIBUTES
      build: default system (autodetected)
      host: host system
      target: target system
      is_cross: true if we are in a cross environment
      is_canadian: true if we are in a canadian environment
      platform: platform name based on host and target

    build, host and target attributes are instances of gnatpython.arch.Arch.

    The only difference between Env and BaseEnv class is that Env is a
    singleton. This is not the case for BaseEnv.
    """

    # class variable that holds the current environment
    _instance = {}

    # class variable that holds the stack of saved environments state
    _context = []

    def __init__(self):
        """Env constructor.

        On first instantiation, build attribute will be computed and
        host and target set to the build attribute.
        """
        if 'build' not in Env._instance:
            self.build = Arch()
            self.host = self.build
            self.target = self.host
            self.environ = None
            self.cwd = None
            self.main_options = None  # Command line switches

    def __setattr__(self, name, value):
        if name == '_instance':
            Env._instance = value
        elif name == '_context':
            Env._context = value
        else:
            self._instance[name] = value


def target_exeext():
    """The target executable filename extension.

    Get the executable filename extension, in accordance with the VxWorks
    RTS if relevant.

    :rtype: str
    """
    env = Env()
    return ('.vxe' if env.RTS is not None and "rtp" in env.RTS else
            env.target.os.exeext)

if __name__ == "__main__":
    print Env().host
    print "discs: " + ", ".join(Env().discriminants)
    for k, v in sorted(Env().to_dict().iteritems()):
        print '%s: %s' % (k, v)

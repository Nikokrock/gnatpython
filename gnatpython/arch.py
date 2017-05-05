############################################################################
#                                                                          #
#                              ARCH.PY                                     #
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

"""System information handling.

This package contains a single class called Arch that allows the user to
instantiate configuration objects containing information about the
system (native or cross).
"""

import os
import platform
import re
import sys

# Note that even if config module could be represented as json or yaml data, it
# is faster to keep it as a Python module
from gnatpython import config
from collections import namedtuple

# Export only the Arch class
__all__ = ('Arch', 'SystemInfo')


UNKNOWN = 'unknown'

Uname = namedtuple("Uname", ["system",
                             "node",
                             "release",
                             "version",
                             "machine",
                             "processor"])


class SystemInfo(object):
    """Class in charge of gathering info about the system.

    :cvar network_ifs: dictionary addressed by network interface name for which
        each value is the result of netifaces.ifaddresses function on the given
        interface
    :cvar linux_distrib: tuple of strings containing respectively the
        Linux distribution name and version.
    :cvar uname: instance of Uname namedtuple containing the result of
        ``uname`` system call.
    :cvar core_number: integer containing the number of processor cores on the
        machine
    :cvar nis_domain: host nis domain
    """

    network_ifs = None
    linux_distrib = None
    uname = None
    core_number = None
    nis_domain = None

    # Cache for SystemInfo methods
    _platform = None
    _os_version = None
    _is_virtual = None
    _hostname = None

    @classmethod
    def reset_cache(cls):
        """Reset SystemInfo cache."""
        cls.network_ifs = None
        cls.linux_distrib = None
        cls.uname = None
        cls.core_number = None
        cls._is_virtual = None
        cls._platform = None
        cls._os_version = None
        cls._hostname = None

    @classmethod
    def fetch_system_data(cls):
        """Fetch info from the host system.

        The function should be the only one that use system calls or programs
        to fetch information from the current system. Overriding this method
        should be enough for example for testing purposes as all the other
        methods use information retrieved in this function.

        The function should set all the class attributes described at the
        beginning of this class.
        """
        # Compute result of uname
        cls.uname = Uname(*platform.uname())

        # Fetch the linux release file
        if cls.uname.system == 'Linux':
            cls.linux_distrib = \
                platform.linux_distribution()
        else:
            cls.linux_distrib = None

        # Fetch network interfaces
        try:
            from netifaces import interfaces, ifaddresses, address_families
            # use string for address families instead of integers which are
            # system dependents
            cls.network_ifs = {itf: {address_families[k]: v
                                     for k, v in ifaddresses(itf).iteritems()}
                               for itf in interfaces()}
        except Exception:
            cls.network_ifs = None

        # Fetch core numbers. Note that the methods does not work
        # on AIX platform but we usually override manually that
        # setting anyway.
        cls.core_number = 1
        try:
            import multiprocessing
            cls.core_number = multiprocessing.cpu_count()
        except Exception:
            try:
                import psutil
                cls.core_number = psutil.cpu_count()
            except Exception:
                pass

        cls.nis_domain = UNKNOWN
        try:
            import nis
            try:
                cls.nis_domain = nis.get_default_domain()
                if not cls.nis_domain:
                    cls.nis_domain = UNKNOWN
            except nis.error:
                pass
        except ImportError:
            pass

    @classmethod
    def platform(cls):
        """Guess platform name.

        Internal function that guess base on uname system call the
        current platform

        :return: the platform name
        :rtype: str
        """
        if cls._platform is not None:
            return cls._platform

        if cls.uname is None:
            cls.fetch_system_data()

        result = [p for p, v in config.host_guess.iteritems()
                  if cls.uname.system == v['os'] and
                  (v['cpu'] is None or
                   re.match(v['cpu'], cls.uname.machine) or
                   re.match(v['cpu'], cls.uname.processor))]

        if result:
            result = result[0]
        else:
            result = UNKNOWN

        cls._platform = result
        return result

    @classmethod
    def os_version(cls):
        """Compute OS version information.

        :return: a tuple containing os version and kernel version
        :rtype: (str, str)
        """
        if cls._os_version is not None:
            return cls._os_version

        if cls.uname is None:
            cls.fetch_system_data()

        version = UNKNOWN
        kernel_version = UNKNOWN
        system = cls.uname.system

        if system == 'Darwin':
            version = cls.uname.release
        elif system == 'FreeBSD':
            version = re.sub('-.*', '', cls.uname.release)
        elif system == 'Linux':
            kernel_version = cls.uname.release
            distrib = cls.linux_distrib
            for name in ('red hat', 'ubuntu', 'debian', 'suse'):
                if name in distrib[0].lower():
                    version = '%s%s' % (
                        name.replace('red hat', 'rhES'),
                        distrib[1].split('.')[0])
                    if name == 'debian':
                        version = version.replace('/sid', '')
                        version = version.replace('wheezy', '7')
                    break
            if version.startswith('debian') \
                    and os.path.exists('/etc/lsb-release'):
                # platform.linux_distribution is deprecated in Python 3.5
                # It probably makes sense to use the package ld available
                # on pypi
                lsb_distrib_id = ''
                lsb_distrib_rel = ''
                with open('/etc/lsb-release') as f:
                    for l in f:
                        if l.startswith('DISTRIB_ID='):
                            lsb_distrib_id = l.split('=')[1].strip()
                        elif l.startswith('DISTRIB_RELEASE='):
                            lsb_distrib_rel = l.split('=')[1].strip()
                if lsb_distrib_id and lsb_distrib_rel:
                    version = lsb_distrib_id + lsb_distrib_rel
                    version = version.lower()
            elif version == UNKNOWN:
                version = '%s%s' % (distrib[0].replace(' ', ''),
                                    distrib[1].split('.')[0])
        elif system == 'AIX':
            version = cls.uname.version + '.' + cls.uname.release
        elif system == 'SunOS':
            version = '2' + cls.uname.release[1:]
        elif system == 'Windows':
            import ctypes

            class WinOSVersion(ctypes.Structure):
                _fields_ = [('dwOSVersionInfoSize', ctypes.c_ulong),
                            ('dwMajorVersion', ctypes.c_ulong),
                            ('dwMinorVersion', ctypes.c_ulong),
                            ('dwBuildNumber', ctypes.c_ulong),
                            ('dwPlatformId', ctypes.c_ulong),
                            ('szCSDVersion', ctypes.c_wchar * 128),
                            ('wServicePackMajor', ctypes.c_ushort),
                            ('wServicePackMinor', ctypes.c_ushort),
                            ('wSuiteMask', ctypes.c_ushort),
                            ('wProductType', ctypes.c_byte),
                            ('wReserved', ctypes.c_byte)]

            def get_os_version():
                """Return the real Windows kernel version.

                On recent version, the kernel version returned by the
                GetVersionEx Win32 function depends on the way the application
                has been compiled. Using RtlGetVersion kernel function ensure
                that the right version is returned.

                :return: the version
                :rtype: float | None
                """
                if sys.platform == 'win32':
                    os_version = WinOSVersion()
                    os_version.dwOSVersionInfoSize = ctypes.sizeof(os_version)
                    retcode = ctypes.windll.Ntdll.RtlGetVersion(
                        ctypes.byref(os_version))
                    if retcode != 0:
                        return None

                    return float("%d.%d" % (os_version.dwMajorVersion,
                                            os_version.dwMinorVersion))
                else:
                    return None

            real_version = get_os_version()
            version = cls.uname.release.replace('Server', '')

            if real_version is None or real_version <= 6.2:
                kernel_version = cls.uname.version
                if version == 'Vista' and '64' in cls.uname.machine:
                    version = 'Vista64'
            else:
                # Starting with Windows 8.1 (6.3), the win32 function
                # that returns the version may return the wrong version
                # depending on the application manifest. So python will
                # always return Windows 8 in that case.
                if real_version == 6.3:
                    if 'Server' in cls.uname.release:
                        version = '2012R2'
                    else:
                        version = '8.1'
                elif real_version == 10.0:
                    if 'Server' in cls.uname.release:
                        version = '2016'
                    else:
                        version = '10'

        cls._os_version = (version, kernel_version)
        return version, kernel_version

    @classmethod
    def is_virtual(cls):
        """Check if current machine is virtual or not.

        :return: True if the machine is a virtual machine (Solaris zone,
            VmWare)
        :rtype: bool
        """
        if cls._is_virtual is not None:
            return cls._is_virtual

        if cls.uname is None:
            cls.fetch_system_data()

        result = False

        if cls.uname.system == 'SunOS' and \
                cls.uname.version == 'Generic_Virtual':
            result = True
        else:
            if cls.network_ifs is not None:
                for interface in cls.network_ifs.values():
                    for family in ('AF_LINK', 'AF_PACKET'):
                        if family in interface:
                            for el in interface[family]:
                                addr = el['addr'].lower()
                                if addr.startswith('00:0c:29') or \
                                        addr.startswith('00:50:56'):
                                    result = True
                                    break
                        if result:
                            break
                    if result:
                        break
        cls._is_virtual = result
        return result

    @classmethod
    def hostname(cls):
        """Get hostname and associated domain.

        :return: a tuple (hostname, domain)
        :rtype: (str, str)
        """
        if cls._hostname is not None:
            return cls._hostname

        if cls.uname is None:
            cls.fetch_system_data()

        # This is host so we can find the machine name using uname fields
        tmp = cls.uname.node.lower().split('.', 1)
        hostname = tmp[0]
        if len(tmp) > 1:
            domain = tmp[1]
        else:
            domain = cls.nis_domain
        cls._hostname = (hostname, domain)
        return cls._hostname


class Immutable(object):
    def __setattr__(self, name, value):
        msg = "'%s' has no attribute %s" % (self.__class__,
                                            name)
        raise AttributeError(msg)

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return False

        return tuple(getattr(self, slot) for slot in self.__slots__) == \
            tuple(getattr(other, slot) for slot in self.__slots__)

    def __hash__(self):
        return hash(tuple(getattr(self, slot) for slot in self.__slots__))

    def __getstate__(self):
        return self.as_dict()

    def __setstate__(self, state):
        for s in self.__slots__:
            object.__setattr__(self, s, state[s])

    def as_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}

    def __str__(self):
        result = ["%s: %s" % (k, getattr(self, k)) for k in self.__slots__]
        return "\n".join(result)


class CPU(Immutable):
    """CPU attributes.

    :ivar name: string containing the cpu name
    :ivar bits: int representing the number of bits for the cpu or 'unknown'
    :ivar endian: 'big', 'little' or 'unknown'
    :ivar cores: int representing the number of cores
    """

    __slots__ = ["name", "bits", "endian", "cores"]

    def __init__(self, name, endian=None, compute_cores=False):
        """Initialize CPU instance.

        :param name: cpu name
        :type name: str
        :param endian: if not None override endianness default settings
        :type endian: str
        :param compute_cores: if True compute the number of cores
        :type compute_cores: bool
        """
        assert name in config.cpu_info, "invalid cpu name"
        set_attr = object.__setattr__
        set_attr(self, "name", name)
        set_attr(self, "bits", config.cpu_info[self.name]['bits'])
        set_attr(self, "endian", endian)
        set_attr(self, "cores", 1)

        if self.endian is None:
            set_attr(self, "endian", config.cpu_info[self.name]['endian'])
        if compute_cores:
            set_attr(self, "cores", SystemInfo.core_number)


class OS(Immutable):
    """OS attributes.

    :ivar name: os name
    :ivar version: string containing the os version
    :ivar exeext: default executable extension
    :ivar dllext: default shared library extension
    :ivar is_bareboard: True if the system is bareboard, False otherwise
    """

    __slots__ = ["name", "version", "exeext", "dllext", "is_bareboard", "mode"]

    def __init__(self, name, is_host=False, version=UNKNOWN, mode=UNKNOWN):
        """Initialize OS instance.

        :param name: os name
        :type name: str
        :param is_host: if True the OS instance is for the host system
        :type is_host: bool
        :param version: os version
        :type version: str | None
        :param mode: os mode
        :type mode: str | None
        """
        set_attr = object.__setattr__
        set_attr(self, "name", name)
        set_attr(self, "version", version)
        set_attr(self, "exeext", "")
        set_attr(self, "dllext", "")
        set_attr(self, "is_bareboard", False)
        set_attr(self, "kernel_version", None)
        set_attr(self, "mode", mode)

        set_attr(self, "is_bareboard",
                 config.os_info[self.name]['is_bareboard'])
        set_attr(self, "exeext", config.os_info[self.name]['exeext'])

        if self.name.startswith('vxworks') and self.mode == 'rtp':
            set_attr(self, "exeext", ".vxe")

        set_attr(self, "dllext", config.os_info[self.name]['dllext'])

        # If version is not given by the user guess it or set it to the
        # default (cross case)
        if self.version == UNKNOWN:
            if is_host:
                version, kernel_version = SystemInfo.os_version()
                set_attr(self, "version", version)
                set_attr(self, "kernel_version", kernel_version)
            else:
                set_attr(self, "version", config.os_info[self.name]['version'])
                set_attr(self, "kernel_version", UNKNOWN)


class Arch(Immutable):
    """Class that allow user to retrieve os/cpu specific information.

    :ivar cpu: CPU information (see Arch.CPU)
    :ivar os: Operating system information (see Arch.OS)
    :ivar is_hie: True if the system is a high integrity system
    :ivar platform: AdaCore platform product name. Ex: x86-linux
    :ivar triplet:  GCC target
    :ivar machine:  machine name
    :ivar domain:   domain name
    :ivar is_host:  True if this is not a cross context
    :ivar is_virtual: Set to True if the current system is a virtual one.
        Currently set only for Solaris containers, Linux VMware and Windows on
        VMware.
    :ivar is_default: True if the platform is the default one
    """

    default_arch = None
    system_info = SystemInfo

    __slots__ = ["cpu", "os", "is_hie", "platform", "triplet",
                 "machine", "domain", "is_host",
                 "is_default"]

    def __init__(self, platform_name=None, version=None, is_host=False,
                 machine=None, compute_default=False, mode=None):
        """Arch constructor.

        :param platform_name: if None or empty then automatically detect
            current platform (native). Otherwise should be a valid platform
            string.
        :type platform_name: str | None
        :param version:  if None, assume default OS version or find it
            automatically (native case only). Otherwise should be a valid
            version string.
        :type version: str | None
        :param is_host:  if True the system is not a cross one. Default is
            False except if a platform_name is not specified or if the
            platform_name is equal to the automatically detected one.
        :type is_host: bool
        :param machine: name of the machine
        :type machine: str | None
        :param compute_default: if True compute the default Arch for the
            current machine (this parameter is for internal purpose only).
        :param mode: an os mode (ex: rtp for vxworks)
        :type mode: str | None
        """
        # normalize arguments
        if not version:
            version = UNKNOWN
        if not machine or machine == UNKNOWN:
            machine = ''
        if not mode:
            mode = UNKNOWN

        def set_attr(name, value):
            object.__setattr__(self, name, value)

        set_attr("cpu", None)
        set_attr("os", None)
        set_attr("platform", platform_name)

        # Initialize default arch class variable
        if self.default_arch is None and not compute_default:
            Arch.default_arch = Arch(compute_default=True)

        set_attr("is_default", False)
        set_attr("machine", machine)
        set_attr("is_hie", False)
        set_attr("domain", UNKNOWN)

        if compute_default:
            default_platform = self.system_info.platform()
        else:
            default_platform = self.default_arch.platform

        if self.platform is None or self.platform in ('', 'default'):
            set_attr("platform", default_platform)

        if self.platform == default_platform or is_host:
            set_attr("is_host", True)

            # This is host so we can guess the machine name and domain
            machine, domain = self.system_info.hostname()
            set_attr("machine", machine)
            set_attr("domain", domain)
            set_attr("is_default", self.platform == default_platform)

        else:
            set_attr("is_host", False)
            # This is a target name. Sometimes it's suffixed by the host os
            # name. If the name is not a key in config.platform_info try to
            # to find a valid name by suppressing -linux, -solaris or -windows
            if self.platform not in config.platform_info:
                for suffix in ('-linux', '-solaris', '-windows'):
                    if self.platform.endswith(suffix):
                        set_attr("platform", self.platform[:-len(suffix)])
                        break

        # Fill other attributes
        pi = config.platform_info[self.platform]
        set_attr("cpu", CPU(pi['cpu'], pi.get('endian', None), self.is_host))
        set_attr("os", OS(pi['os'], self.is_host, version=version, mode=mode))
        set_attr("is_hie", pi['is_hie'])

        # Find triplet
        set_attr("triplet", None)
        set_attr("triplet",
                 config.build_targets[self.platform]['name'] % self.to_dict())

    @property
    def is_virtual(self):
        """Check if we are on a virtual system.

        :return: True if the system represented by Arch is a virtual machine
        :rtype: bool
        """
        if not self.is_host:
            return False
        return self.system_info.is_virtual()

    def to_dict(self):
        """Export os and cpu variables as os_{var} and cpu_{var}.

        :return: a dictionary representing the current Arch instance
        :rtype: dict
        """
        str_dict = self.as_dict()
        str_dict['is_virtual'] = self.is_virtual

        for key, var in self.os.as_dict().iteritems():
            str_dict["os_" + key] = var
        for key, var in self.cpu.as_dict().iteritems():
            str_dict["cpu_" + key] = var
        del str_dict['os']
        del str_dict['cpu']
        return str_dict

    def __str__(self):
        """Return a representation string of the object."""
        result = "platform: %(platform)s\n" \
            "machine:  %(machine)s\n" \
            "is_hie:   %(is_hie)s\n" \
            "is_host:  %(is_host)s\n" \
            "is_virtual: %(is_virtual)s\n" \
            "triplet:  %(triplet)s\n" \
            "domain:   %(domain)s\n" \
            "OS\n" \
            "   name:          %(os_name)s\n" \
            "   version:       %(os_version)s\n" \
            "   exeext:        %(os_exeext)s\n" \
            "   dllext:        %(os_dllext)s\n" \
            "   is_bareboard:  %(os_is_bareboard)s\n" \
            "CPU\n" \
            "   name:   %(cpu_name)s\n" \
            "   bits:   %(cpu_bits)s\n" \
            "   endian: %(cpu_endian)s\n" \
            "   cores:  %(cpu_cores)s" % self.to_dict()
        return result


if __name__ == "__main__":
    print Arch(is_host=True)

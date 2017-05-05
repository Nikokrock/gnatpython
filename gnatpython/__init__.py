############################################################################
#                                                                          #
#                            __INIT__.PY                                   #
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

"""Root module of the GNATpython package."""

import logging

__version__ = "2.0"

# Add a do-nothing handler to avoid "No handler could be found for logger..."
# messages.

# The following setting allows us to prevent the logging module from
# trying to use the threadding and/or multiprocessing modules. Depending
# on how python was configured, these modules may not be available, and
# without these settings, trying to use the logging module would cause
# an exception.
logging.logThreads = 0
logging.logMultiprocessing = 0


class NullHandler(logging.Handler):
    """Add a handler which does nothing."""

    def emit(self, _record):
        """emit nothing."""
        pass

h = NullHandler()
logging.getLogger("gnatpython").addHandler(h)

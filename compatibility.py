#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright © 2013 by Lasse Fister <commander@graphicore.de>
# 
# This file is part of Multitoner.
#
# Multitoner is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# Multitoner is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

from __future__ import division, print_function, unicode_literals

import sys

__all__ = ['repair_gsignals', 'range', 'encode', 'decode']

if sys.version_info < (3,0):
    # Had following error with Python 2.7.4 and GTK 3.6.4 when using
    # from __future__ import unicode_literals
    # TypeError: Error when calling the metaclass bases __gsignals__ keys must be strings
    def repair_gsignals(gsignals):
        new = {}
        for k,v in gsignals.items():
            new[k.encode("utf-8")] = v
        return new
    
    range = xrange
    
    def encode(unicodestring):
        """ unicode to string """
        return unicodestring.encode('utf-8')
    
    def decode(string):
        """ string to unicode """
        return string.decode('utf-8')
else:
    def repair_gsignals(gsignals):
        return gsignals
    
    range = range
    
    def _unit(arg):
        return arg
    
    encode = _unit
    decode = _unit

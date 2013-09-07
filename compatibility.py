#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division, print_function, unicode_literals
import sys

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

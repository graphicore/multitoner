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

from __future__ import print_function, unicode_literals

import sys
import ctypes as c
try:
    # python 2
    from cStringIO import StringIO
except ImportError:
    # python 3
    from io import BytesIO as StringIO

import ghostscript._gsprint as gs

__all__ = ['GhostscriptError', 'GhostScriptRunner']

GhostscriptError = gs.GhostscriptError

class GhostScriptRunner(object):
    """ Render a string of PostScript (better EPS) to a ctypes buffer"""
    def __init__(self):
        self.args = None
        self._args = ['-dEPSCrop']
        self.instance = gs.new_instance()
        self.stdin = self.width = self.height = self.rgbbuf = self.result \
                   = self.buf = self.rowstride = None
        # need to keep a reference of this stuff around
        self._references = {
            'stdin': gs.c_stdstream_call_t(self._gsdll_stdin),
            'stdout': gs.c_stdstream_call_t(self._gsdll_stdout),
            'stderr': gs.c_stdstream_call_t(self._gsdll_stderr),
            'display': gs.Display_callback_s(
                c.c_int(c.sizeof(gs.Display_callback_s)),
                c.c_int(gs.DISPLAY_VERSION_MAJOR),
                c.c_int(gs.DISPLAY_VERSION_MINOR),
                gs.c_display_open(self.display_open),
                gs.c_display_preclose(self.display_preclose),
                gs.c_display_close(self.display_close),
                gs.c_display_presize(self.display_presize),
                gs.c_display_size(self.display_size),
                gs.c_display_sync(self.display_sync),
                gs.c_display_page(self.display_page),
                c.cast(None, gs.c_display_update),
                c.cast(None, gs.c_display_memalloc), # NULL,	/* memalloc */
                c.cast(None, gs.c_display_memfree), # NULL,	/* memfree */
                c.cast(None, gs.c_display_separation)
            )
        }
        
        gs.set_stdio(self.instance, self._references['stdin'],
            self._references['stdout'], self._references['stderr'])
        gs.set_display_callback(self.instance, c.byref(self._references['display']))
    
    def cleanup(self):
        """ Purge the ghostscript instance """
        gs.delete_instance(self.instance)
        self.instance = None
    
    def run(self, eps):
        """ Render the string in eps to a buffer in a format suitable for
        Cairo surfaces. Return a tuple: (width, height, rowstride, ctypes string buffer)
        """
        CAIRO_FORMAT_RGB24 = gs.DISPLAY_COLORS_RGB | gs.DISPLAY_UNUSED_LAST | \
                             gs.DISPLAY_DEPTH_8 | gs.DISPLAY_LITTLEENDIAN
        dformat = "-dDisplayFormat=%d" % \
                  ( CAIRO_FORMAT_RGB24 | gs.DISPLAY_TOPFIRST )
        
        self.stdin = StringIO(eps)
        
        userArgs = self.args or self._args
        #"-sDisplayHandle=123456"
        args = ['-ignored-', dformat, '-sDEVICE=display', '-r72x72', '-q'] \
               + userArgs + ['-_']
        
        try:
            gs.init_with_args(self.instance, args)
        except Exception:
            # re-raise always
            raise
        finally:
            gs.exit(self.instance)
        
        result = self.result
        self.stdin = self.width = self.height = self.result = self.buf \
                   = self.rowstride = None
        return result
    
    def _gsdll_stdin(self, instance, dest, count):
        try:
            data = self.stdin.read(count)
        except Exception:
            count = -1
        else:
            if not data:
                count = 0
            else:
                count = len(data)
                c.memmove(dest, c.c_char_p(data), count)
        return count
    
    def _gsdll_stdout(self, instance, data, length):
        message = data[:length]
        if str is not bytes:
            message = message.decode('utf-8')
        sys.stdout.write(message)
        sys.stdout.flush()
        return length
    
    def _gsdll_stderr(self, instance, data, length):
        message = data[:length]
        if str is not bytes:
            message = message.decode('utf-8')
        sys.stderr.write(message)
        sys.stderr.flush()
        return length
    
    def display_open(self, handle, device):
        return 0
    
    def display_preclose(self, handle, device):
        return 0
    
    def display_close(self, handle, device):
        return 0
    
    def display_presize(self, handle, device, width, height, raster, format):
        return 0
    
    def display_size(self, handle, device, width, height, raster, format, pimage):
        self.width = width
        self.height = height
        self.rowstride = raster
        self.buf = pimage
        return 0
    
    def display_sync(self, handle, device):
        return 0
    
    def display_page(self, handle, device, copies, flush):
        buffer_size = self.rowstride * self.height
        rgbbuf = c.create_string_buffer(buffer_size)
        c.memmove(rgbbuf, self.buf, buffer_size)
        self.result = (self.width, self.height, self.rowstride, rgbbuf)
        return 0

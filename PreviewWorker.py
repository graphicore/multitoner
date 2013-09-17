#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division, print_function, unicode_literals

import sys
from multiprocessing import Pool
import ctypes as c
from functools import wraps
import PIL.Image as Image

from epstool import EPSTool
from model import ModelInk
from GhostScriptRunner import GhostScriptRunner, GhostscriptError

# just a preparation for i18n
def _(string):
    return string

# in the process
gs = None
imageName = None
epsTool = None

def _init_ghostscript():
    global gs
    if gs is not None:
        gs.cleanup()
        gs = None
    gs = GhostScriptRunner()

def initializer(*args):
    """ 
    import and initialize ghostscript only in a worker process
    the main process doesn't need it
    """
    _init_ghostscript()

def _catch_all(func):
    """Catch all exceptions in the process and make an answer to display to the user."""
    @wraps(func)
    def wrapper(*args):
        try:
            return func(*args)
        except Exception as e:
            return ('error'
                   , _('Caught a Fatal Exception')
                   , _('Message: {0} {1} {2}').format(e, type(e), traceback)
                   )
    return wrapper

def _open_image(filename):
    """ returns (epsTool, notice, error)
    
    epsTool: an instance of EPSTool loaded with the data of the image at filename
    notice: a tuple with a notice for the user or None
    error: None or if an error occured an error tuple to return with work,
           then epstool and notice must not be used.
    """
    error = notice = epsTool = None
    try:
        im = Image.open(filename)
    except IOError as e:
        error = ('error'
                , _('Can\'t open image for preview {0}.').format(filename)
                , _('Message: {0} {1}').format(e, type(e))
                )
    else:
        if im.mode != 'L':
            # TODO: This is used to display a message in the ui process.
            # It  should warn that reproducing the result relies on the method
            # used to convert here. It's better to have grayscale as input.
            notice = (_('Converted image to grayscale')
                     , _('From Python Imaging Library mode "{0}".').format(im.mode)
                     )
            im = im.convert('L')
        epsTool = EPSTool()
        epsTool.setImageData(im.tostring(), im.size)
    
    return epsTool, notice, error

@_catch_all
def work(filename, inks):
    """
    This runs in its own process, ideally, then there is no threading
    problem with ghostscript
    """
    global imageName, epsTool
    notice = None
    if filename != imageName:
        # epsTool may use a lot of memory, so it's deleted it early
        epsTool = imageName = None
        epsTool, notice, error = _open_image(filename)
        if error is not None:
            return error
        imageName = imageName
    inks = [ModelInk(**t) for t in inks]
    epsTool.setColorData(*inks)
    eps = epsTool.create()
    
    # with open(imageName + '.tsst.eps', 'w') as f:
    #     f.write(eps)
    
    try:
        r = gs.run(eps)
    except GhostscriptError as e:
        result = ('error'
                 , _('Ghostscript encountered an Error')
                 , _('Message: {0} {1}').format(e, type(e))
                 )
    else:
        # need to transport the result as a string
        result = ('result', r[0], r[1], r[2].raw, notice)
    return result

# end in the process

class PreviewWorker(object):
    def __init__(self, processes=1):
        self.pool = Pool(initializer=initializer, processes=processes)
    
    def callback(self, callback_data, result):
        """
        this restores the buffer data from string and runs the callback
        """
        callback = callback_data[0]
        user_data = callback_data[1:]
        type = result[0]
        if type == 'result':
            buf = c.create_string_buffer(result[-2])
            notice = result[-1]
            result_data = result[1:-2]
            args = (type, ) + user_data + result_data + (buf, notice)
        else:
            result_data = result[1:]
            args = (type, ) + user_data + result_data
        callback(*args)
    
    def addJob(self, callback, imageName, *inks):
        def cb(result):
            self.callback(callback, result)
        inks = [t.getArgs() for t in inks]
        self.pool.apply_async(work, args=(imageName, inks), callback=cb)

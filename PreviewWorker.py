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
            # Display a message in the ui process. Earn that reproducing
            # the result relies on the method used to convert here. It's
            # better to have a grayscale image as input.
            notice = (_('Converted image to grayscale')
                     , _('From Python Imaging Library (PIL) mode "{0}".').format(im.mode)
                     )
            im = im.convert('L')
        epsTool = EPSTool()
        epsTool.setImageData(im.tostring(), im.size)
    
    return epsTool, notice, error

@_catch_all
def work(eps):
    """
    This runs in its own process, ideally, then there is no threading
    problem with ghostscript
    """
    try:
        r = gs.run(eps)
    except GhostscriptError as e:
        result = ('error'
                 , _('Ghostscript encountered an Error')
                 , _('Message: {0} {1}').format(e, type(e))
                 )
    else:
        # need to transport the result as a string
        result = ('result', r[0], r[1], r[2].raw)
    return result

def no_work(result):
    """ stick to the asynchronous paradigma """
    return result

# end in the process
class PreviewWorker(object):
    def __init__(self, processes=1):
        self.pool = Pool(initializer=initializer, processes=processes)
        self._data = {}
    
    def removeClient(self, client_widget, client_id):
        if client_id in self._data:
            del self._data[client_id]
    
    def callback(self, callback, user_data, result, notice):
        """
        this restores the buffer data from string and runs the callback
        """
        type = result[0]
        if type == 'result':
            buf = c.create_string_buffer(result[-1])
            result_data = result[1:-1]
            args = (type, ) + user_data + result_data + (buf, notice)
        else:
            result_data = result[1:]
            args = (type, ) + user_data + result_data
        callback(*args)
    
    def addJob(self, client_id, callback_data, image_name, *inks):
        notice = None
        def cb(result):
            self.callback(callback_data[0], callback_data[1:], result, notice)
        
        if client_id not in self._data:
            self._data[client_id] = {
                'image_name': None,
                'epstool': None
            }
        client_data = self._data[client_id]
        error = None
        if client_data['image_name'] != image_name:
            # notice will be available in the cb closure
            epsTool, notice, error = _open_image(image_name)
            if error:
                # call cb async
                # cb(error)
                return
            client_data['image_name'] = image_name
            client_data['epstool'] = epsTool
        else:
            epsTool = client_data['epstool']
        if error is not None:
            self.pool.apply_async(no_work, args=(error, ), callback=cb)
        else:
            epsTool.setColorData(*inks)
            eps = epsTool.create()
            self.pool.apply_async(work, args=(eps, ), callback=cb)

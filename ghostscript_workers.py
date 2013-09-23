#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division, print_function, unicode_literals

import sys
from multiprocessing import Pool
import ctypes as c
from array import array
from functools import wraps
import PIL.Image as Image

from epstool import EPSTool
from mtt2eps import open_image
from model import ModelInk
from GhostScriptRunner import GhostScriptRunner, GhostscriptError
from compatibility import range, encode

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
    """
    Catch all exceptions in the worker and return an answer to display to the user.
    
    The Worker Pool with callback doesn't propagate Exceptions in the
    worke, instead the callback just never gets called.
    """
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
        result = ('result', r[0], r[1], r[2], r[-1].raw)
    return result

def no_work(result):
    """ stick to the asynchronous paradigma """
    return result

# end in the process
class PreviewWorker(object):
    def __init__(self, pool):
        self.pool = pool
        self._data = {}
    
    @classmethod
    def new_with_pool(Cls, processes=None):
        pool = Pool(initializer=initializer, processes=processes)
        return Cls(pool)
    
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
    
    def _getClientData(self, client_id, image_name):
        if client_id not in self._data:
            self._data[client_id] = {
                'image_name': None,
                'epstool': None
            }
        client_data = self._data[client_id]
        if client_data['image_name'] != image_name:
            epsTool, notice, error = open_image(image_name)
            client_data['image_name'] = image_name
            client_data['epstool'] = epsTool
        else:
            error = notice = None
            epsTool = client_data['epstool']
        return epsTool, notice, error
    
    def addJob(self, client_id, callback_data, image_name, *inks):
        # notice will be used in the cb closure
        epsTool, notice, error = self._getClientData(client_id, image_name)
        
        if error is not None:
            args = (error, )
            worker = no_work
        else:
            epsTool.setColorData(*inks)
            eps = epsTool.create()
            args = (eps, )
            worker = work
        
        def cb(result):
            self.callback(callback_data[0], callback_data[1:], result, notice)
        
        self.pool.apply_async(worker, args=args, callback=cb)
    
class GradientWorker(object):
    def __init__(self, pool):
        self.pool = pool
        
        self._epsTool = EPSTool()
        gradientBin = array(encode('B'), range(0, 256))
        # the input gradient is 256 pixels wide and 1 pixel height
        # we don't need more data and scale this on display
        self._epsTool.setImageData(gradientBin.tostring(), (256, 1))
    
    @classmethod
    def new_with_pool(Cls):
        pool = Pool(initializer=initializer)
        return Cls(pool)
    
    def callback(self, callback, user_data, result):
        """
        this restores the buffer data from string and runs the callback
        """
        assert result[0] == 'result', 'Gradient rendering failed {0}, {1} {2}'.format(*result)
        buf = c.create_string_buffer(result[-1])
        result_data = result[1:-1]
        args = user_data + result_data + (buf, )
        callback(*args)
    
    def addJob(self, callback, *inks):
        self._epsTool.setColorData(*inks)
        eps = self._epsTool.create()
        def cb(result):
            self.callback(callback[0], callback[1:], result)
        self.pool.apply_async(work, args=(eps, ), callback=cb)
    
def factory():
    processes = None
    pool = Pool(initializer=initializer, processes=processes)
    gradientWorker = GradientWorker(pool)
    previewWorker = PreviewWorker(pool)
    return gradientWorker, previewWorker

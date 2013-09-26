#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division, print_function, unicode_literals

from multiprocessing import Pool
import ctypes as c
from array import array
from functools import wraps
import PIL.Image as Image

from epstool import EPSTool
from mtt2eps import open_image
from ghostscript_runner import GhostScriptRunner, GhostscriptError
from compatibility import range, encode

__all__ = ['PreviewWorker', 'GradientWorker', 'factory']

# just a preparation for i18n
def _(string):
    return string

# in the process
gs = None

def _init_ghostscript():
    global gs
    if gs is not None:
        gs.cleanup()
        gs = None
    gs = GhostScriptRunner()

def initializer(*args):
    """  Initialize the worker environment """
    _init_ghostscript()

def _catch_all(func):
    """ Catch all exceptions in the worker and return a message to display to the user.
    
    The Worker Pool with callback doesn't propagate Exceptions in the
    worker, instead the callback just never gets called.
    """
    @wraps(func)
    def wrapper(*args):
        try:
            return func(*args)
        except Exception as e:
            return ('error'
                   , _('Caught a Fatal Exception')
                   , _('Message: {0} {1} {2}').format(e, type(e))
                   )
    return wrapper

@_catch_all
def work(eps):
    """ Render eps in a worker process. Return a result or an error message
    
    A result is ('result', int width, int height, int rowstride, bytes image data)
    An error is ('error', string message, string or None more_info')

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
    """ Stick to the asynchronous paradigma but do nothing. Return the argument. """
    return result

# end in the process
class PreviewWorker(object):
    """ Worker ro render eps images asynchronously """
    def __init__(self, pool):
        self.pool = pool
        self._data = {}
    
    @classmethod
    def new_with_pool(Cls, processes=None):
        pool = Pool(initializer=initializer, processes=processes)
        return Cls(pool)
    
    def remove_client(self, client_id):
        """ remove the cached data for client_id """
        if client_id in self._data:
            del self._data[client_id]
        return True
    
    def _callback(self, callback, user_data, result, notice):
        """ Restore the buffer data from string and run the callback """
        type = result[0]
        if type == 'result':
            buf = c.create_string_buffer(result[-1])
            result_data = result[1:-1]
            args = (type, ) + user_data + result_data + (buf, notice)
        else:
            result_data = result[1:]
            args = (type, ) + user_data + result_data
        callback(*args)
    
    def _get_client_data(self, client_id, image_name):
        if client_id not in self._data:
            self._data[client_id] = {
                'image_name': None,
                'eps_tool': None
            }
        client_data = self._data[client_id]
        if client_data['image_name'] != image_name:
            eps_tool, notice, error = open_image(image_name)
            client_data['image_name'] = image_name
            client_data['eps_tool'] = eps_tool
        else:
            error = notice = None
            eps_tool = client_data['eps_tool']
        return eps_tool, notice, error
    
    def add_job(self, client_id, callback_data, image_name, *inks):
        # 'notice' will be used in the cb closure
        eps_tool, notice, error = self._get_client_data(client_id, image_name)
        
        if error is not None:
            args = (error, )
            worker = no_work
        else:
            eps_tool.set_color_data(*inks)
            eps = eps_tool.create()
            args = (eps, )
            worker = work
        def cb(result):
            self._callback(callback_data[0], callback_data[1:], result, notice)
        
        self.pool.apply_async(worker, args=args, callback=cb)
    
class GradientWorker(object):
    """ Worker to render the gradient of one ore more instances of ModelCurve """
    def __init__(self, pool):
        self.pool = pool
        
        self._eps_tool = EPSTool()
        gradient_bin = array(encode('B'), range(0, 256))
        # the input gradient is 256 pixels wide and 1 pixel height
        # we don't need more data and scale this on display
        self._eps_tool.set_image_data(gradient_bin.tostring(), (256, 1))
    
    @classmethod
    def new_with_pool(Cls):
        pool = Pool(initializer=initializer)
        return Cls(pool)
    
    def _callback(self, callback, user_data, result):
        """ Restore the buffer data from string and run the callback """
        assert result[0] == 'result', 'Gradient rendering failed {0}, {1} {2}'\
                                       .format(*result)
        buf = c.create_string_buffer(result[-1])
        result_data = result[1:-1]
        args = user_data + result_data + (buf, )
        callback(*args)
    
    def add_job(self, callback, *inks):
        self._eps_tool.set_color_data(*inks)
        eps = self._eps_tool.create()
        def cb(result):
            self._callback(callback[0], callback[1:], result)
        self.pool.apply_async(work, args=(eps, ), callback=cb)
    
def factory():
    """ Create a GradientWorker and a PreviewWorker both sharing the same
    worker pool. Return (instance of GradientWorker, instance of PreviewWorker).
    
    """
    processes = None
    pool = Pool(initializer=initializer, processes=processes)
    gradient_worker = GradientWorker(pool)
    preview_worker = PreviewWorker(pool)
    return gradient_worker, preview_worker

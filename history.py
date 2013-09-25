#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division, print_function, unicode_literals

try:
    import cPickle as pickle
except ImportError:
    import pickle
from weakref import ref as weakref
from functools import wraps
from warnings import warn
from compatibility import encode

__all__ = ['History', 'get_setter_command', 'get_calling_command', 'historize',
           'ModelHistoryApi']

def get_setter_command(name, value):
    pickled_value = pickle.dumps(value, -1)
    def cmd(obj):
        value = pickle.loads(pickled_value)
        setattr(obj, name, value)
    cmd.__doc__ = encode('setting {0}'.format(name))
    # name is used to distinguish between different commands on the same model
    # model it is important detect consecutive commands
    cmd.__name__= encode('set__{0}__'.format(name))
    return cmd

def get_calling_command(method, *args):
    pickled_args = pickle.dumps(args, -1)
    def cmd(obj):
        args = pickle.loads(pickled_args)
        getattr(obj, method)(*args)
    cmd.__doc__ = encode('calling {0}'.format(method))
    # name is used to distinguish between different commands on the same
    # model it is important detect consecutive commands
    cmd.__name__= encode('call__{0}__'.format(method))
    return cmd


def historize(fn):
    @wraps(fn)
    def wrapper(*args, **kwds):
        name = fn.__name__
        obj = args[0]
        got_value = False
        try:
            value = getattr(obj, name)
            got_value = True
        except AttributeError:
            pass
        if got_value:
            undo = get_setter_command(name, value)
            obj.add_history(undo)
        return fn(*args, **kwds)
    return wrapper

class ModelHistoryApi(object):
    def _getstate(self, state):
        if '_history_api' in state:
            del state['_history_api'] # remove the WeakRef
    def __getstate__(self):
        state = self.__dict__.copy() # copy the dict since we change it
        return self._getstate(_getstate)
    
    # no need for since this Class can handle a missing _history_api
    # def __setstate__():
    
    @property
    def history_api(self):
        weak_ref = getattr(self, '_history_api', None)
        history_api = None
        if weak_ref is not None:
            history_api = weak_ref()
        if history_api is None:
            warn('Missing History API for ' + str(self))
        return history_api
    
    @history_api.setter
    def history_api(self, api):
        self._history_api = weakref(api)
    
    def add_history(self, command, path=None):
        if path is None:
            path = []
            # print('add history: ', self.__class__.__name__, command.__doc__)
        path.append(self.id)
            
        history_api = self.history_api
        if history_api is None:
            return
        history_api.add_history(command, path)
    
    def register_consecutive_command(self, path=None):
        """
        The view is about to execute the same command with different values
        consecutively zero or more times. To make just one history entry
        of that process, the view can use this method. Then the following
        commands with the same combination of path and command.__name__
        will only make one history undo entry
        """
        if path is None:
            path = []
        path.append(self.id)
        
        history_api = self.history_api
        if history_api is None:
            return
        history_api.register_consecutive_command(path)

class History(object):
    def __init__(self, root_model):
        self._undo_commands = []
        self._redo_commands = []
        self._is_undo = False
        self._is_redo = False
        
        # (path, started, commandName)
        self._conscecutive_command = (None, False, None)
        
        root_model.history_api = self
        self._root_model = root_model;
    
    def _resolve_path(self, path):
        path = path[:-1] # we don't need the root_model id
        model = self._root_model
        for mid in reversed(path):
            model = model.getById(mid)
        return model
    
    def add_history(self, command, path):
        path = tuple(path)
        entry = (path, command)
        if self._is_undo:
            self._end_consecutive_command()
            self._redo_commands.append(entry)
        else:
            if not self._is_redo:
                # if its no redo its do: new history and the old redos are invalid
                self._redo_commands = []
            else:
                self._end_consecutive_command()
            if not self._is_consecutive_command(path, command.__name__):
                self._undo_commands.append(entry)
    
    def register_consecutive_command(self, path):
        self._conscecutive_command = (tuple(path), False, None)
    
    def _end_consecutive_command(self):
        self._conscecutive_command = (None, False, None)
    
    def _is_consecutive_command(self, path, cmd_name):
        registered_path, started, registered_cmd_name = self._conscecutive_command
        if registered_path is None:
            # nothing registered
            return False
        if registered_path != path:
            # other model
            self._end_consecutive_command()
            return False
        if started == True and registered_cmd_name != cmd_name:
            # same model other command
            self._end_consecutive_command()
            return False
        if started == False:
            # this is the first command after registration
            # the command will be added to undo other conscecutive
            # commands with cmd_name will not be added to the undo history
            self._conscecutive_command = (registered_path, True, cmd_name)
            return False
        # this was a consecutive command
        return True
    
    def undo(self):
        if len(self._undo_commands) == 0:
            return
        path, command = self._undo_commands.pop()
        model = self._resolve_path(path)
        # this will add a command to history
        self._is_undo = True
        command(model)
        self._is_undo = False
    
    def redo(self):
        if len(self._redo_commands) == 0:
            return
        path, command = self._redo_commands.pop()
        model = self._resolve_path(path)
        # this will add a command to history
        self._is_redo = True
        command(model)
        self._is_redo = False
    
    def get_counts(self):
        return (len(self._undo_commands), len(self._redo_commands))

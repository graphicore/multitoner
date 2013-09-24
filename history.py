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

__all__ = ['History', 'getSetterCommand', 'getCallingCommand', 'historize',
           'ModelHistoryApi']

def getSetterCommand(name, value):
    pickledValue = pickle.dumps(value, -1)
    def cmd(obj):
        value = pickle.loads(pickledValue)
        setattr(obj, name, value)
    cmd.__doc__ = encode('setting {0}'.format(name))
    # name is used to distinguish between different commands on the same model
    # model it is important detect consecutive commands
    cmd.__name__= encode('set__{0}__'.format(name))
    return cmd

def getCallingCommand(method, *args):
    pickledArgs = pickle.dumps(args, -1)
    def cmd(obj):
        args = pickle.loads(pickledArgs)
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
        gotValue = False
        try:
            value = getattr(obj, name)
            gotValue = True
        except AttributeError:
            pass
        if gotValue:
            undo = getSetterCommand(name, value)
            obj.addHistory(undo)
        return fn(*args, **kwds)
    return wrapper

class ModelHistoryApi(object):
    def _getstate(self, state):
        if '_historyAPI' in state:
            del state['_historyAPI'] # remove the WeakRef
    def __getstate__(self):
        state = self.__dict__.copy() # copy the dict since we change it
        return self._getstate(_getstate)
    
    # no need for since this Class can handle a missing _historyAPI
    # def __setstate__():
    
    @property
    def historyAPI(self):
        weakRef = getattr(self, '_historyAPI', None)
        historyAPI = None
        if weakRef is not None:
            historyAPI = weakRef()
        if historyAPI is None:
            warn('Missing History API for ' + str(self))
        return historyAPI
    
    @historyAPI.setter
    def historyAPI(self, api):
        self._historyAPI = weakref(api)
    
    def addHistory(self, command, path=None):
        if path is None:
            path = []
            # print('add history: ', self.__class__.__name__, command.__doc__)
        path.append(self.id)
            
        historyAPI = self.historyAPI
        if historyAPI is None:
            return
        historyAPI.addHistory(command, path)
    
    def registerConsecutiveCommand(self, path=None):
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
        
        historyAPI = self.historyAPI
        if historyAPI is None:
            return
        historyAPI.registerConsecutiveCommand(path)

class History(object):
    def __init__(self, rootModel):
        self._undoCommands = []
        self._redoCommands = []
        self._isUndo = False
        self._isRedo = False
        
        # (path, started, commandName)
        self._conscecutiveCommand = (None, False, None)
        
        rootModel.historyAPI = self
        self._rootModel = rootModel;
    
    def resolvePath(self, path):
        path = path[:-1] # we don't need the rootModel id
        model = self._rootModel
        for mid in reversed(path):
            model = model.getById(mid)
        return model
    
    def addHistory(self, command, path):
        path = tuple(path)
        entry = (path, command)
        if self._isUndo:
            self._endConsecutiveCommand()
            self._redoCommands.append(entry)
        else:
            if not self._isRedo:
                # if its no redo its do: new history and the old redos are invalid
                self._redoCommands = []
            else:
                self._endConsecutiveCommand()
            if not self._isConsecutiveCommand(path, command.__name__):
                self._undoCommands.append(entry)
    
    def registerConsecutiveCommand(self, path):
        self._conscecutiveCommand = (tuple(path), False, None)
    
    def _endConsecutiveCommand(self):
        self._conscecutiveCommand = (None, False, None)
    
    def _isConsecutiveCommand(self, path, cmdName):
        registeredPath, started, registeredCmdName = self._conscecutiveCommand
        if registeredPath is None:
            # nothing registered
            return False
        if registeredPath != path:
            # other model
            self._endConsecutiveCommand()
            return False
        if started == True and registeredCmdName != cmdName:
            # same model other command
            self._endConsecutiveCommand()
            return False
        if started == False:
            # this is the first command after registration
            # the command will be added to undo other conscecutive
            # commands with cmdName will not be added to the undo history
            self._conscecutiveCommand = (registeredPath, True, cmdName)
            return False
        # this was a consecutive command
        return True
    
    def undo(self):
        if len(self._undoCommands) == 0:
            return
        path, command = self._undoCommands.pop()
        model = self.resolvePath(path)
        # this will add a command to history
        self._isUndo = True
        command(model)
        self._isUndo = False
    
    def redo(self):
        if len(self._redoCommands) == 0:
            return
        path, command = self._redoCommands.pop()
        model = self.resolvePath(path)
        # this will add a command to history
        self._isRedo = True
        command(model)
        self._isRedo = False
    
    def getCounts(self):
        return (len(self._undoCommands), len(self._redoCommands))
    

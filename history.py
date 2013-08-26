#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division
import cPickle as pickle
from weakref import ref as Weakref
from functools import wraps
from warnings import warn
from model import *

def getSetterCommand(name, value):
    pickledValue = pickle.dumps(value)
    def cmd(obj):
        value = pickle.loads(pickledValue)
        setattr(obj, name, value)
    cmd.__doc__ = 'set {0}'.format(name)
    return cmd

def getCallingCommand(method, *args, **kwds):
    print method, 'args:', args;
    pickledArgs = pickle.dumps(args)
    pickledKwds = pickle.dumps(kwds)
    def cmd(obj):
        args = pickle.loads(pickledArgs)
        kwds = pickle.loads(pickledKwds)
        getattr(obj, method)(*args, **kwds)
    cmd.__doc__ = 'call {0}'.format(method)
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
    @property
    def historyAPI(self):
        weakRef = getattr(self, '_historyAPI', None)
        if weakRef is None:
            return None
        return weakRef()
    
    @historyAPI.setter
    def historyAPI(self, api):
        self._historyAPI = Weakref(api)
    
    def addHistory(self, command, path=None):
        if path is None:
            path = []
            print self.__class__.__name__, command.__doc__
        historyAPI = self.historyAPI
        if historyAPI is None:
            warn('Missing History API for ' + str(self))
            return
        path.append(self.id)
        historyAPI.addHistory(command, path)

class History(object):
    def __init__(self, rootModel):
        self._undoCommands = []
        self._redoCommands = []
        self._isUndo = False
        self._isRedo = False
        
        rootModel.historyAPI = self
        self._rootModel = rootModel;
    
    def resolvePath(self, path):
        path = path[:-1] # we don't need the rootModel id
        model = self._rootModel
        for mid in reversed(path):
            model = model.getById(mid)
        return model
    
    def addHistory(self, command, path=None):
        print 'add History', command, path
        entry = (tuple(path), command)
        if self._isUndo:
            print 'is undo'
            self._redoCommands.append(entry)
        else:
            if not self._isRedo:
                print 'is do'
                # if its no redo its new history and the old redos are invalid
                self._redoCommands = []
            else:
                print 'is redo'
            self._undoCommands.append(entry)
    
    def undo(self):
        print 'undo num commands: ', len(self._undoCommands)
        if len(self._undoCommands) == 0:
            return
        path, command = self._undoCommands.pop()
        print path, command.__doc__
        model = self.resolvePath(path)
        # this will add a command to history
        self._isUndo = True
        command(model)
        self._isUndo = False
    
    def redo(self):
        print 'redo num commands: ', len(self._redoCommands)
        if len(self._redoCommands) == 0:
            return
        path, command = self._redoCommands.pop()
        print path, command.__doc__
        model = self.resolvePath(path)
        # this will add a command to history
        self._isRedo = True
        command(model)
        self._isRedo = False

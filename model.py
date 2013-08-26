#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division
from emitter import Emitter
from history import getSetterCommand, getCallingCommand, historize, ModelHistoryApi


# just a preparation for i18n
def _(string):
    return string

_uniqueIdCounter = 0
def getUniqueId():
    global _uniqueIdCounter
    result = _uniqueIdCounter
    _uniqueIdCounter += 1
    return result

class ModelException(Exception):
    pass

class Model(ModelHistoryApi, Emitter):
    def __init__(self, _id=None):
        super(Model, self).__init__()
        if _id is None:
            _id = getUniqueId()
        self._id = _id
    
    @property
    def id(self):
        return self._id
    
    def triggerOnModelUpdated(self, *args):
        for item in self:
            item.onModelUpdated(self, *args)

class ModelControlPoint(Model):
    def __init__(self, xy, _id=None):
        super(ModelControlPoint, self).__init__(_id=_id)
        self.xy = xy
    
    @property
    def xy(self):
        return self._xy
    
    @xy.setter
    @historize
    def xy(self, xy):
        xy = (
            max(0, min(1, xy[0])),
            max(0, min(1, xy[1]))
        )
        if not hasattr(self, '_xy') or xy != self._xy:
            self._xy = xy
            self.triggerOnModelUpdated()

class ModelCurve(Model):
    def __init__(self, points=[(0,0), (1,1)], interpolation='monotoneCubic', displayColor=(0,0,0), locked=False, visible=True, _id=None):
        super(ModelCurve, self).__init__(_id=_id)
        self.interpolation = interpolation
        self.points = points
        self.displayColor = displayColor
        self.locked = locked
        self.visible = visible
    
    def getArgs(self):
        return {
            'points': [p.xy for p in self.points],
            'interpolation': self.interpolation,
            'displayColor': self.displayColor,
            'locked': self.locked,
            'visible': self.visible,
            '_id': self.id
        }
    
    def getById(self, mid):
        for model in self._points:
            if model.id == mid:
                return model
        raise ModelException('Model not found by id {0}'.format(mid))
    
    def onModelUpdated(self, cp_model, *args):
        self.triggerOnModelUpdated('pointUpdate', cp_model, *args)
    
    def _addPoint(self, point, _id=None):
        model = ModelControlPoint(point, _id=_id)
        model.add(self) # subscribe
        model.historyAPI = self # for undo/redo
        self._points.append(model)
        return model
    
    def addPoint(self, point, _id=None):
        model = self._addPoint(point, _id=_id)
        
        undo = getCallingCommand('removePointById', model.id)
        self.addHistory(undo)
        
        self.triggerOnModelUpdated('addPoint', model)
    
    def removePoint(self, model):
        """
            removes the point with model id
            the invert of this is addPoint
        """
        if len(self._points) == 2:
            return
        position = self._points.index(model)
        
        undo = getCallingCommand('addPoint', model.xy, _id=model.id)
        self.addHistory(undo)
        
        self._points.pop(position)
        self.triggerOnModelUpdated('removePoint', model)
    
    def removePointById(self, modelId):
        model = self.getById(modelId)
        self.removePoint(model)
    
    @property
    def points(self):
        # this returns an unordered tuple of the point models
        # the _points list is not returned because changing the _points
        # list would change the model value and that's not intended as part
        # of the interface
        return tuple(self._points)
        
    @points.setter
    @historize
    def points(self, points):
        self._points = []
        for point in points:
            self._addPoint(point)
        self.triggerOnModelUpdated('setPoints')
    
    @property
    def interpolation(self):
        return self._interpolation
    
    @interpolation.setter
    @historize
    def interpolation(self, interpolation):
        self._interpolation = interpolation
        self.triggerOnModelUpdated('interpolationChanged')
    
    @property
    def pointsValue(self):
        return sorted(point.xy for point in self._points)
    
    @property
    def displayColor(self):
        return self._displayColor
    
    @displayColor.setter
    @historize
    def displayColor(self, value):
        self._displayColor = value
        self.triggerOnModelUpdated('displayColorChanged')
    
    @property
    def locked(self):
        return self._locked
    
    @locked.setter
    @historize
    def locked(self, value):
        self._locked = bool(value)
        self.triggerOnModelUpdated('lockedChanged')
    
    @property
    def visible(self):
        return self._visible
    
    @visible.setter
    @historize
    def visible(self, value):
        self._visible = bool(value)
        self.triggerOnModelUpdated('visibleChanged')
    
class ModelCurves(Model):
    def __init__(self, curves=[], ChildModel = ModelCurve,  _id=None):
        super(ModelCurves, self).__init__( _id=_id)
        self.ChildModel = ChildModel
        self.curves = curves
    
    @property
    def curves(self):
        return tuple(self._curves)
    
    @curves.setter
    @historize
    def curves(self, curves=[]):
        self._curves = []
        for curve in curves:
            # -1 appends
            self._insertCurve(-1, **curve)
        self.triggerOnModelUpdated('setCurves')
    
    @property
    def visibleCurves(self):
        return tuple(filter(lambda x: x.visible, self._curves))
    
    def __len__(self):
        return len(self._curves)
    
    def reorderByIdList(self, ids):
        currentOrder = map(lambda c: c.id, self._curves)
        if ids == currentOrder:
            # the same order was supplied
            return;
        
        undo = getCallingCommand('reorderByIdList', currentOrder)
        self.addHistory(undo)
        
        idSet = set(ids)
        if len(idSet) != len(self._curves):
            raise ModelException(
                'Reorder: list of ids is not long enough. Len is {0} but should be {1}'
                .format(len(ids), len(self._curves))
            )
        seen = set()
        newOrder = []
        for mid in ids:
            if mid in seen:
                raise ModelException('Having a duplicate id in ordering {0}'.format(mid))
            seen.add(mid)
            try:
                currentPos = currentOrder.index(mid)
            except ValueError, e:
                raise ModelException('Model not found by id {0}'.format(mid))
            newOrder.append(self._curves[currentPos])
        self._curves = newOrder
        self.triggerOnModelUpdated('reorderedCurves')
    
    def getById(self, mid):
        for model in self._curves:
            if model.id == mid:
                return model
        raise ModelException('Model not found by id {0}'.format(mid))
    
    def onModelUpdated(self, curveModel, *args):
        self.triggerOnModelUpdated('curveUpdate', curveModel, *args)
    
    def _insertCurve(self, position, **kwds):
        model = self.ChildModel(**kwds)
        model.add(self) # subscribe
        model.historyAPI = self # for undo/redo
        if position < 0:
            # this appends to the list
            position = len(self._curves)
        self._curves.insert(position, model)
        return model
    
    def insertCurve(self, position, **args):
        model = self._insertCurve(position, **args)
        
        undo = getCallingCommand('removeCurveById', model.id)
        self.addHistory(undo)
        
        # get the actual position the model has now
        position = self._curves.index(model)
        self.triggerOnModelUpdated('insertCurve', model, position)
    
    def appendCurve(self, **args):
        """ this is a shortcut for self.insertCurve(-1, **args) """
        self.insertCurve(-1, **args)
    
    def removeCurve(self, model):
        position = self._curves.index(model)
        
        undo = getCallingCommand('insertCurve', position, **model.getArgs())
        self.addHistory(undo)
        
        self._curves.pop(position)
        self.triggerOnModelUpdated('removeCurve', model)
    
    def removeCurveById(self, modelId):
        model = self.getById(modelId)
        self.removeCurve(model)

class ModelInk(ModelCurve):
    def __init__(self, name=_('(unnamed)'), cmyk=(0.0, 0.0, 0.0, 0.0), **args):
        super(ModelInk, self).__init__(**args)
        self.name = name
        self.cmyk = cmyk
    
    def getArgs(self):
        args = super(ModelInk, self).getArgs()
        args['name'] = self.name
        args['cmyk'] = self.cmyk
        return args
    
    @property
    def name(self):
        return self._name
    
    @name.setter
    @historize
    def name(self, value):
        self._name = value
        self.triggerOnModelUpdated('nameChanged')
    
    @property
    def cmyk(self):
        return tuple(self._cmyk)
    
    @cmyk.setter
    @historize
    def cmyk(self, value):
        self._cmyk = list(value)
        self.triggerOnModelUpdated('cmykChanged')
    
    @property
    def c(self):
        return self._cmyk[0]
    
    @c.setter
    @historize
    def c(self, value):
        self._cmyk[0] = value
        self.triggerOnModelUpdated('cmykChanged')
    
    @property
    def m(self):
        return self._cmyk[1]
    
    @m.setter
    @historize
    def m(self, value):
        self._cmyk[1] = value
        self.triggerOnModelUpdated('cmykChanged')
    
    @property
    def y(self):
        return self._cmyk[2]
    
    @y.setter
    @historize
    def y(self, value):
        self._cmyk[2] = value
        self.triggerOnModelUpdated('cmykChanged')
    
    @property
    def k(self):
        return self._cmyk[3]
    
    @k.setter
    @historize
    def k(self, value):
        self._cmyk[3] = value
        self.triggerOnModelUpdated('cmykChanged')

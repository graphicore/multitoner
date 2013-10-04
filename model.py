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

from __future__ import division, print_function, unicode_literals

from emitter import Emitter
from history import get_calling_command, historize, HistoryAPI


__all__ = ['ModelException', 'Model', 'ModelControlPoint', 'ModelCurve',
           'ModelCurves', 'ModelInk']


# just a preparation for i18n
def _(string):
    return string


_unique_id_counter = 0
def get_unique_id():
    """ not public method. Create a new id for each created model. 
    
    The id will be unique during the whole runtime of the programm,
    as long as this module is not forcefully reloaded.
    """
    global _unique_id_counter
    result = _unique_id_counter
    _unique_id_counter += 1
    return result


class ModelException(Exception):
    pass


class Model(HistoryAPI, Emitter):
    """ Abstract base class for all models.
    
    Subscribers must implement on_model_updated which is called with the
    emmiting instance as first argument and more arguments depending on
    the concrete model implementation
    """
    def __init__(self):
        super(Model, self).__init__()
        _id = get_unique_id()
        self._id = _id
    
    def __getstate__(self):
        """ pickle protocol: clean state from Emitter subscriptions and HistoryAPI """
        state = self.__dict__.copy() # copy the dict since we change it
        HistoryAPI._cleanstate(state)
        Emitter._cleanstate(state)
        return state
    
    @property
    def id(self):
        return self._id
    
    def _connect(self, *children):
        for child in children:
            child.add(self) # subscribe
            child.history_api = self # for undo/redo
    
    def trigger_on_model_updated(self, *args):
        for item in self._subscriptions:
            item.on_model_updated(self, *args)


class ModelControlPoint(Model):
    """ Model representing one control point """
    def __init__(self, xy):
        super(ModelControlPoint, self).__init__()
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
            self.trigger_on_model_updated()


class ModelCurve(Model):
    """ Model representing a curve: an interpolation strategy and two or
    more control points.
    
    The control points are in no specific order
    
    Further data is:
    display_color: the color used to draw the curve in an editor
    locked: whether the curve can be manipulated via an editor
    visible: whether the curve is visible in an editor or elsewhere
    """
    def __init__(self, points=((0,0), (1,1)), interpolation='monotoneCubic',
                 display_color=(0,0,0), locked=False, visible=True):
        super(ModelCurve, self).__init__()
        self.interpolation = interpolation
        self.points = points
        self.display_color = display_color
        self.locked = locked
        self.visible = visible
    
    def __setstate__(self, state):
        """ for the pickle protocol """
        self.__dict__.update(state)
        self._connect(*self._points)
    
    def get_args(self):
        """ Returns a dict that can be used to make a model with the same value.
        All values in the dict are simple python types.
        """
        return {
            'points': [p.xy for p in self.points],
            'interpolation': self.interpolation,
            'display_color': self.display_color,
            'locked': self.locked,
            'visible': self.visible,
        }
    
    def get_by_id(self, model_id):
        for model in self._points:
            if model.id == model_id:
                return model
        raise ModelException('Model not found by id {0}'.format(model_id))
    
    def on_model_updated(self, cp_model, *args):
        self.trigger_on_model_updated('pointUpdate', cp_model, *args)
    
    def _add_point(self, point):
        if not isinstance(point, ModelControlPoint):
            model = ModelControlPoint(point)
        else:
            model = point
        self._connect(model)
        self._points.append(model)
        return model
    
    def add_point(self, point):
        model = self._add_point(point)
        
        undo = get_calling_command('remove_point_by_id', model.id)
        self.add_history(undo)
        
        self.trigger_on_model_updated('addPoint', model)
    
    def remove_point(self, model):
        """ Remove the point model.
        
            The invert of this is add_point.
        """
        if len(self._points) == 2:
            return
        position = self._points.index(model)
        
        undo = get_calling_command('add_point', model)
        self.add_history(undo)
        
        self._points.pop(position)
        self.trigger_on_model_updated('removePoint', model)
    
    def remove_point_by_id(self, modelId):
        model = self.get_by_id(modelId)
        self.remove_point(model)
    
    @property
    def points(self):
        """ Return an unordered tuple of the point models.
        
        The _points list is not returned because changing the _points list
        would change the model value and that's not intended as part
        of the interface.
        """
        return tuple(self._points)
        
    @points.setter
    @historize
    def points(self, points):
        self._points = []
        for point in points:
            self._add_point(point)
        self.trigger_on_model_updated('setPoints')
    
    @property
    def interpolation(self):
        return self._interpolation
    
    @interpolation.setter
    @historize
    def interpolation(self, interpolation):
        self._interpolation = interpolation
        self.trigger_on_model_updated('interpolationChanged')
    
    @property
    def points_value(self):
        return sorted(point.xy for point in self._points)
    
    @property
    def display_color(self):
        return self._display_color
    
    @display_color.setter
    @historize
    def display_color(self, value):
        self._display_color = value
        self.trigger_on_model_updated('displayColorChanged')
    
    @property
    def locked(self):
        return self._locked
    
    @locked.setter
    @historize
    def locked(self, value):
        self._locked = bool(value)
        self.trigger_on_model_updated('lockedChanged')
    
    @property
    def visible(self):
        return self._visible
    
    @visible.setter
    @historize
    def visible(self, value):
        self._visible = bool(value)
        self.trigger_on_model_updated('visibleChanged')


class ModelInk(ModelCurve):
    """ Model extending ModelCurve with properties needed to use a ModelCurve
    as Ink in an PostScript deviceN setting.
    
    name: will be used to choose the right ink when printing the eps
    cmyk: is used to approximate the ink color in the preview.
    """
    def __init__(self, name=_('(unnamed)'), cmyk=(0.0, 0.0, 0.0, 0.0), **args):
        super(ModelInk, self).__init__(**args)
        self.name = name
        self.cmyk = cmyk
    
    def get_args(self):
        args = super(ModelInk, self).get_args()
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
        self.trigger_on_model_updated('nameChanged')
    
    @property
    def cmyk(self):
        return tuple(self._cmyk)
    
    @cmyk.setter
    @historize
    def cmyk(self, value):
        self._cmyk = list(value)
        self.trigger_on_model_updated('cmykChanged')
    
    @property
    def c(self):
        return self._cmyk[0]
    
    @c.setter
    @historize
    def c(self, value):
        self._cmyk[0] = value
        self.trigger_on_model_updated('cmykChanged')
    
    @property
    def m(self):
        return self._cmyk[1]
    
    @m.setter
    @historize
    def m(self, value):
        self._cmyk[1] = value
        self.trigger_on_model_updated('cmykChanged')
    
    @property
    def y(self):
        return self._cmyk[2]
    
    @y.setter
    @historize
    def y(self, value):
        self._cmyk[2] = value
        self.trigger_on_model_updated('cmykChanged')
    
    @property
    def k(self):
        return self._cmyk[3]
    
    @k.setter
    @historize
    def k(self, value):
        self._cmyk[3] = value
        self.trigger_on_model_updated('cmykChanged')


class ModelCurves(Model):
    """ Model representing a ordered collection of curves """
    def __init__(self, curves=(), ChildModel=ModelCurve):
        """ ChildModel is very often ModelInk but ModelCurve would be enough
        for some uses, like a stand alone CurveEditor.
        """
        super(ModelCurves, self).__init__()
        self.ChildModel = ChildModel
        self.curves = curves
    
    def __setstate__(self, state):
        """ for the pickle protocol """
        self.__dict__.update(state)
        self._connect(*self._curves)
    
    def get_args(self):
        return {'curves': [curve.get_args() for curve in self._curves]}
    
    @property
    def curves(self):
        return tuple(self._curves)
    
    @curves.setter
    @historize
    def curves(self, curves=()):
        self._curves = []
        for curve in curves:
            # -1 appends
            self._insert_curve(-1, curve)
        self.trigger_on_model_updated('setCurves')
    
    @property
    def visible_curves(self):
        return tuple(filter(lambda x: x.visible, self._curves))
    
    def __len__(self):
        return len(self._curves)
    
    @property
    def ids(self):
        return tuple(map(lambda c: c.id, self._curves))
        
    def reorder_by_id_list(self, ids):
        current_order = self.ids
        ids = tuple(ids)
        if ids == current_order:
            # the same order was supplied
            return
        
        undo = get_calling_command('reorder_by_id_list', current_order)
        self.add_history(undo)
        
        id_set = set(ids)
        if len(id_set) != len(self._curves):
            raise ModelException(
                'Reorder: list of ids is not long enough. Len is {0} but should be {1}'
                .format(len(ids), len(self._curves))
            )
        seen = set()
        new_order = []
        for mid in ids:
            if mid in seen:
                raise ModelException('Having a duplicate id in ordering {0}'.format(mid))
            seen.add(mid)
            try:
                current_pos = current_order.index(mid)
            except ValueError as e:
                raise ModelException('Model not found by id {0}'.format(mid))
            new_order.append(self._curves[current_pos])
        self._curves = new_order
        self.trigger_on_model_updated('reorderedCurves', ids)
    
    def get_by_id(self, mid):
        for model in self._curves:
            if model.id == mid:
                return model
        raise ModelException('Model not found by id {0}'.format(mid))
    
    def on_model_updated(self, curve_model, *args):
        self.trigger_on_model_updated('curveUpdate', curve_model, *args)
    
    def _insert_curve(self, position, curve):
        if not isinstance(curve, self.ChildModel):
            model = self.ChildModel(**curve)
        else:
            model = curve
        self._connect(model)
        if position < 0:
            # this appends to the list
            position = len(self._curves)
        self._curves.insert(position, model)
        return model
    
    def insert_curve(self, position, curve=None):
        if curve is None:
            curve = {}
        model = self._insert_curve(position, curve)
        
        undo = get_calling_command('remove_curve_by_id', model.id)
        self.add_history(undo)
        
        # get the actual position the model has now
        position = self._curves.index(model)
        self.trigger_on_model_updated('insertCurve', model, position)
    
    def append_curve(self, curve=None):
        """ this is a shortcut for self.insert_curve(-1, curve) """
        self.insert_curve(-1, curve)
    
    def remove_curve(self, model):
        position = self._curves.index(model)
        
        undo = get_calling_command('insert_curve', position, model)
        self.add_history(undo)
        
        self._curves.pop(position)
        self.trigger_on_model_updated('removeCurve', model)
    
    def remove_curve_by_id(self, modelId):
        model = self.get_by_id(modelId)
        self.remove_curve(model)


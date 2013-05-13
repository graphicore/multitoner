#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division
from weakref import ref as weakRef
import warnings
from math import pi
from gi.repository import Gtk, Gdk
import cairo
import numpy as np
from interpolation import *
from emitter import Emitter
from model import ModelCurves



# just a preparation for i18n
def _(string):
    return string

class CurveException(Exception):
    pass


class Scale(Emitter):
    def __init__(self, wh = (1, 1)):
        super(Scale, self).__init__()
        self._wh = None
        self(wh)
    
    def __call__(self,wh=None):
        if wh is not None and self._wh != wh:
            self._wh = wh
            self.triggerOnChange()
        return self._wh
    
    def triggerOnChange(self):
        for item in self:
            item.onScaleChange(self)
    
    def toScreen(self, point):
        return (point[0] * self._wh[0], point[1] * self._wh[1])
    
    def transformCairo(self, cr):
        cr.scale(self._wh[0], self._wh[1])
    
    def transformEvent(self, eventXY):
        return (eventXY[0], self._wh[1] - eventXY[1])
    
    def toUnit(self, xy):
        return (xy[0] / self._wh[0], xy[1] / self._wh[1])

def inCircle(center_x, center_y, radius, x, y):
    square_dist = (center_x - x) ** 2 + (center_y - y) ** 2
    # if <= is used instead of < the test would include the points *on* the circle
    return square_dist < radius ** 2

class ControlPoint(Emitter):
    displayRadius = 2
    controlRadius = 5
    color = (1,0,0)
    cursorType = Gdk.CursorType.FLEUR
    altCursorType = Gdk.CursorType.PIRATE
    # this is needed for the cairo context arc method, its enough to calculate this once
    endAngle = 2*pi
    def __init__(self, model, scale):
        super(ControlPoint, self).__init__()
        self._screenXY = None
        self.scale = scale
        scale.add(self)
        self.model = model
        model.add(self)
        self.active = False
    
    @property
    def xy(self):
        return self.model.xy
    
    def __lt__(self, other):
        return self.xy < other.xy
    
    def triggerOnPointDelete(self):
        for item in self:
            item.onPointDelete(self)
    
    def onModelUpdated(self, model):
        self.invalidate()
    
    def setCoordinates(self, xy):
        self.model.xy = xy
    
    def invalidate(self):
        self._screenXY = None
    
    def onScaleChange(self, scale):
        self.invalidate()
    
    def getScreenCoordinates(self):
        if self._screenXY is None:
            self._screenXY = self.scale.toScreen(self.xy)
        return self._screenXY
    
    def draw(self, cr):
        """ draw the control point to the cairo context """
        cr.set_source_rgb(*self.color)
        x, y = self.getScreenCoordinates()
        # radius is in pixels
        cr.arc(x, y, self.displayRadius, 0, self.endAngle)
        cr.fill()
    
    def isControl(self, x_in, y_in):
        x, y = self.getScreenCoordinates()
        # radius is in pixels
        return inCircle(x, y, self.controlRadius, x_in, y_in)
    
    def onButtonPress(self, button, x_in, y_in, alternate=False):
        if button == 1:
            # when active this receives onMotionNotify
            self.active = True
    
    def onButtonRelease(self, button, x_in, y_in, alternate=False):
        if button == 1 and self.active:
            self.active = False
            if alternate:
                self.triggerOnPointDelete()
    
    def onMotionNotify(self, x_in, y_in):
        self.setCoordinates(self.scale.toUnit((x_in, y_in)))

class Curve(Emitter):
    controlRadius = 5
    color = (0,0,0)
    lineWidth = 1
    cursorType = Gdk.CursorType.PLUS
    def __init__(self, model, scale):
        super(Curve, self).__init__()
        # active is used by CurveEditor
        self.active = False
        self.scale = scale
        scale.add(self)
        self.model = model
        model.add(self)
        self.invalidate()
        self._setPoints()
    
    def invalidate(self):
        # the actual points that will be drawn
        self._curvePoints = None
        self._interpolationStrategy = None
    
    def _setPoints(self):
        self._controls = []
        for cp_model in self.model.points:
            self._addControlPoint(cp_model)
    
    @property
    def getYs(self):
        """
            this return an InterpolationStrategy which itself is a callable
            that takes as argument either one x or ab array of xs and returns
            the according y value(s)
            
            use like:
                ys = curve.getYs(xs)
        """
        if self._interpolationStrategy is None:
            I = interpolationStrategiesDict[self.model.interpolation]
            self._interpolationStrategy = I(self.model.value)
        return self._interpolationStrategy
    
    def getCurvePoints(self):
        if self._curvePoints is None:
            width, height = self.scale()
            # this should look smooth enough
            amount = max(width, height)
            xs = np.linspace(0, 1, amount)
            ys = self.getYs(xs)
            
            # Returns an array or scalar replacing Not a Number (NaN) with zero,
            # (positive) infinity with a very large number and negative infinity
            # with a very small (or negative) number
            ys = np.nan_to_num(ys)
            
            # no y will be smaller than 0 or bigger than 1
            ys[ys < 0] = 0 # max(0, y)
            ys[ys > 1] = 1 # min(1, y)
            
            self._curvePoints = zip(xs, ys)
        return self._curvePoints

    def onScaleChange(self, scale):
        pass
    
    def _addControlPoint(self, cp_model):
        ctrl = ControlPoint(cp_model, self.scale)
        ctrl.add(self) # subscribe
        self._controls.append(ctrl)
    
    def _removeControlPoint(self, cp_model):
        for ctrl in self._controls:
            if ctrl.model is cp_model:
                self._controls.remove(ctrl)
    
    def onModelUpdated(self, model, event=None, *args):
        """
        there are several occasions for a model update:
            addPoint
            removePoint
            setPoints
            interpolation changed
            
            pointUpdate (this is triggered by a child model of this, this model is just a relay)
            
            all require that _curvePoints are reset
            but addPoint, removePoint, setPoints need actions regarding the controlPoints
        """
        self.invalidate()
        
        if event == 'addPoint':
            # add a new CP
            cp_model = args[0]
            self._addControlPoint(cp_model)
        elif event == 'removePoint':
            # remove the CP
            cp_model = args[0]
            self._removeControlPoint(cp_model)
        elif event == 'setPoints':
            # remove all CPs and build all CPs again
            self._setPoints()
    
    def onPointDelete(self, ctrl):
        self.model.removePoint(ctrl.model)
    
    def getIntersection(self, x_in):
        """ intersection y of x """
        unit_x, _ = self.scale.toUnit((x_in, 0))
        unit_x = max(0, min(1, unit_x))
        unit_y = max(0, min(1, self.getYs(unit_x)))
        return (unit_x, unit_y)
    
    def onButtonPress(self, button, x_in, y_in, alternate=False):
        if button == 1:
            intersection = self.getIntersection(x_in)
            x, y = self.scale.toScreen(intersection)
            if inCircle(x, y, self.controlRadius, x_in, y_in):
                self.model.addPoint(intersection)
    
    def onButtonRelease(self, button, x_in, y_in, alternate=False):
        pass
    
    def draw(self, cr):
        ctm = cr.get_matrix()
        self.scale.transformCairo(cr)
        cr.set_source_rgb(*self.color)
        
        # draw interpolated curve
        points = self.getCurvePoints()
        for point in points:
            cr.line_to(*point)
        
        # reset ctm to have proper controll over the line width
        # and also because everything else that is drawing expects it
        cr.set_matrix(ctm)
        cr.set_line_width(self.lineWidth)
        cr.stroke()
    
    def drawControls(self, cr):
        for ctrl in self._controls:
            ctrl.draw(cr)
    
    def isControl(self, x_in, y_in):
        intersection = self.getIntersection(x_in)
        x, y = self.scale.toScreen(intersection)
        return inCircle(x, y, self.controlRadius, x_in, y_in)
    
    def getControl(self, x, y, level=None):
        """
        When 'level' we can first ask for all ControlPoints and then
        for all curves. So all ControllPoints are 'over' all Curves
        """
        if level is None or level == 0:
            for ctrl in self._controls:
                if ctrl.isControl(x, y):
                    return ctrl
        if level is None or level == 1:
            if self.isControl(x, y):
                return self
        return None

class CurveEditor(Gtk.DrawingArea):
    background_color = (1,1,1)
    def __init__(self, model):
        self.cursorType = None
        self._ctrl = None
        self.scale = Scale()
        self.model = model
        model.add(self) # subscribe
        self._setCurves()
        super(CurveEditor, self).__init__()
    
    @classmethod
    def new(Cls, window, model):
        """
        a factory to create a CurveEditor widget and connect all necessary events
        """
        widget = Cls(model)
        
        widget.add_events( 0
            | Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.BUTTON1_MOTION_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
            | Gdk.EventMask.POINTER_MOTION_HINT_MASK
        )
        # To receive this signal, the GdkWindow associated to the widget
        # needs to enable the GDK_KEY_RELEASE_MASK mask
        # w.add_events( 0
        #     | Gdk.EventMask.KEY_PRESS_MASK
        #     | Gdk.EventMask.KEY_RELEASE_MASK
        # )
        
        widget.connect('draw'                , widget.onDraw)
        widget.connect('button-press-event'  , widget.onButtonPress)
        widget.connect('button-release-event', widget.onButtonRelease)
        widget.connect('motion-notify-event' , widget.onMotionNotify)
        widget.connect('configure-event'     , widget.onConfigure)
        window.connect('key-press-event'     , widget.onKeyPress)
        window.connect('key-release-event'   , widget.onKeyRelease)
        return widget
    
    def _appendCurve(self, curveModel):
        curve = Curve(curveModel, self.scale)
        self._curves.append(curve)
    
    def _removeCurve(self, curveModel):
        for curve in self._curves:
            if curve.model is curveModel:
                self._curves.remove(curve)
    
    def _setCurves(self):
        self._curves = []
        for curveModel in self.model.curves:
            self._appendCurve(curveModel)
    
    # the events are called like onEvent(self, drawingArea[, event, ...])
    # but since drawingArea == self in this case the original self is
    # discarded by using @staticmethod
    @staticmethod
    def onConfigure(self, event):
        # print 'on configure'
        # set the scale to show the data in visible sizes
        newscale = (event.width, event.height)
        # if scale changed it will trigger the onScaleCange callbacks
        # of its subscriptors
        self.scale(newscale)
    
    def getControl(self):
        ctrl = None
        if self._ctrl is not None:
            # self._ctrl is a weakRef
            ctrl = self._ctrl()
        if ctrl is None:
            self._ctrl = None
        return ctrl
    
    def findControl(self, x, y):
        ctrl = self.getControl()
        if ctrl is not None and ctrl.active:
            return ctrl
        width, height = self.scale()
        if x < 0 or x > width or y < 0 or y > height:
            # the mouse is not even in the widget
            pass
        else:
            for level in range(0, 2):
                for curve in self._curves:
                    ctrl = curve.getControl(x, y, level)
                    if ctrl is not None:
                        self._ctrl = weakRef(ctrl)
                        break
                if ctrl is not None:
                    break
        return ctrl
    
    def setCursor(self, ctrl=None, alternate=False):
        #default
        cursorType = Gdk.CursorType.ARROW
        if ctrl is not None:
            cursorType = ctrl.cursorType
            if alternate:
                cursorType = getattr(ctrl, 'altCursorType', cursorType)
            
        if self.cursorType == cursorType:
            return
        self.cursorType = cursorType
        cursor = Gdk.Cursor.new(self.cursorType)
        self.get_window().set_cursor(cursor)
    
    def getPointer(self):
        try:
            (window, x, y, state) = self.get_parent_window().get_pointer()
        except AttributeError:
            #when window is not initiated
            x, y, alternate, allocation = -1, -1, False, {x:0, y:0}
        else:
            alternate = self.stateIsAlternate(state)
            allocation = self.get_allocation()
        #the event needs a transformation
        return self.scale.transformEvent((x - allocation.x, y - allocation.y)), alternate
    
    def onModelUpdated(self, model, event=None, *args):
        if event == 'appendCurve':
            # add a curve
            curveModel = args[0]
            self._appendCurve(curveModel)
        elif event == 'removeCurve':
            # remove a curve
            curveModel = args[0]
            self._removeCurve(curveModel)
        elif event == 'setCurves':
            # remove all curves and build all curves again
            self._setCurves()
        
        self.queue_draw()
    
    @staticmethod
    def onDraw(self, cr):
        # y = 0 is the bottom of the widget
        width, height = self.scale()
        
        cr.set_source_rgb(*self.background_color)
        cr.rectangle(0, 0, width, height)
        cr.fill()
        
        cr.translate(0, height)
        cr.scale(1, -1)
        
        for curve in self._curves:
            curve.draw(cr)
        for curve in self._curves:
            curve.drawControls(cr) 
    
    @staticmethod
    def onButtonPress(self, event):
        #https://developer.gnome.org/gdk/stable/gdk-Event-Structures.html#GdkEventButton
        old_ctrl = None
        x, y = self.scale.transformEvent((event.x, event.y))
        alternate = self.stateIsAlternate(event.state)
        ctrl = self.getControl()
        while ctrl is not None:
            # Curve adds a ControlPoint and that changes control
            # this is that the new ControlPoint can start dragging immediately
            if old_ctrl == ctrl:
                # control did not change
                break;
            old_ctrl = ctrl
            ctrl.onButtonPress(event.button, x, y, alternate)
            ctrl = self.findControl(x, y)
        self.setCursor(ctrl, alternate=alternate)
    
    @staticmethod
    def onButtonRelease(self, event):
        #https://developer.gnome.org/gdk/stable/gdk-Event-Structures.html#GdkEventButton
        old_ctrl = None
        x, y = self.scale.transformEvent((event.x, event.y))
        alternate = self.stateIsAlternate(event.state)
        ctrl = self.getControl()
        while ctrl is not None:
            if old_ctrl == ctrl:
                # control did not change
                break;
            old_ctrl = ctrl
            ctrl.onButtonRelease(event.button, x, y, alternate)
            ctrl = self.findControl(x, y)
        self.setCursor(ctrl, alternate=alternate)
    
    @staticmethod
    def onMotionNotify(self, event):
        # https://developer.gnome.org/gdk/stable/gdk-Event-Structures.html#GdkEventMotion
        
        # this is good for the performance, otherwise we could get events
        # that are lagging behind the actual mouse movement
        # its required that Gdk.EventMask.POINTER_MOTION_HINT_MASK was specified
        (x, y), alternate = self.getPointer()
        # print 'onMotionNotify', x, y
        ctrl = self.findControl(x, y)
        if ctrl is not None and ctrl.active:
            ctrl.onMotionNotify(x, y)
        self.setCursor(ctrl, alternate=alternate)
    
    def keyIsAlternate(self, event):
        return Gdk.keyval_name(event.keyval)  == 'Control_L'
    
    def stateIsAlternate(self, state):
        return not not (state & Gdk.ModifierType.CONTROL_MASK)
    
    def onKeyPress(self, widget, event):
        # print 'onKeyPress', Gdk.keyval_name(event.keyval)
        if self.keyIsAlternate(event):
            ctrl = self.getControl()
            if ctrl is not None:
                self.setCursor(ctrl, alternate=True)
    
    def onKeyRelease(self, widget, event):
        # print 'onKeyPress', Gdk.keyval_name(event.keyval)
        if self.keyIsAlternate(event):
            ctrl = self.getControl()
            if ctrl is not None:
                self.setCursor(ctrl, alternate=False)

if __name__ == '__main__':
    w = Gtk.Window()
    w.set_default_size(640, 480)
    w.connect('destroy', Gtk.main_quit)
    
    m = ModelCurves()
    points = [(0.0,0.0), (0.1, 0.4), (0.2, 0.6), (0.5, 0.2), (0.4, 0.3), (1.0,1.0)]
    for interpolation, _ in interpolationStrategies:
        m.appendCurve(points, interpolation)
    
    a = CurveEditor.new(w, m)
    w.add(a)

    
    w.show_all()
    Gtk.main()

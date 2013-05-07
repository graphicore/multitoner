#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division
from gi.repository import Gtk, Gdk
import cairo

import numpy as np
# http://docs.scipy.org/doc/scipy/reference/tutorial/interpolate.html
from scipy import interpolate 
import math

from weakref import ref as weakRef, WeakSet

# just a preparation for i18n
def _(string):
    return string

class CurveException(Exception):
    pass

class Emitter(object):
    """
        simple event subscription
        important:
            1. this is uses a set, so there is no guaranteed order
            2. the subscriber needs to implement all callbacks of the actual Emitter
        
        to subscribe use emitterObj.add
        to unsubscribe use emitterObj.remove or emitterObj.discard or
           delete all references to the subscriber
    """
    def __init__(self):
        self._subscriptions = WeakSet()
    
    def __iter__(self):
        for item in self._subscriptions:
            yield item
    
    def add(self, thing):
        self._subscriptions.add(thing)
    
    def discard(self, thing):
        self._subscriptions.discard(thing)
    
    def remove(self, thing):
        self._subscriptions.remove(thing)

class Interpolation(object):
    
    @property
    def name(self):
        raise NotImplementedError('Name must be defined by subclass')
    
    @property
    def description(self):
        raise NotImplementedError('Description must be defined by subclass')
    
    def _function(*args):
        raise NotImplementedError('_function must be defined by subclass')
    
    
    def __init__(self, points):
        self.setPoints(points)
    def setPoints(self, points):
        if len(points) < 2:
            raise CurveException('Need at least two points');
        pts = zip(*points)
        self._x = np.array(pts[0], dtype=float)
        self._y = np.array(pts[1], dtype=float)
    
    def getYs(self, xs):
        """
        takes an np array of x values and returns an np array of the same
        length as the input array representing the corresponding y values
        """
        return self._function(xs)

class InterpolatedSpline(Interpolation):
    """
    Produces a smooth spline between the input points
    """
    name = _('Spline')
    description = _('Very smooth but very self-willed, too.')
    def setPoints(self, points):
        super(InterpolatedSpline, self).setPoints(points)
        # The number of data points must be larger than the spline degree k
        k = 5#3
        M = len(self._x)
        if k >= M:
            k = M-1
        self._function = interpolate.UnivariateSpline(self._x,self._y,s=0,k=k)

class InterpolatedMonotoneCubic(Interpolation):
    """
    Produces a smoothend curve between the input points using a monotonic
    cubic interpolation PCHIP: Piecewise Cubic Hermite Interpolating Polynomia
    """
    name = _('Monotone Cubic')
    description = _('Smooth and does what you say. Not as smooth as Spline.')
    def setPoints(self, points):
        super(InterpolatedMonotoneCubic, self).setPoints(points)
        self._function = interpolate.pchip(self._x, self._y)

class InterpolatedLinear(Interpolation):
    """
    Produces a lineaer interpolation between the input points
    """
    name = _('Linear')
    description = _('Just straight lines between control points.')
    def _function(self, xs):
        return np.interp(xs, self._x, self._y)
    
    def getYs(self, xs):
        return self._function(xs)

interpolationStrategies = (
    ('monotoneCubic', InterpolatedMonotoneCubic),
    ('spline'       , InterpolatedSpline),
    ('linear'       , InterpolatedLinear)
)


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
    endAngle = 2*math.pi
    def __init__(self, xy, scale, fixedX = None):
        super(ControlPoint, self).__init__()
        self.fixedX = fixedX
        self.scale = scale
        scale.add(self)
        self.setCoordinates(xy)
        self.active = False
    
    def subscribe(self, item):
        self._subscriptions.add(item)
    
    def triggerOnPointMove(self):
        for item in self:
            item.onPointMove(self)
    
    def triggerOnPointDelete(self):
        for item in self:
            item.onPointDelete(self)
    def setCoordinates(self, xy):
        if self.fixedX is not None:
            xy = (self.fixedX, xy[1])
        self.xy = (
            max(0, min(1, xy[0])),
            max(0, min(1, xy[1]))
        )
        self.invalidate()
    
    def invalidate(self):
        self._screenXY = None
    
    def onScaleChange(self, scale):
        self.invalidate()
    
    def getScreenCoordinates(self):
        if self._screenXY is None:
            self._screenXY = self.scale.toScreen(self.xy)
        return self._screenXY
    
    def __lt__(self, other):
        return self.xy < other.xy
    
    def draw(self, cr):
        """ draw the control point to the cairo context """
        cr.set_source_rgb(*self.color)
        x, y = self.getScreenCoordinates()
        #radius is in pixels
        cr.arc(x, y, self.displayRadius, 0, self.endAngle)
        cr.fill()
    
    def isControl(self, x_in, y_in):
        x, y = self.getScreenCoordinates()
        #radius is in pixels
        return inCircle(x, y, self.controlRadius, x_in, y_in)
    
    def onButtonPress(self, button, x_in, y_in, alternate=False):
        if button == 1:
            # when active this receives onMotionNotify
            self.active = True
    
    def onButtonRelease(self, button, x_in, y_in, alternate=False):
        if button == 1:
            self.active = False
        if button == 1 and alternate:
            self.triggerOnPointDelete()
            return True
    
    def onMotionNotify(self, x_in, y_in):
        # just a test
        self.setCoordinates(self.scale.toUnit((x_in, y_in)))
        self.triggerOnPointMove()
        return True

class Curve(Emitter):
    controlRadius = 5
    color = (0,0,0)
    lineWidth = 1
    cursorType = Gdk.CursorType.PLUS
    def __init__(self, scale, points=[(0,0), (1,1)], Interpolation=InterpolatedMonotoneCubic):
        super(Curve, self).__init__()
        self.active = False
        self.scale = scale
        scale.add(self)
        self._Interpolation = Interpolation
        self.setPoints(points)
    
    def invalidate(self):
        self._curve = None
        self._curvePoints = None
    
    def _addPoint(self, point):
        ctrl = ControlPoint(point, self.scale)
        ctrl.add(self) # subscribe
        self._controls.append(ctrl)
    
    def setPoints(self, points):
        self._controls = []
        for point in points:
            self._addPoint(point)
        self.invalidate()
    
    def setInterpolation(self, Interpolation):
        self._Interpolation = Interpolation
        self.invalidate()
        self.triggerOnControlChanged()
    
    def triggerOnControlChanged(self):
        for item in self:
            item.onControlChanged(self)
    
    def addPoint(self, point):
        self._addPoint(point)
        self.invalidate()
        self.triggerOnControlChanged()
    
    def onPointDelete(self, ctrl):
        if len(self._controls) == 2:
            return
        self._controls.remove(ctrl)
        self.invalidate()
        self.triggerOnControlChanged()
    
    def getCurve(self):
        if self._curve is None:
            self._curve = self._Interpolation(sorted([ctrl.xy for ctrl in self._controls]))
        return self._curve
    
    def getCurvePoints(self):
        if self._curvePoints is None:
            width, height = self.scale()
            # this should look smooth enough
            amount = max(width, height)
            xs = np.linspace(0, 1, amount)
            ys = self.getCurve().getYs(xs)
            
            # Returns an array or scalar replacing Not a Number (NaN) with zero,
            # (positive) infinity with a very large number and negative infinity
            # with a very small (or negative) number
            ys = np.nan_to_num(ys)
            
            # no y will be smaller than 0 or bigger than 1
            ys[ys < 0] = 0 # max(0, y)
            ys[ys > 1] = 1 # min(1, y)
            
            self._curvePoints = zip(xs,ys)
        return self._curvePoints
    
    def onPointMove(self, ctrl):
        self.invalidate()
    
    def onButtonPress(self, button, x_in, y_in, alternate=False):
        if button == 1:
            point = self.getIntersection(x_in)
            x, y = self.scale.toScreen(point)
            if inCircle(x, y, self.controlRadius, x_in, y_in):
                self.addPoint(point)
                return True
    
    def onButtonRelease(self, button, x_in, y_in, alternate=False):
        pass
    
    def onScaleChange(self, scale):
        self._curvePoints = None
    
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
    
    def getIntersection(self, x_in):
        """ intersection y of x """
        unit_x, _ = self.scale.toUnit((x_in, 0))
        unit_x = max(0, min(1, unit_x))
        unit_y = max(0, min(1, self.getCurve().getYs(unit_x)))
        return (unit_x, unit_y)
    
    def isControl(self, x_in, y_in):
        point = self.getIntersection(x_in)
        x, y = self.scale.toScreen(point)
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
    def __init__(self):
        self.curves = []
        self.cursorType = None
        self._ctrl = None
        self.scale = Scale()
        super(CurveEditor, self).__init__()
    @classmethod
    def new(Cls, window):
        """
        a factory to create a CurveEditor widget and connect all necessary events
        """
        widget = Cls()
        
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
    
    def appendCurve(self, curve):
        self.curves.append(curve)
        curve.add(self)
    
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
            for level in range(0,2):
                for curve in self.curves:
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
        (window, x, y, state) = self.get_parent_window().get_pointer()
        alternate = self.stateIsAlternate(state)
        allocation = self.get_allocation()
        #the event needs a transformation
        return self.scale.transformEvent((x - allocation.x, y - allocation.y)), alternate
    
    def onControlChanged(self, source):
        (x, y), alternate = self.getPointer()
        ctrl = self.findControl(x, y)
        self.setCursor(ctrl, alternate=alternate)
    
    @staticmethod
    def onDraw(self, cr):
        # y = 0 is the bottom of the widget
        width, height = self.scale()
        
    #    cr.set_source_rgb(*self.background_color)
    #    cr.rectangle(0, 0, width, height)
    #    cr.fill()
        
        
        cr.translate(0, height)
        cr.scale(1, -1)
        
        for curve in self.curves:
            curve.draw(cr)
        for curve in self.curves:
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
            if ctrl.onButtonPress(event.button, x, y, alternate):
                self.queue_draw()
            ctrl = self.getControl()
    
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
            if ctrl.onButtonRelease(event.button, x, y, alternate):
                self.queue_draw()
            ctrl = self.getControl()
    
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
            if ctrl.onMotionNotify(x, y):
                self.queue_draw()
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
    
    a = CurveEditor.new(w)
    w.add(a)
    
    for label, item in interpolationStrategies:
        a.appendCurve(Curve(a.scale, [(0,0), (0.1, 0.4), (0.2, 0.6), (0.5, 0.2), (0.4, 0.3), (1,1)], Interpolation = item))
    
    
    
    w.show_all()
    Gtk.main()

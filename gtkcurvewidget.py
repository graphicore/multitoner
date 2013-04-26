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
    
class InterpolatedCurve(object):
    """
    This will take n points () where n>1 and provide an interpolated spline
    for the curve
    """
    def __init__(self, points):
        self.setPoints(points)
    
    def setPoints(self, points):
        if len(points) < 2:
            raise CurveException('Need at least two points');
        pts = zip(*points)
        self._x = np.array(pts[0])
        self._y = np.array(pts[1])
        self._tck = None
    
    def _getTCK(self):
        # from help(interpolate.splrep):
        # k:The order of the spline fit. It is recommended to use cubic splines.
        # Even order splines should be avoided especially with small s values.
        # note: splrep won't accept M <= k so this will make it work
        # since the advice is against even k and we will produce this here 
        # with a 3 point spline, we'll have to see if this will ever be a problem
        k = 3
        M = len(self._x)
        if k >= M:
            k = M-1
        
        # The normal output is a 3-tuple, (t,c,k)
        # containing: knot-points t, coefficients c, order k of the spline
        self._tck = interpolate.splrep(self._x,self._y,s=0,k=k)
        
        return self._tck;
    
    def getTCK(self):
        if self._tck is None:
            return self._getTCK()
        return self._tck
    
    def getYs(self, xs):
        tck = self.getTCK()
        return interpolate.splev(xs,tck, der=0)

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
            item.onScaleChange()
    
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
    displayRadius = 3
    controlRadius = 6
    color = (1,0,0)
    cursorType = Gdk.CursorType.FLEUR
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
    
    def onScaleChange(self):
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
    
    def onButtonPress(self, button, x_in, y_in):
        print self, 'onButtonPress', button
        if button == 1:
            # when active this receives onMotionNotify
            self.active = True
    
    def onButtonRelease(self, button, x_in, y_in):
        print self, 'onButtonRelease', button
        if button == 1:
            self.active = False
        if self.active and button == 3:
            self.triggerOnPointDelete()
            return True
    
    def onMotionNotify(self, x_in, y_in):
        # just a test
        print self, 'onMotionNotify', self.active, self.scale.toUnit((x_in, y_in))
        self.setCoordinates(self.scale.toUnit((x_in, y_in)))
        self.triggerOnPointMove()
        return True

class Curve(Emitter):
    controlRadius = 5
    cursorType = Gdk.CursorType.PLUS
    def __init__(self, scale, points=[(0,0), (1,1)]):
        super(Curve, self).__init__()
        self.active = False
        self.scale = scale
        scale.add(self)
        self.setPoints(points)
    
    def invalidate(self):
        self._curve = None
        self._curvePoints = None
        self._controls = None
    
    def setPoints(self, points):
        self._points = points
        self.invalidate()
    
    def addPoint(self, point):
        self._points.append(point)
        self.invalidate()
        self.triggerOnPointAdd()
    
    def triggerOnPointAdd(self):
        for item in self:
            item.onPointAdd(self)
    
    def getCurve(self):
        if self._curve is None:
            self._curve = InterpolatedCurve(sorted(self._points))
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
    
    def getControls(self):
        if self._controls is None:
            self._controls = []
            for point in self._points:
                ctrl = ControlPoint(point, self.scale)
                ctrl.add(self)
                self._controls.append(ctrl)
        return self._controls
    
    def onPointMove(self, ctrl):
        self._curve = None
        self._curvePoints = None
        idx = self._controls.index(ctrl)
        self._points[idx] = ctrl.xy
    
    def onPointDelete(self, ctrl):
        if len(self._points) == 2:
            return
        idx = self._controls.index(ctrl)
        self._controls.remove(ctrl)
        self._points = self._points[0:idx] + self._points[idx+1:]
        self._curve = None
        self._curvePoints = None
    
    def onButtonPress(self, button, x_in, y_in):
        if button == 1:
            point = self.getIntersection(x_in)
            x, y = self.scale.toScreen(point)
            if inCircle(x, y, self.controlRadius, x_in, y_in):
                self.addPoint(point)
                return True
    
    def onButtonRelease(self, button, x_in, y_in):
        pass
    
    def onScaleChange(self):
        self._curvePoints = None
    
    def draw(self, cr):
        ctm = cr.get_matrix()
        self.scale.transformCairo(cr)
        cr.set_source_rgb(0, 0, 0)
        
        # draw interpolated curve
        points = self.getCurvePoints()
        for point in points:
            cr.line_to(*point)
        
        # reset ctm to have proper controll over the line width
        # and also because everything else that is drawing expects it
        cr.set_matrix(ctm)
        cr.set_line_width(1)
        cr.stroke()
    
    def drawControls(self, cr):
        controls = self.getControls()
        for ctrl in controls:
            ctrl.draw(cr)
    
    def getIntersection(self, x_in):
        """ intersection point y of x """
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
        print 'level', level
        if level is None or level == 0:
            controls = self.getControls()
            for ctrl in controls:
                if ctrl.isControl(x, y):
                    return ctrl
        if level is None or level == 1:
            if self.isControl(x, y):
                return self
        return None

class CurveEditor(Gtk.DrawingArea):
    def __init__(self):
        self.curves = []
        self.cursorType = None
        self._ctrl = None
        self.scale = Scale()
        super(CurveEditor, self).__init__()
    
    def appendCurve(self, curve):
        self.curves.append(curve)
        curve.add(self)
    
    # the events are called like onEvent(self, drawingArea[, event, ...])
    # but since drawingArea == self in this case the original self is
    # discarded by using @staticmethod
    @staticmethod
    def onConfigure(self, event):
        print 'on configure'
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
    
    def setCursor(self, ctrl=None):
        if ctrl is not None and self.cursorType != ctrl.cursorType:
            self.cursorType = ctrl.cursorType
        elif ctrl is None and self.cursorType != Gdk.CursorType.ARROW:
            self.cursorType = Gdk.CursorType.ARROW
        else:
            return
        cursor = Gdk.Cursor.new(self.cursorType)
        self.get_window().set_cursor(cursor)
    
    def getPointer(self):
        (window, x, y, state) = self.get_parent_window().get_pointer()
        #the event needs a transformation
        return self.scale.transformEvent((x, y))
    
    def onPointAdd(self, source):
        x, y = self.getPointer()
        ctrl = self.findControl(x, y)
        self.setCursor(ctrl)
    
    @staticmethod
    def onDraw(self, cr):
        print('onDraw')
        # y = 0 is the bottom of the widget
        width, height = self.scale()
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
        ctrl = self.getControl()
        while ctrl is not None:
            # Curve adds a ControlPoint and that changes control
            # this is that the new ControlPoint can start dragging immediately
            if old_ctrl == ctrl:
                # control did not change
                break;
            old_ctrl = ctrl
            if ctrl.onButtonPress(event.button, x, y):
                self.queue_draw()
            ctrl = self.getControl()
    
    @staticmethod
    def onButtonRelease(self, event):
        #https://developer.gnome.org/gdk/stable/gdk-Event-Structures.html#GdkEventButton
        old_ctrl = None
        x, y = self.scale.transformEvent((event.x, event.y))
        ctrl = self.getControl()
        while ctrl is not None:
            if old_ctrl == ctrl:
                # control did not change
                break;
            old_ctrl = ctrl
            if ctrl.onButtonRelease(event.button, x, y):
                self.queue_draw()
            ctrl = self.getControl()
    @staticmethod
    def onMotionNotify(self, event):
        # https://developer.gnome.org/gdk/stable/gdk-Event-Structures.html#GdkEventMotion
        
        # this is good for the performance, otherwise we could get events
        # that are lagging behind the actual mouse movement
        # its required that Gdk.EventMask.POINTER_MOTION_HINT_MASK was specified
        x,y = self.getPointer()
        print 'onMotionNotify', x, y
        ctrl = self.findControl(x, y)
        if ctrl is not None and ctrl.active:
            if ctrl.onMotionNotify(x, y):
                self.queue_draw()
        self.setCursor(ctrl)

w = Gtk.Window()
w.set_default_size(640, 480)
a = CurveEditor()
w.add(a)
w.connect('destroy', Gtk.main_quit)
a.add_events( 0
    | Gdk.EventMask.BUTTON_PRESS_MASK
    | Gdk.EventMask.BUTTON_RELEASE_MASK
    | Gdk.EventMask.BUTTON1_MOTION_MASK
    | Gdk.EventMask.POINTER_MOTION_MASK
    | Gdk.EventMask.POINTER_MOTION_HINT_MASK
)

a.connect('draw', a.onDraw)    
a.connect('button-press-event', a.onButtonPress)
a.connect('button-release-event', a.onButtonRelease)
a.connect('motion-notify-event', a.onMotionNotify)
a.connect('configure-event', a.onConfigure)


a.appendCurve(Curve(a.scale, [(0,0), (0.1, 0.4), (0.2, 0.6), (0.5, 0.2), (0.4, 0.3), (1,1)]))
a.appendCurve(Curve(a.scale, [(0,0), (0.1, 0.4), (0.2, 0.6)]))


w.show_all()

if __name__ == '__main__':
	Gtk.main()

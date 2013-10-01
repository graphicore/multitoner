#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division, print_function, unicode_literals

from weakref import ref as weakref
from math import pi

from gi.repository import Gtk, Gdk
import numpy as np

from interpolation import interpolation_strategies_dict
from emitter import Emitter

__all__ = ['CurveEditor']

# just a preparation for i18n
def _(string):
    return string

class Scale(Emitter):
    """ Scale internal values (between 0 and 1) to screen dimensions and back.
    
    Subscribers must implement on_scale_change which is called with a
    single argument, the instance of scale
    
    """
    def __init__(self, wh = (1, 1)):
        super(Scale, self).__init__()
        self._wh = None
        self(wh)
    
    def __call__(self,wh=None):
        """ Set wh (screen width, screen height) as the screen dimansions
        
        This will inform all subscribers if wh really changes the value.
        """
        if wh is not None and self._wh != wh:
            self._wh = wh
            self.trigger_on_change()
        return self._wh
    
    def trigger_on_change(self):
        """ Inform all subscribers when the screen dimensions changed. """
        for item in self._subscriptions:
            item.on_scale_change(self)
    
    def to_screen(self, point):
        """ Transform point coordinates betewwen 0 and 1 to screen coordinates """
        return (point[0] * self._wh[0], point[1] * self._wh[1])
    
    def transform_cairo(self, cr):
        """ Scale the cairo context cr to screen width and height.
        
        The cairo context will fit to this scale if its contents use 
        coordinates between 0 and 1.
        
        """
        cr.scale(self._wh[0], self._wh[1])
    
    def transform_event(self, event_xy):
        """ Inverted the y value of event_xy """
        return (event_xy[0], self._wh[1] - event_xy[1])
    
    def to_unit(self, xy):
        return (xy[0] / self._wh[0], xy[1] / self._wh[1])


def in_circle(center_x, center_y, radius, x, y):
    """ Test if (x, y) is in the circle described by (center_x, center_y, radius) """
    square_dist = (center_x - x) ** 2 + (center_y - y) ** 2
    # if <= is used instead of < the test would include the points *on* the circle
    return square_dist < radius ** 2


class ControlPoint(Emitter):
    """ A ControlPoint of a Curve in CurveEditor. Will Modify its
    according ModelControlPoint.
    
    Subscribers must implement on_point_delete which is called with a
    single argument, the instance of ControlPoint
    
    """
    display_radius = 2
    control_radius = 5
    color = (1, 0, 0)
    cursor_type = Gdk.CursorType.FLEUR
    alt_cursor_type = Gdk.CursorType.PIRATE
    # this is needed for the cairo context arc method, its enough to calculate this once
    end_angle = 2*pi
    def __init__(self, model, scale):
        super(ControlPoint, self).__init__()
        self._screen_xy = None
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
    
    def trigger_on_point_delete(self):
        for item in self._subscriptions:
            item.on_point_delete(self)
    
    def on_model_updated(self, model):
        self._invalidate()
    
    def _set_coordinates(self, xy):
        self.model.xy = xy
    
    def _invalidate(self):
        self._screen_xy = None
    
    def on_scale_change(self, scale):
        self._invalidate()
    
    def _get_screen_coordinates(self):
        if self._screen_xy is None:
            self._screen_xy = self.scale.to_screen(self.xy)
        return self._screen_xy
    
    def draw(self, cr):
        """ draw the control point to the cairo context """
        cr.set_source_rgb(*self.color)
        x, y = self._get_screen_coordinates()
        # radius is in pixels
        cr.arc(x, y, self.display_radius, 0, self.end_angle)
        cr.fill()
    
    def is_control(self, x_in, y_in):
        x, y = self._get_screen_coordinates()
        # radius is in pixels
        return in_circle(x, y, self.control_radius, x_in, y_in)
    
    def on_button_press(self, button, x_in, y_in, alternate=False):
        if button == 1:
            # when active this receives on_motion_notify
            self.model.register_consecutive_command()
            self.active = True
    
    def on_button_release(self, button, x_in, y_in, alternate=False):
        if button == 1 and self.active:
            self.active = False
            if alternate:
                self.trigger_on_point_delete()
    
    def on_motion_notify(self, x_in, y_in):
        self._set_coordinates(self.scale.to_unit((x_in, y_in)))


class Curve(object):
    """ A Curve in CurveEditor. Will Modify its according ModelCurve """
    control_radius = 5
    line_width = 1
    cursor_type = Gdk.CursorType.PLUS
    def __init__(self, model, scale):
        super(Curve, self).__init__()
        # active is used by CurveEditor
        self.active = False
        self.scale = scale
        scale.add(self)
        self.model = model
        model.add(self)
        self._invalidate()
        self._set_points()
    
    def _invalidate(self):
        # the actual points that will be drawn
        self._curve_points = None
        self._interpolation_strategy = None
    
    def _set_points(self):
        """ Remove all control points and build them again from self.model """
        self._controls = []
        for cp_model in self.model.points:
            self._add_control_point(cp_model)
    
    @property
    def get_ys(self):
        """ Returns an instance of InterpolationStrategy which itself
        is a callable. InterpolationStrategy takes as argument either
        one x or an array of xs and returns the according y value(s).
            
        Use it like: ys = curve.get_ys(xs)
        """
        if self._interpolation_strategy is None:
            IS = interpolation_strategies_dict[self.model.interpolation]
            self._interpolation_strategy = IS(self.model.points_value)
        return self._interpolation_strategy
    
    def _get_curve_points(self):
        if self._curve_points is None:
            width, height = self.scale()
            # this should look smooth enough
            amount = max(width, height)
            xs = np.linspace(0, 1, amount)
            ys = self.get_ys(xs)
            
            # Returns an array or scalar replacing Not a Number (NaN) with zero,
            # (positive) infinity with a very large number and negative infinity
            # with a very small (or negative) number
            ys = np.nan_to_num(ys)
            
            # no y will be smaller than 0 or bigger than 1
            ys[ys < 0] = 0 # max(0, y)
            ys[ys > 1] = 1 # min(1, y)
            
            self._curve_points = zip(xs, ys)
        return self._curve_points

    def on_scale_change(self, scale):
        pass
    
    def _add_control_point(self, cp_model):
        ctrl = ControlPoint(cp_model, self.scale)
        ctrl.add(self) # subscribe
        self._controls.append(ctrl)
    
    def _remove_control_point(self, cp_model):
        for ctrl in self._controls:
            if ctrl.model is cp_model:
                self._controls.remove(ctrl)
    
    def on_model_updated(self, model, event=None, *args):
        """
        There are several occasions for a model update:
            addPoint
            removePoint
            setPoints
            interpolation changed
            displayColorChanged
            pointUpdate (this is triggered by a child model of this, this
                         model is just a relay)
            
            All but displayColorChanged require that _curve_points are reset
            but addPoint, removePoint, setPoints need actions regarding
            the controlPoints.
        """
        if event != 'displayColorChanged':
            self._invalidate()
        
        if event == 'addPoint':
            # add a new CP
            cp_model = args[0]
            self._add_control_point(cp_model)
        elif event == 'removePoint':
            # remove the CP
            cp_model = args[0]
            self._remove_control_point(cp_model)
        elif event == 'setPoints':
            # remove all CPs and build all CPs again
            self._set_points()
    
    def on_point_delete(self, ctrl):
        self.model.remove_point(ctrl.model)
    
    def _get_intersection(self, x_in):
        """ Return a tuple (x, y) where y intersects x
        
        x_in is in screen units. The return values are beteen 0 and 1.
        """
        unit_x, _ = self.scale.to_unit((x_in, 0))
        unit_x = max(0, min(1, unit_x))
        unit_y = max(0, min(1, self.get_ys(unit_x)))
        return (unit_x, unit_y)
    
    def on_button_press(self, button, x_in, y_in, alternate=False):
        if button == 1:
            intersection = self._get_intersection(x_in)
            x, y = self.scale.to_screen(intersection)
            if in_circle(x, y, self.control_radius, x_in, y_in):
                self.model.add_point(intersection)
    
    def on_button_release(self, button, x_in, y_in, alternate=False):
        pass
    
    def draw(self, cr):
        if not self.model.visible:
            return
        
        ctm = cr.get_matrix()
        self.scale.transform_cairo(cr)
        cr.set_source_rgb(*self.model.display_color)
        
        # draw interpolated curve
        points = self._get_curve_points()
        for point in points:
            cr.line_to(*point)
        
        # reset ctm to have proper controll over the line width
        # and also because everything else that is drawing expects it
        cr.set_matrix(ctm)
        cr.set_line_width(self.line_width)
        cr.stroke()
    
    def draw_controls(self, cr):
        if self.model.locked or not self.model.visible:
            return
        for ctrl in self._controls:
            ctrl.draw(cr)
    
    def is_control(self, x_in, y_in):
        if self.model.locked:
            return False
        intersection = self._get_intersection(x_in)
        x, y = self.scale.to_screen(intersection)
        return in_circle(x, y, self.control_radius, x_in, y_in)
    
    def get_control(self, x, y, level=None):
        """ Return the active control at x, y
        
        When 'level' is used we can first ask for all ControlPoints (level = 0)
        and then for all curves (level = 2). So all ControllPoints are 'over'
        all Curves
        """
        if self.model.locked:
            return None
        
        if level is None or level == 0:
            for ctrl in self._controls:
                if ctrl.is_control(x, y):
                    return ctrl
        if level is None or level == 1:
            if self.is_control(x, y):
                return self
        return None


class CurveEditor(Gtk.DrawingArea):
    """ Widget to display and manipulate Curves controlled by ControlPoints. """
    background_color = (1,1,1)
    _tooltip = _('<b>Click</b> on a curve to add a control point. <b>Drag'
                 '</b> a control point to alter its position. <b>Press Ctrl'
                 ' and Click</b> on a control point to delete it.')
    def __init__(self, model):
        Gtk.DrawingArea.__init__(self)
        
        self.cursor_type = None
        self._ctrl = None
        self.scale = Scale()
        self.model = model
        model.add(self) # subscribe
        self._set_curves()
        
        
        self.set_tooltip_markup(self._tooltip)

        #connect all necessary events
        
        self.add_events(
              Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.BUTTON1_MOTION_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
            | Gdk.EventMask.POINTER_MOTION_HINT_MASK
            | Gdk.EventMask.STRUCTURE_MASK
            
        #    | Gdk.EventMask.KEY_PRESS_MASK
        #    | Gdk.EventMask.KEY_RELEASE_MASK
        )
        
        self.connect('draw'                , self.draw_handler)
        self.connect('button-press-event'  , self.button_press_handler)
        self.connect('button-release-event', self.button_release_handler)
        self.connect('motion-notify-event' , self.motion_notify_handler)
        self.connect('configure-event'     , self.configure_handler)
        
        # the self needs to self.grab_focus to receive these events
        # self.connect('key-press-event'     , self.key_press_handler)
        # self.connect('key-release-event'   , self.key_release_handler)
    
    def _insert_curve(self, position, curve_model):
        if position < 0:
            position = len(self._curves)
        curve = Curve(curve_model, self.scale)
        self._curves.insert(position, curve)
    
    def _append_curve(self, curve_model):
        self._insert_curve(-1, curve_model)
    
    def _remove_curve(self, curve_model):
        for curve in self._curves:
            if curve.model is curve_model:
                self._curves.remove(curve)
    
    def _set_curves(self):
        self._curves = []
        for curve_model in self.model.curves:
            self._append_curve(curve_model)
    
    def configure_handler(self, widget, event):
        # set the scale to show the data in visible sizes
        newscale = (event.width, event.height)
        # if scale changed it will trigger the onScaleCange callbacks
        # of its subscriptors
        self.scale(newscale)
    
    def get_control(self):
        ctrl = None
        if self._ctrl is not None:
            # self._ctrl is a weakref
            ctrl = self._ctrl()
        if ctrl is None:
            self._ctrl = None
        return ctrl
    
    def _find_control(self, x, y):
        ctrl = self.get_control()
        if ctrl is not None and ctrl.active:
            return ctrl
        width, height = self.scale()
        if x < 0 or x > width or y < 0 or y > height:
            # the mouse is not even in the widget
            pass
        else:
            for level in range(0, 2):
                for curve in self._curves:
                    ctrl = curve.get_control(x, y, level)
                    if ctrl is not None:
                        self._ctrl = weakref(ctrl)
                        break
                if ctrl is not None:
                    break
        return ctrl
    
    def _set_cursor(self, ctrl=None, alternate=False):
        #default
        cursor_type = Gdk.CursorType.ARROW
        if ctrl is not None:
            cursor_type = ctrl.cursor_type
            if alternate:
                cursor_type = getattr(ctrl, 'alt_cursor_type', cursor_type)
            
        if self.cursor_type == cursor_type:
            return
        self.cursor_type = cursor_type
        cursor = Gdk.Cursor.new(self.cursor_type)
        self.get_window().set_cursor(cursor)
    
    def _state_is_alternate(self, state):
        return not not (state & Gdk.ModifierType.CONTROL_MASK)
    
    def _get_pointer(self):
        try:
            (window, x, y, state) = self.get_parent_window().get_pointer()
        except AttributeError:
            # when window is not initiated
            x, y, alternate, allocation = -1, -1, False, {x:0, y:0}
        else:
            alternate = self._state_is_alternate(state)
            allocation = self.get_allocation()
        #the event needs a transformation
        return (self.scale.transform_event((x - allocation.x, y - allocation.y)),
                alternate)
    
    def on_model_updated(self, model, event=None, *args):
        # especially cmykChanged can happen very often and needs no
        # draw of this widget
        if event == 'curveUpdate' and (args[1] == 'cmykChanged' \
                or args[1] == 'nameChanged'):
            return
        
        if event == 'insertCurve':
            # add a curve
            curve_model = args[0]
            position = args[1] 
            self._insert_curve(position, curve_model)
        elif event == 'removeCurve':
            # remove a curve
            curve_model = args[0]
            self._remove_curve(curve_model)
        elif event == 'setCurves':
            # remove all curves and build all curves again
            self._set_curves()
        elif event == 'reorderedCurves':
            self._set_curves()
        
        self.queue_draw()
    
    def draw_handler(self, widget, cr):
        # y = 0 is the bottom of the widget
        width, height = self.scale()
        
        cr.set_source_rgb(*self.background_color)
        cr.rectangle(0, 0, width, height)
        cr.fill()
        
        cr.translate(0, height)
        cr.scale(1, -1)
        
        for curve in reversed(self._curves):
            curve.draw(cr)
        for curve in self._curves:
            curve.draw_controls(cr) 
    
    def button_press_handler(self, widget, event):
        #https://developer.gnome.org/gdk/stable/gdk-Event-Structures.html#GdkEventButton
        old_ctrl = None
        x, y = self.scale.transform_event((event.x, event.y))
        alternate = self._state_is_alternate(event.state)
        ctrl = self.get_control()
        while ctrl is not None:
            # Curve adds a ControlPoint and that changes control
            # this is that the new ControlPoint can start dragging immediately
            if old_ctrl == ctrl:
                # control did not change
                break
            old_ctrl = ctrl
            ctrl.on_button_press(event.button, x, y, alternate)
            ctrl = self._find_control(x, y)
        self._set_cursor(ctrl, alternate=alternate)
    
    def button_release_handler(self, widget, event):
        #https://developer.gnome.org/gdk/stable/gdk-Event-Structures.html#GdkEventButton
        old_ctrl = None
        x, y = self.scale.transform_event((event.x, event.y))
        alternate = self._state_is_alternate(event.state)
        ctrl = self.get_control()
        while ctrl is not None:
            if old_ctrl == ctrl:
                # control did not change
                break
            old_ctrl = ctrl
            ctrl.on_button_release(event.button, x, y, alternate)
            ctrl = self._find_control(x, y)
        self._set_cursor(ctrl, alternate=alternate)
    
    def motion_notify_handler(self, widget, event):
        # https://developer.gnome.org/gdk/stable/gdk-Event-Structures.html#GdkEventMotion
        
        # this is good for the performance, otherwise we could get events
        # that are lagging behind the actual mouse movement
        # its required that Gdk.EventMask.POINTER_MOTION_HINT_MASK was specified
        (x, y), alternate = self._get_pointer()
        # print('on_motion_notify', x, y)
        ctrl = self._find_control(x, y)
        if ctrl is not None and ctrl.active:
            ctrl.on_motion_notify(x, y)
        self._set_cursor(ctrl, alternate=alternate)
    
    def _key_is_alternate(self, event):
        return Gdk.keyval_name(event.keyval)  == 'Control_L'
    
    def key_press_handler(self, widget, event):
        # print('key_press_handler', Gdk.keyval_name(event.keyval))
        if self._key_is_alternate(event):
            ctrl = self.get_control()
            if ctrl is not None:
                self._set_cursor(ctrl, alternate=True)
    
    def key_release_handler(self, widget, event):
        # print('key_release_handler', Gdk.keyval_name(event.keyval))
        if self._key_is_alternate(event):
            ctrl = self.get_control()
            if ctrl is not None:
                self._set_cursor(ctrl, alternate=False)

if __name__ == '__main__':
    from interpolation import interpolation_strategies
    from model import ModelCurves
    
    w = Gtk.Window()
    w.set_default_size(640, 480)
    w.connect('destroy', Gtk.main_quit)
    
    m = ModelCurves()
    points = [(0.0,0.0), (0.1, 0.4), (0.2, 0.6), (0.5, 0.2), (0.4, 0.3), (1.0,1.0)]
    for interpolation, _ in interpolation_strategies:
        m.append_curve({'points':points, 'interpolation': interpolation})
    
    a = CurveEditor(m)
    w.add(a)
    
    w.connect('key-press-event'     , a.key_press_handler)
    w.connect('key-release-event'   , a.key_release_handler)
    
    w.show_all()
    Gtk.main()

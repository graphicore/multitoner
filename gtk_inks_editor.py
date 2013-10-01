#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division, print_function, unicode_literals

import os
from weakref import ref as weakref

from gi.repository import Gtk, Gdk, GObject, GdkPixbuf, Pango
import cairo

from gtk_curve_editor import CurveEditor
from interpolation import interpolation_strategies, interpolation_strategies_dict
from emitter import Emitter
from compatibility import repair_gsignals, encode, decode, range


__all__ = ['InksEditor']

# just a preparation for i18n
def _(string):
    return string


class CellRendererInk (Gtk.CellRendererText):
    """Display a preview gradient for just one color in the TreeView
    
    Inheriting from CellRendererText has one advantage: The other GtkTreeWidget
    (the InkControlPanel) is rendered with CellRendererText, so this widget
    uses the right height automatically
       
    For anything else, this could be a Gtk.GtkCellRenderer without objections
    """
    __gsignals__ = repair_gsignals({
        'received-surface': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE,
                             (GObject.TYPE_INT, ))
    })
    
    identifier = GObject.property(type=str, default='')
    
    def __init__(self, model, gradient_worker, width=-1, height=-1):
        Gtk.CellRendererText.__init__(self)
        model.add(self) #subscribe
        self._gradient_worker = gradient_worker
        self.width = width
        self.height = height
        self.state = {}
        self._set_curves(model)
    
    def _init_ink(self, iid):
        """ init the state for a ink_model"""
        self.state[iid] = {
            'surface':None,
            'timeout':None,
            'waiting': False,
            'update_needed': None
        }
    
    def _set_curves(self, model):
        inks = model.curves
        ids = model.ids
        # remove all missing inks
        for iid in self.state.keys():
            if iid not in ids:
                del self.state[iid]
        # add all new inks
        for iid, ink_model in zip(ids, inks):
            if iid not in self.state:
                self._init_ink(iid)
                self._request_new_surface(ink_model)
    
    def on_model_updated(self, model, event, *args):
        if event == 'curveUpdate':
            ink_model = args[0]
            ink_event = args[1]
            # whitelist, needs probbaly an update when more relevant events occur
            if ink_event in ('pointUpdate', 'addPoint', 'removePoint',
                            'setPoints', 'interpolationChanged',
                            'cmykChanged', 'nameChanged'):
                self._request_new_surface(ink_model)
        elif event == 'setCurves':
            self._set_curves(model)
        elif event == 'insertCurve':
            ink_model = args[0]
            iid = ink_model.id
            self._init_ink(iid)
            self._request_new_surface(ink_model)
        elif event == 'removeCurve':
            ink_model = args[0]
            iid = ink_model.id
            if iid in self.state:
                del self.state[iid]
    
    def _request_new_surface(self, ink_model):
        """ this will be called very frequently, because generating the
        gradients can take a moment this waits until the last call to this
        method was 300 millisecconds ago and then let the rendering start
        """
        
        iid = ink_model.id
        state = self.state[iid]
        
        # reset the timeout
        if state['timeout'] is not None:
            GObject.source_remove(state['timeout'])
        # schedule a new execution
        state['timeout'] = GObject.timeout_add(
            300, self._update_surface, weakref(ink_model))
    
    def _update_surface(self, weakref_model):
        ink_model = weakref_model()
        # see if the model still exists
        if ink_model is None:
            # need to return False, to cancel the timeout
            return False
        iid = ink_model.id
        state = self.state[iid]
        if state['waiting']:
            # we are waiting for a job to finish, so we don't put another
            # job on the queue right now
            state['update_needed'] = weakref_model
            return False
        state['waiting'] = True
        callback = (self._receive_surface, iid)
        self._gradient_worker.add_job(callback, ink_model)
        
        # this timout shall not be executed repeatedly, thus returning false
        return False
    
    def _receive_surface(self, iid, w, h, rowstride, buf):
        if iid not in self.state:
            return
        state = self.state[iid]
        
        cairo_surface = cairo.ImageSurface.create_for_data(
            buf, cairo.FORMAT_RGB24, w, h, rowstride
        )
        state['__keep'] = buf # so the garbage collection doesn't delete it wrongly
        state['surface'] = cairo_surface
        state['waiting'] = False
        if state['update_needed'] is not None:
            # while we where waiting another update became due
            ink_model = state['update_needed']() # its a weakref
            state['update_needed'] = None
            if ink_model is not None:
                self._request_new_surface(ink_model)
        
        #schedule a redraw
        self.emit('received-surface', iid)
    
    def do_render(self, cr, widget, background_area, cell_area, flags):
        """
        self ... a GtkCellRenderer
        cr : a cairo context to draw to
        widget : the widget owning window
        background_area : entire cell area (including tree expanders and
                          maybe padding on the sides)
        cell_area : area normally rendered by a cell renderer
        flags : flags that affect rendering
        """
        # print ('cellRendererInk', cell_area.width, cell_area.height, cell_area.x, cell_area.y)
        iid = int(self.get_property('identifier'))
        cairo_surface = None
        if iid in self.state:
            cairo_surface = self.state[iid]['surface']
        
        width, height = (self.width, cell_area.height)
        
        # x = cell_area.x # this used to be 1 but should have been 0 ??
        # this workaround make this cell renderer useless for other
        # positions than the first cell in a tree, i suppose
        if cairo_surface is not None:
            x = 0
            y = cell_area.y
            ctm = cr.get_matrix()
            cr.translate(width, 0)
            cr.scale(-(width/256), 1)
            for y in range(0+y, height+y):
                cr.set_source_surface(cairo_surface, x , y)
                cr.paint()
            cr.set_matrix(ctm)


class ColorPreviewWidget(Gtk.DrawingArea):
    """ Display a preview gradient of all visible colors in model. """
    def __init__(self, model, gradient_worker):
        Gtk.DrawingArea.__init__(self)
        model.add(self) #subscribe
        self._gradient_worker = gradient_worker
        self._surface = None
        self._timeout = None
        self._waiting = False
        self._update_needed = None
        self._no_inks = False
        self.connect('draw' , self.draw_handler)
        self._request_new_surface(model)
    
    def on_model_updated(self, inks_model, event, *args):
        if not inks_model.visible_curves:
            self._surface = None
            self.queue_draw()
            self._no_inks = True
            return
        self._no_inks = False
        if event == 'curveUpdate':
            # whitelist, needs probbaly an update when more relevant events occur
            ink_event = args[1]
            if ink_event not in ('pointUpdate', 'addPoint', 'removePoint',
                                'setPoints', 'interpolationChanged',
                                'visibleChanged', 'cmykChanged',
                                'nameChanged'):
                return
        self._request_new_surface(inks_model)
    
    def _request_new_surface(self, inks_model):
        """ this will be called very frequently, because generating the
        gradients can take a moment this waits until the last call to this
        method was 300 millisecconds ago and then let the rendering start
        """
        
        # reset the timeout
        if self._timeout is not None:
            GObject.source_remove(self._timeout)
        # schedule a new execution
        self._timeout = GObject.timeout_add(
            300, self._update_surface, weakref(inks_model))
    
    def _update_surface(self, weakref_model):
        inks_model = weakref_model()
        # see if the model still exists
        if inks_model is None or  not inks_model.visible_curves:
            # need to return False, to cancel the timeout
            return False
        
        if self._waiting:
            # we are waiting for a job to finish, so we don't put another
            # job on the queue right now
            self._update_needed =  weakref_model
            return False
        
        self._waiting = True
        
        callback = (self._receive_surface, )
        self._gradient_worker.add_job(callback, *inks_model.visible_curves)
        
        # this timout shall not be executed repeatedly, thus returning false
        return False
    
    def _receive_surface(self, w, h, rowstride, buf):
        if self._no_inks:
            # this may receive a surface after all inks are invisible
            cairo_surface = None
        else:
            cairo_surface = cairo.ImageSurface.create_for_data(
                buf, cairo.FORMAT_RGB24, w, h, rowstride
            )
        
        self._waiting = False
        if self._update_needed is not None:
            # while we where waiting another update became due
            inks_model = self._update_needed() # its a weakref
            self._update_needed = None
            if inks_model is not None:
                self._request_new_surface(inks_model)
        
        self._surface = cairo_surface
        self.queue_draw()
    
    def draw_handler(self, widget, cr):
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        cairo_surface = self._surface
        if cairo_surface is not None:
            x = 0
            y = 0
            ctm = cr.get_matrix()
            cr.translate(width, 0)
            cr.scale(-(width/256), 1)
            for y in range(0+y, height+y):
                cr.set_source_surface(cairo_surface, x , y)
                cr.paint()
            cr.set_matrix(ctm)


class HScalingTreeColumnView (Gtk.TreeViewColumn):
    """ Gtk.TreeViewColumn that scales its width according to the scale
        object it should to be subscribed to.
        
        Hookup the renderer to the scale objects on_scale_change:
        scale.add(object of HScalingTreeColumnView)
    """
    def __init__(self, name, renderer, identifier):
        self.renderer = renderer
        Gtk.TreeViewColumn.__init__(self, name, renderer, identifier=identifier)
    
    def on_scale_change(self, scale):
        """ Scale this widget to the width of scale.
        
        Be as wide as CurveEditor. So the coherence of the curves and the
        displayed (result) gradient is visible.
        """
        w, _ = scale()
        if w != self.renderer.width:
            self.renderer.width = w
            self.queue_resize()


class InkControllerException(Exception):
    pass


class InkController(Emitter):
    """ Comunicate between model and Gtk.ListStore. The latter is important
    to render the InkControlPanel and the gradients displaying Gtk.TreeView.
    
    This handles the events of the InkControlPanels initialized with
    init_control_panel.
    
    Subscribers must implement on_changed_ink_selection which is called with
    two arguments. The instance of InkController and the currently selected
    ink_id (or None).
    """
    def __init__(self, model):
        Emitter.__init__(self)
        
        self.inks = model
        
        #id, name, interpolation Name (for display), locked, visible
        self.ink_list_store = Gtk.ListStore(int, str, str, bool, bool)
        self._set_curves(self.inks)
        self.inks.add(self) #subscribe
    
    def trigger_on_changed_ink_selection(self, *args):
        for item in self._subscriptions:
            item.on_changed_ink_selection(self, *args)
    
    def changed_ink_selection_handler(self, selection):
        model, paths = selection.get_selected_rows()
        if paths:
            path = paths[0]
            ink_id = model[path][0]
        else:
            ink_id = None
        self.trigger_on_changed_ink_selection(ink_id)
    
    def _get_ink_by_path(self, path):
        row = self.ink_list_store[path]
        return self.inks.get_by_id(row[0])
    
    def _get_row_by_model(self, curve_model):
        ink_id = curve_model.id
        return self._get_row_by_id(ink_id)
    
    def _get_row_by_id(self, ink_id):
        for row in self.ink_list_store:
            if row[0] == ink_id:
                return row
        raise InkControllerException('Row not found by id {0}'.format(ink_id))
    
    def toggle_visibility_handler(self, widget, path):
        model = self._get_ink_by_path(path)
        model.visible = not model.visible
    
    def toggle_lock_handler(self, widget, path):
        model = self._get_ink_by_path(path)
        model.locked = not model.locked
    
    def delete_handler(self, widget, path):
        model = self._get_ink_by_path(path)
        window = widget.get_toplevel()
        
        dialog = Gtk.MessageDialog(window, 0, Gtk.MessageType.QUESTION,
            Gtk.ButtonsType.YES_NO, _('Delete the ink “{0}”?').format(model.name))
        dialog.format_secondary_text(
            _('You will loose all of its properties.'))
        response = dialog.run()
        if response == Gtk.ResponseType.YES:
            self.inks.remove_curve(model)
        dialog.destroy()
    
    def set_display_color_handler(self, widget, path):
        model = self._get_ink_by_path(path)
        window = widget.get_toplevel()
        
        #open colorchooser Dialog
        dialog = Gtk.ColorChooserDialog(_('Pick a color for the editor widget'),
                                        window)
        color = Gdk.RGBA(*model.display_color)
        dialog.set_rgba(color)
        dialog.run()
        color = dialog.get_rgba()
        rgb = (color.red, color.green, color.blue)
        if rgb != model.display_color:
            model.display_color = rgb
        dialog.destroy()
    
    def reorder_handler(self, widget, source_path, target_path, before):
        source = self._get_ink_by_path(source_path)
        target = self._get_ink_by_path(target_path)
        old_order = self.inks.ids
        old_index = old_order.index(source.id)
        removed_source = old_order[0:old_index] + old_order[old_index+1:]
        
        new_index = old_order.index(target.id)
        if not before:
            new_index += 1
        if old_index < new_index:
            new_index -= 1
        new_order = removed_source[0:new_index] + (source.id, ) \
                    + removed_source[new_index:]
        self.inks.reorder_by_id_list(new_order)
    
    def init_control_panel(self):
        # make a treeview …
        ink_control_panel = InkControlPanel(model=self.ink_list_store,
                                            ink_model=self.inks)
        # ink_control_panel.set_valign(Gtk.Align.END)
        tree_selection = ink_control_panel.get_selection()
        tree_selection.connect('changed', self.changed_ink_selection_handler)
        ink_control_panel.connect('toggle-visibility',
                                  self.toggle_visibility_handler)
        ink_control_panel.connect('toggle-lock', self.toggle_lock_handler)
        ink_control_panel.connect('delete', self.delete_handler)
        ink_control_panel.connect('set-display-color',
                                  self.set_display_color_handler)
        ink_control_panel.connect('reorder', self.reorder_handler)
        return ink_control_panel
    
    def init_gradient_view(self, gradient_worker, scale):
        gradient_view = Gtk.TreeView(model=self.ink_list_store)
        # gradient_view.set_valign(Gtk.Align.END)
        
        # gradient_view.set_property('headers-visible', False)
        # the width value is just initial and will change when the scale of
        # the CurveEditor changes
        renderer_ink = CellRendererInk(model=self.inks,
                                       gradient_worker=gradient_worker,
                                       width=256)
        renderer_ink.connect('received-surface', self.receive_surface_handler)
        
        column_ink = HScalingTreeColumnView(_('Single Ink Gradients'),
                                            renderer_ink, identifier=0)
        gradient_view.append_column(column_ink)
        scale.add(column_ink)
        return gradient_view
    
    def receive_surface_handler(self, widget, ink_id):
        """ Schedules a redraw. """
        row = self._get_row_by_id(ink_id)
        path = row.path
        itr = self.ink_list_store.get_iter(path)
        self.ink_list_store.row_changed(path, itr)
    
    def _update_row(self, curve_model, curve_event, *args):
        interpolation = interpolation_strategies_dict[curve_model.interpolation]
        interpolation_name = interpolation.name
        
        row = self._get_row_by_model(curve_model)
        row[1] = curve_model.name
        row[2] = interpolation_name
        row[3] = curve_model.locked
        row[4] = curve_model.visible
    
    def _remove_from_list(self, curve_model):
        row = self._get_row_by_model(curve_model)
        path = row.path
        itr = self.ink_list_store.get_iter(path)
        self.ink_list_store.remove(itr)
    
    def _insert_into_list(self, curve_model, position):
        interpolation = interpolation_strategies_dict[curve_model.interpolation]
        interpolation_name = interpolation.name
        
        #id, name, interpolation_name (for display), locked, visible
        row = [curve_model.id, curve_model.name, interpolation_name,
               curve_model.locked, curve_model.visible]
        # when position is -1 this appends
        self.ink_list_store.insert(position, row)
    
    def _append_to_list(self, curve_model):
        self._insert_into_list(curve_model, -1)
    
    def _set_curves(self, model):
        self.ink_list_store.clear()
        for curve_model in model.curves:
            self._append_to_list(curve_model)
    
    def on_model_updated(self, model, event, *args):
        if event == 'setCurves':
            self._set_curves(model)
        elif event == 'reorderedCurves':
            model_order = args[0]
            old_pos_lookup = {}
            for oldpos, row in enumerate(self.ink_list_store):
                old_pos_lookup[row[0]] = oldpos
            #new_order[newpos] = oldpos
            new_order = [old_pos_lookup[mid] for mid in model_order]
            self.ink_list_store.reorder(new_order)
        elif event == 'insertCurve':
            curve_model = args[0]
            position = args[1]
            self._insert_into_list(curve_model, position)
        elif event == 'removeCurve':
            curve_model = args[0]
            self._remove_from_list(curve_model)
        elif event == 'curveUpdate':
            curve_model = args[0]
            curveEvent = args[1]
            self._update_row(curve_model, curveEvent, args[2:])


class AddInkButton(Gtk.Button):
    """ Button to add one more Ink to the instance of ModelCurves """
    def __init__(self, model, stock_id=None, tooltip=None):
        Gtk.Button.__init__(self)
        if stock_id is not None:
            self.set_label(stock_id)
            self.set_use_stock(True)
        if tooltip is not None:
            self.set_tooltip_text(tooltip)
        
        # ghostscript doesn't do more as it seems
        self.max_inks = 10 
        
        self.model = model
        self.connect('clicked', self.clicked_handler)
        model.add(self)
    
    def clicked_handler(self, *args):
        """ add an ink if there is space """
        if len(self.model) < self.max_inks:
            self.model.append_curve()
    
    def on_model_updated(self, model, event, *args):
        if event not in ('removeCurve', 'insertCurve', 'setCurves'):
            return
        active = len(model) < self.max_inks
        self.set_sensitive(active)


class CellRendererPixbufButton(Gtk.CellRendererPixbuf):
    """ Render a button in a cell and emit a "clicked" signal
    """
    
    __gsignals__ = repair_gsignals({
        'clicked': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE,
                    (GObject.TYPE_STRING, ))
    })

    def __init__(self):
        Gtk.CellRendererPixbuf.__init__(self)
        self.set_property('mode', Gtk.CellRendererMode.ACTIVATABLE)

    def do_activate(self, event, widget, path, background_area, cell_area,
                    flags):
        self.emit('clicked', path)
        return True # activate event got 'consumed'


class CellRendererEditorColor (CellRendererPixbufButton):
    """ Render the display_color of the ink with the id of the "identifier"
    property and emmit a "clicked" signal.
    """
    def __init__(self, model):
        CellRendererPixbufButton.__init__(self)
        self.model = model
    
    identifier = GObject.property(type=str, default='')
    
    def do_render(self, cr, widget, background_area, cell_area, flags):
        """
        self ... a GtkCellRenderer
        cr : a cairo context to draw to
        widget : the widget owning window
        background_area : entire cell area (including tree expanders and
                          maybe padding on the sides)
        cell_area : area normally rendered by a cell renderer
        flags : flags that affect rendering
        """
        ink_id = int(self.get_property('identifier'))
        ink = self.model.get_by_id(ink_id)
        cr.set_source_rgb(*ink.display_color)
        width, height  = self.get_fixed_size()
        width = min(width, cell_area.width)
        height = min(height, cell_area.height)
        x = int(cell_area.x + (cell_area.width/2 - width/2))
        y = int(cell_area.y + (cell_area.height/2 - height/2))
        cr.rectangle(x, y, width, height)
        cr.fill()


class CellRendererToggle(Gtk.CellRenderer):
    """ Render and toggle a property called "active" switching between
    two pixbufs for each state """
    __gsignals__ = repair_gsignals({
        'clicked': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE,
                    (GObject.TYPE_STRING, ))
    })
    
    #active property
    active = GObject.property(type=bool, default=False)
    
    def __init__(self,  active_icon, inactive_icon):
        Gtk.CellRenderer.__init__(self)
        self.set_property('mode', Gtk.CellRendererMode.ACTIVATABLE)
        self.active_icon = active_icon
        self.inactive_icon = inactive_icon

    def do_activate(self, event, widget, path, background_area, cell_area,
                    flags):
        self.emit('clicked', path)
        return True # activate event got 'consumed'

    def do_render(self, cr, widget, background_area, cell_area, flags):
        """
        self ... a GtkCellRenderer
        cr : a cairo context to draw to
        widget : the widget owning window
        background_area : entire cell area (including tree expanders and
                          maybe padding on the sides)
        cell_area : area normally rendered by a cell renderer
        flags : flags that affect rendering
        """
        active = self.get_property('active')
        if active:
            pixbuf = self.active_icon
        else:
            pixbuf = self.inactive_icon
        
        width, height = pixbuf.get_width(), pixbuf.get_height()
        x = int(cell_area.width/2 - width/2) + cell_area.x
        y = int(cell_area.height/2 - height/2) + cell_area.y
        
        Gdk.cairo_set_source_pixbuf(cr, pixbuf, x, y)
        cr.paint()


class InkControlPanel(Gtk.TreeView):
    """ This is the 'table' with the toggles for lock and visibility, the
    delete button and the editor color chooser. Furthermore this can be
    used to reorder the inks with drag and drop.
    """
    _directory = os.path.dirname(os.path.realpath(__file__))
    
    _tooltips = {
          'editor-color': _('Change the color of the curve in the editor.')
        , 'visibility': _('Toggle visibility of the ink. A hidden ink will '
                        'not appear in the final eps document.')
        , 'lock': _('Toggle the controls for this ink in the curve editor. '
                  'A locked curve can\'t be changed in the curve editor')
        , 'delete': _('Delete the curve from the document.')
        , 'drag_n_drop': _('<b>Click</b> to show the setup interface for '
                           ' this ink. Use <b>drag and drop</b> to change '
                           'the order of the inks. The inks will '
                           'theoretically be printed in order, from bottom '
                           'to top. As a rule of thumb darker colors '
                           'should be at the bottom while lighter colors '
                           'should be at the top.') # FIXME: verify these claims!
                       
    }
    
    
    __gsignals__ = repair_gsignals({
          'toggle-visibility': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, (
                            # path
                            GObject.TYPE_STRING, ))
        , 'toggle-lock': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, (
                            # path
                            GObject.TYPE_STRING, ))
        , 'delete': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, (
                            # path
                            GObject.TYPE_STRING, ))
        , 'set-display-color': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, (
                            # path
                            GObject.TYPE_STRING, ))
        , 'reorder': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, (
                            # source_path, target_path, before/after
                            GObject.TYPE_STRING, GObject.TYPE_STRING,
                            GObject.TYPE_BOOLEAN))
    })
    
    def __init__(self, ink_model, model, **args):
        Gtk.TreeView.__init__(self, model=model, **args)
        self.set_property('headers-visible', True)
        
        # self.set_reorderable(True)
        # The reordering is implemented by setting up the tree view as a
        # drag source and destination.
        targets = [('text/plain', Gtk.TargetFlags.SAME_WIDGET, 0)]
        self.enable_model_drag_source(Gdk.ModifierType.BUTTON1_MASK, targets,
                                      Gdk.DragAction.MOVE)
        self.enable_model_drag_dest(targets, Gdk.DragAction.MOVE)
        self.connect('drag-data-received', self.drag_data_received_handler)
        self.connect('drag-data-get', self.drag_data_get_handler)
        
        self.connect('query-tooltip', self.query_tooltip_handler)
        self.set_property('has-tooltip', True)
        
        def init_column_tools():
            """ needs ink_model as argument, thus the currying """
            return self._init_column_tools(ink_model)
        
        for name, initiate in (
                    ('tools', init_column_tools)
                    , ('name', self._init_column_name)
                    , ('curve', self._init_column_curve_type)
                ):
            column = initiate()
            column.name = name
            self.append_column(column)
        
    def query_tooltip_handler(self, treeview, x, y, keyboard_mode, tooltip):
        tooltip_context = treeview.get_tooltip_context(x, y, keyboard_mode)
        has_row, cell_x, cell_y, model, path, iter = tooltip_context
        if not has_row:
            return False
        path_at_pos = treeview.get_path_at_pos(cell_x, cell_y)
        if path_at_pos is None:
            return False
        path, column = path_at_pos[0:2]
        if column is None:
            return False
        if column.name in ('name', 'curve'):
            tooltip.set_markup(self._tooltips['drag_n_drop'])
            return True
        elif column.name != 'tools':
            return False
        # tooltips for the tools column
        for cell in column.get_cells():
            col_x, col_width = column.cell_get_position(cell)
            if cell_x > col_x and cell_x <= col_x + col_width:
                if cell.name not in self._tooltips:
                    return False
                tooltip.set_markup( self._tooltips[cell.name])
                return True
        return True
    
    @staticmethod
    def drag_data_get_handler(treeview, context, selection, info, timestamp):
        # the easiest way seems to assume that the row beeing dropped
        # is the selected row
        model, iter = treeview.get_selection().get_selected()
        path = str(model.get_path(iter))
        selection.set(selection.get_target(), 8, path)
        return
    
    @staticmethod
    def drag_data_received_handler(treeview, context, x, y, data, info,
                                   time, *user_data):
        """
        Atguments:
        GdkDragContext   context    <gtk.gdk.X11DragContext object at 0x325ad70 (GdkX11DragContext at 0x35fdd30)>,
        gint             x          171,
        gint             y          68,
        GtkSelectionData *data      <GtkSelectionData at 0x7fff1c9796c0>,
        guint            info       0L,
        guint            time       4785524L
                         *user_data
        """
        source_path = Gtk.TreePath.new_from_string(data.get_data())
        target_path, drop_position = treeview.get_dest_row_at_pos(x, y)
        # drop_positions:
        #     # both before
        before_positions = (Gtk.TreeViewDropPosition.BEFORE,
                            Gtk.TreeViewDropPosition.INTO_OR_BEFORE)
        after_positions = (Gtk.TreeViewDropPosition.AFTER,
                           Gtk.TreeViewDropPosition.INTO_OR_AFTER)
        if drop_position in before_positions:
            before = True
        elif drop_position in after_positions:
            before = False
        else:
            warn('drop position is neither before nor after {0}'\
                 .format(drop_position))
            return
        
        treeview.emit('reorder', source_path, target_path, before)
        context.finish(success=True, del_=False, time=time)
    
    def _init_toggle(self, icons, callback, *data):
        setup = {}
        for key, filename in icons.items():
            icon_path = os.path.join(self._directory, encode('icons'),
                                     encode(filename))
            setup[key] = GdkPixbuf.Pixbuf.new_from_file_at_size(icon_path,
                                                                16, 16)
        toggle = CellRendererToggle(**setup)
        toggle.set_fixed_size (16, 16)
        toggle.connect('clicked', callback, *data)
        return toggle
    
    def generic_handler(self, cellRenderer, path, signalName):
        self.emit(signalName, path)
    
    def _init_editor_color_interface(self, model):
        editor_color = CellRendererEditorColor(model=model)
        editor_color.set_fixed_size(16,16)
        editor_color.connect('clicked', self.generic_handler,
                             'set-display-color')
        editor_color.name = 'editor-color'
        return editor_color
    
    def _init_visibility_toggle(self):
        icons = {'active_icon': 'visible.svg',
                 'inactive_icon': 'invisible.svg'}
        toggle = self._init_toggle(icons, self.generic_handler,
                                   'toggle-visibility')
        toggle.name = 'visibility'
        return toggle
    
    def _init_lock_toggle(self):
        icons = {'active_icon': 'locked.svg',
                 'inactive_icon': 'unlocked.svg'}
        toggle = self._init_toggle(icons, self.generic_handler,
                                   'toggle-lock')
        toggle.name = 'lock'
        return toggle
    
    def _init_delete_button(self):
        button = CellRendererPixbufButton()
        button.set_property('stock-id', Gtk.STOCK_DELETE)
        button.connect('clicked', self.generic_handler, 'delete')
        button.name = 'delete'
        return button
    
    def _init_column_tools(self, model):
        column = Gtk.TreeViewColumn(_('Tools'))
        
        visibility_toggle = self._init_visibility_toggle()
        lock_toggle = self._init_lock_toggle()
        delete_button = self._init_delete_button()
        editor_color = self._init_editor_color_interface(model)
        
        column.pack_start(visibility_toggle, False)
        column.pack_start(lock_toggle, False)
        column.pack_start(editor_color, False)
        column.pack_start(delete_button, False)
    
        column.add_attribute(editor_color, 'identifier', 0)
        column.add_attribute(lock_toggle, 'active', 3)
        column.add_attribute(visibility_toggle, 'active', 4)
        return column
    
    def _init_column_name(self):
        renderer = Gtk.CellRendererText()
        renderer.set_property('ellipsize', Pango.EllipsizeMode.END)
        column = Gtk.TreeViewColumn(_('Name'), renderer, text=1)
        column.set_property('resizable', True)
        column.set_property('min-width', 120)
        return column
        
    def _init_column_curve_type(self):
        renderer = Gtk.CellRendererText()
        renderer.set_property('ellipsize', Pango.EllipsizeMode.END)
        column = Gtk.TreeViewColumn(_('Interpolation'), renderer, text=2)
        column.set_property('resizable', True)
        column.set_property('min-width', 120)
        return column


class InkSetup(object):
    """ Interface to change the setup of an ink (name, interplation type,
    cmyk)
    """
    
    _cmyk_tooltip_format = _('<b>{color}</b> color component to approximate'
                             ' the ink color in print preview.')
    _tooltips = {
          'c': _cmyk_tooltip_format.format(color=_('Cyan'))
        , 'm': _cmyk_tooltip_format.format(color=_('Magenta'))
        , 'y': _cmyk_tooltip_format.format(color=_('Yellow'))
        , 'k': _cmyk_tooltip_format.format(color=_('Black'))
        , 'name': _('The name of the color, e.g. the color-name of a <i>' 
                    'color matching system</i> such as <i>RAL</i> or '
                    '<i>Pantone</i>. Special names are <b>Cyan</b>, '
                    '<b>Magenta</b>, <b>Yellow</b> and <b>Black</b>. '
                    'These are the names of the <i>CMYK process colors'
                    '</i>. When using a process color setting a custom '
                    'color value for preview will have no effect.')
    }
    
    def __init__(self, model):
        self.model = model
        model.add(self)
        
        self.gtk = frame = Gtk.Box()
        self._ink_options_box = Gtk.Grid()
        self._ink_options_box.set_halign(Gtk.Align.FILL)
        self._ink_options_box.set_hexpand(True)
        self._ink_options_box.set_column_spacing(5)
        self._ink_options_box.set_row_spacing(5)
        
        frame.add(self._ink_options_box)
        frame.set_hexpand(False)
        # this is about the focus-in-event
        # From the docs:
        # To receive this signal, the GdkWindow associated to the widget needs
        # to enable the GDK_FOCUS_CHANGE_MASK mask. 
        # This is done on init using self.gtk.add_events (0 | Gdk.EventMask.FOCUS_CHANGE_MASK)
        # however, since it worked before I have no proof that this is done
        # right, so when it breaks some day, look here
        self.gtk.add_events (0 | Gdk.EventMask.FOCUS_CHANGE_MASK)
        self._interpolations = Gtk.ListStore(str, str, str)
        for key, item in interpolation_strategies:
            self._interpolations.append([key, item.name, item.description])
        
        self._current_ink_id = None
        # events show() connected to
        self._connected = []
        self._widgets = {}
        self.show()
    
    def on_model_updated(self, model, event, *args):
        if event != 'curveUpdate':
            return
        ink = args[0]
        ink_event = args[1]
        if self._current_ink_id != ink.id:
            return
        # note that all gtk handlers are blocked during setting the values
        # this prevents the loop where the model is updated with the very
        # same changes it just triggert
        if ink_event == 'nameChanged':
            widget, handler_id = self._widgets['name']
            if decode(widget.get_text()) != ink.name:
                widget.handler_block(handler_id)
                widget.set_text(ink.name)
                widget.handler_unblock(handler_id)
        elif ink_event == 'cmykChanged':
            for attr in ('c', 'm', 'y', 'k'):
                widget, handler_id = self._widgets[attr]
                adjustment = widget.get_adjustment()
                value = getattr(ink, attr)
                if adjustment.get_value() == value:
                    continue
                widget.handler_block(handler_id)
                adjustment.set_value(value)
                widget.handler_unblock(handler_id)
        elif ink_event == 'interpolationChanged':
            widget, handler_id = self._widgets['interpolation']
            widget.handler_block(handler_id)
            widget.set_active_id(ink.interpolation)
            widget.handler_unblock(handler_id)
    
    def show(self, ink_id=None):
        """ Switch the active ink. """
        if ink_id is None:
            # just disable, this prevents the size of the box from changing
            # and it tells the ui story somehow right, or?
            # self._ink_options_box.set_sensitive(False)
            self._ink_options_box.hide()
        else:
            self._current_ink_id = ink_id
            ink = self.model.get_by_id(ink_id)
            # the 'value-changed' Signal of Gtk.SpinButton fired on calling
            # its destroy method when it had focus (cursor blinking inside
            # the textbox) with a value of 0 and so deleted the actual value
            for widget, handler_id in self._widgets.values():
                widget.disconnect(handler_id)
            
            self._widgets = {}
            widgets = self._widgets
            
            self._ink_options_box.foreach(lambda x, _: x.destroy(), None)
            self._ink_options_box.set_sensitive(True)
            
            label = Gtk.Label(_('Ink Setup'))
            label.get_style_context().add_class('headline')
            label.set_halign(Gtk.Align.START)
            separator = Gtk.Separator()
            self._ink_options_box.attach(separator, 0, -2, 2, 1)
            self._ink_options_box.attach(label, 0, -1, 2, 1)
            
            # make the name widget
            widget = Gtk.Entry()
            widget.set_text(ink.name)
            widget.set_tooltip_markup(self._tooltips['name'])
            
            handler_id = widget.connect('changed', self.name_changed_handler,
                                        ink_id)
            widget.connect('focus-in-event', self.focus_in_handler, ink_id)
            widgets['name'] = (widget, handler_id)
            
            # make the interpolation type widget
            widget = Gtk.ComboBox()
            widget.set_model(self._interpolations)
            widget.set_id_column(0)
            widget.set_property('has-tooltip', True)
            widget.connect('query-tooltip',
                           self.interpolation_query_tooltip_handler)
            
            text_renderer = Gtk.CellRendererText()
            widget.pack_start(text_renderer, False)
            widget.add_attribute(text_renderer, 'text', 1)
            
            widget.set_active_id(ink.interpolation)
            handler_id = widget.connect('changed',
                                        self.interpolation_changed_handler,
                                        ink_id)
            widgets['interpolation'] = (widget, handler_id)
            
            # insert the name and the interpolation type widget with labels
            ws = [
                Gtk.Label(_('Name')), widgets['name'][0],
                Gtk.Label(_('Curve Type')), widgets['interpolation'][0],
            ]
            for i, w in enumerate(ws):
                hi = i % 2
                self._ink_options_box.attach(w, hi, (i-hi)/2, 1, 1)
                w.set_halign(Gtk.Align.FILL if hi else Gtk.Align.START)
            
            # make and insert the cmyk widgets
            offset = len(ws)
            for i, (color_attr, label) in enumerate([('c',_('C')),('m',_('M')),
                                                     ('y',_('Y')),('k', _('K'))]):
                w = Gtk.Label(label)
                w.set_halign(Gtk.Align.START)
                self._ink_options_box.attach(w, 0,i+offset, 1, 1)
                
                # value: the initial value.
                # lower : the minimum value.
                # upper : the maximum value.
                # step_increment : the step increment.
                # page_increment : the page increment.
                # page_size : The page size of the adjustment.
                value = getattr(ink, color_attr)
                adjustment = Gtk.Adjustment(value, 0.0, 1.0, 0.0001,0.01, 0.0)
                widget = Gtk.SpinButton(digits=4, climb_rate=0.0001,
                    adjustment=adjustment)
                widget.set_halign(Gtk.Align.FILL)
                widget.set_tooltip_markup(self._tooltips[color_attr])
                
                handler_id = widget.connect('value-changed',
                    self.cmyk_value_changed_handler, ink_id, color_attr)
                widget.connect('focus-in-event', self.focus_in_handler, ink_id)
                self._ink_options_box.attach(widget, 1, i+offset, 1, 1)
                widgets[color_attr] = (widget, handler_id)
                
            for widget, __ in widgets.values():
                widget.set_hexpand(True)
            self._ink_options_box.show_all()
    
    @staticmethod
    def interpolation_query_tooltip_handler(widget, x, y, keyboard_mode,
                                            tooltip, *user_data):
        iter = widget.get_active_iter()
        model = widget.get_model()
        tooltip.set_text(model[iter][2])
        return True
    
    def focus_in_handler(self, widget, __, ink_id):
        self.model.get_by_id(ink_id).register_consecutive_command()
    
    def interpolation_changed_handler(self, widget, ink_id):
        ink = self.model.get_by_id(ink_id)
        interpolation = widget.get_active_id()
        ink.interpolation = interpolation
    
    def name_changed_handler(self, widget, ink_id):
        ink = self.model.get_by_id(ink_id)
        name = decode(widget.get_text())
        ink.name = name
    
    def cmyk_value_changed_handler(self, widget, ink_id, color_attr):
        ink = self.model.get_by_id(ink_id)
        value = widget.get_adjustment().get_value()
        setattr(ink, color_attr,  value)


class InksEditor(Gtk.Grid):
    """ Display and manipulate a model like ModelCurves with 'ChildModel's
    like ModelInk """
    __gsignals__ = repair_gsignals({
          'open-preview': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, 
                            # nothing
                            ())
    })
    
    def __init__(self, model, gradient_worker):
        Gtk.Grid.__init__(self)
        self.set_column_spacing(5)
        self.set_row_spacing(5)
        
        self.ink_controller = InkController(model)
        
        curve_editor = self._init_curve_editor(model)
        
        tool_column = Gtk.Grid()
        tool_column.set_row_spacing(5)
        
        
        # its important to keep a reference of this, otherwise its __dict__
        # gets lost and the ink_setup won't know its model anymore
        # this is a phenomen with gtk
        self.ink_setup = ink_setup = self._init_ink_setup(model)
        # todo: the selection could and maybe should be part of the
        # model data. Then the ink_setup could just subscribe to
        # on_model_updated
        def on_changed_ink_selection(ink_controller, inkId=None):
            """ callback for the ink_controller event """
            ink_setup.show(inkId)
        ink_setup.on_changed_ink_selection = on_changed_ink_selection
        self.ink_controller.add(ink_setup) # subscribe
        
        ink_control_panel = self.ink_controller.init_control_panel()
        
        # scales to the width of curve_editor.scale
        gradient_view = self.ink_controller.init_gradient_view(
            gradient_worker, curve_editor.scale)
        
        color_preview_widget = self._init_color_preview_widget(model,
            gradient_worker)
        
        color_preview_label = self._init_color_preview_label()
        open_preview_button = self._init_open_preview_button()
        add_ink_button = self._init_add_ink_button(model)
        
        # left : the column number to attach the left side of child to
        # top : the row number to attach the top side of child to
        # width : the number of columns that child will span
        # height : the number of rows that child will span
        self.attach(tool_column,          0, 0, 1, 3)
        self.attach(curve_editor,         2, 2, 1, 1)
        self.attach(gradient_view,        2, 0, 1, 1)
        self.attach(color_preview_widget, 2, 1, 1, 1)
        
        tool_column.attach(ink_setup.gtk,       0, 2, 1, 1)
        tool_column.attach(ink_control_panel,   0, 0, 1, 1)
        
        tool_column.attach(add_ink_button,      0, 1, 1, 1)
        tool_column.attach(open_preview_button, 0, 1, 1, 1)
        tool_column.attach(color_preview_label, 0, 1, 1, 1)
        
    def _init_curve_editor(self, model):
        curve_editor = CurveEditor.new(model)
        # will take all the space it can get
        curve_editor.set_hexpand(True)
        curve_editor.set_vexpand(True)
        # min width is 256
        curve_editor.set_size_request(256, -1)
        
        self.add_events(Gdk.EventMask.KEY_PRESS_MASK | \
                        Gdk.EventMask.KEY_RELEASE_MASK)
        self.connect('key-press-event'  , curve_editor.key_press_handler)
        self.connect('key-release-event', curve_editor.key_release_handler)
        
        return curve_editor
    
    def _init_ink_setup(self, model):
        ink_setup = InkSetup(model)
        ink_setup.gtk.set_valign(Gtk.Align.FILL)
        ink_setup.gtk.set_vexpand(True) # so this pushes itself to the bottom
        return ink_setup
    
    def _init_color_preview_widget(self, model, gradient_worker):
        widget = ColorPreviewWidget(model, gradient_worker)
        widget.set_hexpand(True)
        widget.set_vexpand(False)
        # set min height
        widget.set_size_request(-1, 30)
        return widget
    
    def _init_color_preview_label(self):
        label = Gtk.Label(_('Result:'))
        label.set_halign(Gtk.Align.END)
        return label
    
    def _init_add_ink_button(self, model):
        button = AddInkButton(model, Gtk.STOCK_ADD, _('Add a new ink'))
        button.set_halign(Gtk.Align.START)
        return button
    
    def _init_open_preview_button(self):
        # label 
        label = Gtk.Grid()
        # label icon
        icon = Gtk.Image.new_from_stock(Gtk.STOCK_PRINT_PREVIEW,
                                        Gtk.IconSize.BUTTON)
        label.attach(icon, 0, 0, 1, 1)
        # label text
        text = Gtk.Label(' ' + _('Open Preview'))
        label.attach_next_to(text, icon, Gtk.PositionType.RIGHT, 1, 1)
        
        button = Gtk.Button()
        button.add(label)
        button.set_tooltip_text(_('Open a Preview Window'))
        
        def clicked_handler(widget):
            self.emit('open-preview')
        button.connect('clicked', clicked_handler)
        button.set_halign(Gtk.Align.CENTER)
        return button

if __name__ == '__main__':
    import sys
    
    from model import ModelCurves, ModelInk
    from ghostscript_workers import GradientWorker, PreviewWorker
    from gtk_preview import PreviewWindow
    from history import History
    
    GObject.threads_init()
    use_gui, __ = Gtk.init_check(sys.argv)
    window = Gtk.Window()
    
    css_provider = Gtk.CssProvider()
    css_provider.load_from_path('style.css')
    screen = window.get_screen()
    style_context = Gtk.StyleContext()
    style_context.add_provider_for_screen(screen, css_provider,
                                          Gtk.STYLE_PROVIDER_PRIORITY_USER)
    
    window.set_title(_('Ink Tool'))
    window.set_default_size(640, 480)
    window.set_has_resize_grip(True)
    # the theme should do so
    window.set_border_width(5)
    
    window.connect('destroy', Gtk.main_quit)
    
    model = ModelCurves(ChildModel=ModelInk)
    history = History(model)
    gradient_worker = GradientWorker.new_with_pool()
    inks_editor = InksEditor(model, gradient_worker)
    
    window.add(inks_editor)
    
    
    # control the history with buttons
    def ctrl_history(widget, action):
        getattr(history, action)()
    
    undo_button = Gtk.Button()
    undo_button.set_label('gtk-undo')
    undo_button.set_use_stock(True)
    undo_button.connect('clicked', ctrl_history, 'undo')
    
    redo_button = Gtk.Button()
    redo_button.set_label('gtk-redo')
    redo_button.set_use_stock(True)
    redo_button.connect('clicked', ctrl_history, 'redo')
    
    inks_editor.attach(undo_button, 0, -1, 1, 1)
    inks_editor.attach(redo_button, 2, -1, 1, 1)
    
    # preview_window
    preview_worker = None
    def open_preview(image_name=None):
        global preview_worker
        if preview_worker is None:
            preview_worker = PreviewWorker(gradient_worker.pool) # shares the pool
        preview_window = PreviewWindow(preview_worker, model, image_name)
        preview_window.show_all()
        if image_name is None:
            preview_window.ask_for_image()
    
    def request_preview_handler(widget, *user_data):
        open_preview()
    inks_editor.connect('open-preview', request_preview_handler)
    
    # load an image if requested
    if len(sys.argv) > 1:
        image_name = sys.argv[1]
        open_preview(image_name)
    
    # fixture for development
    init_inks = [
        {
            'locked': True,
            'name': 'PANTONE 406 C',
            'display_color': (0.8233333333333334, 0.7876555555555557,
                              0.7876555555555557),
            'cmyk': (0.05, 0.09, 0.1, 0.13),
            'visible': True,
            'points': [(0, 0.13370473537604458), (1, 0.45403899721448465),
                       (0.18808777429467086, 0.2590529247910863)],
            'interpolation': 'monotoneCubic'
        },
        {
            'locked': False,
            'name': 'PANTONE 409 C',
            'display_color': (0.5333333333333333, 0.5411764705882353,
                              0.5215686274509804),
            'cmyk': (0.16, 0.25, 0.21, 0.45),
            'visible': True,
            'points': [(0, 0), (0.38557993730407525, 0.22841225626740946),
                       (0.7084639498432602, 0.6434540389972145),
                       (1, 0.8495821727019499)],
            'interpolation': 'linear'
        },
        {
            'locked': False,
            'name': 'Black',
            'display_color': (0, 0, 0),
            'cmyk': (0.0, 0.0, 0.0, 0.0),
            'visible': True,
            'points': [(0.4890282131661442, 0), (1, 1), (0, 0),
                       (0.780564263322884, 0.6295264623955432)],
            'interpolation': 'spline'
        }
    ]
    
    for t in init_inks:
        model.append_curve(t)
    
    window.show_all()
    Gtk.main()

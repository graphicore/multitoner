#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division
import os
from gi.repository import Gtk, Gdk, GObject, GdkPixbuf
import cairo
import numpy as np
from weakref import ref as Weakref
from gtkcurvewidget import CurveEditor, CurveException
from interpolation import interpolationStrategies, interpolationStrategiesDict
from model import ModelCurves, ModelTint
from GradientWorker import GradientWorker

# just a preparation for i18n
def _(string):
    return string
    
class TintList(object):
    def __init__(maxTints = None):
        # its a ghostscript limitation that is used as  delimiter here
        self.maxTints = maxTints if maxTints is not None else float('inf')
        pass

import cairo
from array import array

class CellRendererTint (Gtk.CellRendererText):
    """
    inheriting from CellRendererText had two advantages
    1. the other GtkTreeWidget is rendered with CellRendererTexts, that
       this widget uses the right height automatically
    2. I couldn't figure out how to set a custom property, so i can reuse
       the "text" property to get the tint id
    for anything else, this could be a Gtk.GtkCellRenderer without objections
    """
    def __init__(self, ctrl, model, gradientWorker, width=-1, height=-1):
        Gtk.CellRendererText.__init__(self)
        model.add(self) #subscribe
        self.ctrl = ctrl
        self.gradientWorker = gradientWorker
        self.width = width
        self.height = height
        self.state = {}
    
    def _init_tint(self, tintModel):
        """ init the state for a tintModel"""
        tid = id(tintModel)
        self.state[tid] = {
            'surface':None,
            'timeout':None,
            'waiting': False,
            'update_needed': None
        }
        self._requestNewSurface(tintModel)
    
    def onModelUpdated(self, model, event, *args):
        if event == 'curveUpdate':
            tintModel = args[0]
            tintEvent = args[1]
            # whitelist, needs probbaly an update when more relevant events occur
            if tintEvent in ('pointUpdate', 'addPoint', 'removePoint', 'setPoints',
                   'interpolationChanged', 'cmykChanged'):
                self._requestNewSurface(tintModel)
        if event == 'removeCurve':
            tintModel = args[0]
            tid = id(tintModel)
            if tid in self.state:
                del self.state[tid]
    
    def _requestNewSurface(self, tintModel):
        """ this will be called very frequently, because generating the
        gradients can take a moment this waits until the last call to this
        method was 300 millisecconds ago and then let the rendering start
        """
        
        tid = id(tintModel)
        state =  self.state[tid]
        
        # reset the timeout
        if state['timeout'] is not None:
            GObject.source_remove(state['timeout'])
        # schedule a new execution
        state['timeout'] = GObject.timeout_add(
            300, self._updateSurface, Weakref(tintModel))
    
    def _updateSurface(self, weakrefModel):
        tintModel = weakrefModel()
        # see if the model still exists
        if tintModel is None:
            # need to return False, to cancel the timeout
            return False
        tid = id(tintModel)
        state = self.state[tid]
        if state['waiting']:
            # we are waiting for a job to finish, so we don't put another
            # job on the queue right now
            state['update_needed'] = weakrefModel
            return False
        state['waiting'] = True
        callback = (self._receiveSurface, tid)
        self.gradientWorker.addJob(callback, tintModel)
        
        # this timout shall not be executed repeatedly, thus returning false
        return False
    
    def _receiveSurface(self, tid, w, h, buf):
        if tid not in self.state:
            return
        state = self.state[tid]
        cairo_surface = cairo.ImageSurface.create_for_data(
            buf, cairo.FORMAT_RGB24, w, h, w * 4
        )
        state['surface'] = cairo_surface
        state['waiting'] = False
        if state['update_needed'] is not None:
            # while we where waiting another update became due
            tintModel = state['update_needed']() # its a weakref
            state['update_needed'] = None
            if tintModel is not None:
                self._requestNewSurface(tintModel)
        
        #schedule a redraw
        self.ctrl.triggerRowChanged(tid)
    
    def do_render(self, cr, widget, background_area, cell_area, flags):
        """
        self ... a GtkCellRenderer
        cr : a cairo context to draw to
        widget : the widget owning window
        background_area : entire cell area (including tree expanders and maybe padding on the sides)
        cell_area : area normally rendered by a cell renderer
        flags : flags that affect rendering
        """
        # print 'cellRendererTint', cell_area.width, cell_area.height, cell_area.x, cell_area.y
        tidHash = self.get_property('text')
        tid = int(tidHash)
        tintModel = self.ctrl.getTintById(tid)
        
        if tid not in self.state:
            self._init_tint(tintModel)
            
        
        width, height = (self.width, cell_area.height)
        cairo_surface = self.state[tid]['surface']
        # x = cell_area.x # this used to be 1 but should have been 0 ??
        # this workaround make this cell renderer useless for other
        # positions than the first cell in a tree, i suppose
        if cairo_surface is not None:
            x = 0
            y = cell_area.y
            ctm = cr.get_matrix()
            cr.translate(width, 0)
            cr.scale(-(width/256), 1)
            for y in xrange(0+y, height+y):
                cr.set_source_surface(cairo_surface, x , y)
                cr.paint()
            cr.set_matrix(ctm)
    
    #def do_get_size(self, widget, cell_area):
    #    return (0, 0, self.width, self.height)
    def do_get_preferred_size(self, widget):
        
        return (
            Gtk.Requisition(self.width, self.height),
            Gtk.Requisition(self.width, self.height)
        )

class ColorPreviewWidget(Gtk.DrawingArea):
    def __init__(self, model, gradientWorker):
        super(ColorPreviewWidget, self).__init__()
        model.add(self) #subscribe
        self._gradientWorker = gradientWorker
        self._surface = None
        self._timeout = None
        self._waiting = False
        self._update_needed = None
        self.connect('draw' , self.onDraw)
    
    def onModelUpdated(self, tintsModel, event, *args):
        if len(tintsModel.visibleCurves) == 0:
            self._surface = None
            self.queue_draw()
            return
        if event == 'curveUpdate':
            # whitelist, needs probbaly an update when more relevant events occur
            tintEvent = args[1]
            if tintEvent not in ('pointUpdate', 'addPoint', 'removePoint',
                                 'setPoints', 'interpolationChanged',
                                 'visibleChanged', 'cmykChanged'):
                return
        self._requestNewSurface(tintsModel)
    
    def _requestNewSurface(self, tintsModel):
        """ this will be called very frequently, because generating the
        gradients can take a moment this waits until the last call to this
        method was 300 millisecconds ago and then let the rendering start
        """
        
        # reset the timeout
        if self._timeout is not None:
            GObject.source_remove(self._timeout)
        # schedule a new execution
        self._timeout = GObject.timeout_add(
            300, self._updateSurface, Weakref(tintsModel))
    
    def _updateSurface(self, weakrefModel):
        tintsModel = weakrefModel()
        # see if the model still exists
        if tintsModel is None or len(tintsModel.visibleCurves) == 0:
            # need to return False, to cancel the timeout
            return False
        
        if self._waiting:
            # we are waiting for a job to finish, so we don't put another
            # job on the queue right now
            self._update_needed =  weakrefModel
            return False
        
        self._waiting = True
        
        callback = (self._receiveSurface, )
        self._gradientWorker.addJob(callback, *tintsModel.visibleCurves)
        
        # this timout shall not be executed repeatedly, thus returning false
        return False
    
    def _receiveSurface(self, w, h, buf):
        cairo_surface = cairo.ImageSurface.create_for_data(
            buf, cairo.FORMAT_RGB24, w, h, w * 4
        )
        
        self._waiting = False
        if self._update_needed is not None:
            # while we where waiting another update became due
            tintsModel = self._update_needed() # its a weakref
            self._update_needed = None
            if tintsModel is not None:
                self._requestNewSurface(tintsModel)
        
        self._surface = cairo_surface
        self.queue_draw()
    
    @staticmethod
    def onDraw(self, cr):
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        cairo_surface = self._surface
        # x = cell_area.x # this used to be 1 but should have been 0 ??
        # this workaround make this cell renderer useless for other
        # positions than the first cell in a tree, i suppose
        if cairo_surface is not None:
            x = 0
            y = 0
            ctm = cr.get_matrix()
            cr.translate(width, 0)
            cr.scale(-(width/256), 1)
            for y in xrange(0+y, height+y):
                cr.set_source_surface(cairo_surface, x , y)
                cr.paint()
            cr.set_matrix(ctm)

class CellRendererEditorColor (Gtk.CellRendererText):
    """
    inheriting from CellRendererText had two advantages
    1. the other GtkTreeWidget is rendered with CellRendererTexts, that
       this widget uses the right height automatically
    2. I couldn't figure out how to set a custom property, so i can reuse
       the "text" property to get the tint id
    for anything else, this could be a Gtk.GtkCellRenderer without objections
    """
    def __init__(self, ctrl):
        Gtk.CellRendererText.__init__(self)
        self.ctrl = ctrl
    
    def do_render(self, cr, widget, background_area, cell_area, flags):
        """
        self ... a GtkCellRenderer
        cr : a cairo context to draw to
        widget : the widget owning window
        background_area : entire cell area (including tree expanders and maybe padding on the sides)
        cell_area : area normally rendered by a cell renderer
        flags : flags that affect rendering
        """
        tid = int(self.get_property('text'))
        tint = self.ctrl.getTintById(tid)
        cr.set_source_rgb(*tint.displayColor)
        width, height  = self.get_fixed_size()
        width = min(width, cell_area.width)
        height = min(height, cell_area.height)
        x = int(cell_area.x + (cell_area.width/2 - width/2))
        y = int(cell_area.y + (cell_area.height/2 - height/2))
        cr.rectangle(x, y, width, height)
        cr.fill()

class TintColumnView (Gtk.TreeViewColumn):
    def __init__(self, name, renderer, scale, text):
        self.renderer = renderer
        # hookup the renderer to the scale objects onScaleChange event of the curveEditor
        scale.add(self)
        #self.scale  = scale
        
        Gtk.TreeViewColumn.__init__(self, name, self.renderer, text=text)
    
    def onScaleChange(self, scale):
        """ be as wide as the curve widget """
        w, _ = scale()
        if w != self.renderer.width:
            self.renderer.width = w
            self.queue_resize()

class TintControllerException(Exception):
    pass

class TintController(object):
    def __init__(self, curves=[]):
        # ghosscript doesn't do more as it seems
        self.max_tints = 10 
        
        
        self.tints = ModelCurves(ChildModel=ModelTint)
        #id, name, interpolation Name (for display), locked, visible
        self.tintListStore = Gtk.ListStore(int, str, str, bool, bool)
        
        self.tintListStore.connect('row_deleted', self.onRowDeleted)
        
        self.tints.add(self) #subscribe
        self.tints.curves = curves
    
    def triggerRowChanged(self, tid):
        row = self._getRowById(tid)
        path = row.path
        itr = self.tintListStore.get_iter(path)
        self.tintListStore.row_changed(path, itr)
    
    def addTint(self, **args):
        if len(self.tints) < self.max_tints:
            self.tints.appendCurve(**args)
    
    def deleteTint(self, tintModel):
        self.tints.removeCurve(tintModel)
    
    def onRowDeleted(self, *args):
        """
        we use this to reorder the curves
        """
        newOrder = []
        for row in self.tintListStore:
            newOrder.append(row[0])
        self.tints.reorderByIdList(newOrder)
    
    def onModelUpdated(self, model, event, *args):
        if event == 'setCurves':
            self.tintListStore.clear()
            for curveModel in self.tints.curves:
                self._appendToList(curveModel)
        elif event == 'appendCurve':
            curveModel = args[0]
            self._appendToList(curveModel)
        elif event == 'removeCurve':
            curveModel = args[0]
            self._removeFromList(curveModel)
        elif event == 'curveUpdate':
            curveModel = args[0]
            curveEvent = args[1]
            self._updateRow(curveModel, curveEvent, args[2:])
    
    def _updateRow(self, curveModel, curveEvent, *args):
        interpolationName = interpolationStrategiesDict[curveModel.interpolation].name
        row = self._getRowByModel(curveModel)
        row[1] = curveModel.name
        row[2] = interpolationName
        row[3] = curveModel.locked
        row[4] = curveModel.visible
        
    
    def _getRowByModel(self, curveModel):
        tintId = id(curveModel)
        return self._getRowById(tintId)
    
    def _getRowById(self, tintId):
        for row in self.tintListStore:
            if row[0] == tintId:
                return row
        raise TintControllerException('Row not found by id {0}'.format(tintId))
        
    def _removeFromList(self, curveModel):
        row = self._getRowByModel(curveModel)
        path = row.path
        itr = self.tintListStore.get_iter(path)
        self.tintListStore.remove(itr)
    
    def _appendToList(self, curveModel):
        modelId = id(curveModel)
        interpolationName = interpolationStrategiesDict[curveModel.interpolation].name
        #id, name, interpolation Name (for display), locked, visible
        self.tintListStore.append([modelId, curveModel.name, interpolationName, curveModel.locked, curveModel.visible])
    
    def getTintByPath(self, path):
        row = self.tintListStore[path]
        return self.getTintById(row[0])
    
    def getTintById(self, tintId):
        for curveModel in self.tints.curves:
            if id(curveModel) == tintId:
                return curveModel
        raise TintControllerException('Tint not found by id {0}'.format(tintId))

class AddInkButton(Gtk.Button):
    def __init__(self, ctrl, stockID=None, tooltip=None):
        Gtk.Button.__init__(self)
        if stockID is not None:
            self.set_label(stockID)
            self.set_use_stock(True)
        if tooltip is not None:
            self.set_tooltip_text(tooltip)
        self.ctrl = ctrl
        self.connect('clicked', self.addInk)
        self.ctrl.tints.add(self)
    
    def addInk(self, *args):
        self.ctrl.addTint()
    
    def onModelUpdated(self, model, event, *args):
        if event not in ('removeCurve', 'appendCurve', 'setCurves'):
            return
        active = len(model) < self.ctrl.max_tints
        addInkButton.set_sensitive(active)

class CellRendererPixbufButton(Gtk.CellRendererPixbuf):
    __gsignals__ = {
        'clicked': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, (GObject.TYPE_STRING, ))
    }

    def __init__(self):
        Gtk.CellRendererPixbuf.__init__(self)
        self.set_property('mode', Gtk.CellRendererMode.ACTIVATABLE)

    def do_activate(self, event, widget, path, background_area, cell_area,
                    flags):
        self.emit('clicked', path)
        return True # activate event got 'consumed'

class CellRendererToggle(Gtk.CellRenderer):
    __gsignals__ = {
        'clicked': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, (GObject.TYPE_STRING, ))
    }
    
    #active property
    active = GObject.property(type=bool, default=False)
    
    def __init__(self,  activeIcon, inactiveIcon):
        Gtk.CellRenderer.__init__(self)
        self.set_property('mode', Gtk.CellRendererMode.ACTIVATABLE)
        self.activeIcon = activeIcon
        self.inactiveIcon = inactiveIcon

    def do_activate(self, event, widget, path, background_area, cell_area,
                    flags):
        self.emit('clicked', path)
        return True # activate event got 'consumed'

    def do_render(self, cr, widget, background_area, cell_area, flags):
        """
        self ... a GtkCellRenderer
        cr : a cairo context to draw to
        widget : the widget owning window
        background_area : entire cell area (including tree expanders and maybe padding on the sides)
        cell_area : area normally rendered by a cell renderer
        flags : flags that affect rendering
        """
        active = self.get_property('active')
        print 'do render ', active
        
        if active:
            pixbuf = self.activeIcon
        else:
            pixbuf = self.inactiveIcon
        
        
        
        width, height = pixbuf.get_width(), pixbuf.get_height()
        
        x = int(cell_area.width/2 - width/2) + cell_area.x
        y = int(cell_area.height/2 - height/2) + cell_area.y
        Gdk.cairo_set_source_pixbuf(cr, pixbuf, x, y)
        cr.paint()


#Model for the curveType choices, will be used with GtkCellRendererCombo 
interpolationStrategiesListStore = Gtk.ListStore(str, str)
for key, item in interpolationStrategies:
    interpolationStrategiesListStore.append([item.name, key])
        
if __name__ == '__main__':
    import sys
    
    GObject.threads_init()
    gradientWorker = GradientWorker()
    
    use_gui, __ = Gtk.init_check(sys.argv)
    
    w = Gtk.Window()
    
    cssProvider = Gtk.CssProvider()
    cssProvider.load_from_path('style.css')
    screen = w.get_screen()
    styleContext = Gtk.StyleContext()
    styleContext.add_provider_for_screen(screen, cssProvider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
    
    w.set_name('win')
    w.set_default_size(640, 480)
    w.set_has_resize_grip(True)
    # the theme should do so
    w.set_border_width(5)
    
    w.connect('destroy', Gtk.main_quit)
    
    tintController = TintController()
    
    curveEditor = CurveEditor.new(w, tintController.tints)
    # will take all the space it can get
    curveEditor.set_hexpand(True)
    curveEditor.set_vexpand(True)
    # min width is 256
    curveEditor.set_size_request(256, -1)
    
    tintGrid = Gtk.Grid()
    tintGrid.set_column_spacing(5)
    # tintGrid.set_column_homogeneous(True)
    # tintGrid.set_row_homogeneous(True)
    w.add(tintGrid)
    
    # left : the column number to attach the left side of child to
    # top : the row number to attach the top side of child to
    # width : the number of columns that child will span
    # height : the number of rows that child will span
    tintGrid.attach(curveEditor, 0, 0, 1, 1)
    
    # make a treeview …
    controlView = Gtk.TreeView(model=tintController.tintListStore)
    controlView.set_reorderable(True)
    controlView.set_property('headers-visible', True)
    
    treeSelection = controlView.get_selection()
    def onChangedSelection(selection):
        model, paths = selection.get_selected_rows()
        if len(paths):
            path = paths[0]
            selected = model[path][0]
        else:
            selected = None
        show_tint_options(selected)
        print 'selected is', selected
    treeSelection.connect("changed", onChangedSelection)
    
    gradientView = Gtk.TreeView(model=tintController.tintListStore)
    gradientView.set_property('headers-visible', False)
    
    # the width value is just initial and will change when the scale of
    # the curveEditor changes
    renderer_tint = CellRendererTint(ctrl=tintController, model=tintController.tints, gradientWorker=gradientWorker, width=256)
    column_tint = TintColumnView(_('Tint'), renderer_tint, scale=curveEditor.scale, text=0)
    gradientView.append_column(column_tint)
    
    renderer_editorColor = CellRendererEditorColor(ctrl=tintController)
    renderer_editorColor.set_fixed_size (16,16)
    column_id = Gtk.TreeViewColumn(_('ID'), renderer_editorColor, text=0)
    
    def deleteRow(cellRenderer, path):
        model = tintController.getTintByPath(path)
        
        dialog = Gtk.MessageDialog(w, 0, Gtk.MessageType.QUESTION,
            Gtk.ButtonsType.YES_NO, _('Delete the color “{0}”?').format(model.name))
        dialog.format_secondary_text(
            _('You will loose all of its properties.'))
        response = dialog.run()
        if response == Gtk.ResponseType.YES:
            tintController.deleteTint(model)
        dialog.destroy()
    
    renderer_deleteRow = CellRendererPixbufButton()
    renderer_deleteRow.set_property('stock-id', Gtk.STOCK_DELETE)
    renderer_deleteRow.connect('clicked', deleteRow)
    
    #locked row
    def toggleLocked(cellRenderer, path):
        model = tintController.getTintByPath(path)
        model.locked = not model.locked
    
    icons = {}
    for key, fileName in {'activeIcon': 'locked.svg', 'inactiveIcon': 'unlocked.svg'}.items():
        iconPath = os.path.join(os.path.dirname(__file__), 'icons', fileName)
        icons[key] = GdkPixbuf.Pixbuf.new_from_file_at_size(iconPath, 16, 16)
    renderer_lockRow = CellRendererToggle(**icons)
    renderer_lockRow.set_fixed_size (16, 16)
    renderer_lockRow.connect('clicked', toggleLocked)
    
    def toggleVisible(cellRenderer, path):
        model = tintController.getTintByPath(path)
        model.visible = not model.visible
    
    icons = {}
    for key, fileName in {'activeIcon': 'visible.svg', 'inactiveIcon': 'invisible.svg'}.items():
        iconPath = os.path.join(os.path.dirname(__file__), 'icons', fileName)
        icons[key] = GdkPixbuf.Pixbuf.new_from_file_at_size(iconPath, 16, 16)
    renderer_visibilityRow = CellRendererToggle(**icons)
    renderer_visibilityRow.set_fixed_size (16, 16)
    renderer_visibilityRow.connect('clicked', toggleVisible)
    
    
    column_id.pack_start(renderer_lockRow, False)
    column_id.add_attribute(renderer_lockRow, 'active', 3)
    
    column_id.pack_start(renderer_visibilityRow, False)
    column_id.add_attribute(renderer_visibilityRow, 'active', 4)
    
    column_id.pack_start(renderer_deleteRow, False)
    
    controlView.append_column(column_id)
    
    
    
    renderer_name = Gtk.CellRendererText()
    column_name = Gtk.TreeViewColumn(_('Name'), renderer_name, text=1)
    controlView.append_column(column_name)
    
    renderer_curveType = Gtk.CellRendererText()
    column_curveType = Gtk.TreeViewColumn(_('Interpolation'), renderer_curveType, text=2)
    controlView.append_column(column_curveType)
    
    controlView.set_valign(Gtk.Align.END)
    #controlView.set_vexpand(True) # so this pushes itself to the bottom
    gradientView.set_valign(Gtk.Align.END)
    
    
    tintGrid.attach(gradientView, 0, 1, 1, 1)
    
    
    colorPreviewWidget = ColorPreviewWidget(tintController.tints, gradientWorker)
    colorPreviewWidget.set_hexpand(True)
    colorPreviewWidget.set_vexpand(False)
    # set min height
    colorPreviewWidget.set_size_request(-1, 30)
    tintGrid.attach(colorPreviewWidget, 0, 2, 1, 1)
    
    colorPreviewLabel = Gtk.Label(_('Result'))
    colorPreviewLabel.set_halign(Gtk.Align.START)
    tintGrid.attach(colorPreviewLabel, 1, 2, 1, 1)
    
    addInkButton = AddInkButton(tintController, Gtk.STOCK_ADD, _('Add a new ink'))
    addInkButton.set_halign(Gtk.Align.END)
    tintGrid.attach(addInkButton, 2, 2, 1, 1)
    
    
    
    
    tintGrid.set_row_spacing(5)
    
    rightColumn = Gtk.Grid()
    rightColumn.set_row_spacing(5)
    rightColumn.attach(controlView, 0, 1, 1, 1)
    tintGrid.attach(rightColumn, 1, 0, 2, 2)
    
    tintOptionsBox = Gtk.Grid(orientation=Gtk.Orientation.VERTICAL)
    
    
    frame = Gtk.Frame()
    frame.set_label(_('Tint Setup'))
    frame.set_valign(Gtk.Align.FILL)
    frame.add(tintOptionsBox)
    frame.set_vexpand(True) # so this pushes itself to the bottom
    
    rightColumn.attach(frame, 0, 0, 1, 1)
    
    
    def onWidgetCurveTypeChange(widget, tintId):
        interpolation = widget.get_active_id()
        tintController.getTintById(tintId).interpolation = interpolation
    
    def onWidgetNameChange(widget, tintId):
        name = widget.get_text()
        tintController.getTintById(tintId).name = name
    
    def onWidgetColorChange(widget, tintId):
        color = widget.get_rgba()
        rgb = (color.red, color.green, color.blue)
        tintController.getTintById(tintId).displayColor = rgb
    
    def onWidgetCMYKValueChange(widget, tintId, colorAttr):
        tint = tintController.getTintById(tintId)
        value = widget.get_adjustment().get_value()
        setattr(tint, colorAttr,  value)
    
    
    def show_tint_options(tintId=None):
        if tintId is None:
            tintOptionsBox.set_sensitive(False)
            # just disable, this prevents the size of the box from changing
            # and it tells the ui story right
        else:
            tintOptionsBox.foreach(lambda x, _: x.destroy(), None)
            tintOptionsBox.set_sensitive(True)
            tint = tintController.getTintById(tintId)
            
            widget_id = Gtk.Label(tintId)
            widget_id.set_halign(Gtk.Align.START)
        
            widget_name = Gtk.Entry()
            widget_name.set_text(tint.name)
            widget_name.connect('changed', onWidgetNameChange, tintId);
            
            widget_curveType = Gtk.ComboBoxText.new()
            widget_curveType.set_model(interpolationStrategiesListStore)
            widget_curveType.set_id_column(1)
            widget_curveType.set_active_id(tint.interpolation)
            widget_curveType.connect('changed', onWidgetCurveTypeChange, tintId);
            
            rgba = Gdk.RGBA(*tint.displayColor)
            colorButton = Gtk.ColorButton.new_with_rgba(rgba)
            colorButton.connect('color-set', onWidgetColorChange, tintId);
            
            ws = [
                Gtk.Label(_('Id')), widget_id,
                Gtk.Label(_('Name')), widget_name,
                Gtk.Label(_('Curve Type')), widget_curveType,
                Gtk.Label(_('Editor Color')), colorButton
            ]
            
            
            for i, w in enumerate(ws):
                hi = i % 2
                tintOptionsBox.attach(w, hi, (i-hi)/2, 1, 1)
                w.set_halign(Gtk.Align.FILL if hi else Gtk.Align.START)
            
            offset = len(ws)
            for i, (colorAttr, label) in enumerate([('c',_('C')),('m',_('M')),('y',_('Y')),('k', _('K'))]):
                w = Gtk.Label(label)
                w.set_halign(Gtk.Align.START)
                tintOptionsBox.attach(w, 0,i+offset, 1, 1)
                
                # value: the initial value.
                # lower : the minimum value.
                # upper : the maximum value.
                # step_increment : the step increment.
                # page_increment : the page increment.
                # page_size : The page size of the adjustment.
                value = getattr(tint, colorAttr)
                adjustment = Gtk.Adjustment(value, 0.0, 1.0, 0.0001,0.01, 0.0)
                entry = Gtk.SpinButton(digits=4, climb_rate=0.0001, adjustment=adjustment)
                entry.set_halign(Gtk.Align.FILL)
                entry.connect('value-changed', onWidgetCMYKValueChange,tintId, colorAttr)
                tintOptionsBox.attach(entry, 1, i+offset, 1, 1)
                
        tintOptionsBox.show_all()
    show_tint_options()
    
    
    
    ###
    tintController.tints.appendCurve(points=[(0.0, 1.0), (0.5, 0.3), (1, 0.0)], interpolation='spline', name="Yellow")
    tintController.tints.appendCurve(points=[(0.0, 0.0), (0.1, 0.4), (0.4, 0.7)], interpolation='spline', name="Magenta")
    tintController.tints.appendCurve(points=[(0.0, 0.0), (0.2, 0.6), (0.5, 0.2), (0.4, 0.3), (1.0,1.0)], name="Black")
    
    w.show_all()
    Gtk.main()

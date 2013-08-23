#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division
import os
import sys
from gi.repository import Gtk, Gdk, GObject, GdkPixbuf
import cairo
from weakref import ref as Weakref

from gtkcurvewidget import CurveEditor
from interpolation import interpolationStrategies, interpolationStrategiesDict
from emitter import Emitter
from model import ModelCurves, ModelInk
from GradientWorker import GradientWorker
from PreviewWindow import PreviewWindow

# just a preparation for i18n
def _(string):
    return string

class CellRendererInk (Gtk.CellRendererText):
    """
    Display a preview gradient for just one color in the TreeView
    
    inheriting from CellRendererText had two advantages
    1. the other GtkTreeWidget is rendered with CellRendererTexts, that
       this widget uses the right height automatically
    2. I couldn't figure out how to set a custom property, so i can reuse
       the "text" property to get the ink id
    for anything else, this could be a Gtk.GtkCellRenderer without objections
    """
    __gsignals__ = {
        'received-surface': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, (GObject.TYPE_INT, ))
    }
    
    def __init__(self, model, gradientWorker, width=-1, height=-1):
        Gtk.CellRendererText.__init__(self)
        model.add(self) #subscribe
        self.gradientWorker = gradientWorker
        self.width = width
        self.height = height
        self.state = {}
    
    def _init_ink(self, iid):
        """ init the state for a inkModel"""
        self.state[iid] = {
            'surface':None,
            'timeout':None,
            'waiting': False,
            'update_needed': None
        }
    
    def onModelUpdated(self, model, event, *args):
        if event == 'curveUpdate':
            inkModel = args[0]
            inkEvent = args[1]
            # whitelist, needs probbaly an update when more relevant events occur
            if inkEvent in ('pointUpdate', 'addPoint', 'removePoint',
                            'setPoints', 'interpolationChanged',
                            'cmykChanged', 'nameChanged'):
                self._requestNewSurface(inkModel)
        elif event == 'setCurves':
            inks = model.curves
            ids = map(id, inks)
            # remove all missing inks
            for iid in self.state.keys():
                if iid not in ids:
                    del self.state[iid]
            # add all new inks
            for iid, inkModel in zip(ids, inks):
                if iid not in self.state:
                    self._init_ink(iid)
                    self._requestNewSurface(inkModel)
        elif event == 'appendCurve':
            inkModel = args[0]
            iid = id(inkModel)
            self._init_ink(iid)
            self._requestNewSurface(inkModel)
        elif event == 'removeCurve':
            inkModel = args[0]
            iid = id(inkModel)
            if iid in self.state:
                del self.state[iid]
    
    def _requestNewSurface(self, inkModel):
        """ this will be called very frequently, because generating the
        gradients can take a moment this waits until the last call to this
        method was 300 millisecconds ago and then let the rendering start
        """
        
        iid = id(inkModel)
        state =  self.state[iid]
        
        # reset the timeout
        if state['timeout'] is not None:
            GObject.source_remove(state['timeout'])
        # schedule a new execution
        state['timeout'] = GObject.timeout_add(
            300, self._updateSurface, Weakref(inkModel))
    
    def _updateSurface(self, weakrefModel):
        inkModel = weakrefModel()
        # see if the model still exists
        if inkModel is None:
            # need to return False, to cancel the timeout
            return False
        iid = id(inkModel)
        state = self.state[iid]
        if state['waiting']:
            # we are waiting for a job to finish, so we don't put another
            # job on the queue right now
            state['update_needed'] = weakrefModel
            return False
        state['waiting'] = True
        callback = (self._receiveSurface, iid)
        self.gradientWorker.addJob(callback, inkModel)
        
        # this timout shall not be executed repeatedly, thus returning false
        return False
    
    def _receiveSurface(self, iid, w, h, buf):
        if iid not in self.state:
            return
        state = self.state[iid]
        cairo_surface = cairo.ImageSurface.create_for_data(
            buf, cairo.FORMAT_RGB24, w, h, w * 4
        )
        
        state['surface'] = cairo_surface
        state['waiting'] = False
        if state['update_needed'] is not None:
            # while we where waiting another update became due
            inkModel = state['update_needed']() # its a weakref
            state['update_needed'] = None
            if inkModel is not None:
                self._requestNewSurface(inkModel)
        
        #schedule a redraw
        self.emit('received-surface', iid)
    
    def do_render(self, cr, widget, background_area, cell_area, flags):
        """
        self ... a GtkCellRenderer
        cr : a cairo context to draw to
        widget : the widget owning window
        background_area : entire cell area (including tree expanders and maybe padding on the sides)
        cell_area : area normally rendered by a cell renderer
        flags : flags that affect rendering
        """
        # print 'cellRendererInk', cell_area.width, cell_area.height, cell_area.x, cell_area.y
        iidHash = self.get_property('text')
        iid = int(iidHash)
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
    """
        display a preview gradient of all visible colors using ghostscript
    """
    def __init__(self, model, gradientWorker):
        super(ColorPreviewWidget, self).__init__()
        model.add(self) #subscribe
        self._gradientWorker = gradientWorker
        self._surface = None
        self._timeout = None
        self._waiting = False
        self._update_needed = None
        self._noInks = False
        self.connect('draw' , self.onDraw)
    
    def onModelUpdated(self, inksModel, event, *args):
        if len(inksModel.visibleCurves) == 0:
            self._surface = None
            self.queue_draw()
            self._noInks = True
            return
        self._noInks = False
        if event == 'curveUpdate':
            # whitelist, needs probbaly an update when more relevant events occur
            inkEvent = args[1]
            if inkEvent not in ('pointUpdate', 'addPoint', 'removePoint',
                                'setPoints', 'interpolationChanged',
                                'visibleChanged', 'cmykChanged',
                                'nameChanged'):
                return
        self._requestNewSurface(inksModel)
    
    def _requestNewSurface(self, inksModel):
        """ this will be called very frequently, because generating the
        gradients can take a moment this waits until the last call to this
        method was 300 millisecconds ago and then let the rendering start
        """
        
        # reset the timeout
        if self._timeout is not None:
            GObject.source_remove(self._timeout)
        # schedule a new execution
        self._timeout = GObject.timeout_add(
            300, self._updateSurface, Weakref(inksModel))
    
    def _updateSurface(self, weakrefModel):
        inksModel = weakrefModel()
        # see if the model still exists
        if inksModel is None or len(inksModel.visibleCurves) == 0:
            # need to return False, to cancel the timeout
            return False
        
        if self._waiting:
            # we are waiting for a job to finish, so we don't put another
            # job on the queue right now
            self._update_needed =  weakrefModel
            return False
        
        self._waiting = True
        
        callback = (self._receiveSurface, )
        self._gradientWorker.addJob(callback, *inksModel.visibleCurves)
        
        # this timout shall not be executed repeatedly, thus returning false
        return False
    
    def _receiveSurface(self, w, h, buf):
        if self._noInks:
            # this may receive a surface after all inks are invisible
            cairo_surface = None
        else:
            cairo_surface = cairo.ImageSurface.create_for_data(
                buf, cairo.FORMAT_RGB24, w, h, w * 4
            )
        
        self._waiting = False
        if self._update_needed is not None:
            # while we where waiting another update became due
            inksModel = self._update_needed() # its a weakref
            self._update_needed = None
            if inksModel is not None:
                self._requestNewSurface(inksModel)
        
        self._surface = cairo_surface
        self.queue_draw()
    
    @staticmethod
    def onDraw(self, cr):
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        cairo_surface = self._surface
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

class HScalingTreeColumnView (Gtk.TreeViewColumn):
    """ 
        a Gtk.TreeViewColumn that scales its width according to the scale
        object it should to be subscribed to.
        
        hookup the renderer to the scale objects onScaleChange:
        scale.add(object of HScalingTreeColumnView)
    """
    def __init__(self, name, renderer, text):
        self.renderer = renderer
        Gtk.TreeViewColumn.__init__(self, name, renderer, text=text)
    
    def onScaleChange(self, scale):
        """ be as wide as the curve widget """
        w, _ = scale()
        if w != self.renderer.width:
            self.renderer.width = w
            self.queue_resize()

class InkControllerException(Exception):
    pass

class InkController(Emitter):
    """
    This is the interface used by the widgets.
    I'm unsure right now if the Widgets should rather emmit events
    that the instance of this class would subscribe to
    The attempt to have control over ModelCurves and a here synchronized
    Gtk.ListStore
    """
    def __init__(self, model):
        Emitter.__init__(self)
        
        self.inks = model
        
        #id, name, interpolation Name (for display), locked, visible
        self.inkListStore = Gtk.ListStore(int, str, str, bool, bool)
        
        # we use this to reorder the curves
        self.inkListStore.connect('row_deleted', self.reorderInks)
        
        self.inks.add(self) #subscribe
    
    def triggerOnChangedInkSelection(self, *args):
        for item in self:
            item.onChangedInkSelection(self, *args)
    
    def changedInkSelectionHandler(self, selection):
        model, paths = selection.get_selected_rows()
        if len(paths):
            path = paths[0]
            inkId = model[path][0]
        else:
            inkId = None
        self.triggerOnChangedInkSelection(inkId)
        print 'selected is', inkId
    
    def toggleVisibilityHandler(self, inkControlPanel, path):
        model = self.getInkByPath(path)
        model.visible = not model.visible
    
    def toggleLockedHandler(self, inkControlPanel, path):
        model = self.getInkByPath(path)
        model.locked = not model.locked
    
    def deleteHandler(self, inkControlPanel, path):
        model = self.getInkByPath(path)
        window = inkControlPanel.get_toplevel()
        
        dialog = Gtk.MessageDialog(window, 0, Gtk.MessageType.QUESTION,
            Gtk.ButtonsType.YES_NO, _('Delete the ink “{0}”?').format(model.name))
        dialog.format_secondary_text(
            _('You will loose all of its properties.'))
        response = dialog.run()
        if response == Gtk.ResponseType.YES:
            self.inks.removeCurve(model)
        dialog.destroy()
    
    def setDisplayColorHandler(self, inkControlPanel, path):
        model = self.getInkByPath(path)
        window = inkControlPanel.get_toplevel()
        
        #open colorchooser Dialog
        dialog = Gtk.ColorChooserDialog(_('Pick a color for the editor widget'), window)
        color = Gdk.RGBA(*model.displayColor)
        dialog.set_rgba(color)
        dialog.run()
        color = dialog.get_rgba()
        rgb = (color.red, color.green, color.blue)
        model.displayColor = rgb
        dialog.destroy()
    
    def initControlPanel(self):
        # make a treeview …
        inkControlPanel = InkControlPanel(
                          model=self.inkListStore, inkModel=self.inks)
        inkControlPanel.set_valign(Gtk.Align.END)
        treeSelection = inkControlPanel.get_selection()
        treeSelection.connect('changed', self.changedInkSelectionHandler)
        inkControlPanel.connect('toggle-visibility', self.toggleVisibilityHandler)
        inkControlPanel.connect('toggle-locked', self.toggleLockedHandler)
        inkControlPanel.connect('delete', self.deleteHandler)
        inkControlPanel.connect('set-display-color', self.setDisplayColorHandler)
        return inkControlPanel
    
    def initGradientView(self, gradientWorker, scale):
        gradientView = Gtk.TreeView(model=self.inkListStore)
        gradientView.set_valign(Gtk.Align.END)
        
        gradientView.set_property('headers-visible', False)
        # the width value is just initial and will change when the scale of
        # the curveEditor changes
        renderer_ink = CellRendererInk(model=self.inks, gradientWorker=gradientWorker, width=256)
        renderer_ink.connect('received-surface', self.queueDrawRow)
        
        column_ink = HScalingTreeColumnView(_('Ink'), renderer_ink, text=0)
        gradientView.append_column(column_ink)
        scale.add(column_ink)
        return gradientView
    
    def queueDrawRow(self, widget, iid):
        """ schedules a redraw """
        row = self._getRowById(iid)
        path = row.path
        itr = self.inkListStore.get_iter(path)
        self.inkListStore.row_changed(path, itr)
    
    def reorderInks(self, *args):
        newOrder = []
        for row in self.inkListStore:
            newOrder.append(row[0])
        self.inks.reorderByIdList(newOrder)
    
    def onModelUpdated(self, model, event, *args):
        if event == 'setCurves':
            self.inkListStore.clear()
            for curveModel in model.curves:
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
        inkId = id(curveModel)
        return self._getRowById(inkId)
    
    def _getRowById(self, inkId):
        for row in self.inkListStore:
            if row[0] == inkId:
                return row
        raise InkControllerException('Row not found by id {0}'.format(inkId))
        
    def _removeFromList(self, curveModel):
        row = self._getRowByModel(curveModel)
        path = row.path
        itr = self.inkListStore.get_iter(path)
        self.inkListStore.remove(itr)
    
    def _appendToList(self, curveModel):
        modelId = id(curveModel)
        interpolationName = interpolationStrategiesDict[curveModel.interpolation].name
        #id, name, interpolation Name (for display), locked, visible
        self.inkListStore.append([modelId, curveModel.name, interpolationName, curveModel.locked, curveModel.visible])
    
    def getInkByPath(self, path):
        row = self.inkListStore[path]
        return self.inks.getById(row[0])

class AddInkButton(Gtk.Button):
    """
    Button to add one more Ink to model
    """
    def __init__(self, model, stockID=None, tooltip=None):
        Gtk.Button.__init__(self)
        if stockID is not None:
            self.set_label(stockID)
            self.set_use_stock(True)
        if tooltip is not None:
            self.set_tooltip_text(tooltip)
        
        # ghosscript doesn't do more as it seems
        self.max_inks = 10 
        
        self.model = model
        self.connect('clicked', self.addInk)
        model.add(self)
    
    def addInk(self, *args):
        if len(self.model) < self.max_inks:
            self.model.appendCurve()
    
    def onModelUpdated(self, model, event, *args):
        if event not in ('removeCurve', 'appendCurve', 'setCurves'):
            return
        active = len(model) < self.max_inks
        self.set_sensitive(active)

class CellRendererPixbufButton(Gtk.CellRendererPixbuf):
    """
    used to render a button in a cell using a Gtk.CellRendererPixbuf
    and emits a "clicked" signal
    """
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

class CellRendererEditorColor (CellRendererPixbufButton):
    """
    render the color of the ink that has the id of the "identifier" property
    and emmits a "clicked" signal
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
        background_area : entire cell area (including tree expanders and maybe padding on the sides)
        cell_area : area normally rendered by a cell renderer
        flags : flags that affect rendering
        """
        iid = int(self.get_property('identifier'))
        ink = self.model.getById(iid)
        cr.set_source_rgb(*ink.displayColor)
        width, height  = self.get_fixed_size()
        width = min(width, cell_area.width)
        height = min(height, cell_area.height)
        x = int(cell_area.x + (cell_area.width/2 - width/2))
        y = int(cell_area.y + (cell_area.height/2 - height/2))
        cr.rectangle(x, y, width, height)
        cr.fill()

class CellRendererToggle(Gtk.CellRenderer):
    """
    A cell renderer that renders and can toggle a  property called "active"
    """
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
        if active:
            pixbuf = self.activeIcon
        else:
            pixbuf = self.inactiveIcon
        
        width, height = pixbuf.get_width(), pixbuf.get_height()
        x = int(cell_area.width/2 - width/2) + cell_area.x
        y = int(cell_area.height/2 - height/2) + cell_area.y
        
        Gdk.cairo_set_source_pixbuf(cr, pixbuf, x, y)
        cr.paint()

class InkControlPanel(Gtk.TreeView):
    """
    This is the 'table' with the toggles for lock and visibility, the
    delete button and the editor color chooser. Furthermore this can be
    used to reorder the inks with drag and drop.
    """
    __gsignals__ = {
          'toggle-visibility': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, (
                            # path
                            GObject.TYPE_STRING, ))
        , 'toggle-locked': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, (
                            # path
                            GObject.TYPE_STRING, ))
        , 'delete': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, (
                            # path
                            GObject.TYPE_STRING, ))
        , 'set-display-color': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, (
                            # path
                            GObject.TYPE_STRING, )) 
    }
    
    def __init__(self, inkModel, model, **args):
        Gtk.TreeView.__init__(self, model=model, **args)
        self.set_reorderable(True)
        self.set_property('headers-visible', True)
        
        def initColumnId():
            return self._initColumnId(inkModel)
        
        for initiate in (initColumnId, self._initColumnName,
                         self._initColumnCurveType):
            column = initiate()
            self.append_column(column)
    
    def _initToggle(self, icons, callback, *data):
        setup = {}
        for key, fileName in icons.items():
            iconPath = os.path.join(os.path.dirname(__file__), 'icons', fileName)
            setup[key] = GdkPixbuf.Pixbuf.new_from_file_at_size(iconPath, 16, 16)
        toggle = CellRendererToggle(**setup)
        toggle.set_fixed_size (16, 16)
        toggle.connect('clicked', callback, *data)
        return toggle
    
    def trigger(self, cellRenderer, path, signalName):
        self.emit(signalName, path)
    
    def _initEditorColorInterface(self, model):
        editorColor = CellRendererEditorColor(model=model)
        editorColor.set_fixed_size(16,16)
        editorColor.connect('clicked', self.trigger, 'set-display-color')
        return editorColor;
    
    def _initVisibilityToggle(self):
        icons = {'activeIcon': 'visible.svg', 'inactiveIcon': 'invisible.svg'}
        return self._initToggle(icons, self.trigger, 'toggle-visibility')
    
    def _initLockedToggle(self):
        icons = {'activeIcon': 'locked.svg', 'inactiveIcon': 'unlocked.svg'}
        return self._initToggle(icons, self.trigger, 'toggle-locked')
    
    def _initDeleteButton(self):
        button = CellRendererPixbufButton()
        button.set_property('stock-id', Gtk.STOCK_DELETE)
        button.connect('clicked', self.trigger, 'delete')
        return button;
    
    def _initColumnId(self, model):
        column = Gtk.TreeViewColumn(_('Tools'))
        
        visibilityToggle = self._initVisibilityToggle()
        lockedToggle = self._initLockedToggle()
        deleteButton = self._initDeleteButton()
        editorColor = self._initEditorColorInterface(model)
        
        column.pack_start(visibilityToggle, False)
        column.pack_start(lockedToggle, False)
        column.pack_start(editorColor, False)
        column.pack_start(deleteButton, False)
    
        column.add_attribute(editorColor, 'identifier', 0)
        column.add_attribute(lockedToggle, 'active', 3)
        column.add_attribute(visibilityToggle, 'active', 4)
        return column;
    
    def _initColumnName(self):
        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn(_('Name'), renderer, text=1)
        return column
        
    def _initColumnCurveType(self):
        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn(_('Interpolation'), renderer, text=2)
        return column

class InkSetup(object):
    """
    This is the Interface to change the setup of an ink
    
    todo: this should subscribe to model
    """
    def __init__(self, model):
        self.model = model
        self.gtk = Gtk.Frame()
        self.gtk.set_label(_('Ink Setup'))
        
        self._interpolations = Gtk.ListStore(str, str)
        for key, item in interpolationStrategies:
            self._interpolations.append([item.name, key])
        
        self._inkOptionsBox = Gtk.Grid(orientation=Gtk.Orientation.VERTICAL)
        self.gtk.add(self._inkOptionsBox)
        
        self._connected = [];
        self.show();
    
    def show(self, inkId=None):
        if inkId is None:
            self._inkOptionsBox.set_sensitive(False)
            # just disable, this prevents the size of the box from changing
            # and it tells the ui story right
        else:
            ink = self.model.getById(inkId)
            # the 'value-changed' Signal of Gtk.SpinButton fired on calling
            # its destroy method when it had focus (cursor blinking inside
            # the textbox) with a value of 0 and so deleted the actual value
            for widget, handler_id in self._connected:
                widget.disconnect(handler_id)
            self._connected = []
            
            self._inkOptionsBox.foreach(lambda x, _: x.destroy(), None)
            self._inkOptionsBox.set_sensitive(True)
            inkId = id(ink)
            
            widget_name = Gtk.Entry()
            widget_name.set_text(ink.name)
            widget_name.connect('changed', self.onNameChange, inkId);
            
            widget_curveType = Gtk.ComboBoxText.new()
            widget_curveType.set_model(self._interpolations)
            widget_curveType.set_id_column(1)
            widget_curveType.set_active_id(ink.interpolation)
            widget_curveType.connect('changed', self.onCurveTypeChange, inkId);
            
            ws = [
                Gtk.Label(_('Name')), widget_name,
                Gtk.Label(_('Curve Type')), widget_curveType,
            ]
            
            
            for i, w in enumerate(ws):
                hi = i % 2
                self._inkOptionsBox.attach(w, hi, (i-hi)/2, 1, 1)
                w.set_halign(Gtk.Align.FILL if hi else Gtk.Align.START)
            
            offset = len(ws)
            for i, (colorAttr, label) in enumerate([('c',_('C')),('m',_('M')),('y',_('Y')),('k', _('K'))]):
                w = Gtk.Label(label)
                w.set_halign(Gtk.Align.START)
                self._inkOptionsBox.attach(w, 0,i+offset, 1, 1)
                
                # value: the initial value.
                # lower : the minimum value.
                # upper : the maximum value.
                # step_increment : the step increment.
                # page_increment : the page increment.
                # page_size : The page size of the adjustment.
                value = getattr(ink, colorAttr)
                adjustment = Gtk.Adjustment(value, 0.0, 1.0, 0.0001,0.01, 0.0)
                entry = Gtk.SpinButton(digits=4, climb_rate=0.0001, adjustment=adjustment)
                entry.set_halign(Gtk.Align.FILL)
                handler_id = entry.connect('value-changed', self.onCMYKValueChange, inkId, colorAttr)
                self._connected.append((entry, handler_id))
                self._inkOptionsBox.attach(entry, 1, i+offset, 1, 1)
                
        self._inkOptionsBox.show_all()
    
    def onCurveTypeChange(self, widget, inkId):
        interpolation = widget.get_active_id()
        self.model.getById(inkId).interpolation = interpolation
    
    def onNameChange(self, widget, inkId):
        name = widget.get_text()
        self.model.getById(inkId).name = name
    
    def onCMYKValueChange(self, widget, inkId, colorAttr):
        ink = self.model.getById(inkId)
        value = widget.get_adjustment().get_value()
        setattr(ink, colorAttr,  value)

class InksEditor(Gtk.Grid):
    def __init__(self, model, gradientWorker):
        """
        gradientWorker: a initialized GradientWorker
        """
        Gtk.Grid.__init__(self)
        self.set_column_spacing(5)
        self.set_row_spacing(5)
        
        self.inkController = InkController(model)
        
        curveEditor = self.initCurveEditor(model)
        # left : the column number to attach the left side of child to
        # top : the row number to attach the top side of child to
        # width : the number of columns that child will span
        # height : the number of rows that child will span
        self.attach(curveEditor, 0, 0, 1, 1)
        
        rightColumn = Gtk.Grid()
        rightColumn.set_row_spacing(5)
        self.attach(rightColumn, 1, 0, 2, 2)
        
        inkSetup = self.initInkSetup(model);
        # todo: the selection could and maybe should be part of the
        # model data. Then the inksetup could just subscribe to
        # onModelUpdated
        def onChangedInkSelection(inkController, inkId=None):
            """ callback for the inkController event """
            inkSetup.show(inkId)
        inkSetup.onChangedInkSelection = onChangedInkSelection
        self.inkController.add(inkSetup) # subscribe
        rightColumn.attach(inkSetup.gtk, 0, 0, 1, 1)
        
        inkControlPanel = self.inkController.initControlPanel()
        rightColumn.attach(inkControlPanel, 0, 1, 1, 1)
        
        # scales to the width of curveEditor.scale
        gradientView = self.inkController.initGradientView(
                       gradientWorker, curveEditor.scale)
        self.attach(gradientView, 0, 1, 1, 1)
        
        colorPreviewWidget = self.initColorPreviewWidget(model, gradientWorker)
        self.attach(colorPreviewWidget, 0, 2, 1, 1)
        
        colorPreviewLabel = self.initColorPreviewLabel()
        self.attach(colorPreviewLabel, 1, 2, 1, 1)
        
        addInkButton = self.initAddInkButton(model)
        self.attach(addInkButton, 2, 2, 1, 1)
        
    def initCurveEditor(self, model):
        curveEditor = CurveEditor.new(model)
        # will take all the space it can get
        curveEditor.set_hexpand(True)
        curveEditor.set_vexpand(True)
        # min width is 256
        curveEditor.set_size_request(256, -1)
        return curveEditor
    
    def initInkSetup(self, model):
        inkSetup = InkSetup(model)
        inkSetup.gtk.set_valign(Gtk.Align.FILL)
        inkSetup.gtk.set_vexpand(True) # so this pushes itself to the bottom
        return inkSetup;
    
    def initColorPreviewWidget(self, model, gradientWorker):
        widget = ColorPreviewWidget(model, gradientWorker)
        widget.set_hexpand(True)
        widget.set_vexpand(False)
        # set min height
        widget.set_size_request(-1, 30)
        return widget
    
    def initColorPreviewLabel(self):
        label = Gtk.Label(_('Result'))
        label.set_halign(Gtk.Align.START)
        return label
    
    def initAddInkButton(self, model):
        button = AddInkButton(model, Gtk.STOCK_ADD, _('Add a new ink'))
        button.set_halign(Gtk.Align.END)
        return button

if __name__ == '__main__':
    import sys
    
    GObject.threads_init()
    use_gui, __ = Gtk.init_check(sys.argv)
    window = Gtk.Window()
    
    cssProvider = Gtk.CssProvider()
    cssProvider.load_from_path('style.css')
    screen = window.get_screen()
    styleContext = Gtk.StyleContext()
    styleContext.add_provider_for_screen(screen, cssProvider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
    
    window.set_title(_('Multitoner Tool'))
    window.set_default_size(640, 480)
    window.set_has_resize_grip(True)
    # the theme should do so
    window.set_border_width(5)
    
    window.connect('destroy', Gtk.main_quit)
    
    model = ModelCurves(ChildModel=ModelInk)
    gradientWorker = GradientWorker()
    inksEditor = InksEditor(model, gradientWorker)
    window.add(inksEditor)
    
    # preview Window
    if len(sys.argv) > 1:
        imageName = sys.argv[1]
        previewWindow = PreviewWindow(model, imageName)
        previewWindow.connect('destroy', Gtk.main_quit)
        previewWindow.show_all()
    
    # fixture for development
    initInks = [
        {
            'locked': True,
            'name': 'PANTONE 406 C',
            'displayColor': (0.8233333333333334, 0.7876555555555557, 0.7876555555555557),
            'cmyk': (0.05, 0.09, 0.1, 0.13),
            'visible': True,
            'points': [(0, 0.13370473537604458), (1, 0.45403899721448465), (0.18808777429467086, 0.2590529247910863)],
            'interpolation': 'monotoneCubic'
        },
        {
            'locked': False,
            'name': 'PANTONE 409 C',
            'displayColor': (0.5333333333333333, 0.5411764705882353, 0.5215686274509804),
            'cmyk': (0.16, 0.25, 0.21, 0.45),
            'visible': True,
            'points': [(0, 0), (0.38557993730407525, 0.22841225626740946), (0.7084639498432602, 0.6434540389972145), (1, 0.8495821727019499)],
            'interpolation': 'linear'
        },
        {
            'locked': False,
            'name': 'Black',
            'displayColor': (0, 0, 0),
            'cmyk': (0.0, 0.0, 0.0, 0.0),
            'visible': True,
            'points': [(0.4890282131661442, 0), (1, 1), (0, 0), (0.780564263322884, 0.6295264623955432)],
            'interpolation': 'spline'
        }
    ]
    
    for t in initInks:
        model.appendCurve(**t)
    
    window.show_all()
    Gtk.main()

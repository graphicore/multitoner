#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division
import os
import sys
from gi.repository import Gtk, Gdk, GObject, GdkPixbuf
import cairo
from weakref import ref as Weakref

from gtkcurvewidget import CurveEditor, CurveException
from interpolation import interpolationStrategies, interpolationStrategiesDict
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
    def __init__(self, ctrl, model, gradientWorker, width=-1, height=-1):
        Gtk.CellRendererText.__init__(self)
        model.add(self) #subscribe
        self.ctrl = ctrl
        self.gradientWorker = gradientWorker
        self.width = width
        self.height = height
        self.state = {}
    
    def _init_ink(self, inkModel):
        """ init the state for a inkModel"""
        iid = id(inkModel)
        self.state[iid] = {
            'surface':None,
            'timeout':None,
            'waiting': False,
            'update_needed': None
        }
        self._requestNewSurface(inkModel)
    
    def onModelUpdated(self, model, event, *args):
        if event == 'curveUpdate':
            inkModel = args[0]
            inkEvent = args[1]
            # whitelist, needs probbaly an update when more relevant events occur
            if inkEvent in ('pointUpdate', 'addPoint', 'removePoint', 'setPoints',
                   'interpolationChanged', 'cmykChanged'):
                self._requestNewSurface(inkModel)
        if event == 'removeCurve':
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
        self.ctrl.triggerRowChanged(iid)
    
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
        
        if iid not in self.state:
            inkModel = self.ctrl.getInkById(iid)
            self._init_ink(inkModel)
            
        
        width, height = (self.width, cell_area.height)
        
        
        cairo_surface = self.state[iid]['surface']
        
        
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
                                 'visibleChanged', 'cmykChanged'):
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
        object it subscribes to.
    """
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

class InkControllerException(Exception):
    pass

class InkController(object):
    def __init__(self, curves=[]):
        # ghosscript doesn't do more as it seems
        self.max_inks = 10 
        
        
        self.inks = ModelCurves(ChildModel=ModelInk)
        #id, name, interpolation Name (for display), locked, visible
        self.inkListStore = Gtk.ListStore(int, str, str, bool, bool)
        
        self.inkListStore.connect('row_deleted', self.onRowDeleted)
        
        self.inks.add(self) #subscribe
        self.inks.curves = curves
    
    def triggerRowChanged(self, iid):
        row = self._getRowById(iid)
        path = row.path
        itr = self.inkListStore.get_iter(path)
        self.inkListStore.row_changed(path, itr)
    
    def addInk(self, **args):
        if len(self.inks) < self.max_inks:
            self.inks.appendCurve(**args)
    
    def deleteInk(self, inkModel):
        self.inks.removeCurve(inkModel)
    
    def onRowDeleted(self, *args):
        """
        we use this to reorder the curves
        """
        newOrder = []
        for row in self.inkListStore:
            newOrder.append(row[0])
        self.inks.reorderByIdList(newOrder)
    
    def onModelUpdated(self, model, event, *args):
        if event == 'setCurves':
            self.inkListStore.clear()
            for curveModel in self.inks.curves:
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
        return self.getInkById(row[0])
    
    def getInkById(self, inkId):
        for curveModel in self.inks.curves:
            if id(curveModel) == inkId:
                return curveModel
        raise InkControllerException('Ink not found by id {0}'.format(inkId))

class AddInkButton(Gtk.Button):
    """
        Button to add one more Ink
    """
    def __init__(self, ctrl, stockID=None, tooltip=None):
        Gtk.Button.__init__(self)
        if stockID is not None:
            self.set_label(stockID)
            self.set_use_stock(True)
        if tooltip is not None:
            self.set_tooltip_text(tooltip)
        self.ctrl = ctrl
        self.connect('clicked', self.addInk)
        self.ctrl.inks.add(self)
    
    def addInk(self, *args):
        self.ctrl.addInk()
    
    def onModelUpdated(self, model, event, *args):
        if event not in ('removeCurve', 'appendCurve', 'setCurves'):
            return
        active = len(model) < self.ctrl.max_inks
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

class CellRendererEditorColor (CellRendererPixbufButton):
    def __init__(self, ctrl):
        CellRendererPixbufButton.__init__(self)
        self.ctrl = ctrl
    
    text = GObject.property(type=str, default='')
    
    def do_render(self, cr, widget, background_area, cell_area, flags):
        """
        self ... a GtkCellRenderer
        cr : a cairo context to draw to
        widget : the widget owning window
        background_area : entire cell area (including tree expanders and maybe padding on the sides)
        cell_area : area normally rendered by a cell renderer
        flags : flags that affect rendering
        """
        iid = int(self.get_property('text'))
        ink = self.ctrl.getInkById(iid)
        cr.set_source_rgb(*ink.displayColor)
        width, height  = self.get_fixed_size()
        width = min(width, cell_area.width)
        height = min(height, cell_area.height)
        x = int(cell_area.x + (cell_area.width/2 - width/2))
        y = int(cell_area.y + (cell_area.height/2 - height/2))
        cr.rectangle(x, y, width, height)
        cr.fill()

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
    
    w.set_title(_('Multitoner Tool'))
    w.set_default_size(640, 480)
    w.set_has_resize_grip(True)
    # the theme should do so
    w.set_border_width(5)
    
    w.connect('destroy', Gtk.main_quit)
    
    inkController = InkController()
    
    curveEditor = CurveEditor.new(w, inkController.inks)
    # will take all the space it can get
    curveEditor.set_hexpand(True)
    curveEditor.set_vexpand(True)
    # min width is 256
    curveEditor.set_size_request(256, -1)
    
    inkGrid = Gtk.Grid()
    inkGrid.set_column_spacing(5)
    # inkGrid.set_column_homogeneous(True)
    # inkGrid.set_row_homogeneous(True)
    w.add(inkGrid)
    
    # left : the column number to attach the left side of child to
    # top : the row number to attach the top side of child to
    # width : the number of columns that child will span
    # height : the number of rows that child will span
    inkGrid.attach(curveEditor, 0, 0, 1, 1)
    
    # make a treeview …
    controlView = Gtk.TreeView(model=inkController.inkListStore)
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
        show_ink_options(selected)
        print 'selected is', selected
    treeSelection.connect("changed", onChangedSelection)
    
    gradientView = Gtk.TreeView(model=inkController.inkListStore)
    gradientView.set_property('headers-visible', False)
    
    # the width value is just initial and will change when the scale of
    # the curveEditor changes
    renderer_ink = CellRendererInk(ctrl=inkController, model=inkController.inks, gradientWorker=gradientWorker, width=256)
    column_ink = HScalingTreeColumnView(_('Ink'), renderer_ink, scale=curveEditor.scale, text=0)
    gradientView.append_column(column_ink)
    
    
    def changeColor(cellRenderer, path):
        model = inkController.getInkByPath(path)
        #open colorchooser Dialog
        dialog = Gtk.ColorChooserDialog(_('Pick a color for the editor widget'), w)
        color = Gdk.RGBA(*model.displayColor)
        dialog.set_rgba(color)
        dialog.run()
        color = dialog.get_rgba()
        rgb = (color.red, color.green, color.blue)
        model.displayColor = rgb
        dialog.destroy()
    
    renderer_editorColor = CellRendererEditorColor(ctrl=inkController)
    renderer_editorColor.set_fixed_size (16,16)
    renderer_editorColor.connect('clicked', changeColor)
    
    def deleteRow(cellRenderer, path):
        model = inkController.getInkByPath(path)
        
        dialog = Gtk.MessageDialog(w, 0, Gtk.MessageType.QUESTION,
            Gtk.ButtonsType.YES_NO, _('Delete the ink “{0}”?').format(model.name))
        dialog.format_secondary_text(
            _('You will loose all of its properties.'))
        response = dialog.run()
        if response == Gtk.ResponseType.YES:
            inkController.deleteInk(model)
        dialog.destroy()
    
    renderer_deleteRow = CellRendererPixbufButton()
    renderer_deleteRow.set_property('stock-id', Gtk.STOCK_DELETE)
    renderer_deleteRow.connect('clicked', deleteRow)
    
    #locked row
    def toggleLocked(cellRenderer, path):
        model = inkController.getInkByPath(path)
        model.locked = not model.locked
    
    icons = {}
    for key, fileName in {'activeIcon': 'locked.svg', 'inactiveIcon': 'unlocked.svg'}.items():
        iconPath = os.path.join(os.path.dirname(__file__), 'icons', fileName)
        icons[key] = GdkPixbuf.Pixbuf.new_from_file_at_size(iconPath, 16, 16)
    renderer_lockRow = CellRendererToggle(**icons)
    renderer_lockRow.set_fixed_size (16, 16)
    renderer_lockRow.connect('clicked', toggleLocked)
    
    def toggleVisible(cellRenderer, path):
        model = inkController.getInkByPath(path)
        model.visible = not model.visible
    
    icons = {}
    for key, fileName in {'activeIcon': 'visible.svg', 'inactiveIcon': 'invisible.svg'}.items():
        iconPath = os.path.join(os.path.dirname(__file__), 'icons', fileName)
        icons[key] = GdkPixbuf.Pixbuf.new_from_file_at_size(iconPath, 16, 16)
    renderer_visibilityRow = CellRendererToggle(**icons)
    renderer_visibilityRow.set_fixed_size (16, 16)
    renderer_visibilityRow.connect('clicked', toggleVisible)
    
    
    column_id = Gtk.TreeViewColumn(_('Tools'))
    
    column_id.pack_start(renderer_visibilityRow, False)
    column_id.pack_start(renderer_lockRow, False)
    column_id.pack_start(renderer_editorColor, False)
    column_id.pack_start(renderer_deleteRow, False)
    
    column_id.add_attribute(renderer_editorColor, 'text', 0)
    column_id.add_attribute(renderer_lockRow, 'active', 3)
    column_id.add_attribute(renderer_visibilityRow, 'active', 4)
    
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
    
    
    inkGrid.attach(gradientView, 0, 1, 1, 1)
    
    
    colorPreviewWidget = ColorPreviewWidget(inkController.inks, gradientWorker)
    colorPreviewWidget.set_hexpand(True)
    colorPreviewWidget.set_vexpand(False)
    # set min height
    colorPreviewWidget.set_size_request(-1, 30)
    inkGrid.attach(colorPreviewWidget, 0, 2, 1, 1)
    
    colorPreviewLabel = Gtk.Label(_('Result'))
    colorPreviewLabel.set_halign(Gtk.Align.START)
    inkGrid.attach(colorPreviewLabel, 1, 2, 1, 1)
    
    addInkButton = AddInkButton(inkController, Gtk.STOCK_ADD, _('Add a new ink'))
    addInkButton.set_halign(Gtk.Align.END)
    inkGrid.attach(addInkButton, 2, 2, 1, 1)
    
    
    
    
    inkGrid.set_row_spacing(5)
    
    rightColumn = Gtk.Grid()
    rightColumn.set_row_spacing(5)
    rightColumn.attach(controlView, 0, 1, 1, 1)
    inkGrid.attach(rightColumn, 1, 0, 2, 2)
    
    inkOptionsBox = Gtk.Grid(orientation=Gtk.Orientation.VERTICAL)
    
    
    frame = Gtk.Frame()
    frame.set_label(_('Ink Setup'))
    frame.set_valign(Gtk.Align.FILL)
    frame.add(inkOptionsBox)
    frame.set_vexpand(True) # so this pushes itself to the bottom
    
    rightColumn.attach(frame, 0, 0, 1, 1)
    
    
    def onWidgetCurveTypeChange(widget, inkId):
        interpolation = widget.get_active_id()
        inkController.getInkById(inkId).interpolation = interpolation
    
    def onWidgetNameChange(widget, inkId):
        name = widget.get_text()
        inkController.getInkById(inkId).name = name
    
    def onWidgetCMYKValueChange(widget, inkId, colorAttr):
        ink = inkController.getInkById(inkId)
        value = widget.get_adjustment().get_value()
        setattr(ink, colorAttr,  value)
    
    
    def show_ink_options(inkId=None):
        if inkId is None:
            inkOptionsBox.set_sensitive(False)
            # just disable, this prevents the size of the box from changing
            # and it tells the ui story right
        else:
            inkOptionsBox.foreach(lambda x, _: x.destroy(), None)
            inkOptionsBox.set_sensitive(True)
            ink = inkController.getInkById(inkId)
            
            widget_name = Gtk.Entry()
            widget_name.set_text(ink.name)
            widget_name.connect('changed', onWidgetNameChange, inkId);
            
            widget_curveType = Gtk.ComboBoxText.new()
            widget_curveType.set_model(interpolationStrategiesListStore)
            widget_curveType.set_id_column(1)
            widget_curveType.set_active_id(ink.interpolation)
            widget_curveType.connect('changed', onWidgetCurveTypeChange, inkId);
            
            ws = [
                Gtk.Label(_('Name')), widget_name,
                Gtk.Label(_('Curve Type')), widget_curveType,
            ]
            
            
            for i, w in enumerate(ws):
                hi = i % 2
                inkOptionsBox.attach(w, hi, (i-hi)/2, 1, 1)
                w.set_halign(Gtk.Align.FILL if hi else Gtk.Align.START)
            
            offset = len(ws)
            for i, (colorAttr, label) in enumerate([('c',_('C')),('m',_('M')),('y',_('Y')),('k', _('K'))]):
                w = Gtk.Label(label)
                w.set_halign(Gtk.Align.START)
                inkOptionsBox.attach(w, 0,i+offset, 1, 1)
                
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
                entry.connect('value-changed', onWidgetCMYKValueChange, inkId, colorAttr)
                inkOptionsBox.attach(entry, 1, i+offset, 1, 1)
                
        inkOptionsBox.show_all()
    show_ink_options()
    
    ###
    # inkController.inks.appendCurve(points=[(0.0, 1.0), (0.5, 0.3), (1, 0.0)], interpolation='spline', name="Yellow")
    # inkController.inks.appendCurve(points=[(0.0, 0.0), (0.1, 0.4), (0.4, 0.7)], interpolation='spline', name="Magenta")
    # inkController.inks.appendCurve(points=[(0.0, 0.0), (0.2, 0.6), (0.5, 0.2), (0.4, 0.3), (1.0,1.0)], name="Black")
    
    
    if len(sys.argv) > 1:
        imageName = sys.argv[1]
        previewWindow = PreviewWindow(inkController.inks, imageName)
        previewWindow.connect('destroy', Gtk.main_quit)
        previewWindow.show_all()
    
    
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
        inkController.inks.appendCurve(**t)
    
    w.show_all()
    Gtk.main()
